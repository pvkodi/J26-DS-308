"""Offline services for the separate recorded presentation package."""
import hashlib,json,math,sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent;WORK=ROOT.parent
OLD=WORK/'c1_mvp_phase1/risk_two_rule_frontend'
sys.path.insert(0,str(OLD))
from model import Evidence,digest,eligibility,vector,probability,adjusted,verify,word_count
from server import Demo
sys.path.insert(0,str(WORK/'obligation_detector'))
from detector.core import Detector,registered_ledger
from detector.llm import InferenceError,LocalModel
MODEL_ALIAS='recorded-only'
def detector_baseline():
    path=OLD/'data/detector_baseline.json'
    raw=path.read_bytes()
    expected=(OLD/'data/detector_baseline.sha256').read_text().strip()
    h=hashlib.sha256(raw).hexdigest()
    h_crlf=hashlib.sha256(raw.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')).hexdigest()
    if h!=expected and h_crlf!=expected:
        raise ValueError('Saved detector evidence checksum mismatch')
    return json.loads(path.read_text(encoding='utf-8'))
def model_status():
    return dict(ready=False,model=MODEL_ALIAS,message='Recorded presentation package; no local model required.')
def unavailable(*args,**kwargs):
    raise InferenceError('Live inference is not included. Use the component owner laptop for live runs.')
extract=analyze=generate=live_predictions=unavailable
def exact_report(policy,user,response,rules,history=None,prior=None):
    return Detector(LocalModel()).analyze(policy,user,response,history=history or [],ledger=registered_ledger(policy,rules),prior=prior)
def utc():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
def contributions(v,base):
    if not v:return []
    encoded={(k+'='+x if isinstance(x,str) else k):(1. if isinstance(x,str) else x) for k,x in v.items()}
    return sorted([dict(feature=n,input=encoded.get(n,0),log_odds_contribution=c*encoded.get(n,0)/s) for n,s,c in zip(base['feature_names'],base['scale'],base['coefficients'])],key=lambda x:abs(x['log_odds_contribution']),reverse=True)
