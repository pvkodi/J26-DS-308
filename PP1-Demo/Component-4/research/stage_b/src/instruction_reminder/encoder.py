"""Frozen CPU encoder; every candidate sees the complete supplied profile.

No label, source ID, reasoning category, or API answer is passed to this class.
The encoder is an existing pretrained asset, not a new semantic teacher.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time
from typing import Sequence

import numpy as np

from .data import Case

FEATURE_VERSION = "joint_and_separate_v1"
MAX_TOKENS = 512


class UnsupportedInput(ValueError):
    """An input cannot be represented completely by this bounded model."""


@dataclass
class FeatureBatch:
    X: np.ndarray
    similarity: np.ndarray
    offsets: np.ndarray
    joint_token_lengths: list[int]
    input_hashes: list[str]


def _unit(x: np.ndarray) -> np.ndarray:
    return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-12)


def format_joint(context: str, instructions: Sequence[str]):
    """Return text and exact character spans, without candidate IDs or labels."""
    text = "Current request:\n"
    context_span = (len(text), len(text) + len(context))
    text += context + "\nStanding instructions:\n"
    spans = []
    for instruction in instructions:
        start = len(text)
        text += instruction
        spans.append((start, len(text)))
        text += "\n"
    return text, context_span, spans


class FeatureEncoder:
    """ONNX CPU only, fixed weights, no truncation and no target LLM calls."""

    def __init__(self, asset_dir: str | Path, threads: int = 4):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        if threads < 1:
            raise ValueError("threads must be positive")
        self.asset_dir = Path(asset_dir)
        self.source = json.loads((self.asset_dir / "source.json").read_text())
        for name in ("onnx/model.onnx", "tokenizer.json"):
            item = next(x for x in self.source["files"] if x["name"] == name)
            actual = hashlib.sha256((self.asset_dir / name).read_bytes()).hexdigest()
            if actual != item["sha256"]:
                raise ValueError(f"encoder asset hash mismatch: {name}")
        self.tokenizer = Tokenizer.from_file(str(self.asset_dir / "tokenizer.json"))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        self.session = ort.InferenceSession(
            str(self.asset_dir / "onnx/model.onnx"), sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        if self.session.get_providers() != ["CPUExecutionProvider"]:
            raise RuntimeError("CPU execution provider was not enforced")
        self.input_names = {x.name for x in self.session.get_inputs()}
        output_names = {x.name for x in self.session.get_outputs()}
        self.hidden_name = next((x for x in ("last_hidden_state", "token_embeddings")
                                 if x in output_names), None)
        if self.hidden_name is None:
            raise RuntimeError(f"token-level encoder output required; found {output_names}")
        self.pad_id = self.tokenizer.token_to_id("[PAD]")
        if self.pad_id is None:
            raise RuntimeError("pinned tokenizer has no PAD token")
        self._text_cache: dict[str, np.ndarray] = {}

    def _encode(self, text: str):
        if not isinstance(text, str) or not text.strip():
            raise UnsupportedInput("empty context or instruction text")
        encoded = self.tokenizer.encode(text, add_special_tokens=True)
        if len(encoded.ids) > MAX_TOKENS:
            raise UnsupportedInput(
                f"complete input has {len(encoded.ids)} tokens; maximum is {MAX_TOKENS}; no truncation performed"
            )
        return encoded

    def _hidden(self, encodings):
        longest = max(len(e.ids) for e in encodings)
        ids = np.full((len(encodings), longest), self.pad_id, dtype=np.int64)
        mask = np.zeros_like(ids)
        types = np.zeros_like(ids)
        for i, e in enumerate(encodings):
            n = len(e.ids)
            ids[i, :n] = e.ids
            mask[i, :n] = e.attention_mask
            types[i, :n] = e.type_ids
        feed = {"input_ids": ids, "attention_mask": mask, "token_type_ids": types}
        hidden = self.session.run([self.hidden_name], {k: v for k, v in feed.items() if k in self.input_names})[0]
        if hidden.ndim != 3 or not np.isfinite(hidden).all():
            raise RuntimeError("invalid encoder hidden states")
        return hidden

    def encode_texts(self, texts: Sequence[str], batch_size: int = 16) -> np.ndarray:
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        missing = list(dict.fromkeys(t for t in texts if t not in self._text_cache))
        for start in range(0, len(missing), batch_size):
            batch = missing[start:start + batch_size]
            enc = [self._encode(t) for t in batch]
            h = self._hidden(enc)
            for i, (text, e) in enumerate(zip(batch, enc)):
                # SentenceTransformer mean pooling includes special tokens.
                self._text_cache[text] = _unit(h[i, :len(e.ids)].mean(axis=0)).astype(np.float32)
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        return np.stack([self._text_cache[t] for t in texts])

    @staticmethod
    def _span_pool(hidden, encoding, span):
        start, end = span
        indices = [i for i, (a, b) in enumerate(encoding.offsets)
                   if b > a and b > start and a < end]
        if not indices:
            raise UnsupportedInput("a complete text block has no representable tokens")
        return _unit(hidden[indices].mean(axis=0)).astype(np.float32)

    def inspect_lengths(self, cases: Sequence[Case]) -> list[int]:
        return [len(self._encode(format_joint(c.context, [i.text for i in c.instructions])[0]).ids)
                for c in cases]

    def encode_cases(self, cases: Sequence[Case], batch_size: int = 16) -> FeatureBatch:
        if not cases:
            raise ValueError("at least one case is required")
        if any(not c.instructions for c in cases):
            raise UnsupportedInput("empty candidate collection; use explicit no-instructions bypass")
        # Validate all joint inputs before doing expensive feature extraction.
        formatted = [format_joint(c.context, [i.text for i in c.instructions]) for c in cases]
        encodings = [self._encode(t) for t, _, _ in formatted]
        lengths = [len(e.ids) for e in encodings]
        queries = self.encode_texts([c.context for c in cases], batch_size)
        candidate_texts = [i.text for c in cases for i in c.instructions]
        standalone = self.encode_texts(candidate_texts, batch_size)
        offsets = np.r_[0, np.cumsum([len(c.instructions) for c in cases])].astype(np.int64)
        features, similarities = [], []
        start_time = time.monotonic()
        for start in range(0, len(cases), batch_size):
            enc = encodings[start:start + batch_size]
            hidden = self._hidden(enc)
            for local, e in enumerate(enc):
                index = start + local
                _, cspan, spans = formatted[index]
                joint_context = self._span_pool(hidden[local], e, cspan)
                q = queries[index]
                for j, span in enumerate(spans):
                    v = standalone[offsets[index] + j]
                    r = self._span_pool(hidden[local], e, span)
                    sim = float(q @ v)
                    vector = np.concatenate((q, v, q * v, np.abs(q - v),
                                             joint_context, r, joint_context * r,
                                             np.abs(joint_context - r),
                                             np.array([sim, float(joint_context @ r)], dtype=np.float32)))
                    features.append(vector)
                    similarities.append(sim)
            if start == 0 or start + batch_size >= len(cases) or (start // batch_size) % 10 == 0:
                print(json.dumps({"event": "joint_features", "cases_done": min(start + batch_size, len(cases)),
                                  "cases_total": len(cases), "seconds": round(time.monotonic() - start_time, 3)}), flush=True)
        X = np.stack(features).astype(np.float32)
        if X.shape[0] != len(candidate_texts) or not np.isfinite(X).all():
            raise RuntimeError("feature-to-candidate alignment or finite check failed")
        hashes = [hashlib.sha256(json.dumps(c.model_input(), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                  for c in cases]
        return FeatureBatch(X, np.asarray(similarities, dtype=np.float32), offsets, lengths, hashes)
