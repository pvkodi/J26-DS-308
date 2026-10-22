import json,secrets,threading,time
from pathlib import Path
from model import Evidence
NAMES={'qwen7':'Qwen 2.5 7B','granite2':'Granite 3.3 2B'}
LABELS={'kite_display':'Kite display','oral_history':'Oral history recording'}

class Demo:
    def __init__(self):self.evidence=Evidence();self.sessions={};self.lock=threading.RLock()
    def catalog(self):return dict(models=[dict(id=k,label=v) for k,v in NAMES.items()],scenarios=[dict(id=k,label=LABELS.get(k,k.replace('_',' ').title())) for k in self.evidence.scenarios],threshold=self.evidence.base['threshold'],reports=self.evidence.reports,total_answers=sum(len(r) for r in self.evidence.paths.values()))
    def session(self,body):
        model=body.get('model','qwen7');family=body.get('family',next(iter(self.evidence.scenarios)));length=body.get('length','compact');load=body.get('load',4)
        if type(load)!=int or (model,family,length,load) not in self.evidence.paths:raise ValueError('Choose an available recorded conversation')
        sid=secrets.token_urlsafe(24)
        self.sessions[sid]=dict(id=sid,key=(model,family,length,load),turn=0,predicted=False,revealed=False,profile=False,access=time.monotonic())
        # Discard abandoned browser sessions after twelve hours.
        for old,s in list(self.sessions.items()):
            if time.monotonic()-s['access']>43200:self.sessions.pop(old,None)
        return self.view(self.sessions[sid])
    def get(self,sid):
        if sid not in self.sessions:raise ValueError('Replay expired. Choose a conversation to start again.')
        s=self.sessions[sid];s['access']=time.monotonic();return s
    def act(self,body):
        s=self.get(body.get('session'));action=body.get('action')
        if action=='predict':s['predicted']=True
        elif action=='reveal':
            if not s['predicted']:raise ValueError('Predict risk before revealing the recorded answer')
            s['revealed']=True
        elif action=='next':
            if not s['revealed'] or s['turn']>=11:raise ValueError('Reveal this answer before continuing')
            s.update(turn=s['turn']+1,predicted=False,revealed=False)
        elif action=='profile':
            if s['key'][0]!='granite2' or type(body.get('enabled'))!=bool:raise ValueError('Profile is available for Granite only')
            s['profile']=body['enabled']
        else:raise ValueError('Unknown replay action')
        return self.view(s)
    def detector_input(self,sid):
        s=self.get(sid)
        if not s['revealed']:raise ValueError('Reveal the recorded answer before opening it in the detector.')
        row=self.evidence.paths[s['key']][s['turn']]
        messages=row['messages_before']
        return dict(policy='\n'.join(m['content'] for m in messages if m['role']=='system'),
                    user=messages[-1]['content'],response=row['response'],reference='',
                    history=[m for m in messages[:-1] if m['role']!='system'],
                    source=f"Genuine {NAMES[s['key'][0]]} recorded answer · turn {s['turn']+1}")
    @staticmethod
    def request(text):return text.split('Additional background documents',1)[0].strip()
    def view(self,s):
        model,family,length,load=s['key'];rows=self.evidence.paths[s['key']];t=s['turn'];r=rows[t]
        predictions=self.evidence.predict(r,rows[:t],model,s['profile']) if s['predicted'] else None
        outcome=self.evidence.outcome(r,predictions) if s['revealed'] else None
        history=[];totals=dict(opportunities=0,events=0,warned=0,false_alarms=0)
        for i in range(t+int(s['revealed'])):
            old=rows[i];p=self.evidence.predict(old,rows[:i],model,s['profile']);o=self.evidence.outcome(old,p)
            if i<t:history.append(dict(turn=i+1,request=self.request(old['messages_before'][-1]['content']),answer=old['response'],checks=o['checks'],capped=o['capped']))
            for prediction,check in zip(p,o['checks']):
                if prediction['risk'] is not None and old['eligible_primary']:
                    totals['opportunities']+=1;totals['events']+=not check['passed'];totals['warned']+=check['kind']=='warned';totals['false_alarms']+=check['kind']=='false_alarm'
        content=r['messages_before'][0]['content']
        facts=content.split('Established facts: ',1)[-1].split('\nREGISTERED RULES',1)[0]
        return dict(session=s['id'],model=model,model_label=NAMES[model],family=family,family_label=LABELS.get(family,family),length=length,load=load,
            turn=t+1,total_turns=12,predicted=s['predicted'],revealed=s['revealed'],profile_on=s['profile'],
            request=self.request(r['messages_before'][-1]['content']),facts=facts,
            background_added='Additional background documents' in r['messages_before'][-1]['content'],prompt_tokens=r['prompt_tokens'],
            rules=[dict(id=x['id'],text=x['text'],value=x['value'],focal=x['type'] in ('word_limit','ending')) for x in r['rules']],
            history=history,predictions=predictions,outcome=outcome,totals=totals)
