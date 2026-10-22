(function () {
  'use strict';

  const STAGES = ['Reports', 'Candidate groups', 'Evidence features', 'Recorded ranking', 'Decision checks', 'Memory handoff'];
  const NAV = [['evidence', 'Conflict resolver']];
  const escape = value => String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
  const number = value => Number(value).toLocaleString('en-US');
  const percent = value => (Number(value) * 100).toFixed(2) + '%';
  const status = value => `<span class="c2-state ${escape(value)}">${escape(value === 'LIVE' ? 'ACTIVE' : value)}</span>`;
  const shortValue = value => /^\d{4}-\d\d-\d\dT/.test(value || '') ? value.slice(11) : value;
  function shortScope(value) {
    if (!String(value).startsWith('evidence:')) return value;
    try { return JSON.parse(value.slice(9))[0] || 'historical release'; }
    catch (_) { return value; }
  }
  const details = (title, value) => `<details><summary>${escape(title)}</summary><pre>${escape(typeof value === 'string' ? value : JSON.stringify(value, null, 2))}</pre></details>`;
  const table = (headings, rows) => `<div class="c2-tablewrap"><table><thead><tr>${headings.map(x => `<th>${escape(x)}</th>`).join('')}</tr></thead><tbody>${rows.map(row => `<tr>${row.map(cell => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
  const card = (title, body, note = '') => `<section class="c2-card"><div class="c2-cardhead"><b>${escape(title)}</b><small>${escape(note)}</small></div>${body}</section>`;
  const body = html => `<div class="c2-cardbody">${html}</div>`;
  const kv = rows => rows.map(([key, value]) => `<div class="c2-kv"><span>${escape(key)}</span><b>${escape(value)}</b></div>`).join('');
  const flow = labels => `<div class="c2-flow">${labels.map(escape).map(x => `<span>${x}</span>`).join('<i>→</i>')}</div>`;

  function mountC2Studio(container, options = {}) {
    if (!container || !container.appendChild) throw new Error('Provide a DOM element for the C2 dashboard.');
    const data = options.data || window.KEEL_C2_DEMO_DATA;
    if (!data || data.version !== 'c2-replay-studio-v1') throw new Error('Load data/recordings.js before mounting the C2 dashboard.');
    const cases = data.cases;
    const initialCase = options.caseId || new URLSearchParams(window.location.search).get('case') || (window.location.hash ? window.location.hash.replace(/^#/,'') : '') || 'flight';
    const state = {page:'evidence', caseId:initialCase, step:0, timer:null};
    let destroyed = false;
    const root = document.createElement('section');
    root.className = 'c2-studio';
    if (options.embedded || new URLSearchParams(window.location.search).get('embedded') === '1') root.classList.add('c2-embedded');
    root.setAttribute('aria-label', 'C2 Evidence Studio');
    root.tabIndex = 0;
    container.appendChild(root);

    function current() { return cases.find(c => c.id === state.caseId) || cases[0]; }
    function maximum(c = current()) { return c.kind === 'structured' ? STAGES.length - 1 : c.frames.length - 1; }
    function stop() { if (state.timer) window.clearInterval(state.timer); state.timer = null; }
    function setCase(id) {
      stop();
      if (!cases.some(c => c.id === id)) return;
      state.caseId = id; state.step = 0;
    }
    function frame() { return current().frames[state.step]; }

    function memoryRows(rows) {
      return table(['Person / object', 'Property', 'Value', 'Time scope', 'State'], rows.map(c => [escape(String(c.entity || c.memory_key?.entity || '').replace(/^evidence\/[^/]+\//,'')), escape(c.property || c.memory_key?.property), escape(shortValue(c.value)), escape(shortScope(c.scope || c.memory_key?.scope)), status(c.status)]));
    }

    function graph(rows, label) {
      if (!rows.length) return '<p class="c2-muted c2-small">No claims are present at this recorded step.</p>';
      const height = Math.max(170, 55 + rows.length * 58);
      const colors = {ACTIVE:'#3c927a', LIVE:'#3c927a', SUPERSEDED:'#b18a4e', CONTESTED:'#8d6bb0', ABSTAINED:'#8d6bb0'};
      return `<svg class="c2-graph" role="img" aria-label="Recorded claim states" viewBox="0 0 680 ${height}">
        <rect x="18" y="${height/2-28}" width="190" height="56" rx="6" fill="#edf3f8" stroke="#ccdce9"/>
        <text x="113" y="${height/2-3}" text-anchor="middle" font-size="12" fill="#406b8b">${escape(label.slice(0,25))}</text>
        <text x="113" y="${height/2+14}" text-anchor="middle" font-size="10" fill="#8a9aaa">recorded memory key</text>
        ${rows.map((c, i) => {
          const y = 22 + i * 58, color = colors[c.status] || '#8195a6';
          return `<path d="M208 ${height/2} C265 ${height/2},270 ${y+21},320 ${y+21}" fill="none" stroke="${color}" stroke-width="1.5"/>
            <rect x="320" y="${y}" width="338" height="43" rx="5" fill="#fbfcfd" stroke="${color}"/>
            <circle cx="337" cy="${y+21}" r="3" fill="${color}"/>
            <text x="350" y="${y+25}" font-size="12" fill="#365166">${escape(String(shortValue(c.value)).slice(0,29))}</text>
            <text x="642" y="${y+25}" text-anchor="end" font-size="9" font-weight="650" fill="${color}">${escape(c.status === 'LIVE' ? 'ACTIVE' : c.status)}</text>`;
        }).join('')}
      </svg>`;
    }

    function evidenceGraph(c) {
      const candidates = c.request.candidates, p = c.prediction;
      const height = Math.max(290, 65 + candidates.length * 100);
      const ranked = state.step >= 3, checked = state.step >= 4;
      const rows = state.step === 5 && c.commit ? c.commit.memory : c.contract.evidence;
      const clip = (value, length) => String(value).length > length ? String(value).slice(0,length-1)+'…' : String(value);
      const outcome = !ranked ? 'Awaiting recorded ranking' : p.abstained ? 'Selection withheld' : checked ? 'Checked disposition' : 'Recorded selection';
      const selected = !ranked ? 'Advance to stage 4' : p.abstained ? 'Candidates remain contested' : shortValue(p.selected_value);
      return card('Evidence → candidate → decision', `<div style="overflow:auto;max-height:540px"><svg role="img" aria-label="Source support, candidate values and recorded decision" viewBox="0 0 1000 ${height}" style="display:block;width:100%;min-width:740px">
        <text x="155" y="27" text-anchor="middle" font-size="12" fill="#71869a">SOURCE SUPPORT</text>
        <text x="505" y="27" text-anchor="middle" font-size="12" fill="#71869a">CANDIDATE VALUES</text>
        <text x="845" y="27" text-anchor="middle" font-size="12" fill="#71869a">${checked?'CHECKED DISPOSITION':'RECORDED DECISION'}</text>
        ${candidates.map((x,i) => {
          const y=50+i*100, chosen=ranked && !p.abstained && x.candidate_id===p.selected_candidate_id;
          const claim=rows.find(r=>String(r.value_norm)===String(x.candidate_value_norm));
          const color=chosen?'#3c927a':'#6489ac';
          const score=p.candidate_scores.find(s=>s.candidate_id===x.candidate_id);
          const description=checked && claim ? claim.status : ranked && score ? 'Saved utility: '+Number(score.utility).toFixed(4) : 'Comparable reported value';
          return `<rect x="20" y="${y}" width="270" height="78" rx="6" fill="#fbfcfd" stroke="#a9bacb"/>
            <text x="34" y="${y+23}" font-size="14" font-weight="650" fill="#405c74">${escape(x.support_count)} distinct sources</text>
            <text x="34" y="${y+44}" font-size="12" fill="#71869a">${escape(clip(x.supporting_sources.slice(0,2).join(', '),35))}</text>
            <text x="34" y="${y+64}" font-size="11" fill="#71869a">${x.supporting_sources.length>2?'+ '+(x.supporting_sources.length-2)+' more':'recorded supporting reports'}</text>
            <path d="M290 ${y+39} H360 l-8 -5 m8 5 l-8 5" stroke="#b5c8da" fill="none"/>
            <rect x="370" y="${y}" width="270" height="78" rx="6" fill="${chosen?'#eef8f4':'#fbfcfd'}" stroke="${color}" stroke-width="${chosen?2:1}"/>
            <text x="384" y="${y+25}" font-size="14" font-weight="650" fill="${color}">${escape(clip(x.candidate_value_norm,31))}</text>
            <text x="384" y="${y+52}" font-size="12" fill="#71869a">${escape(description)}</text>
            ${chosen?`<path d="M640 ${y+39} C685 ${y+39},685 ${height/2},710 ${height/2}" stroke="#3c927a" fill="none" stroke-width="2"/>`:''}`;
        }).join('')}
        <rect x="710" y="${height/2-47}" width="275" height="94" rx="6" fill="${ranked&&!p.abstained?'#eef8f4':'#f5f8fb'}" stroke="#a9bacb"/>
        <text x="726" y="${height/2-17}" font-size="14" font-weight="650" fill="#405c74">${escape(outcome)}</text>
        <text x="726" y="${height/2+7}" font-size="13" fill="#405c74">${escape(clip(selected,32))}</text>
        <text x="726" y="${height/2+29}" font-size="11" fill="#71869a">${checked?'Saved claim states shown below':'Saved execution · no fresh inference'}</text>
      </svg></div>`, 'recorded walkthrough');
    }

    function evidence() {
      const c = current();
      if (c.kind !== 'structured') return memory();
      const p = c.prediction, sources = new Set(c.request.candidates.flatMap(x => x.supporting_sources));
      let main = '', inspect = '';
      if (state.step === 0) {
        const raw = c.rawReports || [];
        const reports = raw.length ? raw : (c.observations || []).map(x => ({source:x.source_id, raw_value:x.candidate_value_raw, normalized_value:x.candidate_value_norm, status:'retained_source'}));
        main = card('Supplied source reports', table(['Source','Reported value','Normalized value','Disposition'], reports.slice(0,10).map(x => [escape(x.source), escape(x.raw_value), escape(x.normalized_value || '—'), escape(x.status==='retained_source'?'Retained':x.status==='excluded_airline_reference_source'?'Reference source excluded':(x.status || 'Supplied').replaceAll('_',' '))])) + body(`<p class="c2-small c2-muted">Showing up to 10 rows from this recorded example.</p>${reports.length > 10 ? details('All recorded report rows',reports) : ''}`), c.archiveMember || 'authored guard input');
        inspect = '<h2>Comparable evidence</h2>' + kv([['Object',c.scope.object_id],['Property',c.request.property],['Date',c.scope.date || 'Not released'],['Context',c.scope.context],['Example partition',c.partition || 'Authored check']]);
      } else if (state.step === 1) {
        main = card('Distinct candidates and source support', table(['Candidate value','Support count','Share of support','Sources'], c.request.candidates.map(x => [escape(shortValue(x.candidate_value_norm)), escape(x.support_count), percent(x.support_count / sources.size), escape(x.supporting_sources.join(', '))])));
        inspect = '<h2>From reports to candidates</h2><p>Equivalent normalized values are combined into one candidate. Distinct source identifiers provide the supporting-source count.</p><p>Different values compete only within the declared object, property and observation scope.</p>';
      } else if (state.step === 2) {
        main = card('Saved evidence features', table(['Candidate','Agreement share','History reliability mean','Unfamiliar-source fraction'], p.candidate_scores.map(x => [escape(shortValue(x.value)), Number(x.features.support_share).toFixed(3), Number(x.features.reliability_mean).toFixed(3), Number(x.features.unseen_source_fraction).toFixed(3)])) + body(details('Complete saved candidate feature vectors',p.candidate_scores.map(x => ({value:x.value,features:x.features})))));
        inspect = '<h2>Inputs to the ranker</h2><p>Agreement, TRAIN source histories, relative value positions and group context become numeric features.</p><p>Reference values and evaluation labels are excluded from the inference request.</p>';
      } else if (state.step === 3) {
        const scores = p.candidate_scores, lo = Math.min(...scores.map(x=>x.utility)), hi = Math.max(...scores.map(x=>x.utility));
        main = card('Recorded LightGBM ranking', `<table><thead><tr><th>Candidate</th><th>Relative utility</th><th>Score</th><th>Result</th></tr></thead><tbody>${scores.map(x=>`<tr class="${x.candidate_id===p.selected_candidate_id?'c2-selected':''}"><td>${escape(shortValue(x.value))}</td><td><div class="c2-score"><i style="width:${25+75*(x.utility-lo)/(hi-lo||1)}%"></i></div></td><td class="c2-mono">${Number(x.utility).toFixed(5)}</td><td>${x.candidate_id===p.selected_candidate_id?status('ACTIVE'):p.abstained?status('CONTESTED'):'—'}</td></tr>`).join('')}</tbody></table>` + body(`<p class="c2-small c2-muted">Bars show relative utility within this group. Scores are not correctness probabilities.</p>`), 'saved model output');
        inspect = '<h2>'+(p.abstained?'Selection withheld':'Selected reported value')+'</h2><div class="c2-result">'+escape(shortValue(p.selected_value)||'Abstained')+'</div><p>'+escape(p.decision_basis.replaceAll('_',' '))+'</p><p class="c2-small c2-muted">This step displays a saved prediction. No LightGBM inference is performed by this frontend.</p>';
      } else if (state.step === 4) {
        main = card('Recorded decision contract', memoryRows(c.contract.evidence) + body(details('Exact saved decision contract', c.contract)), 'checked preview');
        inspect = '<h2>Bindings and permitted changes</h2><p>The backend binds the selected candidate to its exact claim ID and scope, then checks the memory disposition.</p><p>If the ranker abstains, candidate claims remain contested. Superseded reports remain historical evidence.</p><p class="c2-small c2-muted">This is a recorded contract preview, not a new database commit.</p>';
      } else {
        const commit = c.commit, rows = commit ? commit.memory : c.contract.evidence;
        main = card(commit?'Saved Neo4j memory snapshot':'Recorded memory handoff preview', body(graph(rows,c.request.property)) + memoryRows(rows), commit?'captured from an earlier successful commit':'no database write included');
        inspect = '<h2>'+(commit?'Original commit evidence':'Memory handoff')+'</h2>'+(commit?kv([['Original backend',commit.backend],['Original graph ID',commit.graph_id],['Snapshot revision',commit.revision]])+'<p class="c2-small c2-muted" style="margin-top:12px">The graph ID belongs to the original laptop’s database. This portable dashboard displays the saved snapshot and does not create or connect to a database.</p>':'<p>No matching successful Neo4j commit is bundled for this example. The checked preview is shown instead.</p>');
      }
      return `<h1>${escape(c.title)}</h1><p class="c2-subtitle">${escape(c.scope.object_id)} · ${escape(c.request.property)} · ${escape(c.scope.date || 'released date unavailable')} · ${escape(c.partition ? c.partition.toUpperCase()+' example' : 'authored guard check')}</p>
        <div class="c2-stagebar">${STAGES.map((name,i)=>`<button data-step="${i}" class="${i===state.step?'active':''}" aria-current="${i===state.step?'step':'false'}">${i+1} · ${name}</button>`).join('')}</div>
        <div class="c2-notice">Recorded execution. Next and Play reveal saved results; they do not call a model or write memory.</div>
        <div class="c2-stats"><div class="c2-stat"><label>Candidate values</label><strong>${c.request.candidates.length}</strong><small>supplied alternatives</small></div><div class="c2-stat"><label>Distinct source IDs</label><strong>${sources.size}</strong><small>recorded support metadata</small></div><div class="c2-stat"><label>Selected report</label><strong style="font-size:21px">${state.step<3?'—':escape(shortValue(p.selected_value)||'Withheld')}</strong><small>${state.step<3?'revealed at ranking stage':'recorded model decision'}</small></div><div class="c2-stat"><label>Current stage</label><strong>${state.step+1} / 6</strong><small>${STAGES[state.step]}</small></div></div>
        ${evidenceGraph(c)}
        <div class="c2-grid">${main}${card('Inspection',body(inspect + details('Execution provenance',{execution:'recorded_replay',recorded_at:c.recordedAt,original_inference_seconds:c.seconds,model_sha256:p.model_sha256,request_sha256:c.requestSha256,live_model_calls:0,live_database_writes:0}) + details('Reference comparison · evaluation only',c.references)))}</div>`;
    }

    function memory() {
      const c = current();
      if (c.kind !== 'conversation') return evidence();
      const f = frame(), message = f.message, rows = f.claims;
      const active = rows.filter(x=>['ACTIVE','LIVE'].includes(x.status)).length;
      const superseded = rows.filter(x=>x.status==='SUPERSEDED').length;
      return `<h1>${escape(c.title)}</h1><p class="c2-subtitle">Recorded conversational pathway · extraction, assertion admission and explicit C2 memory policies.</p>
        <div class="c2-notice">This is playback of an earlier execution. Qwen and Neo4j are not called while navigating this recording.</div>
        <div class="c2-stats"><div class="c2-stat"><label>Recorded turn</label><strong>${f.step} / ${c.frames[c.frames.length-1].step}</strong><small>${message.role==='user'?'user input':'assistant response'}</small></div><div class="c2-stat"><label>Active claims</label><strong>${active}</strong><small>at this recorded turn</small></div><div class="c2-stat"><label>Superseded claims</label><strong>${superseded}</strong><small>retained history</small></div><div class="c2-stat"><label>Current-page model calls</label><strong>0</strong><small>saved results only</small></div></div>
        <div class="c2-grid">
          <div>${card('Turn '+f.step+' · '+(message.role==='user'?'Input':'Response'),body(`<div class="c2-message ${message.role==='user'?'user':''}">${escape(message.text)}</div>`))}
          ${card('Belief states at this turn',body(graph(rows,'Residence')) + memoryRows(rows))}</div>
          <div>${card('Recorded conversation',`<div class="c2-timeline">${c.frames.map((x,i)=>`<button data-step="${i}" class="${i===state.step?'active':''}"><small>TURN ${x.step} · ${x.message.role==='user'?'INPUT':'RESPONSE'}</small>${escape(x.message.text)}</button>`).join('')}</div>`)}
          ${card('Original execution evidence',body(kv([['Original storage backend',c.backend],['Original final graph ID',c.graphId],['Replay model calls','0'],['Replay database writes','0']])+details('Recorded decisions available at this turn',f.decisions)+details('Recorded response metadata',message.modelEvidence)))}</div>
        </div>`;
    }

    function comparison() {
      const e = data.evaluation, methods = Object.values(e.methods).sort((a,b)=>b.test_exact-a.test_exact);
      return `<div class="c2-compare"><h1>Model comparison</h1><p class="c2-subtitle">Exact reference match on <b>${number(e.test_groups)}</b> structured TEST groups · saved experimental results.</p>
        ${card('Structured arbitration results',`<table><thead><tr><th>Method</th><th>TEST exact match</th><th></th></tr></thead><tbody>${methods.map(m=>`<tr><td>${escape(m.label)}</td><td><div class="c2-score"><i style="width:${m.test_exact*100}%"></i></div></td><td><b>${percent(m.test_exact)}</b></td></tr>`).join('')}</tbody></table>`+body('<p class="c2-small">LightGBM achieved the highest exact-match result among these seven compared methods. The custom context scorer did not outperform it.</p>'))}
        <div class="c2-grid equal">${card('Beyond majority voting',body('<p>Candidate scoring combines agreement, historical source performance and group features.</p>'))}${card('Selection, not forecasting',body('<p>The model chooses among supplied reports. It does not predict a new arrival time or stock value.</p>'))}</div>
        <p class="c2-small c2-muted">These figures measure structured report selection, not general conversational accuracy or transfer to unfamiliar providers.</p>
        <details><summary>Evaluation details and domain results</summary>${table(['Domain','TEST groups','Exact match','Reference among candidates'],Object.entries(e.domains).map(([name,d])=>[escape(name),number(d.groups),percent(d.exact_gold_rate_on_answered),percent(d.gold_available_rate)]))}<p>Weather performance is weak; candidate coverage and domain differences limit the result.</p><p>${escape(e.test_status)}.</p><p>The model was retained through the declared validation procedure. The small observed difference from Random Forest does not establish a general or statistically significant advantage.</p><p>Conversational transfer remains limited. The residence examples demonstrate a separate assertion/policy pathway and are not a conversational accuracy benchmark.</p></details>
        ${details('Result provenance',{source:'reports/research_completion_summary.json',source_sha256:data.sources.summary,scope:'Frozen structured study; no new evaluation runs in this dashboard'})}</div>`;
    }

    function render() {
      if (destroyed) return;
      const c = current(); state.step = Math.min(state.step,maximum(c));
      const playable = true;
      const position = c.kind==='structured'?'Stage '+(state.step+1)+' / 6':'Turn '+c.frames[state.step].step+' / '+c.frames[c.frames.length-1].step;
      root.innerHTML = `<aside class="c2-sidebar"><div class="c2-brand"><span class="c2-logo">✳</span><div><strong>KEEL · C2 Studio</strong><small>EVIDENCE ARBITRATION</small></div></div><nav class="c2-nav" aria-label="C2 sections"><div class="c2-eyebrow">Console</div>${NAV.map(([id,label],i)=>`<button data-page="${id}" aria-current="page"><span>${i+1}</span>${label}</button>`).join('')}</nav><div class="c2-sidefoot"><strong>● Recorded replay</strong><br>Offline-ready frontend<br>No local model required<br>No database connection</div></aside>
        <div class="c2-workspace"><header class="c2-toolbar"><div class="c2-session"><strong>${escape(c.title)}</strong><small>${c.kind==='structured'?'Structured evidence':'Conversational memory'} · C2</small></div><select class="c2-select" aria-label="Recorded example">${cases.map(x=>`<option value="${x.id}" ${x.id===c.id?'selected':''}>${escape(x.title)}</option>`).join('')}</select><div class="c2-player"><button class="c2-iconbtn" data-action="prev" aria-label="Previous recorded step" ${!playable||!state.step?'disabled':''}>◀</button><button class="c2-iconbtn" data-action="play" aria-label="${state.timer?'Pause':'Play'} recorded steps" ${!playable?'disabled':''}>${state.timer?'Ⅱ':'▶'}</button><button class="c2-iconbtn" data-action="next" aria-label="Next recorded step" ${!playable||state.step>=maximum()?'disabled':''}>▶|</button><span class="c2-position">${playable?position:'Saved examples'}</span><input class="c2-progress" type="range" min="0" max="${maximum()}" value="${state.step}" aria-label="Recorded step" ${!playable?'disabled':''}></div><span class="c2-badge blue">Recorded replay</span></header>
        <main class="c2-content"><h1>Conflict resolver</h1><p class="c2-subtitle">C2 · Evidence arbitration and memory updates · choose an example above, then use the playback controls.</p>${current().kind==='conversation'?memory():evidence()}<details class="c2-research"><summary>Model comparison · seven methods on 6,206 structured TEST groups</summary>${comparison()}</details></main><footer class="c2-footer"><span>C2 standalone presentation module · saved executions</span><span>No inference or memory writes occur in this frontend</span></footer></div>`;
    }

    function click(event) {
      const page = event.target.closest('[data-page]');
      if (page && root.contains(page)) {
        stop();state.page=current().kind==='structured'?'evidence':'memory';
        render();return;
      }
      const open = event.target.closest('[data-open-case]');
      if (open && root.contains(open)) {setCase(open.dataset.openCase);state.page=current().kind==='structured'?'evidence':'memory';render();return;}
      const step = event.target.closest('[data-step]');
      if (step && root.contains(step)) {stop();state.step=Number(step.dataset.step);render();return;}
      const action = event.target.closest('[data-action]');
      if (!action || !root.contains(action)) return;
      if (action.dataset.action==='play') {
        if (state.timer) {stop();render();return;}
        if (state.step>=maximum()) state.step=0;
        state.timer=window.setInterval(()=>{if(state.step>=maximum()){stop();render();return;}state.step++;if(state.step>=maximum())stop();render();},1800);
      } else {stop();state.step=Math.max(0,Math.min(maximum(),state.step+(action.dataset.action==='next'?1:-1)));}
      render();
    }
    function change(event) {
      if (event.target.matches('select[aria-label="Recorded example"]')) {
        setCase(event.target.value);
        if (state.page==='memory'||state.page==='evidence') state.page=current().kind==='structured'?'evidence':'memory';
        render();
      }
      if (event.target.matches('input[aria-label="Recorded step"]')) {stop();state.step=Number(event.target.value);render();}
    }
    function onHash() {
      const h = window.location.hash.replace(/^#/, '');
      if (h && cases.some(c => c.id === h)) {
        setCase(h);
        state.page = current().kind === 'structured' ? 'evidence' : 'memory';
        render();
      }
    }
    function onMsg(e) {
      if (e.data && e.data.type === 'c2-set-case' && e.data.caseId) {
        setCase(e.data.caseId);
        state.page = current().kind === 'structured' ? 'evidence' : 'memory';
        render();
      }
    }
    window.addEventListener('hashchange', onHash);
    window.addEventListener('message', onMsg);
    root.addEventListener('click',click);root.addEventListener('change',change);render();
    return {destroy(){stop();destroyed=true;window.removeEventListener('hashchange',onHash);window.removeEventListener('message',onMsg);root.removeEventListener('click',click);root.removeEventListener('change',change);root.remove();}};
  }

  window.mountC2Studio=mountC2Studio;
  document.querySelectorAll('[data-c2-studio]').forEach(element=>mountC2Studio(element));
})();
