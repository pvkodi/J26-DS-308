'use strict';
let component4Cache = null;
const c4Labels = {
  context_length: ['Context length', 'About 2K → 8K input tokens'],
  instruction_position: ['Rule position', 'Early → late within the system message'],
  turn_count: ['Conversation depth', '12 → 20 previous exchanges'],
  obligation_load: ['Active obligations', '4 → 8 registered rules'],
  request_pressure: ['Request detail', 'Concise → detailed current request']
};
const c4Names = {qwen7: 'Qwen2.5 7B', granite2: 'Granite 3.3 2B'};
const c4Pp = value => `${value > 0 ? '+' : ''}${(100 * value).toFixed(1)} pp`;
const c4Download = (name, label) => download('/api/component4-files?name=' + encodeURIComponent(name), label);
function c4Effect(row) {
  const effect = row.signed_change;
  return `<span class="c4-effect ${effect > 0 ? 'increase' : effect < 0 ? 'decrease' : ''}">${c4Pp(effect)}</span><div class="c4-axis" aria-hidden="true"><i class="c4-zero"></i><i class="c4-bar ${effect < 0 ? 'negative' : ''}" style="width:${Math.min(50, Math.abs(effect) * 100)}%;left:${effect < 0 ? 50 - Math.min(50, Math.abs(effect) * 100) : 50}%"></i></div>`;
}
async function renderComponent4Profiles() {
  const target = $('component4-content');
  if (component4Cache) return;
  target.innerHTML = '<p class="subtle">Loading reviewed Component 4 measurements…</p>';
  try {
    const data = await api('/api/component4-profiles');
    component4Cache = data;
    const factors = Object.keys(c4Labels);
    const cards = ['qwen7', 'granite2'].map(model => {
      const profileName = model + '_component4_behavior_profile.json';
      const profile = data.profiles[profileName];
      return `<article class="profile-card"><span class="badge">Standalone behavioural profile</span><h2>${c4Names[model]}</h2><p>${esc(profile.model.repo)}</p><dl class="kv"><dt>Controlled answers</dt><dd>144</dd><dt>Generated-history answers</dt><dd>48</dd><dt>Compared focal rules</dt><dd>4</dd><dt>Deployment</dt><dd>4-bit NF4 · Tesla T4</dd></dl><p class="modal-note">${model === 'qwen7' ? 'Comparison model. Each sensitivity is measured against Qwen’s own reference condition.' : 'Each sensitivity is measured against Granite’s own reference condition; Qwen provides a separate cross-model comparison.'}</p><div class="c4-actions"><button class="button" data-c4-profile="${model}">Inspect profile ↗</button>${c4Download(profileName, 'Profile JSON')}</div></article>`;
    }).join('');
    const comparisonRows = factors.map(factor => {
      const q = data.factors.find(x => x.model_key === 'qwen7' && x.factor === factor);
      const g = data.factors.find(x => x.model_key === 'granite2' && x.factor === factor);
      return [`<b>${c4Labels[factor][0]}</b><br><small>${c4Labels[factor][1]}</small>`, c4Effect(q), c4Effect(g)];
    });
    target.innerHTML = `<div class="c4-section-head"><div><div class="eyebrow">COMPONENT 4 · SEPARATE HANDOFF</div><h2>How conversation conditions affect each model</h2><p>Measured rule-failure changes from real Kaggle generations. These profiles are not connected to the predictor toggle above.</p></div><span class="badge">Preliminary · collection complete</span></div>
      <div class="stats"><div class="stat-box"><b>2</b><span>model configurations</span></div><div class="stat-box"><b>384</b><span>generated answers</span></div><div class="stat-box"><b>12</b><span>controlled conditions</span></div><div class="stat-box"><b>4</b><span>focal obligations</span></div></div>
      <div class="profile-grid">${cards}</div>
      <article class="profile-card c4-comparison"><h3>Factor comparison</h3><p>Change in average failure rate across the same four rules. Positive means more failures; negative means fewer. <b>pp = percentage points.</b></p>${table(['Change from the reference', 'Qwen2.5 7B', 'Granite 3.3 2B'], comparisonRows)}<div class="quiet-box"><b>Read it this way:</b> Granite’s +19.8 pp context score means its matched failure rate rose from 28.1% to 47.9% in this comparison. It is not a 19.8% prediction for the next answer. More rules improved the measured average here; that does not establish that adding rules is generally safer.</div><div class="c4-actions"><button class="button" data-c4-details="method">Design, scoring & limitations ↗</button><button class="button" data-c4-details="comparison">Full comparison JSON ↗</button><button class="button" data-c4-details="natural">Generated-history check ↗</button></div></article>
      <article class="profile-card c4-resources"><div><h3>Dataset & run evidence</h3><p>Browse the workbook or download complete inputs, answers, checker results, profile JSONs and the original checkpoint.</p><small>1,536 focal-rule rows · 1,532 primary-valid · one capped answer retained as censored evidence.</small></div><div class="c4-actions">${c4Download('Component4_Profile_Dataset.xlsx', 'Dataset workbook')}${c4Download('Component4_Profile_Dataset_Package.zip', 'Complete dataset ZIP')}<button class="button" data-c4-details="evidence">Provenance ↗</button></div></article>`;
  } catch (error) {
    component4Cache = null;
    target.innerHTML = `<div class="quiet-box">Component 4 measurements could not be loaded: ${esc(error.message)} <button class="text-button" id="c4-retry">Retry</button></div>`;
  }
}
function inspectComponent4(kind, model) {
  const data = component4Cache;
  if (!data) return;
  if (model) {
    const rows = data.factors.filter(row => row.model_key === model);
    openDrawer(c4Names[model] + ' · Component 4 profile', `<p>Signed changes retain improvements. Harmful sensitivity is max(0, signed change); zero does not mean zero baseline risk.</p>${table(['Factor', 'Matched reference → changed', 'Signed change', 'Harmful score', 'Approx. interval', 'Pairs'], rows.map(row => [esc(c4Labels[row.factor][0]), `${pct(row.reference_failure_rate)} → ${pct(row.changed_failure_rate)}`, c4Pp(row.signed_change), num(row.harmful_sensitivity), `${c4Pp(row.interval_low)} to ${c4Pp(row.interval_high)}`, row.matched_answer_pairs]))}<p class="modal-note">Intervals resample only four scenario families and are exploratory. Granite’s context comparison has 11 pairs after excluding one capped answer. Other comparisons have 12.</p>${rawDetails('Complete frozen profile', data.profiles[model + '_component4_behavior_profile.json'])}`, 'COMPONENT 4');
    return;
  }
  if (kind === 'comparison') return openDrawer('Cross-model comparison', '<p>Granite minus Qwen effects use common valid matched blocks. Their difference can differ from subtracting the rounded table values because matched exclusions also apply to Qwen.</p>' + rawDetails('Full comparison', data.profiles['granite_vs_qwen_comparison.json']), 'COMPONENT 4');
  if (kind === 'natural') return openDrawer('Generated-history check', `<p>Eight scripted-user conversations, each with 12 genuinely generated assistant turns. Four conversations per model. Reference and combined-stress paths develop different histories, so these are not isolated factor effects.</p>${table(['Model', 'Path', 'Answers', 'Failed / valid focal checks', 'Failure rate'], data.natural.map(row => [c4Names[row.model_key], esc(row.condition_id.replaceAll('_', ' ')), row.answers, `${row.failed_focal_checks} / ${row.valid_focal_checks}`, pct(row.failure_rate)]))}<div class="quiet-box">Stress improved Qwen’s measured average and worsened Granite’s. This small check does not establish universal deterioration or generalization.</div>`, 'COMPONENT 4');
  if (kind === 'evidence') return openDrawer('Component 4 provenance', `<p>The dataset package includes the source checkpoint, full original records, pre-generation input commitments, audit report and SHA256 manifest. Hashes show consistency, not independent certification.</p>${rawDetails('Collection provenance', data.provenance)}${rawDetails('Download file hashes', data.files)}`, 'COMPONENT 4');
  openDrawer('Component 4 · design & limits', `<h3>What we measured</h3><p>Failure to follow four exact rules: fewer than 120 words, an exact ending, no ASCII comma, and inclusion of the whole word “provisional”. These are formal compliance measures, not severity-weighted safety scores.</p><h3>Controlled collection</h3><p>2 models × 4 authored scenario families × 12 conditions × 3 sampling repeats = 288 answers. Families cover support handover, research planning, incident triage and community coordination. Earlier assistant messages are constructed compliant examples; only the target answer is generated.</p><p>Reference: about 2,048 native prompt tokens, 12 prior exchanges, 4 registered rules, early system rule block and concise request. Role and grounding instructions stay fixed and are not counted among the registered rules.</p>${table(['Condition', 'Tokens ≈', 'Prior exchanges', 'Rules', 'System position', 'Request'], data.conditions.map(row => [esc(row.condition_id), row.nominal_context_tokens, row.prior_exchanges, row.active_obligations, esc(row.system_rule_position), esc(row.request_pressure)]))}<h3>How scores are calculated</h3><p>Match changed and reference answers by family and sampling repeat. Average repeat differences within each family, then weight the four families equally. Signed score = changed failure rate − reference failure rate. Harmful score = max(0, signed score). Do not add factor scores into a probability.</p><h3>Inference settings</h3><p>Pinned Qwen2.5-7B-Instruct and Granite3.3-2B-Instruct revisions, 4-bit NF4 weights, FP16 computation, temperature 0.7, top-p 0.9, maximum 768 output tokens. Labels come from deterministic code, not an LLM judge.</p><h3>Limits</h3><ul class="limit-list"><li>Two configurations, four related controlled families and only three sampling repeats. Four labels share each answer.</li><li>Neutral background adjusts token length; inputs are matched operationally, not identical across tokenizers. More context also changes background quantity and instruction distance.</li><li>System rule position stays within SYSTEM, not at the end of the full conversation. Compliant histories can prime output style.</li><li>One capped Granite answer is excluded from primary estimates, retained in raw evidence, and never labelled a clean pass.</li><li>Only selected interactions were collected. Negative effects do not imply universal protection. Bootstrap intervals based on four families are approximate.</li><li>No classifier accuracy or calibrated next-answer probability is claimed. No automatic transfer to the live Qwen3 4B model or integration benefit for Component 4 is established.</li></ul>${c4Download('PANEL_PREPARATION_GUIDE.txt', 'Preparation guide')}`, 'COMPONENT 4');
}
document.addEventListener('click', event => {
  const profile = event.target.closest('[data-c4-profile]');
  const details = event.target.closest('[data-c4-details]');
  if (profile) inspectComponent4(null, profile.dataset.c4Profile);
  if (details) inspectComponent4(details.dataset.c4Details);
  if (event.target.id === 'c4-retry') renderComponent4Profiles();
});
