#!/usr/bin/env python3
"""Component 4 local CPU backend: frozen Stage-B residual selector + provenance."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
import re
import sqlite3
import sys
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_STAGE_B = (HERE / "../research/stage_b").resolve()
DEFAULT_DB = HERE / "data/component4.sqlite3"
DEFAULT_STAGE_A = (HERE / "../data/stage_a_recorded.json").resolve()


def canonical(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha_file(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class Store:
    """Small local SQLite store; each completed turn commits atomically."""
    def __init__(self, path: pathlib.Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.db:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("""CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, policy TEXT NOT NULL, turn_count INTEGER NOT NULL DEFAULT 0)""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS turns (
                turn_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, turn_index INTEGER NOT NULL,
                created_at TEXT NOT NULL, request_sha256 TEXT NOT NULL, payload_json TEXT NOT NULL,
                UNIQUE(session_id, turn_index), FOREIGN KEY(session_id) REFERENCES sessions(session_id))""")
            self.db.execute("""CREATE TABLE IF NOT EXISTS stage_a_versions (
                profile_id TEXT NOT NULL, version INTEGER NOT NULL, title TEXT NOT NULL,
                source_prompt TEXT NOT NULL, prompt TEXT NOT NULL, created_at TEXT NOT NULL, parent_version INTEGER,
                provenance_json TEXT NOT NULL, PRIMARY KEY(profile_id, version))""")
            columns = {r[1] for r in self.db.execute("PRAGMA table_info(stage_a_versions)")}
            if "source_prompt" not in columns:
                self.db.execute("ALTER TABLE stage_a_versions ADD COLUMN source_prompt TEXT NOT NULL DEFAULT ''")

    def create_session(self, title, policy, now):
        sid = str(uuid.uuid4())
        with self.lock, self.db:
            self.db.execute("INSERT INTO sessions(session_id,title,created_at,updated_at,policy) VALUES(?,?,?,?,?)",
                            (sid, title, now, now, policy))
        return sid

    def save_turn(self, sid, policy, payload, now):
        with self.lock, self.db:
            row = self.db.execute("SELECT turn_count FROM sessions WHERE session_id=?", (sid,)).fetchone()
            if row is None:
                raise KeyError("session not found")
            index = int(row["turn_count"]) + 1
            tid = str(uuid.uuid4())
            body = {**payload, "turn_id": tid, "session_id": sid, "turn_index": index, "created_at": now}
            reqhash = body["request_sha256"]
            self.db.execute("INSERT INTO turns VALUES(?,?,?,?,?,?)",
                            (tid, sid, index, now, reqhash, json.dumps(body, ensure_ascii=False)))
            self.db.execute("UPDATE sessions SET policy=?,updated_at=?,turn_count=? WHERE session_id=?",
                            (policy, now, index, sid))
        return body

    def has_session(self, sid):
        with self.lock:
            return self.db.execute("SELECT 1 FROM sessions WHERE session_id=?", (sid,)).fetchone() is not None

    def list_sessions(self):
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM sessions ORDER BY updated_at DESC")]

    def get_session(self, sid):
        with self.lock:
            row = self.db.execute("SELECT * FROM sessions WHERE session_id=?", (sid,)).fetchone()
            if row is None:
                return None
            turns = [json.loads(r[0]) for r in self.db.execute(
                "SELECT payload_json FROM turns WHERE session_id=? ORDER BY turn_index", (sid,))]
        return {"session": dict(row), "turns": turns}

    def save_stage_a_version(self, profile_id, title, source_prompt, prompt, now, provenance):
        with self.lock, self.db:
            row = self.db.execute("SELECT MAX(version) FROM stage_a_versions WHERE profile_id=?", (profile_id,)).fetchone()
            version = int(row[0] or 0) + 1
            self.db.execute("INSERT INTO stage_a_versions(profile_id,version,title,source_prompt,prompt,created_at,parent_version,provenance_json) VALUES(?,?,?,?,?,?,?,?)",
                            (profile_id, version, title, source_prompt, prompt, now, version - 1 if version > 1 else None,
                             json.dumps(provenance, ensure_ascii=False, sort_keys=True)))
        return self.get_stage_a_profile(profile_id)["versions"][-1]

    def get_stage_a_profile(self, profile_id):
        with self.lock:
            rows = [dict(r) for r in self.db.execute(
                "SELECT * FROM stage_a_versions WHERE profile_id=? ORDER BY version", (profile_id,))]
        for row in rows:
            row["provenance"] = json.loads(row.pop("provenance_json"))
        return {"profile_id": profile_id, "versions": rows}

    def list_stage_a_profiles(self):
        with self.lock:
            ids = [r[0] for r in self.db.execute("SELECT DISTINCT profile_id FROM stage_a_versions ORDER BY profile_id")]
        return [self.get_stage_a_profile(x) for x in ids]


class Runtime:
    def __init__(self, stage_b_root: pathlib.Path, threads: int):
        self.root = stage_b_root.resolve()
        if not (self.root / "src/instruction_reminder/residual_set_attention_candidate.py").is_file():
            raise FileNotFoundError(f"Stage-B source tree not found under {self.root}")
        sys.path.insert(0, str(self.root / "src"))
        started = time.perf_counter()
        from instruction_reminder.residual_set_attention_candidate import ResidualSetAttentionCandidate
        self.model = ResidualSetAttentionCandidate(
            self.root / "runs/residual_set_attention_20261022/fit_v2",
            self.root / "models/applicability_nlsi_full_profile_seed20261021_v1",
            self.root / "assets/encoder",
            self.root / "runs/context_policy_live_demo_20261021/crossencoder_tinybert_diag_v2/serving_selected_epoch3",
            threads=threads, batch_size=16,
            deployment_manifest=(self.root / "runtime_deployment_manifest.json"
                                 if (self.root / "runtime_deployment_manifest.json").is_file() else None))
        self.inference_lock = threading.Lock()
        from transformers import AutoTokenizer
        self.tokenizer_dir = self.root / "assets/qwen2_5_7b_kaggle_v1_tokenizer"
        provenance_path = self.tokenizer_dir / "provenance.json"
        runtime_manifest_path = self.root / "runs/joint_correction_planner_20261022/stage_b_cooperative_runtime_v2/runtime_manifest.json"
        if not provenance_path.is_file() or not runtime_manifest_path.is_file():
            raise FileNotFoundError("pinned Qwen tokenizer provenance or Stage-B runtime manifest is missing")
        self.tokenizer_provenance_sha = sha_file(provenance_path)
        runtime_manifest = json.loads(runtime_manifest_path.read_text(encoding="utf-8"))
        if runtime_manifest.get("native_tokenizer", {}).get("provenance_sha256") != self.tokenizer_provenance_sha:
            raise RuntimeError("native tokenizer provenance does not match the frozen Stage-B runtime manifest")
        tokenizer_provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        for filename, expected in tokenizer_provenance.get("tokenizer_files", {}).items():
            if sha_file(self.tokenizer_dir / filename) != expected:
                raise RuntimeError(f"native tokenizer file binding mismatch: {filename}")
        self.tokenizer = AutoTokenizer.from_pretrained(str(self.tokenizer_dir), local_files_only=True, use_fast=True)
        if not getattr(self.tokenizer, "chat_template", None):
            raise RuntimeError("pinned native tokenizer is missing its chat template")
        self.load_ms = (time.perf_counter() - started) * 1000
        self.bindings = {
            "selected_state_sha256": self.model.bindings.selected_state_sha256,
            "fit_receipt_sha256": self.model.bindings.fit_receipt_sha256,
            "artifact_manifest_sha256": self.model.bindings.artifact_manifest_sha256,
            "plan_sha256": self.model.bindings.plan_sha256,
            "baseline_result_sha256": self.model.bindings.baseline_result_sha256,
            "baseline_head_sha256": self.model.bindings.baseline_head_sha256,
            "pair_model_sha256": self.model.bindings.pair_model_sha256,
            "native_tokenizer_provenance_sha256": self.tokenizer_provenance_sha,
            "threshold": self.model.bindings.threshold,
            "selected_epoch": self.model.bindings.selected_epoch,
            "source_tree": str(self.root),
        }

    def plan(self, policy: str, context: str, native_messages=None, rules=None):
        from instruction_reminder.data import Case, Instruction
        from instruction_reminder.joint_correction_plans import render_plan, validate_case
        if not policy.strip() or not context.strip():
            raise ValueError("Standing policy and current context are required.")
        if len(policy) > 24000 or len(context) > 24000:
            raise ValueError("Policy and context are limited to 24,000 characters each.")
        if native_messages is None:
            native_messages = [{"role": "system", "content": policy}, {"role": "user", "content": context}]
        if not isinstance(native_messages, list) or not native_messages:
            raise ValueError("native_messages must be a nonempty message list")
        messages = []
        for m in native_messages:
            if not isinstance(m, dict) or not isinstance(m.get("role"), str) or not isinstance(m.get("content"), str):
                raise ValueError("each native message needs string role and content")
            messages.append({"role": m["role"], "content": m["content"]})
        if not any(m["role"] == "system" and m["content"] == policy for m in messages):
            raise ValueError("native history must contain the exact standing policy as a system message")
        if messages[-1]["role"] != "user" or messages[-1]["content"] != context:
            raise ValueError("the final native message must be the exact current user context")
        if rules is None:
            candidates = [{"id": "0", "text": policy, "span": [0, len(policy)]}]
            selection_scope = "whole_policy_single_candidate"
        else:
            if not isinstance(rules, list) or not rules or len(rules) > 64:
                raise ValueError("rules must be a nonempty list of up to 64 exact policy excerpts")
            candidates, seen = [], set()
            for i, raw in enumerate(rules):
                if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not isinstance(raw.get("text"), str):
                    raise ValueError(f"rule {i} must have string id and text")
                rid, text = raw["id"], raw["text"]
                if not rid or rid in seen or not text.strip(): raise ValueError(f"rule {i} has duplicate/empty id or empty text")
                seen.add(rid)
                span = raw.get("source_span")
                if span is not None:
                    if (not isinstance(span, list) or len(span) != 2 or not all(isinstance(v,int) for v in span)
                            or span[0] < 0 or span[1] < span[0] or policy[span[0]:span[1]] != text):
                        raise ValueError(f"rule {rid} source_span must point to its exact policy text")
                else:
                    start = policy.find(text)
                    if start < 0: raise ValueError(f"rule {rid} is not an exact excerpt of the standing policy")
                    span = [start, start + len(text)]
                candidates.append({"id": rid, "text": text, "span": span})
            selection_scope = "explicit_policy_excerpts"
        request = {"policy": policy, "context": context, "native_messages": messages, "rules": candidates}
        request_hash = sha_bytes(canonical(request))
        case_id = "c4-" + request_hash[:20]
        predict_start = time.perf_counter()
        case = Case(example_id=case_id, context=context,
                    instructions=tuple(Instruction(c["id"], c["text"]) for c in candidates), gold_indices=())
        with self.inference_lock:
            selected, scores = self.model.predict([case])
        selection_ms = (time.perf_counter() - predict_start) * 1000
        selected_indices = [int(x) for x in selected[case_id]]
        selected_ids = [candidates[i]["id"] for i in selected_indices]
        render_case = {"case_id": case_id, "source_group_id": case_id,
                       "native_messages": messages,
                       "requirements": [{"rule_id": c["id"], "text": c["text"],
                                         "source_ref": f"user-policy-excerpt:{c['span'][0]}:{c['span'][1]}",
                                         "source_label": ("system_policy" if selection_scope == "whole_policy_single_candidate" else c["id"]),
                                         "bundle_ids": [], "evidence_spans": []}
                                        for c in candidates], "bundles": []}
        validate_case(render_case)
        mask = [[int(i in set(selected_indices)), 0, 0] for i in range(len(candidates))]
        rendered = render_plan(render_case, mask)
        optimized = copy.deepcopy(messages)
        if rendered["suffix"]:
            optimized.append({"role": "user", "content": rendered["suffix"]})
        if optimized[:len(messages)] != messages:
            raise RuntimeError("native prefix was modified")
        orig_ids = self.tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=False)
        new_ids = self.tokenizer.apply_chat_template(optimized, tokenize=True, add_generation_prompt=False)
        if hasattr(orig_ids, "tolist"): orig_ids = orig_ids.tolist()
        if hasattr(new_ids, "tolist"): new_ids = new_ids.tolist()
        if orig_ids and isinstance(orig_ids[0], list): orig_ids = orig_ids[0]
        if new_ids and isinstance(new_ids[0], list): new_ids = new_ids[0]
        if list(new_ids[:len(orig_ids)]) != list(orig_ids):
            raise RuntimeError("serialized native token prefix changed after adding the restatement")
        return {"request_sha256": request_hash, "selected": bool(selected_indices), "selected_rule_ids": selected_ids,
                "selection_scope": selection_scope, "candidate_rules": candidates,
                "model_score": scores[case_id], "suffix": rendered["suffix"],
                "suffix_sha256": rendered["suffix_sha256"], "plan_sha256": rendered["plan_sha256"],
                "native_messages": messages, "optimized_messages": optimized,
                "native_prefix_preserved": True, "native_prefix_message_count": len(messages),
                "native_prefix_tokens": len(orig_ids), "optimized_native_tokens": len(new_ids),
                "added_native_tokens": len(new_ids)-len(orig_ids),
                "native_prefix_token_ids_sha256": sha_bytes(canonical(orig_ids)),
                "optimized_token_ids_sha256": sha_bytes(canonical(new_ids)),
                "checkpoint_bindings": self.bindings,
                "timing_ms": {"selection": round(selection_ms, 3), "request_total": round((time.perf_counter()-predict_start)*1000,3),
                              "process_model_startup": round(self.load_ms,3)},
                "target_model_calls": 0, "target_answers_generated": False,
                "run_type": "optimizer_only_no_answer_generation",
                "cache_note": "Original native messages remain byte-for-byte in place; this establishes cache eligibility only, not a measured hosted cache hit."}


class Component4:
    def __init__(self, stage_b_root, db_path, stage_a_path, threads=2):
        self.store = Store(db_path)
        self.runtime = Runtime(stage_b_root, threads)
        self.stage_a_path = stage_a_path
        self.stage_a = self._load_stage_a(stage_a_path)
        self.evidence = self._load_evidence_bundle(HERE / "../data/evidence_manifest.json")

    @staticmethod
    def _load_stage_a(path):
        if not path.is_file():
            return {"status": "not_imported", "notice": "Verified BPO recording has not been copied into this package yet.", "cases": []}
        raw = path.read_bytes()
        obj = json.loads(raw)
        if not isinstance(obj, dict) or not isinstance(obj.get("cases"), list):
            raise ValueError("Stage A recorded artifact must contain a cases array")
        optimizer = obj.get("optimizer") or {}
        target = obj.get("target") or {}
        prompts = target.get("system_prompts_by_arm", {}) if isinstance(target, dict) else {}
        normalized = []
        for row in obj["cases"]:
            if not isinstance(row, dict): raise ValueError("Stage A recorded rows must be objects")
            arms = row.get("arms") or {}
            orig_arm = arms.get("original") or {}
            bpo_arm = arms.get("bpo") or {}
            orig_prompt = (row.get("original_prompt") or row.get("source_prompt") or row.get("original")
                           or (orig_arm.get("system_prompt") if isinstance(orig_arm, dict) else None)
                           or prompts.get("original") or optimizer.get("original_prompt") or "")
            rewrite_prompt = (row.get("rewrite_prompt") or row.get("optimized_prompt") or row.get("rewrite")
                              or (bpo_arm.get("system_prompt") if isinstance(bpo_arm, dict) else None)
                              or prompts.get("bpo") or optimizer.get("rewritten_prompt") or "")
            metrics = row.get("metrics")
            if metrics is None:
                metrics = {"checker": row.get("checker"),
                           "original": {k: v for k, v in orig_arm.items() if k in {"status", "checker", "response_sha256", "input_tokens", "output_tokens", "runtime_s"}} if isinstance(orig_arm, dict) else {},
                           "bpo": {k: v for k, v in bpo_arm.items() if k in {"status", "checker", "response_sha256", "input_tokens", "output_tokens", "runtime_s"}} if isinstance(bpo_arm, dict) else {}}
            if not arms and ("original_response" in row or "optimized_response" in row):
                arms = {
                    "original": {"system_prompt": orig_prompt, "response": row.get("original_response"),
                                 "response_sha256": (metrics or {}).get("original_response_sha256"),
                                 "source_evaluator": {"name": (metrics or {}).get("evaluator", "source evaluator"),
                                                      "pass": (metrics or {}).get("original_correct")}},
                    "bpo": {"system_prompt": rewrite_prompt, "response": row.get("optimized_response"),
                            "response_sha256": (metrics or {}).get("optimized_response_sha256"),
                            "source_evaluator": {"name": (metrics or {}).get("evaluator", "source evaluator"),
                                                 "pass": (metrics or {}).get("optimized_correct")}},
                }
            user_messages = row.get("user_messages") or []
            user_message = row.get("user_message") or "\n".join(str(m.get("content", "")) for m in user_messages if isinstance(m, dict))
            normalized.append({**row, "user_message": user_message, "arms": arms,
                               "original_prompt": orig_prompt, "rewrite_prompt": rewrite_prompt, "metrics": metrics})
        summary = obj.get("summary") or {}
        if isinstance(summary, dict):
            paired = summary.get("paired") or {}
            orig, bpo = summary.get("original") or {}, summary.get("bpo") or summary.get("stage_a") or {}
            summary_text = (f"Recorded BPO target examples · n={summary.get('n', len(normalized))}; "
                            f"original complete {orig.get('complete','not reported')}; BPO complete {bpo.get('complete','not reported')}; "
                            f"paired repairs {paired.get('repairs','not reported')}, regressions {paired.get('regressions','not reported')}, ties {paired.get('ties','not reported')}. "
                            "These are saved outcomes; no Stage A target call was made by this service.")
        else: summary_text = str(summary)
        return {**obj, "cases": normalized, "summary": summary_text,
                "provenance": {"source": obj.get("source"), "optimizer": optimizer, "target": target},
                "status": obj.get("status", "recorded"), "artifact_sha256": sha_bytes(raw),
                "artifact_path": str(path)}

    @staticmethod
    def _load_evidence_bundle(manifest_path):
        if not manifest_path.is_file(): return {"status": "not_available", "files": {}}
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema") != "component4_evidence_bindings_v1":
            raise RuntimeError("unrecognized Component 4 evidence manifest")
        objects = {}
        base = manifest_path.parent.parent
        for name, row in manifest.get("files", {}).items():
            path = (base / row["path"]).resolve()
            if base.resolve() not in path.parents or sha_file(path) != row["sha256"]:
                raise RuntimeError(f"evidence file binding failed: {name}")
            objects[name] = json.loads(path.read_text(encoding="utf-8"))
        return {"status": "verified", "manifest_sha256": sha_file(manifest_path), "manifest": manifest, "objects": objects}


def handler_for(app: Component4):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            print("C4", self.address_string(), fmt % args, flush=True)

        def reply(self, code, data, headers=None):
            payload = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", self.reply_content_type if isinstance(data, bytes) else "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            origin = self.headers.get("Origin", "")
            if re.fullmatch(r"http://(127\.0\.0\.1|localhost)(:\d+)?", origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            if headers:
                for k, v in headers.items(): self.send_header(k, v)
            self.end_headers(); self.wfile.write(payload)

        def read_json(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 1_000_000: raise ValueError("Request body must be 1 to 1,000,000 bytes")
            obj = json.loads(self.rfile.read(length))
            if not isinstance(obj, dict): raise ValueError("JSON body must be an object")
            return obj

        def do_OPTIONS(self):
            origin = self.headers.get("Origin", "")
            self.send_response(204)
            if re.fullmatch(r"http://(127\.0\.0\.1|localhost)(:\d+)?", origin):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type"); self.end_headers()

        def do_GET(self):
            parsed = urlparse(self.path); path = parsed.path; parts = path.strip("/").split("/")
            try:
                static = {"/": ("index.html", "text/html; charset=utf-8"),
                          "/c4/": ("index.html", "text/html; charset=utf-8"),
                          "/index.html": ("index.html", "text/html; charset=utf-8"),
                          "/c4/index.html": ("index.html", "text/html; charset=utf-8"),
                          "/styles.css": ("styles.css", "text/css; charset=utf-8"),
                          "/c4/styles.css": ("styles.css", "text/css; charset=utf-8"),
                          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                          "/c4/app.js": ("app.js", "text/javascript; charset=utf-8")}
                if path in static:
                    filename, ctype = static[path]
                    asset = HERE.parent / "frontend" / filename
                    if not asset.is_file(): return self.reply(503, {"error": f"frontend asset {filename} is being prepared"})
                    self.reply_content_type = ctype
                    return self.reply(200, asset.read_bytes())
                if path == "/api/c4/health":
                    return self.reply(200, {"status": "ready", "component": 4, "runtime": "frozen_residual_R_cpu",
                        "runtime_bindings": app.runtime.bindings, "model_startup_ms": round(app.runtime.load_ms,3),
                        "stage_a_recording": {"status": app.stage_a["status"], "artifact_sha256": app.stage_a.get("artifact_sha256")},
                        "evidence": {"status": app.evidence["status"], "manifest_sha256": app.evidence.get("manifest_sha256")},
                        "persistence": {"backend": "sqlite", "path": str(app.store.path)}})
                if path == "/api/c4/evidence": return self.reply(200, app.evidence)
                if path == "/api/c4/stage-a/recorded": return self.reply(200, app.stage_a)
                if path == "/api/c4/stage-a/versions": return self.reply(200, {"profiles": app.store.list_stage_a_profiles()})
                if len(parts) == 5 and parts[:4] == ["api", "c4", "stage-a", "versions"]:
                    value = app.store.get_stage_a_profile(parts[4])
                    return self.reply(200 if value["versions"] else 404, value)
                if path == "/api/c4/sessions": return self.reply(200, {"sessions": app.store.list_sessions()})
                if len(parts) == 5 and parts[:3] == ["api", "c4", "sessions"] and parts[4] == "export":
                    sid = parts[3]; val = app.store.get_session(sid)
                    if val is None: return self.reply(404, {"error": "session not found"})
                    val["exported_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    data = json.dumps(val, ensure_ascii=False, indent=2).encode()
                    dest = app.store.path.parent / "exports" / f"{sid}.json"
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    tmp = dest.with_suffix(".json.tmp"); tmp.write_bytes(data); tmp.replace(dest)
                    return self.reply(200, val, {"Content-Disposition": f'attachment; filename="{sid}.json"', "X-Export-SHA256": sha_bytes(data)})
                if len(parts) == 4 and parts[:3] == ["api", "c4", "sessions"]:
                    value = app.store.get_session(parts[3])
                    return self.reply(200 if value else 404, value or {"error": "session not found"})
                return self.reply(404, {"error": "unknown Component 4 route"})
            except Exception as exc: return self.reply(400, {"error": str(exc)})

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                body = self.read_json()
                if path == "/api/c4/sessions":
                    policy = body.get("policy", ""); title = body.get("title", "Conversation")
                    if not isinstance(policy, str) or not policy.strip(): raise ValueError("policy is required")
                    if not isinstance(title, str): raise ValueError("title must be a string")
                    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    sid = app.store.create_session(title[:200], policy, now)
                    return self.reply(201, {"session_id": sid, "created_at": now, "turn_count": 0})
                if path == "/api/c4/turns":
                    policy, context = body.get("policy"), body.get("context")
                    sid = body.get("session_id")
                    if not isinstance(sid, str) or not sid: raise ValueError("session_id is required")
                    if not app.store.has_session(sid): return self.reply(404, {"error": "session not found"})
                    result = app.runtime.plan(policy, context, body.get("native_messages"), body.get("rules"))
                    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    saved = app.store.save_turn(sid, policy, result, now)
                    return self.reply(200, saved)
                if path == "/api/c4/stage-a/versions":
                    profile_id = body.get("profile_id") or str(uuid.uuid4())
                    title, prompt = body.get("title", "Manual prompt"), body.get("prompt")
                    if not isinstance(profile_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", profile_id): raise ValueError("invalid profile_id")
                    if not isinstance(title, str) or not isinstance(prompt, str) or not prompt.strip(): raise ValueError("title and nonempty prompt are required")
                    source_prompt = body.get("source_prompt", "")
                    if not isinstance(source_prompt, str): raise ValueError("source_prompt must be a string")
                    provenance = {"origin": "manual_user_entry", "optimizer": None, "model": None,
                                  "recorded_bpo_artifact_sha256": app.stage_a.get("artifact_sha256")}
                    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    row = app.store.save_stage_a_version(profile_id, title[:200], source_prompt, prompt, now, provenance)
                    return self.reply(201, row)
                return self.reply(404, {"error": "unknown Component 4 route"})
            except KeyError as exc: return self.reply(404, {"error": str(exc)})
            except Exception as exc: return self.reply(400, {"error": str(exc)})

        def do_PUT(self):
            parts = urlparse(self.path).path.strip("/").split("/")
            try:
                body = self.read_json()
                if len(parts) == 5 and parts[:4] == ["api", "c4", "stage-a", "versions"]:
                    profile_id = parts[4]
                    existing = app.store.get_stage_a_profile(profile_id)
                    if not existing["versions"]: return self.reply(404, {"error": "profile not found"})
                    prompt, title = body.get("prompt"), body.get("title", existing["versions"][-1]["title"])
                    if not isinstance(prompt, str) or not prompt.strip() or not isinstance(title, str): raise ValueError("title and nonempty prompt are required")
                    source_prompt = body.get("source_prompt", existing["versions"][-1]["source_prompt"])
                    if not isinstance(source_prompt, str): raise ValueError("source_prompt must be a string")
                    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    provenance = {"origin": "manual_user_entry", "optimizer": None, "model": None,
                                  "recorded_bpo_artifact_sha256": app.stage_a.get("artifact_sha256")}
                    return self.reply(201, app.store.save_stage_a_version(profile_id, title[:200], source_prompt, prompt, now, provenance))
                return self.reply(404, {"error": "unknown Component 4 route"})
            except Exception as exc: return self.reply(400, {"error": str(exc)})

    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8774)
    p.add_argument("--stage-b-root", type=pathlib.Path, default=DEFAULT_STAGE_B)
    p.add_argument("--db", type=pathlib.Path, default=DEFAULT_DB)
    p.add_argument("--stage-a-recorded", type=pathlib.Path, default=DEFAULT_STAGE_A)
    p.add_argument("--threads", type=int, default=2)
    a = p.parse_args()
    if a.host not in {"127.0.0.1", "localhost"}: raise SystemExit("Component 4 backend only binds localhost")
    app = Component4(a.stage_b_root, a.db, a.stage_a_recorded, a.threads)
    with ThreadingHTTPServer((a.host, a.port), handler_for(app)) as srv:
        print(f"Component 4 CPU backend: http://{a.host}:{a.port}/api/c4/health", flush=True)
        print("Frozen residual R only. No target calls. Local sessions are saved to SQLite.", flush=True)
        srv.serve_forever()


if __name__ == "__main__": main()
