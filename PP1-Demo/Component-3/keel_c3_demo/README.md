# Keel Component 3 (The Memory): replay demo for the common frontend

This folder shows Component 3's work through its own viewer, using **pre-recorded runs only**. It holds no model, no
extraction pipeline and no Python dependencies. Live runs (a local LLM extracting turn by turn) are shown on the C3
presenter's own laptop, from the `keel-mvp` repository.

## What Component 3 does (one paragraph for the tab)

C3 is the belief tracker. As an agent talks with a user (or works in a code repo), every checkable fact it commits to
becomes a node. When the user or a tool refutes one (it **dies**), C3 walks the justification links to find the
**shear front**: the later steps and still-live facts that rested on the dead one (the **orphans**). It scores each
flagged case with a triage model (will the agent repair it on its own?) and keeps the full lineage. Spec:
`keel-mvp/docs/COMPONENT_3_v2.md`.

## Contents

| Path | What it is |
|---|---|
| `frontend/index.html` | The C3 viewer page, an exact copy of `keel-mvp/mvp/viz/static/index.html`. Do not edit it. |
| `data/conversations.json` | The conversation list (what `GET /api/conversations` returns). |
| `data/bundles/<conv>/<run>.json` | One replay per stored chat run (what `GET /api/bundle?conv=&run=` returns). |
| `data/bundles/<conv>/swe.json` | One replay per SWE-agent trajectory (dev split). |
| `data/manifest.json` | Export date, source commit of `keel-mvp`, counts. |
| `serve_demo.py` | Replay-only server, Python standard library, same API as the real viewer. |
| `tools/export_bundles.py` | How `data/` was made (needs the `keel-mvp` repo; not needed to run the demo). |

The two conversations of the frozen evaluation split are listed but greyed out and have no bundle, as in the real viewer.
`travel_demo` and `travel_demo_iso` are listed but have no stored run; they give an error in the real viewer too. Skip them.

## Run it on its own

```bash
python serve_demo.py            # opens http://127.0.0.1:8765/
python serve_demo.py --port 8800 --no-browser
```

Needs internet once for Cytoscape.js (`cdnjs.cloudflare.com/ajax/libs/cytoscape/3.30.2/cytoscape.min.js`).

## Putting it under a tab of the common frontend (instructions for the integrating agent)

Keep `frontend/index.html` unchanged. It calls these paths on its **own origin**:

| Method, path | Answer |
|---|---|
| `GET /` | `frontend/index.html` |
| `GET /api/conversations` | file `data/conversations.json` |
| `GET /api/bundle?conv=ID&run=KEY` | chat: `data/bundles/ID/KEY.json`; if `run` is empty use the first entry of that conversation's `runs`. SWE (`kind == "swe"`): `data/bundles/ID/swe.json`. Blocked (`blocked: true`) → 403 `{"error": "..."}` |
| `GET /api/models` | `[]` |
| `POST /api/live/start`, `/api/live/next`, `/api/live/stop` | 503 `{"error": "Live runs ... presenter's laptop"}` (the page shows the message) |

Errors are JSON `{"error": "..."}`; the page displays them.

Two ways to do it (the first is simplest):

1. **Iframe.** Run `serve_demo.py` next to the common frontend and embed `http://127.0.0.1:8765/` in an `<iframe>`
   that fills the C3 tab (e.g. `style="width:100%;height:100%;border:0"`). The page is full-screen and expects to own
   the viewport, so an iframe also keeps its CSS from clashing with the host app.
2. **Same server as the common frontend.** Serve `frontend/index.html` at some route and reproduce the table above
   under that route's origin (the paths are absolute, `/api/...`, so they must exist at the server root, or proxy
   `/api/*` for this tab). Then iframe that route. If another component already uses `/api/conversations` or
   `/api/bundle`, use option 1 (separate port) instead of renaming paths in the page.

Do not rebuild the page in React or another framework: the replay logic (graph, step slider, tabs, gold overlay,
triage cards) lives in that one file.

## Suggested runs to show

- `car_bike_demo`, run `W+T__qwen3-0.6b-q8_0`: the user changes the car from manual to automatic; the old choice dies
  and its item id, price, quote, total, deposit, monthly payment and delivery date are the shear front; the bike facts
  stay alive. Repairs tab shows triage scores.
- `easy_repair_demo`, `bike_build_demo`, `catering_order_demo`: chat demos with several stored runs (Run dropdown).
- `AnalogJ__lexicon-336__swe-agent-llama-70b`: the coding trace used as the example in the C3 spec.

The `*_demo` chats are hand-written case studies (synthetic). The `tau2_*` chats are τ²-bench retail runs. The SWE
trajectories are public SWE-agent runs.
