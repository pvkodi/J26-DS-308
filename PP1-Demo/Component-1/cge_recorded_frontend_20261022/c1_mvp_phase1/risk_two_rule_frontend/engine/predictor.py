"""Portable state predictor and independently fitted target profile."""
import json,math,re
from checks import word_count

FOCAL=('word_limit','ending')
def eligibility(rule,history):
    if not history:return 'initial_compliance_not_established'
    unknown=False
    for r in history:
        if not r['eligible_primary']:unknown=True;continue
        c=next((c for c in r['checks'] if c['id']==rule['id']),None)
        if c is None:unknown=True
        elif not c['passed']:return 'already_failed'
    return 'history_unresolved' if unknown else 'at_risk_before_first_failure'
def vector(f,rule,messages):
    prior=[word_count(m['content']) for m in messages if m['role']=='assistant'][-3:]
    req=messages[-1]['content'].split('Additional background documents',1)[0].lower()
    v=dict(rule_type=rule['type'],log_context=math.log1p(f['prompt_tokens'])/math.log1p(24000),load=f['active_rules']/8,
      turns=f['prior_turns']/12,instruction_distance=math.log1p(f['tokens_since_latest_instruction'])/math.log1p(24000),
      request_words=min(word_count(req)/100,3),request_detail=float(bool(re.search(r'thorough|detail|explain|expand|rationale|trade.off|implication',req))),
      request_brief=float(bool(re.search(r'brief|short|compact|concise',req))),previous_words=prior[-1]/120,
      recent_max_words=max(prior)/120,word_growth=(prior[-1]-prior[0])/120)
    # Rule-specific state effects; no family names, model identity or assigned condition IDs.
    for k in ('log_context','load','request_detail','request_brief','previous_words'):
        v[rule['type']+'__'+k]=v[k]
    return v
def sigmoid(x):return 1/(1+math.exp(-x)) if x>=0 else math.exp(x)/(1+math.exp(x))
def logit(p):p=max(1e-6,min(1-1e-6,p));return math.log(p/(1-p))
def probability(v,model):
    if model['kind']=='rule_prior':return model['priors'][v['rule_type']]
    encoded={(k+'='+x if isinstance(x,str) else k):(1.0 if isinstance(x,str) else x) for k,x in v.items()}
    return sigmoid(model['intercept']+sum(c*encoded.get(n,0)/s for n,s,c in zip(model['feature_names'],model['scale'],model['coefficients'])))
def profile_vector(v):return [1.,float(v['rule_type']=='ending'),v['log_context']-.75,v['load']-.75,v['request_detail']]
def adjusted(p,v,profile):return sigmoid(logit(p)+sum(a*b for a,b in zip(profile['coefficients'],profile_vector(v))))
