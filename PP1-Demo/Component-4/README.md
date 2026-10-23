# Component 4 — demo runtime

Open the shared demo at http://127.0.0.1:8051/ and select **Stage A · Rewrite**, **Stage B · Optimize**, or **Evidence & Showcase**.

## Start

Keep this folder beside Component-1, Component-2 and Component-3 in PP1-Demo. Install Python 3.11 dependencies from `requirements.txt` into your environment. Set `C4_PYTHON` if necessary, then run `START_SHARED_DEMO.command` or `python integration/START_COMPONENT4_SHARED_DEMO.py`. It uses the existing shared shell; no duplicate shell build is bundled. For standalone C4 use `START_COMPONENT4.command` (port 8774).

Stage A displays recorded BPO rewrites and supports editing/versioning. Stage B performs real CPU rule selection and request preparation. LLM answer panels are recorded results, not fresh generation. Model loading, live optimization latency, token overhead and prefix checks are shown separately. No hosted KV-cache-hit claim is made.

## Included

- `frontend/`: the three UI files.
- `backend/app.py`: API, immutable policy versions and per-turn session records.
- `data/`: recorded BPO/IHEval answers and the benchmark evidence displayed by the UI.
- `research/stage_b/`: minimal frozen serving code, checkpoint, encoder, tokenizer and provenance needed for offline inference; the name is retained for compatibility with the shared launcher.
- `integration/`: a small launcher for the existing shared shell.

Training datasets, feature caches, old checkpoints, notebooks, copied shell builds, backups and research history are excluded from this demo repository. They are preserved outside J26-DS-308 in `component4_delivery/research_archive_20261023/` in the original workspace. The source research projects are also preserved.

Session databases, caches and generated files are ignored by Git. Required runtime model files are explicitly included; they must remain with the demo for offline operation. No BPO or target-LLM weights are required for recorded Stage A replay.
