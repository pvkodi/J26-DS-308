# Component 4 local backend

This localhost-only service supports the shared Component 4 shell. Stage B loads the frozen CPU residual-R restatement selector from `../research/stage_b`; it never generates a target answer. It appends the canonical reminder as a new user message and verifies that the original native messages and serialized token prefix remain intact. The receipt says “cache eligible”; no hosted KV-cache hit is claimed.

Run `../START_COMPONENT4.command` from the packaged Component-4 directory. The shared shell is served at `http://127.0.0.1:8774/`; the API uses the same origin. The default address is `http://127.0.0.1:8774`. An alternate model tree, local SQLite file, or recorded BPO receipt can be passed with `--stage-b-root`, `--db`, or `--stage-a-recorded`.

## API

All routes are under `/api/c4/`.

| Method and path | Purpose |
| --- | --- |
| `GET /health` | Frozen-model bindings, startup time, persistence location, recorded BPO status |
| `GET /evidence` | Hash-verifies the packaged IHEval/IFBench/latency receipts and returns the exact bound JSON objects |
| `GET /stage-a/recorded` | Read-only exact BPO recorded artifact and provenance |
| `GET /stage-a/versions` | User-created manual prompt profiles and immutable versions |
| `GET /stage-a/versions/{profile_id}` | Full version history for a manual profile |
| `POST /stage-a/versions` | Create a manual version. Optional `profile_id` starts a new version chain |
| `PUT /stage-a/versions/{profile_id}` | Append an immutable new manual version; prior versions remain |
| `GET /sessions` | List persistent local sessions and turn counts |
| `POST /sessions` | Create a persistent session from `{title, policy}` |
| `POST /turns` | Run current-context R selection and atomically save a turn |
| `GET /sessions/{session_id}` | Session and saved turn history |
| `GET /sessions/{session_id}/export` | Export session and turns as downloadable JSON and persist the same snapshot under `data/exports/` |

`POST /turns` accepts `{session_id, policy, context, native_messages?, rules?}`. When omitted, native messages are exactly one system policy and one current user message. When supplied, the complete history must contain the exact policy as a system message and the exact current context as its final user message. `rules`, if provided, must be a list of explicit `{id, text, source_span?}` entries. Each text must be an exact substring of the policy; the optional `[start, end]` span must match those exact policy bytes. The service does not parse rules out of the prompt or fabricate rule boundaries. Without `rules`, the model treats the whole policy as one candidate and records that scope explicitly; it does not represent per-rule selection. The API returns selected IDs, scores, suffix, before/after native message lists, protected prefix/token hashes, native added-token count, measured selection/request time, cold model startup, and frozen checkpoint bindings. Fresh output is unscored and contains no answer.

Stage A BPO recordings are read-only and must be supplied at `data/stage_a_recorded.json`; the health endpoint indicates when absent. Manually entered prompt revisions are explicitly tagged `manual_user_entry`, model-less and append-only; they do not claim to be optimized by BPO. Sessions and turns are local and persisted in `backend/data/component4.sqlite3`; exported JSON snapshots are written under the SQLite directory's `exports/`. The API accepts only local loopback binds.

## Start A / B example

```json
{
  "session_id": "returned-by-POST-sessions",
  "policy": "Your answer must be in all capital letters and in English.",
  "context": "Is praying for someone's health a good idea?"
}
```

Every recorded target answer remains bound to its original request in the read-only evidence artifact; live edits do not look up or reuse those answers.
