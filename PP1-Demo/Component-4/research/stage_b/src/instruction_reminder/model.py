"""Reloadable CPU selection head with a lazy frozen-encoder dependency."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from .data import Case


def _encode_features(cases: Sequence[Case], assets: str | Path, threads: int, batch_size: int, encoder=None):
    # Import only when a selector is used, so data/metrics stay lightweight.
    from .encoder import FeatureEncoder  # supplied by the frozen-encoder component

    if encoder is None:
        encoder = FeatureEncoder(str(assets), threads=threads)
    batch = encoder.encode_cases(cases, batch_size=batch_size)
    x = np.asarray(batch.X, dtype=np.float32)
    similarity = np.asarray(batch.similarity, dtype=np.float32).reshape(-1)
    offsets = np.asarray(batch.offsets, dtype=np.int64)
    if x.ndim != 2 or x.shape[0] != len(similarity):
        raise ValueError("encoder returned misaligned X/similarity arrays")
    if offsets.shape != (len(cases) + 1,) or offsets[0] != 0 or offsets[-1] != len(x):
        raise ValueError("encoder returned invalid case offsets")
    expected = np.asarray([len(c.instructions) for c in cases], dtype=np.int64)
    if not np.array_equal(np.diff(offsets), expected):
        raise ValueError("encoder candidate rows do not match each case's instruction count")
    if not np.isfinite(x).all() or not np.isfinite(similarity).all():
        raise ValueError("encoder returned nonfinite features")
    return (x.astype(np.float32, copy=False), offsets,
            list(batch.joint_token_lengths), list(batch.input_hashes), similarity)


def _asset_hashes(path: Path) -> dict[str, str]:
    def sha(file: Path) -> str:
        h = hashlib.sha256()
        with file.open("rb") as f:
            for block in iter(lambda: f.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()
    if path.is_file():
        return {path.name: sha(path)}
    return {str(p.relative_to(path)): sha(p) for p in sorted(path.rglob("*")) if p.is_file()}


class CPUSelector:
    """Frozen ONNX encoder plus a pickle-free logistic selection head."""

    def __init__(self, model_dir: str | Path, assets: str | Path, threads: int = 4):
        self.model_dir = Path(model_dir)
        self.assets = Path(assets)
        self.threads = threads
        self.config = json.loads((self.model_dir / "config.json").read_text(encoding="utf-8"))
        from .encoder import FEATURE_VERSION
        if self.config.get("encoder_feature_version") != FEATURE_VERSION:
            raise ValueError("encoder feature version does not match the trained model")
        if self.config.get("assets_sha256") != _asset_hashes(self.assets):
            raise ValueError("encoder assets do not match the trained model binding")
        arrays = np.load(self.model_dir / "head.npz", allow_pickle=False)
        self.coef = np.asarray(arrays["coef"], dtype=np.float64)
        self.intercept = np.asarray(arrays["intercept"], dtype=np.float64)
        self.mean = np.asarray(arrays["scaler_mean"], dtype=np.float64)
        self.scale = np.asarray(arrays["scaler_scale"], dtype=np.float64)
        if self.coef.ndim != 2 or self.coef.shape[0] != 1 or self.intercept.size != 1:
            raise ValueError("head.npz must contain a binary logistic classifier")
        if self.mean.ndim != 1 or self.scale.shape != self.mean.shape or self.coef.shape[1] != self.mean.size:
            raise ValueError("classifier and scaler dimensions do not match")
        if int(self.config.get("feature_dimension", -1)) != self.mean.size:
            raise ValueError("classifier dimension does not match the trained feature configuration")
        if not np.isfinite(self.coef).all() or not np.isfinite(self.intercept).all():
            raise ValueError("classifier contains nonfinite parameters")
        if not np.isfinite(self.mean).all() or not np.isfinite(self.scale).all() or np.any(self.scale <= 0):
            raise ValueError("scaler contains invalid parameters")
        self.threshold = float(self.config["threshold"])
        self._encoder = None

    @classmethod
    def load(cls, model_dir: str | Path, assets: str | Path, threads: int = 4) -> "CPUSelector":
        return cls(model_dir, assets, threads)

    def predict(self, cases: Sequence[Case], batch_size: int = 16, encoder=None) -> tuple[dict[str, list[int]], dict[str, list[float]]]:
        if len({c.example_id for c in cases}) != len(cases):
            raise ValueError("cases must have unique example IDs")
        if encoder is None:
            if self._encoder is None:
                from .encoder import FeatureEncoder
                self._encoder = FeatureEncoder(self.assets, threads=self.threads)
            encoder = self._encoder
        x, offsets, _lengths, _input_hashes, _similarity = _encode_features(
            cases, self.assets, self.threads, batch_size, encoder)
        z = (x.astype(np.float64) - self.mean) / self.scale
        logits = (z @ self.coef[0]) + float(self.intercept[0])
        # Stable sigmoid in both tails.
        probabilities = np.empty_like(logits)
        positive = logits >= 0
        probabilities[positive] = 1.0 / (1.0 + np.exp(-logits[positive]))
        ex = np.exp(logits[~positive])
        probabilities[~positive] = ex / (1.0 + ex)
        predictions: dict[str, list[int]] = {}
        scores: dict[str, list[float]] = {}
        for n, case in enumerate(cases):
            a, b = int(offsets[n]), int(offsets[n + 1])
            local = probabilities[a:b]
            scores[case.example_id] = local.astype(float).tolist()
            predictions[case.example_id] = np.flatnonzero(local >= self.threshold).astype(int).tolist()
        return predictions, scores
