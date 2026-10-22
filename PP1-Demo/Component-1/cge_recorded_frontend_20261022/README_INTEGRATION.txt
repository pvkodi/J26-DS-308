CGE OBLIGATION MONITOR - RECORDED PRESENTATION HANDOFF
22 October 2026

PURPOSE
Display this component beside teammates' separate frontends. This is UI assembly,
not integration of component logic. The original working demo is unchanged.

START (Windows, macOS or Linux; Python 3.10+ standard library only)
1. Extract the whole ZIP. Keep its internal folders together.
2. From this folder run: python START_RECORDED_DEMO.py
3. Open http://127.0.0.1:8051/
Alternative port: python START_RECORDED_DEMO.py --port 8053
Windows users can also double-click START_RECORDED_DEMO.bat.
Keep the terminal running; Ctrl+C stops it. No pip, GPU, internet, HF token,
llama.cpp, model weights, or local LLM server is needed.

WHAT WORKS
- Recorded Qwen and Granite conversations, turn by turn.
- Actual frozen CPU predictor scores computed before revealing saved answers.
- Granite predictor-profile toggle and exact post-answer rule checks.
- Saved obligation extractions, source maps, JSON export.
- Saved detector judgments, multiple turns, known misses and limitations.
- Metrics, feature contributions, original run evidence and proposed handoff.
- Dataset snapshot, architecture and separate Component 4 profiles/comparison.
- Component 4 workbook, ZIP, profile JSON and evidence downloads.
Recorded inputs stay fixed. Generation means reveal a genuine recorded answer.
Learned extraction and semantic detector judgments in saved tabs are replayed,
not recomputed. Exact checks and predictor scores are CPU computations.

NOT INCLUDED
Live generation/extraction/semantic inference. Controls are hidden and backend
live requests are rejected. Use each component owner's original laptop for live
runs. No automatic remote laptop connection or downstream integration is claimed.

RECOMMENDED COMMON FRONTEND INTEGRATION
Copy this whole folder under components/obligation_monitor/ in the common repo.
Run its Python service on an unused port. Add a sidebar tab in the common shell
that mounts <iframe src="http://127.0.0.1:8051/" title="Obligation monitor"
style="width:100%;height:100%;border:0"></iframe>.
Use a normal unsandboxed local iframe; restrictive sandbox settings can block
downloads, JSON exports or scripts. Keep the iframe mounted when switching tabs
if you want to preserve the current replay position. A shared shell can offer
separate entries for Conversation, Extraction, Detector and Profiles, but this
component already contains those four internal tabs. An outer component tab is
the simplest handoff. The existing internal sidebar is preserved.

This isolates all CSS, element IDs, global functions and /api routes from other
teams' frontends. All services run on localhost; do not publicly expose them.
For another port, change the start command AND iframe URL. If the main shell
is HTTPS, use its dev proxy or serve the shell locally to avoid mixed content.

IF THE AI AGENT CHOOSES TO MERGE SOURCE DIRECTLY
Do not paste app.js/style.css into a shared global scope. They contain generic
names and root-relative URLs. Scope styles, IDs and state; namespace /api and
static routes; rewrite EVERY fetch, download link and asset URL, including those
in component4-profiles.js. Prefer the iframe approach for this presentation.
Do not change model weights, datasets, source hashes, eligibility logic or labels.
The frontend requires the Python API; opening index.html directly will not work.
Do not replace real computations with invented scores or editable fake answers.

DATA AND LIMITATIONS
The original predictor evidence includes all 192 held-out answers, pinned fitted
artifacts and provenance. Original evidence hashes are checked on server startup.
The two new Component 4 profiles are a separate study, not the predictor toggle.
Their snapshot, source records and censored-answer policy remain included.
Detector semantic examples contain authored answers with saved model judgments;
they are not generator benchmark data. These distinctions remain labelled.

FILES
cge_studio/: UI, API, recorded-only services, dataset and Component 4 exports.
c1_mvp_phase1/risk_two_rule_frontend/: minimal CPU predictor, evidence and replay.
c1_mvp_phase1/granite_state_profile_v4/: fresh evaluation report for metrics.
obligation_detector/detector/: exact checkers, ledger/state tracking and a
deliberately disabled model stub. No model client or runtime is bundled.
MANIFEST.json: SHA256 and byte size of every supplied file except itself.
