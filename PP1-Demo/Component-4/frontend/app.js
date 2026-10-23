(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const apiRoot = '/api/c4';
  const qs = new URLSearchParams(location.search);
  if (qs.get('embedded') === '1') document.documentElement.classList.add('embedded');
  const pageNames = {'stage-a':'Stage A · Rewrite','stage-b':'Stage B · Optimize',evidence:'Recorded evidence'};
  const state = {page:'stage-a',health:null,profiles:[],recorded:null,selected:null,selectedDirty:false,policy:'',activeSession:null,sessionPolicy:null,lastResult:null,turns:[],pair:'2341',evidence:null};
  const esc = (v) => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pretty = (v) => JSON.stringify(v == null ? {} : v, null, 2);
  const shaShort = (v) => v ? `${String(v).slice(0,12)}…` : '—';
  const asArray = v => Array.isArray(v) ? v : [];
  const percent = v => Number.isFinite(Number(v)) ? `${(100*Number(v)).toFixed(1)}%` : '—';
  function lineDiffMarkup(before, after, labels=['Original','Rewrite']) {
    const beforeText=String(before||'').replace(/\r\n/g,'\n'),afterText=String(after||'').replace(/\r\n/g,'\n');
    const a=beforeText?beforeText.split('\n'):[], b=afterText?afterText.split('\n'):[];
    const n=a.length,m=b.length;
    if(n*m>90000) return `<div class="line-diff"><p class="subtle">Text is too long for an inline line comparison.</p></div>`;
    const dp=Array.from({length:n+1},()=>new Uint32Array(m+1));
    for(let i=n-1;i>=0;i--)for(let j=m-1;j>=0;j--)dp[i][j]=a[i]===b[j]?dp[i+1][j+1]+1:Math.max(dp[i+1][j],dp[i][j+1]);
    const ops=[];let i=0,j=0;
    while(i<n||j<m){
      if(i<n&&j<m&&a[i]===b[j]){ops.push(['same',i+1,j+1,a[i]]);i++;j++;}
      else if(i<n&&(j===m||dp[i+1][j]>=dp[i][j+1])){ops.push(['remove',i+1,null,a[i]]);i++;}
      else{ops.push(['add',null,j+1,b[j]]);j++;}
    }
    const row=(kind,cls,ln,text)=>`<div class="diff-line ${cls} ${kind}"><span class="diff-line-number">${ln||''}</span><code>${esc(text||' ')}</code></div>`;
    const rows=ops.map(([kind,ai,bj,text])=>kind==='same'?row(kind,'same',`${ai} · ${bj}`,text):kind==='remove'?row(kind,'remove',`${ai} · −`,text):row(kind,'add',`+ · ${bj}`,text)).join('');
    return `<div class="line-diff" role="table" aria-label="Line by line comparison"><div class="diff-line diff-head"><span>${esc(labels[0])} · ${n} lines</span><span>${esc(labels[1])} · ${m} lines</span></div>${rows}</div>`;
  }
  function exactMessages(messages){return asArray(messages).map(x=>`${String(x.role||'message').toUpperCase()}\n${String(x.content||'')}`).join('\n\n');}
  async function api(path, options={}) {
    const response = await fetch(`${apiRoot}${path}`, {headers:{'Content-Type':'application/json'}, ...options});
    let body;
    try { body = await response.json(); } catch (_) { body = {}; }
    if (!response.ok) throw new Error(body.error || `${response.status} ${response.statusText}`);
    return body;
  }
  function notice(message, kind='info') {
    const el=$('notice'); el.hidden=!message; el.textContent=message||''; el.className=`notice ${kind==='error'?'error':kind==='success'?'success':''}`;
  }
  function page(name, updateUrl=true) {
    if (!pageNames[name]) name='stage-a';
    state.page=name;document.documentElement.dataset.c4Page=name;
    document.querySelectorAll('.page').forEach(x=>x.hidden=x.id!==`${name}-page`);
    document.querySelectorAll('[data-page]').forEach(x=>x.classList.toggle('active',x.dataset.page===name));
    $('crumb-title').textContent=pageNames[name];
    if($('mode-chip')){
      const unavailable=state.health?.status==='unavailable';
      $('mode-chip').textContent=unavailable?'Service unavailable':name==='stage-a'?'BPO · recorded rewrite':name==='stage-b'?'Frozen residual R · local CPU':'Recorded native-checker evidence';
    }
    if(updateUrl){const u=new URL(location.href);u.searchParams.set('view',name);history.replaceState({},'',u);}
  }
  function versionRows(){return state.profiles.flatMap(p=>asArray(p.versions).map(v=>({...v,profile_id:p.profile_id}))).sort((a,b)=>String(b.created_at||'').localeCompare(String(a.created_at||'')));}
  function renderVersions(){
    const rows=versionRows();
    $('version-list').innerHTML=rows.length?rows.map(v=>{
      const key=`${v.profile_id}:${v.version}`;const selected=state.selected?.key===key;
      return `<button class="version-item ${selected?'selected':''}" data-version="${esc(key)}"><span class="v-title"><span>${esc(v.title||v.profile_id)}</span><span class="badge">v${esc(v.version)}</span></span><p>${esc(v.created_at||'Saved manual version')} · ${esc(v.provenance?.origin||'versioned source')}</p></button>`;
    }).join(''):'<div class="empty-state">No saved manual versions are available yet. Create one from a policy in the editor.</div>';
    $('use-version').disabled=!state.selected;
  }
  function selectVersion(key){
    state.bpoReplayToken=(state.bpoReplayToken||0)+1;
    if($('bpo-preview-answers'))$('bpo-preview-answers').textContent='Manual saved version. No recorded BPO answer is attached to this version.';
    const v=versionRows().find(x=>`${x.profile_id}:${x.version}`===key); if(!v)return;
    const siblings=state.profiles.find(p=>p.profile_id===v.profile_id)?.versions||[];const idx=siblings.findIndex(x=>x.version===v.version);const previous=idx>0?siblings[idx-1]:null;
    state.selected={...v,key};state.selectedDirty=false;
    $('version-name').textContent=`${v.title||v.profile_id} · version ${v.version}`;
    $('version-origin').textContent=`${v.profile_id} · ${v.created_at||'saved'}`;
    $('version-state').textContent='Saved version';
    $('original-policy').value=v.source_prompt||v.provenance?.original_prompt||v.provenance?.source_prompt||previous?.prompt||'';
    $('rewrite-policy').value=v.prompt||'';
    $('rewrite-policy').readOnly=false;
    updateEditorDiff(false);
    $('save-version').disabled=false;$('compare-version').disabled=false;$('export-version').disabled=false;
    renderVersions();
  }
  function renderRecorded(){
    const data=state.recorded||{};const cases=asArray(data.cases);
    if(!cases.length){$('bpo-summary').innerHTML=`<p>${esc(data.notice||'No recorded rewrite artifact has been attached to the local service.')}</p><div class="evidence-badges"><span class="badge muted">No saved run substituted</span><span class="badge muted">No live rewrite call available</span></div>`;$('bpo-provenance').textContent=pretty({status:data.status||'not_imported',artifact_sha256:data.artifact_sha256||null});return;}
    const summary=data.summary||{};
    const measuredRate=arm=>{const checks=cases.map(c=>c.arms?.[arm]?.source_evaluator?.pass).filter(x=>typeof x==='boolean');return checks.length?checks.filter(Boolean).length/checks.length:null;};
    const limits=['This development panel is not held-out evidence or a published benchmark score.','Both paired outcomes are ties: the rewrite adds no measured accuracy gain.','Prompt rewriting and target-answer generation were measured separately.','The BPO model was a Q4_K_M CPU adaptation; equivalence to original precision was not established.'];
    $('bpo-summary').innerHTML=`<p>Recorded development panel: source checks pass for both original and rewritten policies, with no measured repairs or regressions.</p><div class="evidence-badges"><span class="badge muted">RECORDED DEVELOPMENT PANEL</span><span class="badge">Original · ${percent(measuredRate('original'))} source-check pass</span><span class="badge">Rewrite · ${percent(measuredRate('bpo'))} source-check pass</span><span class="badge">Repairs · 0.0%</span><span class="badge">Regressions · 0.0%</span></div><details><summary>How to read this result</summary><ul>${limits.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></details><div class="recorded-cases">${cases.slice(0,8).map((c,i)=>{const originalArm=c.arms?.original||{},bpoArm=c.arms?.bpo||{};const original=c.original_prompt||c.source_prompt||c.original||originalArm.system_prompt||'';const rewrite=c.rewrite_prompt||c.optimized_prompt||c.rewrite||bpoArm.system_prompt||'';const originalResponse=c.original_response||originalArm.response||'';const bpoResponse=c.optimized_response||bpoArm.response||'';const evaluator=originalArm.source_evaluator||bpoArm.source_evaluator;return `<details class="recorded-case"><summary>${esc(c.title||c.case_id||`Recorded example ${i+1}`)}</summary><div class="pair-view"><div class="pair-context"><h3>Original policy / prompt</h3><pre>${esc(original)}</pre>${originalResponse?`<p class="subtle">Recorded answer · ${esc(shaShort(originalArm.response_sha256||c.metrics?.original_response_sha256))}</p><pre>${esc(originalResponse)}</pre>`:''}</div><div class="pair-context"><h3>Recorded rewrite</h3><pre>${esc(rewrite)}</pre>${bpoResponse?`<p class="subtle">Recorded answer · ${esc(shaShort(bpoArm.response_sha256||c.metrics?.optimized_response_sha256))}</p><pre>${esc(bpoResponse)}</pre>`:''}</div></div><details class="line-diff-details"><summary>Line-by-line policy changes</summary>${lineDiffMarkup(original,rewrite,['Original','Rewrite'])}</details>${evaluator?`<p class="subtle">Source evaluator ${esc(evaluator.name||'exact-text match')} · original ${percent(originalArm.source_evaluator?.pass?1:0)} · rewrite ${percent(bpoArm.source_evaluator?.pass?1:0)}</p>`:''}<button class="button" data-recorded-version="${i}">Open rewrite in version editor</button>${c.metrics?`<details><summary>Case receipt</summary><pre>${esc(pretty(c.metrics))}</pre></details>`:''}</details>`;}).join('')}</div>`;
    $('bpo-provenance').textContent=pretty({status:data.status,artifact_sha256:data.artifact_sha256,artifact_path:data.artifact_path,provenance:data.provenance,case_count:cases.length});
  }
  async function loadStageA(){
    const [recorded,profiles]=await Promise.all([api('/stage-a/recorded'),api('/stage-a/versions')]);
    state.recorded=recorded;state.profiles=asArray(profiles.profiles);renderRecorded();renderVersions();
    const cases=asArray(recorded.cases),picker=$('bpo-example-picker');
    if(picker){picker.innerHTML=cases.length?cases.map((c,i)=>`<option value="${i}">${esc(c.title||c.case_id||'Recorded example')}</option>`).join(''):'<option value="">No recorded examples available</option>';}
    if(picker && state.selected?.provenance?.recorded){const active=cases.findIndex(c=>c.case_id===state.selected.provenance.case_id);if(active>=0)picker.value=String(active);}
    if(!state.selected && cases.length) prepareRecordedExample(state.bpoPreviewIndex||0);
    else if(!state.selected && versionRows().length) selectVersion(`${versionRows()[0].profile_id}:${versionRows()[0].version}`);
    if(!cases.length && $('bpo-preview-answers'))$('bpo-preview-answers').textContent='No recorded run is available. No result has been substituted.';
  }
  function makeManualVersion(){
    state.bpoReplayToken=(state.bpoReplayToken||0)+1;
    if($('bpo-preview-answers'))$('bpo-preview-answers').textContent='Manual draft. No recorded BPO answer is attached to this draft.';
    const policy=$('rewrite-policy').value.trim()||$('original-policy').value.trim();
    if(!policy){notice('Enter or select a policy before creating a manual version.','error');return;}
    $('original-policy').value=$('original-policy').value||policy;
    $('rewrite-policy').value=policy;$('rewrite-policy').readOnly=false;
    $('version-name').textContent='New manual policy';$('version-origin').textContent='Manual entry · not BPO optimized';$('version-state').textContent='Unsaved draft';
    state.selected={key:null,profile_id:null,version:null,title:'Manual policy'};state.selectedDirty=true;
    $('save-version').disabled=false;$('compare-version').disabled=false;$('use-version').disabled=false;$('export-version').disabled=true;
    notice('Manual policy draft opened. Saving creates a versioned record; it does not claim a Stage A optimizer run.');
  }
  function prepareRecordedExample(index){
    const c=asArray(state.recorded?.cases)[Number(index)];if(!c)return;
    state.bpoReplayToken=(state.bpoReplayToken||0)+1;state.bpoPreviewIndex=Number(index);state.bpoAwaiting=true;
    state.selected=null;state.selectedDirty=false;
    const original=c.original_prompt||c.source_prompt||c.original||c.arms?.original?.system_prompt||'';
    $('original-policy').value=original;$('rewrite-policy').value='';$('rewrite-policy').readOnly=true;
    $('rewrite-policy').placeholder='Click Rewrite below the original prompt to reveal the saved BPO rewrite.';
    $('original-line-numbers').textContent=original.split(/\r?\n/).map((_,i)=>i+1).join('\n');$('rewrite-line-numbers').textContent='';
    $('version-name').textContent=c.title||'Recorded BPO example';$('version-origin').textContent='Original loaded · saved rewrite hidden';$('version-state').textContent='Ready to replay';
    $('diff-panel').hidden=true;$('diff-panel').open=false;
    for(const id of ['save-version','compare-version','use-version','export-version'])$(id).disabled=true;
    $('bpo-example-picker').value=String(index);
    $('bpo-replay-button').disabled=false;$('bpo-replay-button').textContent='Rewrite';
    $('bpo-preview-answers').textContent='Recorded playback with a 1.5-second presentation delay. This is not live BPO generation or measured inference latency.';
    notice('');
  }
  function replayRecordedRewrite(){
    const index=Number($('bpo-example-picker').value);if(!asArray(state.recorded?.cases)[index])return;
    prepareRecordedExample(index);
    const token=(state.bpoReplayToken||0)+1;state.bpoReplayToken=token;
    $('bpo-replay-button').disabled=true;$('bpo-replay-button').textContent='Replaying saved rewrite…';
    $('bpo-preview-answers').textContent='Replaying the recorded BPO result… Presentation delay: 1.5 seconds. No model call is being made.';
    setTimeout(()=>{if(state.bpoReplayToken!==token)return;state.bpoAwaiting=false;openRecordedVersion(index);$('bpo-replay-button').disabled=false;$('bpo-replay-button').textContent='Rewrite';},1500);
  }
  function showBpoPreview(c,index){
    if($('bpo-example-picker'))$('bpo-example-picker').value=String(index);
    const a=c.arms?.original||{},b=c.arms?.bpo||{};
    const before=c.original_response||a.response||'',after=c.optimized_response||b.response||'';
    if($('bpo-preview-answers'))$('bpo-preview-answers').textContent=`Saved original answer: ${before}  •  Saved BPO answer: ${after}  •  Recorded outputs, not a live BPO run.`;
  }
  function openRecordedVersion(index){const c=asArray(state.recorded?.cases)[Number(index)];if(!c)return;const originalArm=c.arms?.original||{},bpoArm=c.arms?.bpo||{};const original=c.original_prompt||c.source_prompt||c.original||originalArm.system_prompt||'';const rewrite=c.rewrite_prompt||c.optimized_prompt||c.rewrite||bpoArm.system_prompt||'';showBpoPreview(c,index);if(!original&&!rewrite){notice('This recorded row has no source/rewrite text to load.','error');return;}$('original-policy').value=original;$('rewrite-policy').value=rewrite;$('rewrite-policy').readOnly=false;$('version-name').textContent=c.title||c.case_id||`Recorded BPO example ${Number(index)+1}`;$('version-origin').textContent='Recorded optimizer output · inspect before reuse';$('version-state').textContent='Recorded BPO · unsaved draft';state.selected={key:null,profile_id:null,version:null,title:c.title||'Recorded BPO candidate',provenance:{recorded:true,case_id:c.case_id||null}};state.selectedDirty=true;$('save-version').disabled=false;$('compare-version').disabled=false;$('use-version').disabled=!rewrite;$('export-version').disabled=true;compare();notice('Loaded a saved BPO comparison. It is a recorded result; using it sends the visible draft, and saving creates a separate manual policy version.');}
  async function saveVersion(){
    const prompt=$('rewrite-policy').value.trim();if(!prompt){notice('The policy cannot be empty.','error');return;}
    const body={title:state.selected?.title||'Manual policy',prompt,source_prompt:$('original-policy').value};
    const saved=state.selected?.profile_id?await api(`/stage-a/versions/${encodeURIComponent(state.selected.profile_id)}`,{method:'PUT',body:JSON.stringify(body)}):await api('/stage-a/versions',{method:'POST',body:JSON.stringify(body)});
    const prior=state.selected;await loadStageA();const profile_id=saved.profile_id||prior?.profile_id;const version=saved.version||1;
    selectVersion(`${profile_id}:${version}`);notice('Saved as an immutable manual version. No BPO optimizer call was made.','success');
  }
  function useVersion(){if(!state.selected)return;state.policy=$('rewrite-policy').value;$('stage-b-policy').value=state.policy;$('rule-excerpts').value='';const provenance=state.selectedDirty?'Unsaved draft':'Saved version';const choice={handoff_id:crypto.randomUUID(),prompt:state.policy,title:state.selected.title||state.selected.profile_id||'policy',profile_id:state.selected.profile_id||null,version:state.selected.version||null,provenance};try{localStorage.setItem('component4:selected-policy-v1',JSON.stringify(choice));}catch(_){}$('frozen-policy-label').textContent=`${provenance}: ${choice.title} · ${choice.version?`v${choice.version}`:'not saved'}`;invalidateStageB();if(window.parent!==window&&qs.get('embedded')==='1')window.parent.postMessage({type:'component4:navigate',view:'stage-b'},location.origin);else page('stage-b');notice(`${provenance} copied into the Stage B call form. The policy remains editable for this call.`);}
  function exportVersion(){if(!state.selected||state.selectedDirty||!state.selected.profile_id||!state.selected.version)return;const data={schema:'component4_policy_version_export_v1',profile_id:state.selected.profile_id,version:state.selected.version,title:state.selected.title,prompt:state.selected.prompt,source_prompt:state.selected.source_prompt||null,provenance:state.selected.provenance||null};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`component4-policy-${state.selected.profile_id}-v${state.selected.version}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1200);}
  function diffText(a,b){const aa=a.split('\n'),bb=b.split('\n'),n=Math.max(aa.length,bb.length),out=[];for(let i=0;i<n;i++){if(aa[i]===bb[i])out.push(`  ${aa[i]||''}`);else{if(aa[i]!==undefined)out.push(`- ${aa[i]}`);if(bb[i]!==undefined)out.push(`+ ${bb[i]}`);}}return out.join('\n');}
  function compare(){ updateEditorDiff(true); }
  function updateEditorDiff(open=false){
    const a=$('original-policy')?.value||'',b=$('rewrite-policy')?.value||'';
    if($('original-line-numbers'))$('original-line-numbers').textContent=a.split(/\r?\n/).map((_,i)=>i+1).join('\n');
    if($('rewrite-line-numbers'))$('rewrite-line-numbers').textContent=b.split(/\r?\n/).map((_,i)=>i+1).join('\n');
    if($('original-line-numbers')&&$('original-policy'))$('original-line-numbers').scrollTop=$('original-policy').scrollTop;
    if($('rewrite-line-numbers')&&$('rewrite-policy'))$('rewrite-line-numbers').scrollTop=$('rewrite-policy').scrollTop;
    if($('diff-text'))$('diff-text').innerHTML=lineDiffMarkup(a,b,['Original policy','Rewrite']);
    if($('diff-panel')){ $('diff-panel').hidden=false;if(open)$('diff-panel').open=true; }
  }
  function markStageADraft(){
    if($('bpo-preview-answers'))$('bpo-preview-answers').textContent='Draft edited. Recorded answers apply only to the saved example, not to this edited draft.';
    if(!state.selected)return;
    state.selectedDirty=true;
    $('version-state').textContent='Unsaved draft';
    $('version-origin').textContent='Changes are not part of the selected saved version';
    $('save-version').disabled=false;
    $('export-version').disabled=true;
    $('use-version').disabled=!$('rewrite-policy').value.trim();
  }
  function invalidateStageB(){
    state.lastResult=null;
    $('decision-content').hidden=true;$('decision-empty').hidden=false;
    $('decision-empty').textContent='Inputs changed. Run Stage B again to see results for this exact policy and context.';
    $('selected-count').textContent='Rerun required';
    $('cache-badge').textContent='Input changed · rerun required';$('cache-badge').className='cache-badge warn';
    $('latency-label').textContent='Latency appears after a real local run.';
    if($('retry-selection-button'))$('retry-selection-button').disabled=true;
    if($('export-session-button'))$('export-session-button').disabled=!state.activeSession;
    if($('stage-b-workspace-status'))$('stage-b-workspace-status').textContent='Edited inputs · run the selector again to refresh this result.';
  }
  function renderResult(value){
    state.lastResult=value;$('decision-empty').hidden=true;$('decision-content').hidden=false;
    if($('retry-selection-button'))$('retry-selection-button').disabled=false;
    if($('export-session-button'))$('export-session-button').disabled=!state.activeSession;
    const selected=Boolean(value.selected);const selectedIds=asArray(value.selected_rule_ids).map(String);const scoreArr=asArray(value.model_score);const candidateRules=asArray(value.candidate_rules);
    $('selected-count').textContent=selected?`${selectedIds.length||1} selected`:'Identity · no suffix';
    const t=value.timing_ms||{};const token=value;
    $('turn-stats').innerHTML=[['CANDIDATES',`${candidateRules.length||1} rule${(candidateRules.length||1)===1?'':'s'}`],['SELECTED',selected?`${selectedIds.length} rule${selectedIds.length===1?'':'s'}`:'Identity · no suffix'],['SELECTOR SCORES',scoreArr.length?scoreArr.map(v=>Number(v).toFixed(3)).join(' · '):'Unavailable']].map(([k,v])=>`<div class="stat"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join('');
    $('selection-list').innerHTML=(value.demo_guard?.applied?`<div class="notice"><b>Context-sensitive selection policy</b><p>${esc(value.demo_guard.reason)}</p><p><details><summary>Model and policy details</summary>CPU model prediction: ${asArray(value.raw_model_selected_rule_ids).length?'repeat':'do not repeat'}. The backend applies a deterministic language and capitalization gate to this example. Scores below are raw model scores, not conflict probabilities.</details></p></div>`:'')+(candidateRules.length?candidateRules:[{id:'0',text:$('stage-b-policy').value}]).map((r,i)=>{const active=selectedIds.includes(String(r.id));const score=scoreArr[i];return `<article class="selection"><header><b>${active?'Selected for repetition':'Not repeated'}</b><span class="score">${Number.isFinite(Number(score))?Number(score).toFixed(4):'score unavailable'}</span></header><p>${esc(r.text)}</p></article>`}).join('')+`<p class="subtle">${selected?'A request-specific suffix was appended.':(value.demo_guard?.applied?'The backend selection policy chose no extra reminder for this context.':'The frozen selector chose identity for this context.')} The standing policy remains in the original system message. · threshold ${esc(value.checkpoint_bindings?.threshold??'—')} · checkpoint ${esc(shaShort(value.checkpoint_bindings?.selected_state_sha256))}</p>`;
    const originalPrefix=[{role:'system',content:$('stage-b-policy').value},{role:'user',content:activeContext().context}];
    const optimizedMessages=asArray(value.optimized_messages);
    const prefixPreserved=optimizedMessages.length>=originalPrefix.length&&originalPrefix.every((m,i)=>optimizedMessages[i]?.role===m.role&&optimizedMessages[i]?.content===m.content);
    const suffixMessages=prefixPreserved?optimizedMessages.slice(originalPrefix.length):[];
    const suffixText=suffixMessages.map(m=>`${String(m.role||'message').toUpperCase()} · appended\n${String(m.content||'')}`).join('\n\n')||String(value.suffix||'');
    const prefixText=exactMessages(originalPrefix);
    if($('prefix-display'))$('prefix-display').innerHTML=`<div class="prefix-lock-badge">${prefixPreserved?'Original system and user prefix preserved byte for byte':'Original prefix comparison unavailable'}</div><pre>${esc(prefixText)}</pre>`;
    if($('suffix-display'))$('suffix-display').innerHTML=suffixText?lineDiffMarkup('',suffixText,['No suffix','New appended suffix']):'<p class="subtle">Identity selected · no suffix appended.</p>';
    $('rendered-suffix').textContent=value.suffix||'(No additional suffix was selected.)';$('optimized-messages').textContent=pretty(optimizedMessages);
    $('token-stats').innerHTML=`<span><small>Native prefix</small><strong>${esc(token.native_prefix_tokens??'—')}</strong><em>tokens</em></span><span><small>Optimized request</small><strong>${esc(token.optimized_native_tokens??'—')}</strong><em>tokens</em></span><span><small>Added suffix</small><strong>${esc(token.added_native_tokens??'—')}</strong><em>tokens</em></span><span><small>Request binding</small><strong>${esc(shaShort(value.request_sha256))}</strong></span>`;
    const prefix=Boolean(value.native_prefix_preserved);$('cache-badge').textContent=prefix?'Native token prefix verified · no KV-cache claim':'Prefix verification unavailable';$('cache-badge').className=`cache-badge ${prefix?'ok':'warn'}`;
    $('latency-label').textContent=`Local selector ${Number(t.selection||0).toFixed(1)} ms · request planning ${Number(t.request_total||0).toFixed(1)} ms · model startup ${Number(t.process_model_startup||0).toFixed(0)} ms (separate)`;
    refreshSession().catch(()=>{});
  }
  function activeContext(){const history=$('history-input').value.trim(),current=$('current-input').value.trim();return {history,current,context:history?`Earlier conversation context:\n${history}\n\nCurrent user message:\n${current}`:current};}
  async function optimize(){
    if(state.selecting)return;
    const inputBinding=()=>JSON.stringify(['stage-b-policy','history-input','current-input','rule-excerpts'].map(id=>$(id).value));
    const submittedBinding=inputBinding();
    const policy=$('stage-b-policy').value.trim(),ctx=activeContext();if(!policy||!ctx.current){notice('Enter the governing policy and current user message first.','error');return;}
    invalidateStageB();state.selecting=true;
    document.querySelectorAll('[data-pair],[data-use-pair-context]').forEach(b=>b.disabled=true);
    $('optimize-button').disabled=true;$('optimize-status').textContent='Calling the local CPU selector…';if($('stage-b-workspace-status'))$('stage-b-workspace-status').textContent='Selecting from the current policy and context…';notice('');
    try{
      if(!state.activeSession||state.sessionPolicy!==policy){const created=await api('/sessions',{method:'POST',body:JSON.stringify({title:$('conversation-id').value||'Component 4 conversation',policy})});state.activeSession=created.session_id;state.sessionPolicy=policy;}
      // Keep the model context and final native user message identical. The
      // optional history is explicitly presented as context text within that
      // user message; we do not invent role turns from a free-text field.
      const native_messages=[{role:'system',content:policy},{role:'user',content:ctx.context}];
      const rulesText=$('rule-excerpts').value;const ruleLines=rulesText.split(/\r?\n/).filter(x=>x.trim());const rules=ruleLines.length?ruleLines.map((text,i)=>({id:`rule-${String(i+1).padStart(2,'0')}`,text})):undefined;
      const result=await api('/turns',{method:'POST',body:JSON.stringify({session_id:state.activeSession,policy,context:ctx.context,native_messages,demo_language_guard:true,...(rules?{rules}:{})})});
      if(inputBinding()!==submittedBinding){invalidateStageB();$('optimize-status').textContent='Previous input finished. Your edits need a new run.';notice('Inputs changed while selection was running. Click Optimize to run the edited context.');return;}
      renderResult(result);$('decision-content').scrollIntoView({block:'start',behavior:'smooth'});$('optimize-status').textContent=`Saved turn · ${new Date(result.created_at||Date.now()).toLocaleTimeString()}`;if($('stage-b-workspace-status'))$('stage-b-workspace-status').textContent='Current result matches the visible policy and context.';notice('Stage B completed a real local CPU selection. No answer-generation call was made.','success');
      await refreshSession();
    }catch(e){$('optimize-status').textContent='The local selection did not complete.';if($('stage-b-workspace-status'))$('stage-b-workspace-status').textContent='No result was saved for these inputs.';notice(`Stage B failed: ${e.message}`,'error');}
    finally{state.selecting=false;$('optimize-button').disabled=false;document.querySelectorAll('[data-pair],[data-use-pair-context]').forEach(b=>b.disabled=false);}
  }
  function newPromptWorkspace(){
    $('history-input').value='';$('current-input').value='';$('conversation-id').value='Component 4 session';
    state.activeSession=null;state.sessionPolicy=null;state.turns=[];
    state.selectedExample=null;if($('resume-session'))$('resume-session').value='';
    $('turn-history').innerHTML='<div class="empty-state">New workspace. Choose an evaluated example above or enter your own inputs.</div>';
    $('optimize-status').textContent='No request has been sent.';invalidateStageB();
    if($('retry-selection-button'))$('retry-selection-button').disabled=true;
    if($('export-session-button'))$('export-session-button').disabled=true;
    if($('stage-b-workspace-status'))$('stage-b-workspace-status').textContent='New prompt workspace · saved sessions were kept.';
    notice('Started a new prompt workspace. The current policy and rule excerpts remain; prior saved sessions were not changed.');
  }
  async function exportCurrentSession(){
    if(!state.activeSession){notice('Save a Stage B turn before exporting a session.','error');return;}
    try{const data=await api(`/sessions/${encodeURIComponent(state.activeSession)}/export`);const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`component4-session-${state.activeSession}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1200);notice('Saved session exported. No history was deleted.','success');}
    catch(e){notice(`Could not export this session: ${e.message}`,'error');}
  }
  async function refreshSession(){
    if(!state.activeSession)return;
    const data=await api(`/sessions/${encodeURIComponent(state.activeSession)}`);const turns=asArray(data.turns);state.turns=turns;
    $('turn-history').innerHTML=turns.length?turns.map(t=>`<div class="turn-row"><strong>Turn ${esc(t.turn_index)}</strong><span class="turn-msg">${esc(t.native_messages?.at(-1)?.content||t.context||'')}</span><span class="badge ${t.selected?'ok':''}">${t.selected?'Policy suffix':'Identity'}</span></div>`).join(''):'<div class="empty-state">No turns recorded in this session.</div>';
    await loadSessions();
  }
  async function loadSessions(){
    const groups=asArray((state.evidence?.objects||{}).iheval_recorded_pairs?.pairs);
    $('resume-session').innerHTML='<option value="">Choose an evaluated example…</option>'+groups.map(g=>asArray(g.contexts).map((c,i)=>`<option value="example:${esc(g.source_group_id)}:${i}">${esc(c.system_policy.slice(0,85))} · ${/aligned/i.test(c.source_set)?'Aligned':'Conflicting'}</option>`).join('')).join('');
    if(state.selectedExample)$('resume-session').value=state.selectedExample;
  }
  function loadSavedExample(value){
    const [,gid,index]=value.split(':');state.pair=gid;state.selectedExample=value;renderPair();useRecordedPairContext(Number(index));
    $('resume-session').value=value;
    $('optimize-status').textContent='Saved example loaded. Edit this context or continue with a next turn.';
    notice('Exact evaluated policy and context loaded. Edit either input and click Optimize, or choose Continue with next turn. The saved LLM answers remain unchanged.','success');
  }
  function continueNextTurn(){
    const current=$('current-input').value.trim();if(!current){notice('Load an example or enter a current message first.','error');return;}
    const prior=$('history-input').value.trim();$('history-input').value=[prior,current].filter(Boolean).join('\n\n--- Previous user turn ---\n\n');$('current-input').value='';invalidateStageB();
    $('current-input').focus();notice('Previous context kept above. Type the next user message and click Optimize to run the CPU model.','success');
  }
  async function resumeSession(sessionId){
    if(!sessionId){state.activeSession=null;state.sessionPolicy=null;state.turns=[];if($('export-session-button'))$('export-session-button').disabled=true;$('turn-history').innerHTML='<div class="empty-state">No turns recorded in this session.</div>';return;}
    if($('export-session-button'))$('export-session-button').disabled=false;
    const data=await api(`/sessions/${encodeURIComponent(sessionId)}`);state.activeSession=sessionId;state.sessionPolicy=data.session?.policy||null;if(state.sessionPolicy){$('stage-b-policy').value=state.sessionPolicy;$('frozen-policy-label').textContent=`Resumed policy · ${data.session?.title||'saved session'}`;invalidateStageB();}
    const turns=asArray(data.turns);state.turns=turns;const priorContexts=turns.map(t=>t.native_messages?.at(-1)?.content||t.context||'').filter(Boolean);$('history-input').value=priorContexts.join('\n\n--- Previous turn ---\n\n');$('current-input').value='';invalidateStageB();$('turn-history').innerHTML=turns.length?turns.map(t=>`<div class="turn-row"><strong>Turn ${esc(t.turn_index)}</strong><span class="turn-msg">${esc(t.native_messages?.at(-1)?.content||t.context||'')}</span><span class="badge ${t.selected?'ok':''}">${t.selected?'Policy suffix':'Identity'}</span></div>`).join(''):'<div class="empty-state">No turns recorded in this session.</div>';notice(`Resumed saved conversation · ${turns.length} turn${turns.length===1?'':'s'} loaded. Enter the next user message to continue.`,'success');
  }
  function renderPair(){
    const objects=state.evidence?.objects||state.evidence||{};const pairBundle=objects.iheval_recorded_pairs||{};const pairs=asArray(pairBundle.pairs);const group=pairs.find(x=>String(x.source_group_id)===state.pair);
    if(!group){$('pair-view').innerHTML='<div class="empty-state">Frozen context-pair recording is not available from the local service yet. No synthetic response was substituted.</div>';return;}
    const picker=$('iheval-all-examples');if(picker){picker.innerHTML=pairs.map(p=>`<option value="${esc(p.source_group_id)}">${esc(asArray(p.contexts)[0]?.system_policy?.slice(0,110)||p.source_group_id)}</option>`).join('');picker.value=state.pair;}
    const contexts=asArray(group.contexts),armLabels={identity:'Original',frozen_residual_R_restatement:'Residual R',composite_utility_critic_selected_plan:'Composite plan'};
    $('pair-view').innerHTML=contexts.map((c,i)=>{
      const sourceSet=String(c.source_set||'');const friendly=/aligned/i.test(sourceSet)?'Aligned request':/conflict/i.test(sourceSet)?'Conflicting request':`Recorded context ${i+1}`;
      const arms=Object.entries(armLabels).map(([key,label])=>{const a=c.arms?.[key];if(!a)return '';const check=a.official_checker||{},hasVerdict=typeof check.prompt_all_pass==='boolean',verdict=hasVerdict?(check.prompt_all_pass?'PASS':'FAIL'):'CHECK UNAVAILABLE',verdictClass=hasVerdict?(check.prompt_all_pass?'pass':'fail'):'unknown';return `<details class="arm-recording"><summary>${esc(label)} · <span class="recorded-verdict ${verdictClass}">${verdict}</span></summary><span class="badge muted">RECORDED SOURCE RESPONSE</span><p class="subtle">${asArray(a.native_messages).length>2?'Saved optimization: suffix appended':'Saved optimization: original request unchanged'}</p><pre>${esc(a.response||'')}</pre><details><summary>Exact saved request and suffix</summary><pre>${esc(exactMessages(a.native_messages))}</pre></details><p class="subtle">Response ${esc(shaShort(a.response_sha256))} · EOS ${esc(a.eos_terminated===true?'yes':a.eos_terminated===false?'no':'unknown')} · not regenerated</p></details>`}).join('');
      return `<article class="pair-context"><h3>${esc(friendly)}</h3><p class="context-quote">${esc(c.user_context||'')}</p><p class="subtle"><b>Same system policy:</b> ${esc(c.system_policy||'')}</p><button class="button" data-use-pair-context="${i}">Load &amp; optimize this context</button><div class="arm-recordings">${arms}</div><details class="source-metadata"><summary>Source and checker details</summary><p class="subtle">${esc(c.case_id||'')}<br>${esc(sourceSet)}<br><b>Native checkers:</b> ${esc((c.checker_ids||[]).join(', '))}<br>kwargs ${esc(pretty(c.checker_kwargs||[]))}</p></details></article>`;
    }).join('');
  }
  function useRecordedPairContext(index){
    const objects=state.evidence?.objects||state.evidence||{};const groups=asArray(objects.iheval_recorded_pairs?.pairs);const group=groups.find(x=>String(x.source_group_id)===state.pair);const c=asArray(group?.contexts)[Number(index)];if(!c)return;
    $('stage-b-policy').value=c.system_policy||'';$('history-input').value='';$('current-input').value=c.user_context||'';$('rule-excerpts').value='';$('conversation-id').value=`IHEval ${c.case_id||state.pair} live selector`;state.activeSession=null;state.sessionPolicy=null;state.turns=[];
    $('frozen-policy-label').textContent=`Source policy loaded · ${c.case_id||state.pair}`;invalidateStageB();page('stage-b',false);$('stage-b-policy').scrollIntoView({block:'start',behavior:'smooth'});notice('Example loaded into the editable workspace. Running the trained CPU selector on this policy and context.');
  }
  function renderEvidence(){
    const d=state.evidence||{};const o=d.objects||{};const iheval=o.iheval_official_metrics||{};const ihevalSummary=o.iheval_summary||{};const ifbench=o.ifbench_scores||{};const latency=o.ifbench_latency||{};const iArms=iheval.full32_observed_official_metrics_by_arm||{};const fArms=ifbench.arms||{};
    const methodLabel={identity:'Original',frozen_residual_R_restatement:'Residual R',composite_utility_critic_selected_plan:'Composite plan',new_composite_utility_critic_selected_plan:'Composite plan'};
    const ihevalRows=Object.entries(iArms).map(([k,v])=>`<div class="metric-row"><span>${esc(methodLabel[k]||k)}</span><b>Strict all-pass · ${percent(v.strict_prompt_all_pass_observed_only)}</b><b>Loose all-pass · ${percent(v.loose_prompt_all_pass_observed_only)}</b><b>Instruction checks · ${percent(v.strict_instruction_accuracy_observed_only)}</b></div>`).join('');
    const ifRows=Object.entries(fArms).map(([k,v])=>`<div class="metric-row"><span>${esc(methodLabel[k]||k)}</span><b>Strict all-pass · ${percent(v.strict_prompt_success_rate)}</b><b>Loose all-pass · ${percent(v.loose_prompt_success_rate)}</b><b>Required checks · ${percent(v.strict_constraint_success_rate)}</b></div>`).join('');
    const latencyRows=(latency.passes||[]).map(x=>`<div class="metric-row"><span>${esc(methodLabel[x.method]||x.method)} · ${x.pass==='first_32_case_pass'?'first':'repeat'}</span><b>p50 · ${Number(x.latency?.p50_ms).toFixed(1)} ms</b><b>p95 · ${Number(x.latency?.p95_ms).toFixed(1)} ms</b></div>`).join('');
    const iRepairs=percent((ihevalSummary.paired_vs_identity_strict?.repairs||0)/32),iRegressions=percent((ihevalSummary.paired_vs_identity_strict?.regressions||0)/32),iCi=asArray(ihevalSummary.paired_vs_identity_strict?.source_group_bootstrap_95_ci).map(x=>`${(100*x).toFixed(1)} percentage points`).join(' to ');
    const rPair=ifbench.paired_vs_identity?.frozen_residual_R_restatement?.strict_prompt||{},cPair=ifbench.paired_vs_identity?.new_composite_utility_critic_selected_plan?.strict_prompt||{};
    const rRepair=percent((rPair.repairs||0)/32),rRegression=percent((rPair.regressions||0)/32),cRepair=percent((cPair.repairs||0)/32),cRegression=percent((cPair.regressions||0)/32);
    const cards=`<article class="metric-card"><span class="scope-tag">RECORDED · SELECTED IHEVAL PILOT</span><h3>IHEval · native strict / loose checkers</h3><p>Selected priority-conflict pilot; this is not the full IHEval benchmark.</p><div class="metric-row"><span>Method</span><b>Strict all-pass</b><b>Loose all-pass</b><b>Instruction checks</b></div>${ihevalRows||'<p>Frozen metrics unavailable.</p>'}<p class="metric-note">Residual R moved strict all-pass from ${percent(iArms.identity?.strict_prompt_all_pass_observed_only)} to ${percent(iArms.frozen_residual_R_restatement?.strict_prompt_all_pass_observed_only)}: ${iRepairs} repairs and ${iRegressions} regressions against the original. The paired source-group interval is ${iCi}.</p><details><summary>Result and independent-audit receipts</summary><pre>${esc(pretty({metrics:iheval,summary:ihevalSummary,audit:o.iheval_independent_audit}))}</pre></details></article>
      <article class="metric-card"><span class="scope-tag">RECORDED · ALL LISTED CONSTRAINTS REQUIRED</span><h3>IFBench · native constraint checkers</h3><p>These prompts require every listed constraint. Native checker passes measure those constraints and can still miss substantive task omissions.</p><div class="metric-row"><span>Method</span><b>Strict all-pass</b><b>Loose all-pass</b><b>Required checks</b></div>${ifRows||'<p>Frozen metrics unavailable.</p>'}<p class="metric-note">Residual R matches the original at ${percent(fArms.identity?.strict_prompt_success_rate)} strict all-pass, with ${rRepair} repairs and ${rRegression} regressions. The composite plan reached ${percent(fArms.new_composite_utility_critic_selected_plan?.strict_prompt_success_rate)}; its checker accepted “Supplemental Supplemental” while the answer omitted the requested alternate-history narrative. Official scores are preserved; this is not a broad quality result.</p><details><summary>Result and independent-audit receipts</summary><pre>${esc(pretty({scores:ifbench,audit:o.ifbench_independent_audit,paired:{residualR:rPair,composite:cPair},composite_repair_percent:cRepair,composite_regression_percent:cRegression}))}</pre></details></article>
      <article class="metric-card"><span class="scope-tag">RECORDED · LOCAL CPU ONLY</span><h3>Optimizer-path latency</h3><p>First pass through the frozen cohort. This excludes answer generation and is not hosted API latency.</p><div class="metric-row"><span>Method</span><b>p50</b><b>p95</b></div>${latencyRows||'<p>Frozen latency receipt unavailable.</p>'}<p class="metric-note">Cold model startup: ${Number(latency.runtime_cold_load_seconds||0).toFixed(2)} s. Shared per-batch GPU time is not represented as per-call latency.</p><details><summary>Latency receipt</summary><pre>${esc(pretty(latency))}</pre></details></article>`;
    $('metrics-grid').innerHTML=(ihevalRows||ifRows||latencyRows)?cards:'<div class="empty-state">Evaluation receipts are not connected yet. The panel will show only saved, source-bound metrics.</div>';
    $('evidence-scope').innerHTML=`<div class="evidence-scope"><ul><li>Recorded examples and metrics are separate from live CPU selection.</li><li>The results are consistent with the optimizer’s objective: restating governing policy can help when an IHEval context creates a priority conflict, while novel IFBench constraints require task execution beyond relevance selection. This interpretation is not proof of how the model understands context.</li><li>IFBench requires every listed constraint. Its checker pass can miss whether an answer fulfills the substantive task, as the repeated “Supplemental” example shows.</li><li>Never drop a mandatory constraint because an optimizer predicts it is less important. These pilot metrics do not establish general safety or answer quality.</li></ul></div>`;
    $('evidence-receipts').textContent=pretty({status:d.status,manifest_sha256:d.manifest_sha256,manifest:d.manifest,independentAudits:{iheval:o.iheval_independent_audit,ifbench:o.ifbench_independent_audit}});
  }
  async function loadEvidence(){try{state.evidence=await api('/evidence');renderEvidence();renderPair();await loadSessions();}catch(e){state.evidence={};renderEvidence();renderPair();}}
  async function refreshAll(){
    try{const health=await api('/health');state.health=health;$('health-dot').className='dot ok';$('health-label').textContent='Local service ready';$('mode-chip').classList.add('ready');page(state.page,false);}
    catch(e){state.health={status:'unavailable'};$('health-dot').className='dot err';$('health-label').textContent='Local service unavailable';page(state.page,false);}
    try{await loadStageA();}catch(e){$('version-list').innerHTML=`<div class="empty-state">Could not load policy versions: ${esc(e.message)}</div>`;}
    try{await loadSessions();}catch(_){/* health status already shows service availability */}
    await loadEvidence();
  }
  document.addEventListener('click',e=>{
    const nav=e.target.closest('[data-page]');if(nav){if(window.parent!==window&&qs.get('embedded')==='1'){window.parent.postMessage({type:'component4:navigate',view:nav.dataset.page},location.origin);}else page(nav.dataset.page);return;}
    const version=e.target.closest('[data-version]');if(version){selectVersion(version.dataset.version);return;}
    const recorded=e.target.closest('[data-recorded-version]');if(recorded){openRecordedVersion(recorded.dataset.recordedVersion);return;}
    const pair=e.target.closest('[data-pair]');if(pair){if(state.selecting)return;state.pair=pair.dataset.pair;document.querySelectorAll('.pair-tab').forEach(x=>x.classList.toggle('active',x===pair));renderPair();useRecordedPairContext(1);optimize();return;}
    const pairContext=e.target.closest('[data-use-pair-context]');if(pairContext){if(state.selecting)return;useRecordedPairContext(pairContext.dataset.usePairContext);optimize();return;}
    if(e.target.closest('[data-open-about]')){$('about-dialog').showModal();return;}
  });
  if($('iheval-all-examples'))$('iheval-all-examples').onchange=e=>{state.pair=e.target.value;document.querySelectorAll('.pair-tab').forEach(b=>b.classList.toggle('active',b.dataset.pair===state.pair));renderPair();};
  if($('bpo-replay-button'))$('bpo-replay-button').onclick=replayRecordedRewrite;
  if($('bpo-example-picker'))$('bpo-example-picker').onchange=e=>{if(e.target.value!=='')prepareRecordedExample(e.target.value);};
  if($('bpo-reset-example'))$('bpo-reset-example').onclick=()=>{const value=$('bpo-example-picker')?.value;if(value!==''&&value!=null)prepareRecordedExample(value);};
  $('refresh-button').onclick=refreshAll;$('reload-versions').onclick=()=>loadStageA().catch(e=>notice(e.message,'error'));
  $('new-version').onclick=makeManualVersion;$('save-version').onclick=()=>saveVersion().catch(e=>notice(`Could not save version: ${e.message}`,'error'));
  $('use-version').onclick=useVersion;$('export-version').onclick=exportVersion;$('compare-version').onclick=compare;$('optimize-button').onclick=optimize;
  $('resume-session').onchange=e=>{if(e.target.value.startsWith('example:'))loadSavedExample(e.target.value);};
  if($('next-turn-button'))$('next-turn-button').onclick=continueNextTurn;
  if($('new-prompt-button'))$('new-prompt-button').onclick=newPromptWorkspace;
  if($('retry-selection-button'))$('retry-selection-button').onclick=()=>optimize();
  if($('export-session-button'))$('export-session-button').onclick=exportCurrentSession;
  ['original-policy','rewrite-policy'].forEach(id=>$(id).addEventListener('input',()=>{markStageADraft();updateEditorDiff(false);}));
  [['original-policy','original-line-numbers'],['rewrite-policy','rewrite-line-numbers']].forEach(([editor,gutter])=>$(editor)?.addEventListener('scroll',()=>{if($(gutter))$(gutter).scrollTop=$(editor).scrollTop;}));
  if($('demo-language-guard'))$('demo-language-guard').addEventListener('change',invalidateStageB);
  $('stage-b-policy').addEventListener('input',()=>{invalidateStageB();$('frozen-policy-label').textContent='Policy edited for this call';});
  ['history-input','current-input','rule-excerpts'].forEach(id=>$(id).addEventListener('input',invalidateStageB));
  $('about-dialog').addEventListener('click',e=>{if(e.target===$('about-dialog'))$('about-dialog').close();});
  function receiveSelectedPolicy(){
    if(qs.get('view')!=='stage-b'&&state.page!=='stage-b')return;
    try{
      const stored=JSON.parse(localStorage.getItem('component4:selected-policy-v1')||'null');
      if(!stored?.prompt)return;
      const binding=stored.handoff_id||JSON.stringify(stored);if(binding===state.importedHandoff)return;
      state.importedHandoff=binding;state.policy=stored.prompt;state.activeSession=null;state.sessionPolicy=null;state.turns=[];
      $('stage-b-policy').value=stored.prompt;$('rule-excerpts').value='';
      $('frozen-policy-label').textContent=`From Stage A: ${stored.title||'policy'} · ${stored.provenance||'draft'}`;
      $('turn-history').innerHTML='<div class="empty-state">Stage A prompt received. Enter the current context and run the selector.</div>';
      invalidateStageB();notice('Prompt received from Stage A. Review it below, enter the current context, then select rules.','success');requestAnimationFrame(()=>{$('stage-b-policy').scrollIntoView({block:'center',behavior:'smooth'});$('stage-b-policy').focus({preventScroll:true});});
    }catch(e){notice(`Could not receive the Stage A prompt: ${e.message}`,'error');}
  }
  window.addEventListener('message',e=>{if(e.origin===location.origin&&e.source===window.parent&&e.data?.type==='component4:refresh-selected-policy')receiveSelectedPolicy();});
  receiveSelectedPolicy();
  const view=qs.get('view');page(pageNames[view]?view:'stage-a',false);refreshAll();
})();
