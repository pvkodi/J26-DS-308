"""CGE Studio: server-owned workflow, actual component inference, source-linked evidence."""
import argparse,json,secrets,threading,traceback,zipfile
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs
from services import *

class Studio:
    def __init__(self):
        self.demo=Demo();self.sessions={};self.mutex=threading.RLock()
        self.dataset_manifest=json.loads((ROOT/'data/manifest.json').read_text())
        import hashlib
        if hashlib.sha256((ROOT/'data/dataset.json').read_bytes()).hexdigest()!=self.dataset_manifest['dataset_sha256']:raise ValueError('Dataset snapshot checksum mismatch')
        self.dataset=json.loads((ROOT/'data/dataset.json').read_text(encoding='utf-8'))
        self.detector=detector_baseline()
    def catalog(self):
        return dict(**self.demo.catalog(),app='cge_studio',version='2.0',local=model_status(),detector=dict(model=self.detector['model'],pipeline=self.detector['pipeline']),dataset=dict(**self.dataset['provenance'],**self.dataset_manifest,obligation_rows=len(self.dataset['rows'])))
    def extraction_examples(self):
        examples=[]
        for scenario in self.detector['scenarios']:
            ledger=scenario['turns'][0]['report']['ledger']
            if ledger['policy_sha256']!=digest(scenario['policy']):raise ValueError('Saved extraction does not match its source prompt.')
            examples.append(dict(id=scenario['id'],title=scenario['title'],policy=scenario['policy'],ledger=ledger,
              source='Saved extraction from the accepted detector showcase',model=self.detector['model'],pipeline=self.detector['pipeline'],
              provenance=dict(showcase_sha256=(OLD/'data/detector_baseline.sha256').read_text().strip(),policy_sha256=ledger['policy_sha256'],
                note='Actual saved source-selection output. The scenario was authored; this is not a Kaggle generation or a new model call.')))
        return dict(examples=examples)
    def run_extraction(self,b):
        fresh=b.get('fresh',True)
        if not isinstance(fresh,bool):raise ValueError('Fresh inference must be true or false.')
        policy=b.get('policy','');started=utc();clock=time.monotonic();ledger=extract(policy,fresh=fresh)
        value=dict(policy=policy,ledger=ledger,source='Local extraction',model=MODEL_ALIAS,
          provenance=dict(policy_sha256=ledger['policy_sha256'],started_utc=started,completed_utc=utc(),elapsed_seconds=round(time.monotonic()-clock,2),
            fresh_inference=fresh,note='Fresh inference bypasses the detector response cache. Model prompt-token caching may still be used. No saved example is substituted on failure.'))
        value['extraction_sha256']=digest(value)
        folder=ROOT/'runtime/extractions';folder.mkdir(parents=True,exist_ok=True)
        (folder/(secrets.token_hex(16)+'.json')).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        return value
    def create(self,b):
        mode=b.get('mode','recorded')
        if mode!='recorded':raise ValueError('This distribution supports recorded sessions only.')
        if mode=='recorded':
            v=self.demo.session(b);sid=v['session'];row=self.row(sid)
            s=dict(id=sid,mode=mode,policy=row['messages_before'][0]['content'],ledger=None,phase='policy',report=None,reports=[],lock=threading.RLock())
        elif mode=='live':
            policy=b.get('policy','')
            if not isinstance(policy,str) or not policy.strip():raise ValueError('Paste a system prompt first.')
            sid=secrets.token_urlsafe(24);s=dict(id=sid,mode=mode,policy=policy,ledger=None,phase='policy',report=None,reports=[],history=[],records=[],lock=threading.RLock())
        else:raise ValueError('Choose a recorded session or local model.')
        with self.mutex:
            if len(self.sessions)>100:raise ValueError('Too many open sessions. Restart Studio to clear them.')
            self.sessions[sid]=s
        return self.view(s)
    def get(self,sid):
        if sid not in self.sessions:raise ValueError('Session expired. Start a new conversation.')
        return self.sessions[sid]
    def row(self,sid):
        s=self.demo.get(sid);return self.demo.evidence.paths[s['key']][s['turn']]
    def act(self,b):
        s=self.get(b.get('session'));action=b.get('action')
        with s['lock']:
            if action=='extract':
                if s['phase']!='policy':raise ValueError('This policy is already committed. Start a new session to edit it.')
                if s['mode']=='recorded':
                    s['ledger']=registered_ledger(s['policy'],self.row(s['id'])['rules'])
                    s['extraction_note']='Imported the run’s explicit registered rules with exact source text. Learned extraction is not evaluated in this mode.'
                else:
                    s['ledger']=extract(s['policy']);s['extraction_note']='Local source-selection extractor copied binding policy passages. Inspect coverage issues; extraction may omit or group requirements.'
                s['phase']='user'
            elif action=='profile':
                if s['mode']!='recorded':raise ValueError('The Granite profile is not valid for the local Qwen3 model.')
                self.demo.act(dict(session=s['id'],action='profile',enabled=b.get('enabled')))
            elif action=='predict':
                if s['phase']!='user':raise ValueError('Extract the policy, then enter the next message before scoring.')
                if s['mode']=='recorded':self.demo.act(dict(session=s['id'],action='predict'))
                else:
                    user=b.get('user','')
                    if not isinstance(user,str) or not user.strip():raise ValueError('Enter a message.')
                    if len(user)>18000:raise ValueError('User message is too long for this local context profile.')
                    s['pending']=live_predictions(s,user,self.demo.evidence);s['user']=user
                    self.save(s,'forecast',s['pending'])
                s['phase']='predicted'
            elif action=='generate':
                if s['phase']!='predicted':raise ValueError('Score the next answer before generation.')
                if s['mode']=='recorded':self.demo.act(dict(session=s['id'],action='reveal'))
                else:
                    s['generation']=generate(s['pending']['messages']);self.save(s,'generation',s['generation'])
                s['phase']='generated'
            elif action=='detect':
                if s['phase']!='generated':raise ValueError('Generate or reveal the answer before inspection.')
                prior=s['reports'][-1] if s['reports'] else None
                if s['mode']=='recorded':
                    row=self.row(s['id']);messages=row['messages_before']
                    report=exact_report(s['policy'],messages[-1]['content'],row['response'],row['rules'],history=messages[1:-1],prior=prior)
                    report['presentation_source']='computed_exact_checks_on_recorded_answer';report['capped']=not row['eligible_primary']
                else:
                    g=s['generation'];report=analyze(s['policy'],s['user'],g['text'],history=s['history'],ledger=s['ledger'],prior=prior)
                    report['capped']=g['finish_reason']=='length'
                    rules=s['pending']['rules'];checks=[]
                    for r in rules:
                        result=next(x for x in report['results'] if x['obligation']['id']==r['id'])
                        checks.append(dict(id=r['id'],passed=result['verdict']=='PASS'))
                    s['records'].append(dict(response=g['text'],checks=checks,eligible_primary=not report['capped'] and all(x['verdict'] in ('PASS','FAIL') for x in report['results'] if x['obligation']['id'] in {r['id'] for r in rules})))
                    s['history'].extend([dict(role='user',content=s['user']),dict(role='assistant',content=g['text'])])
                if report.get('capped'):
                    report['coverage_note']='Truncated answer: checks describe observed text only. Temporal transitions and forecast outcomes are unresolved.'
                    for result in report['results']:
                        result['event']='unresolved_transition';result['last_applicable_verdict']='UNKNOWN'
                if s['mode']=='live':self.save(s,'detector',report)
                s['report']=report;s['reports'].append(report);s['phase']='detected'
            elif action=='next':
                if s['phase']!='detected':raise ValueError('Inspect this answer before continuing.')
                if s['mode']=='recorded':self.demo.act(dict(session=s['id'],action='next'))
                s['phase']='user';s['report']=None
                for k in ('pending','generation','user'):s.pop(k,None)
            else:raise ValueError('Unknown action')
            return self.view(s)
    def save(self,s,kind,payload):
        turn=len(s['records'])+1 if kind!='detector' else len(s['records'])
        p=ROOT/'runtime/sessions'/s['id'];p.mkdir(parents=True,exist_ok=True)
        target=p/f'{turn:03}_{kind}.json';tmp=target.with_suffix('.tmp')
        tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(target)
    def view(self,s):
        if s['mode']=='recorded':
            v=self.demo.view(self.demo.get(s['id']));row=self.row(s['id'])
            v.update(system_prompt=s['policy'],current_user_full=row['messages_before'][-1]['content'])
            if s['phase']!='detected':v['outcome']=None
            v['answer']=row['response'] if s['phase'] in ('generated','detected') else None
            v['answer_origin']='Genuine recorded '+v['model_label']+' answer'
        else:
            pending=s.get('pending',{});g=s.get('generation',{});t=len(s['records'])+(s['phase']!='detected')
            v=dict(session=s['id'],model='local_qwen3',model_label='Qwen3 4B · local',family_label='Your conversation',turn=t,total_turns=None,
              prompt_tokens=pending.get('prompt_tokens'),predictions=pending.get('predictions'),profile_on=False,history=[],system_prompt=s['policy'],request=s.get('user',''),current_user_full=s.get('user',''),
              answer=g.get('text'),answer_origin='Generated locally · '+g.get('model',MODEL_ALIAS),generation=g,outcome=None)
            history=s['history'][:-2] if s['phase']=='detected' else s['history']
            v['history']=[dict(turn=i//2+1,request=history[i]['content'],answer=history[i+1]['content']) for i in range(0,len(history),2)]
            if s['report']:
                checks=[]
                for prediction in pending.get('predictions',[]):
                    result=next(r for r in s['report']['results'] if r['obligation']['id']==prediction['id']);status=prediction['status'];passed=result['verdict']=='PASS';scored=result['verdict'] in ('PASS','FAIL') and not s['report'].get('capped')
                    if not scored:kind,label='unscored','Unscored · unresolved or capped'
                    elif status=='initial_compliance_not_established':kind,label=('initial_pass','Initial pass') if passed else ('initial_failure','Failed on first answer')
                    elif status=='already_failed':kind,label='closed','Passing now · earlier failure' if passed else 'Still failing · earlier failure'
                    elif prediction['risk'] is None:kind,label='unscored','Outside the first-failure risk set'
                    elif passed:kind,label=('false_alarm','Passed · false alarm') if prediction['warning'] else ('pass','Passed · no warning')
                    else:kind,label=('warned','First failure · warned') if prediction['warning'] else ('missed','First failure · missed')
                    checks.append(dict(id=prediction['id'],passed=passed if scored else None,kind=kind,verdict=label))
                v['outcome']=dict(checks=checks,ranking=None,capped=s['report'].get('capped',False))
        v.update(mode=s['mode'],phase=s['phase'],ledger=s['ledger'],extraction_note=s.get('extraction_note'),detector=s['report'],timeline=[dict(turn=i+1,counts=r['counts'],capped=r.get('capped',False),events=[x['event'] for x in r['results']]) for i,r in enumerate(s['reports'])])
        return v
    def metrics(self):
        e=self.demo.evidence;compare=[]
        for m in ('qwen7','granite2'):
            values=[]
            for key,rows in e.paths.items():
                if key[0]!=m:continue
                for t,r in enumerate(rows):
                    if not r['eligible_primary']:continue
                    for p in e.predict(r,rows[:t],m,False):
                        if p['inputs'] is None:continue
                        y=int(not next(c['passed'] for c in r['checks'] if c['id']==p['id']))
                        values.append((y,p['base_risk'],e.base['priors'][p['inputs']['rule_type']],probability(p['inputs'],e.base['request_only_baseline']),e.base['events']/e.base['checks']))
            for label,ix in [('Obligation prior',2),('Previous outcome only (constant)',4),('Request only',3),('Conversation state + request',1)]:
                n=len(values);k=sum(v[0] for v in values);neg=n-k;tp=sum(v[0] and v[ix]>=.5 for v in values);fp=sum(not v[0] and v[ix]>=.5 for v in values)
                compare.append(dict(model=m,variant=label,checks=n,events=k,warned=tp,false_alarms=fp,balanced_accuracy=(tp/k+(neg-fp)/neg)/2,brier=sum((v[ix]-v[0])**2 for v in values)/n))
        experiment=WORK/'c1_mvp_phase1/granite_state_profile_v4/review_upload1/review.json'
        return dict(evaluation=e.reports,ablations=compare,source_family_validation={k:e.base[k] for k in ('family_validation','rule_prior_validation','request_only_validation')},
          experiment=json.loads(experiment.read_text()) if experiment.exists() else None,
          scope='Original evaluation: two unseen authored families per model, 96 generated answers each. Checks are clustered in conversations, not independent samples.',
          absent_baselines='A state-only model was not separately fitted. Current-answer outcome is a target, never a pre-answer input. The previous-outcome-only baseline is constant because all earlier answers passed: it returns the source training first-failure rate (24/152), without using rule identity or conversation state.')
    def evidence(self,s):
        if s['mode']=='recorded':
            r=self.row(s['id']);model=self.demo.get(s['id'])['key'][0]
            with zipfile.ZipFile(OLD/f'data/{model}.zip') as z:config=json.loads(z.read('run_config.json'));status=json.loads(z.read('status.json'))
            result=dict(source='Genuine Kaggle generation',artifact_manifest=self.demo.evidence.manifest,run_config=config,run_status=status,
              record_sha256=r['record_sha256'],messages_before_sha256=r['messages_before_sha256'],forecast_sha256=r['forecast_sha256'],forecast=r['early_warning_forecast'],
              verification='On startup: file hashes, record hashes, input hashes, forecast chronology, history lineage and all original forecasts are independently recomputed.')
            if s['phase']=='detected':result['record']=r;result['computed_detector_report']=s['report']
            else:result['record_note']='Full answer record becomes available after detector inspection; later turns are not exposed here.'
            return result
        return dict(source='Local generation; no Kaggle run claimed',runtime=dict(model=model_status(),manifest=json.loads((WORK/'obligation_detector/runtime/qwen4_manifest.json').read_text())),forecast=s.get('pending'),generation=s.get('generation'),detector=s.get('report'),
          storage='Saved locally under cge_studio/runtime/sessions/'+s['id'],note='Hashes bind the displayed inputs and outputs. Hashes establish consistency, not independent attestation.')
    def handoff(self,s):
        v=self.view(s)
        return dict(schema_version='cge.obligation-monitor.v1',component='obligation_monitor',session_id=s['id'],turn=v['turn'],mode=s['mode'],
          generator_model=v['model'],policy_sha256=digest(s['policy']),phase=s['phase'],
          obligations=[] if not s['ledger'] else s['ledger']['obligations'],pre_generation=dict(predictions=v.get('predictions'),prompt_tokens=v.get('prompt_tokens'),profile_on=v.get('profile_on')),
          post_generation=None if not s['report'] else dict(results=s['report']['results'],counts=s['report']['counts'],capped=s['report'].get('capped',False)),
          integration_status='Proposed versioned contract. Exported from this actual session; other team components are not connected.')

def main():
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8051);a=p.parse_args();app=Studio()
    class Handler(BaseHTTPRequestHandler):
        def send(self,status,data,mime='application/json; charset=utf-8',download=None):
            data=json.dumps(data,ensure_ascii=False).encode() if mime.startswith('application/json') and not isinstance(data,bytes) else data
            self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            if download:self.send_header('Content-Disposition','attachment; filename="'+download+'"')
            self.end_headers();self.wfile.write(data)
        def do_GET(self):
            u=urlsplit(self.path);q=parse_qs(u.query)
            try:
                if u.path=='/api/catalog':return self.send(200,app.catalog())
                if u.path=='/api/local-status':return self.send(200,model_status())
                if u.path=='/api/metrics':return self.send(200,app.metrics())
                if u.path=='/api/component4-profiles':
                    return self.send(200,json.loads((ROOT/'data/component4_profiles/snapshot.json').read_text(encoding='utf-8')))
                if u.path=='/api/component4-files':
                    name=q.get('name',[''])[0]
                    allowed={
                        'qwen7_component4_behavior_profile.json':'application/json; charset=utf-8',
                        'granite2_component4_behavior_profile.json':'application/json; charset=utf-8',
                        'granite_vs_qwen_comparison.json':'application/json; charset=utf-8',
                        'Component4_Profile_Dataset.xlsx':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        'Component4_Profile_Dataset_Package.zip':'application/zip',
                        'PANEL_PREPARATION_GUIDE.txt':'text/plain; charset=utf-8'}
                    if name not in allowed:return self.send(404,dict(error='Unknown Component 4 download'))
                    file=ROOT/'data/component4_profiles'/name
                    value=file.read_bytes()
                    return self.send(200,value,allowed[name],download=name)
                if u.path=='/api/detector/catalog':return self.send(200,app.detector)
                if u.path=='/api/extractor/examples':return self.send(200,app.extraction_examples())
                if u.path=='/api/dataset':
                    if q.get('download'):return self.send(200,app.dataset,download='cge_training_profile_dataset.json')
                    rows=app.dataset['rows'];stage=q.get('stage',['all'])[0]
                    if stage!='all':rows=[r for r in rows if r['stage']==stage]
                    kind=q.get('rule',['all'])[0]
                    if kind!='all':rows=[r for r in rows if r['obligation']['type']==kind]
                    offset=max(0,int(q.get('offset',['0'])[0]));return self.send(200,dict(provenance=app.dataset['provenance'],total=len(rows),rows=rows[offset:offset+20]))
                if u.path in ('/api/evidence','/api/handoff','/api/features'):
                    s=app.get(q.get('session',[''])[0])
                    if u.path=='/api/evidence':value=app.evidence(s)
                    elif u.path=='/api/handoff':value=app.handoff(s)
                    else:
                        v=app.view(s);value=dict(intercept=app.demo.evidence.base['intercept'],note='Additive log-odds contributions from the full model. These are not independent risk probabilities.',rules=[dict(id=r['id'],label=r.get('label',r['id']),inputs=r.get('inputs'),contributions=contributions(r.get('inputs'),app.demo.evidence.base)) for r in v.get('predictions') or []])
                    return self.send(200,value,download=('cge_'+u.path.rsplit('/',1)[-1]+'.json') if q.get('download') else None)
                routes={'/recorded-only.js':('recorded-only.js','text/javascript; charset=utf-8'),'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/component4-profiles.js':('component4-profiles.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8'),'/architecture.svg':('architecture.svg','image/svg+xml')}
                if u.path not in routes:return self.send(404,dict(error='Not found'))
                name,mime=routes[u.path];return self.send(200,(ROOT/'static'/name).read_bytes(),mime)
            except (ValueError,KeyError) as e:self.send(400,dict(error=str(e)))
            except Exception:traceback.print_exc();self.send(500,dict(error='Unable to load this view. See the Studio console.'))
        def do_POST(self):
            try:
                n=int(self.headers.get('Content-Length','0'))
                if not 0<n<=512000:raise ValueError('Request exceeds the local workflow size limit.')
                b=json.loads(self.rfile.read(n));path=urlsplit(self.path).path
                if not isinstance(b,dict):raise ValueError('Expected an object')
                if path in ('/api/extract','/api/extractor/run','/api/detector/analyze'):raise ValueError('Live inference is not included in this distribution.')
                if path=='/api/session':value=app.create(b)
                elif path=='/api/action':value=app.act(b)
                elif path=='/api/extract':value=extract(b.get('policy',''))
                elif path=='/api/extractor/run':value=app.run_extraction(b)
                elif path=='/api/detector/analyze':value=analyze(b['policy'],b.get('user',''),b['response'],history=b.get('history',[]),reference=b.get('reference',''),prior=b.get('prior'))
                else:return self.send(404,dict(error='Not found'))
                self.send(200,value)
            except (ValueError,KeyError,TypeError,InferenceError) as e:self.send(400,dict(error=str(e)))
            except Exception:traceback.print_exc();self.send(500,dict(error='This operation failed. No saved response was substituted. See the Studio console.'))
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',a.port),Handler);print(f'CGE Studio ready: http://127.0.0.1:{a.port}/',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
if __name__=='__main__':main()
