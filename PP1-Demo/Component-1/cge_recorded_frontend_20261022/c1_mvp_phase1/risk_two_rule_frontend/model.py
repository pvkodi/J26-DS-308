"""Load verified evidence and compute forecasts from prefixes using the actual fitted model."""
import hashlib,json,math,sys,zipfile
from pathlib import Path
from collections import defaultdict
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'engine'))
from predictor import FOCAL,eligibility,vector,probability,adjusted
from checks import verify,word_count

def digest(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def close(a,b):
    if type(a)!=type(b):return False
    if isinstance(a,dict):return set(a)==set(b) and all(close(a[k],b[k]) for k in a)
    if isinstance(a,list):return len(a)==len(b) and all(close(x,y) for x,y in zip(a,b))
    if isinstance(a,float):return math.isfinite(a) and math.isfinite(b) and abs(a-b)<1e-10
    return a==b

class Evidence:
    def __init__(self):
        self.manifest=json.loads((ROOT/'data/manifest.json').read_text(encoding='utf-8'))
        for name,sha in self.manifest['files'].items():
            if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=sha:raise ValueError('Evidence file changed: '+name)
        self.base=json.loads((ROOT/'data/base.json').read_text());self.profile=json.loads((ROOT/'data/profile.json').read_text())
        if self.profile['base_sha256']!=digest(self.base):raise ValueError('Profile belongs to another base predictor')
        if self.profile.get('supported_rules')!=['word_limit']:raise ValueError('Unexpected target profile scope')
        self.paths={};self.scenarios={};self.reports=[]
        for model in ('qwen7','granite2'):
            with zipfile.ZipFile(ROOT/f'data/{model}.zip') as z:
                plan=json.loads(z.read('plan.json'));status=json.loads(z.read('status.json'));config=json.loads(z.read('run_config.json'))
                if status['completed_answers']!=96 or status['pending_answers']!=0:raise ValueError('Incomplete evaluation')
                if plan['spec']['stage']!='evaluation' or config['model']['key']!=model:raise ValueError('Wrong evidence stage')
                if json.loads(z.read('artifacts/base.json'))!=self.base or json.loads(z.read('artifacts/profile.json'))!=self.profile:raise ValueError('Artifact snapshot mismatch')
                q=dict(plan);sha=q.pop('plan_sha256')
                if digest(q)!=sha or config['plan_sha256']!=sha:raise ValueError('Plan checksum mismatch')
                records=[json.loads(z.read(n)) for n in z.namelist() if n.startswith('records/') and n.endswith('.json')]
                groups=defaultdict(list)
                for r in records:
                    q=dict(r);sha=q.pop('record_sha256')
                    if digest(q)!=sha or digest(r['messages_before'])!=r['messages_before_sha256']:raise ValueError('Record checksum mismatch')
                    if verify(r['rules'],r['response'])!=r['checks']:raise ValueError('Checker mismatch')
                    if r['eligible_primary']!=(bool(r['response'].strip()) and r['finish_reason']=='eos'):raise ValueError('Censoring mismatch')
                    groups[r['job_id'].rsplit('__',1)[0]].append(r)
                for s in plan['spec']['scenarios']:
                    self.scenarios[s['family']]=s
                    rows=sorted(groups.pop(s['id']),key=lambda r:r['job']['turn_index'])
                    if [r['job']['turn_index'] for r in rows]!=list(range(12)):raise ValueError('Noncontiguous conversation')
                    history=[]
                    for r in rows:
                        if r['parent_record_sha256']!=[p['record_sha256'] for p in history]:raise ValueError('History mismatch')
                        if r['model']!=config['model'] or r['plan_sha256']!=plan['plan_sha256']:raise ValueError('Model/plan mismatch')
                        forecast=r['early_warning_forecast']
                        if digest(forecast)!=r['forecast_sha256'] or json.loads(z.read('forecasts/'+r['job_id']+'.json'))!=forecast:raise ValueError('Forecast checksum mismatch')
                        if not self.base['fitted_utc']<forecast['committed_utc']<=r['completed_utc'] or not self.profile['fitted_utc']<forecast['committed_utc']:raise ValueError('Forecast chronology mismatch')
                        actual=self.predict(r,history,model,False)
                        for new,old in zip(actual,forecast['predictions']):
                            if new['id']!=old['obligation_id'] or new['status']!=old['status']:raise ValueError('Forecast alignment mismatch')
                            if not close(new['inputs'],old['inputs']) or not close(new['base_risk'],old['first_failure_next_answer_risk']) or not close(new['profile_risk'],old['profile_on_risk']):raise ValueError('Recomputed forecast mismatch')
                        history.append(r)
                    self.paths[(model,s['family'],s['length'],s['load'])]=rows
                if groups:raise ValueError('Unexpected conversation')
            self.reports.append(self.metrics(model,False))
            if model=='granite2':self.reports.append(self.metrics(model,True))

    def predict(self,row,history,model,profile_on):
        predictions=[]
        for rule,f in zip(row['rules'],row['features']):
            status=eligibility(rule,history)
            v=vector(f,rule,row['messages_before']) if rule['type'] in FOCAL and status=='at_risk_before_first_failure' else None
            base=probability(v,self.base) if v is not None else None
            on=adjusted(base,v,self.profile) if base is not None and model=='granite2' else base
            if rule['type'] not in FOCAL:continue
            p=on if profile_on and model=='granite2' else base
            predictions.append(dict(id=rule['id'],label='Word limit' if rule['type']=='word_limit' else 'Exact ending',
                text='Keep every reply below 120 words.' if rule['type']=='word_limit' else 'End exactly with: '+rule['value'],
                requirement=rule['value'],status=status,inputs=v,base_risk=base,profile_risk=on,risk=p,
                warning=None if p is None else p>=self.base['threshold'],first_failed_turn=next((i+1 for i,r in enumerate(history) if r['eligible_primary'] and any(c['id']==rule['id'] and not c['passed'] for c in r['checks'])),None)))
        return predictions

    def outcome(self,row,predictions):
        outcomes=[]
        for p in predictions:
            check=next(c for c in verify(row['rules'],row['response']) if c['id']==p['id'])
            if not row['eligible_primary']:kind,label='unscored','Unscored · output capped'
            elif p['status']=='initial_compliance_not_established':
                kind='initial_pass' if check['passed'] else 'initial_failure';label='Initial pass' if check['passed'] else 'Failed on first answer'
            elif p['status']=='already_failed':kind,label='closed',('Passing now' if check['passed'] else 'Still failing')+' · earlier failure'
            elif p['status']=='history_unresolved':kind,label='unscored','Unscored · earlier output capped'
            elif not check['passed']:kind,label=('warned','First failure · warned') if p['warning'] else ('missed','First failure · missed')
            else:kind,label=('false_alarm','Passed · false alarm') if p['warning'] else ('pass','Passed · no warning')
            outcomes.append(dict(id=p['id'],label=p['label'],passed=check['passed'] if row['eligible_primary'] else None,kind=kind,verdict=label,
                detail=f"{word_count(row['response'])} words · must be below 120" if p['id']=='word_limit' else 'Exact ending '+('matched' if check['passed'] else 'not matched')))
        valid=[(p,o) for p,o in zip(predictions,outcomes) if p['risk'] is not None and row['eligible_primary']]
        ranking=None
        if len(valid)==2 and valid[0][1]['passed']!=valid[1][1]['passed']:
            failed=next(p for p,o in valid if not o['passed']);passed=next(p for p,o in valid if o['passed'])
            ranking='Higher-risk rule failed; lower-risk rule passed.' if failed['risk']>passed['risk'] else 'Lower-risk rule failed; higher-risk rule passed.' if failed['risk']<passed['risk'] else 'Risks were tied; only one rule failed.'
        return dict(text=row['response'],capped=not row['eligible_primary'],checks=outcomes,ranking=ranking)

    def metrics(self,model,profile_on):
        values=[];initial=0;capped=0
        for key,rows in self.paths.items():
            if key[0]!=model:continue
            for t,row in enumerate(rows):
                capped+=not row['eligible_primary']
                for p in self.predict(row,rows[:t],model,profile_on):
                    c=next(c for c in row['checks'] if c['id']==p['id'])
                    if t==0 and row['eligible_primary'] and not c['passed']:initial+=1
                    if p['risk'] is not None and row['eligible_primary']:values.append((int(not c['passed']),p['risk']))
        n=len(values);events=sum(y for y,p in values);neg=n-events
        tp=sum(y==1 and p>=self.base['threshold'] for y,p in values);fp=sum(y==0 and p>=self.base['threshold'] for y,p in values)
        recall=tp/events if events else None;fpr=fp/neg if neg else None
        return dict(model=model,profile_on=profile_on,checks=n,events=events,warned=tp,false_alarms=fp,
            balanced_accuracy=(recall+1-fpr)/2 if recall is not None and fpr is not None else None,
            brier=sum((p-y)**2 for y,p in values)/n if n else None,initial_failures=initial,capped=capped,
            rule_prior_brier=self.prior_brier(model))

    def prior_brier(self,model):
        values=[]
        for key,rows in self.paths.items():
            if key[0]!=model:continue
            for t,r in enumerate(rows):
                for rule in r['rules']:
                    if rule['type'] in FOCAL and eligibility(rule,rows[:t])=='at_risk_before_first_failure' and r['eligible_primary']:
                        check=next(c for c in r['checks'] if c['id']==rule['id'])
                        values.append((self.base['priors'][rule['type']]-int(not check['passed']))**2)
        return sum(values)/len(values) if values else None
