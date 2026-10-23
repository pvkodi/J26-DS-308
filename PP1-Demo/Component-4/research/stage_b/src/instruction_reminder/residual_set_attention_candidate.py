"""Isolated CPU runtime for the frozen residual set-attention diagnostic.

This candidate keeps the epoch-3 pairwise selector frozen and adds the fitted
zero-initialized set residual over the complete ordered instruction profile.
It is an experimental adapter, not the production selector. Labels and target
outputs are never read by prediction.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Sequence

import numpy as np

from .data import Case
from .tinybert_pair_candidate import TinyBertPairCandidate


VERSION = "residual_set_attention_v2_selected_epoch3"
FEATURE_DIM = 3075
THRESHOLD = 0.45


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _sigmoid(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=np.float64)
    out = np.empty_like(x)
    pos = x >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-x[pos]))
    ex = np.exp(x[~pos])
    out[~pos] = ex / (1.0 + ex)
    return out


@dataclass(frozen=True)
class RuntimeBindings:
    version: str
    plan_sha256: str
    fit_receipt_sha256: str
    artifact_manifest_sha256: str
    selected_state_sha256: str
    baseline_result_sha256: str
    baseline_head_sha256: str
    pair_model_sha256: str
    trainer_sha256: str
    threshold: float
    selected_epoch: int


class _ResidualSet:
    """Architecture copied exactly from train_residual_set_attention_v2."""

    def __new__(cls, torch):
        class Module(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.project = torch.nn.Linear(3075, 64)
                self.attn = torch.nn.MultiheadAttention(64, 2, batch_first=True)
                self.out = torch.nn.Linear(64, 1)

            def forward(self, x, pad):
                h = torch.nn.functional.gelu(self.project(x))
                attended, _ = self.attn(h, h, h, key_padding_mask=pad, need_weights=False)
                return self.out(h + attended).squeeze(-1)
        return Module()


class ResidualSetAttentionCandidate:
    """Frozen CPU candidate with exact full-profile batching and ID order."""

    def __init__(
        self,
        fit_dir: str | Path,
        frozen_model_dir: str | Path,
        encoder_assets: str | Path,
        pair_candidate_run_dir: str | Path,
        threads: int = 4,
        batch_size: int = 32,
        deployment_manifest: str | Path | None = None,
    ) -> None:
        if threads < 1 or batch_size < 1:
            raise ValueError("threads and batch_size must be positive")
        self.fit_dir = Path(fit_dir).resolve()
        self.threads = int(threads)
        self.batch_size = int(batch_size)
        from .runtime_deployment import load_deployment
        deployment = load_deployment(deployment_manifest)
        self.plan_path = self.fit_dir.parent / "experiment_plan_v2.json"
        self.receipt_path = self.fit_dir / "fit_receipt.json"
        self.artifact_path = self.fit_dir / "artifact_manifest.json"
        self.state_path = self.fit_dir / "selected_state.pt"
        for path in (self.plan_path, self.receipt_path, self.artifact_path, self.state_path):
            if not path.is_file():
                raise FileNotFoundError(path)

        self.plan = json.loads(self.plan_path.read_text(encoding="utf-8"))
        self.receipt = json.loads(self.receipt_path.read_text(encoding="utf-8"))
        self.artifact = json.loads(self.artifact_path.read_text(encoding="utf-8"))
        if self.receipt.get("status") != "complete" or self.receipt.get("schema") != "residual_set_attention_fit_receipt_v1":
            raise ValueError("residual fit receipt is not complete or has an unexpected schema")
        exclusions = self.receipt.get("exclusions", {})
        if exclusions != {
            "test_split_opened": False,
            "test_labels_read": False,
            "locked48_opened": False,
            "target_calls": 0,
            "production_changed": False,
        }:
            raise ValueError("residual fit receipt does not certify the declared development-only scope")
        # The frozen plan intentionally retains its pre-fit status after the
        # fit; the completed receipt is separately bound to its exact digest.
        if (self.plan.get("schema_version") != 1
                or self.plan.get("kind") != "frozen_baseline_residual_set_attention_v2"):
            raise ValueError("unexpected residual experiment plan schema")
        plan_sha = _sha(self.plan_path)
        if self.receipt.get("plan_sha256") != plan_sha or self.artifact.get("plan_sha256") != plan_sha:
            raise ValueError("plan hash does not match both frozen fit receipts")
        if self.receipt.get("selected_epoch") != 3 or self.receipt.get("selected_threshold") != THRESHOLD:
            raise ValueError("this adapter is only for the frozen selected epoch 3 at threshold 0.45")
        if self.artifact.get("selection", {}).get("selected_epoch") != 3 or self.artifact.get("selection", {}).get("threshold") != THRESHOLD:
            raise ValueError("artifact selection metadata disagrees with the frozen fit receipt")

        # Bind the receipt before choosing strict research or deployment checks.
        bind = self.receipt.get("bindings", {})
        file_entries = self.artifact.get("files", {})
        if deployment is None:
            for name, entry in file_entries.items():
                path = self.fit_dir / name
                if not path.is_file() or _sha(path) != entry.get("sha256") or path.stat().st_size != entry.get("bytes"):
                    raise ValueError(f"residual artifact file binding failed: {name}")
        else:
            if deployment.root != self.fit_dir.parents[2]:
                raise ValueError("deployment manifest is not at the active Stage-B runtime root")
            for path in (self.plan_path, self.receipt_path, self.artifact_path, self.state_path):
                deployment.require(path.relative_to(deployment.root).as_posix())
            lineage = deployment.source_lineage
            expected_lineage = {
                "fit_plan_sha256": plan_sha,
                "fit_receipt_sha256": _sha(self.receipt_path),
                "artifact_manifest_sha256": _sha(self.artifact_path),
                "selected_state_sha256": _sha(self.state_path),
                "upstream_fit_bindings": bind,
            }
            if any(lineage.get(key) != value for key, value in expected_lineage.items()):
                raise ValueError("deployment lineage does not match the frozen residual fit receipts")
            state_entry = file_entries.get(self.state_path.name)
            if not isinstance(state_entry, dict) or state_entry.get("sha256") != _sha(self.state_path):
                raise ValueError("deployment selected state is not the one recorded in the fit artifact manifest")
        if _sha(self.state_path) != "e0fac9e1f3c75902a15e054131379497287996eefef6bc54a218af10345b0f26":
            raise ValueError("selected residual state is not the reviewed frozen checkpoint")

        # Bind every upstream serving dependency to the exact completed fit.
        root = self.fit_dir.parents[2]
        expected_paths = {
            "trainer_sha256": root / "scripts/train_residual_set_attention_v2.py",
            "train_sha256": root / "runs/nlsi_full_profile_seed20261021_v1/splits/train.jsonl",
            "dev_sha256": root / "runs/nlsi_full_profile_seed20261021_v1/splits/validation.jsonl",
            "split_manifest_sha256": root / "runs/nlsi_full_profile_seed20261021_v1/splits/split_manifest.json",
            "feature_cache_sha256": root / "runs/representation_ablation_20261021/train_validation_features.npz",
            "pair_score_sha256": root / "runs/context_policy_live_demo_20261021/crossencoder_tinybert_diag_v2/epoch_3/scores.npz",
            "baseline_head_sha256": root / "runs/context_policy_live_demo_20261021/crossencoder_tinybert_diag_v2/epoch_3/augmented_head.npz",
            "baseline_result_sha256": root / "runs/context_policy_live_demo_20261021/crossencoder_tinybert_diag_v2/result.json",
            "pair_model_sha256": root / "runs/context_policy_live_demo_20261021/crossencoder_tinybert_diag_v2/epoch_3/crossencoder/model.safetensors",
            "baseline_probability_parity_sha256": root / "runs/context_policy_live_demo_20261021/crossencoder_tinybert_diag_v2/serving_selected_epoch3/adapter_validation_parity_and_product_probes.json",
            "baseline_prediction_sha256": root / "runs/context_policy_live_demo_20261021/crossencoder_tinybert_diag_v2/serving_selected_epoch3/candidate_validation_predictions.json",
            "minilm_source_sha256": root / "assets/encoder/source.json",
        }
        if deployment is None:
            for key, path in expected_paths.items():
                if not path.is_file() or _sha(path) != bind.get(key):
                    raise ValueError(f"upstream fit binding mismatch for {key}")
        else:
            # The copied training receipt retains these original upstream hashes.
            # They remain inspectable provenance, but the large source/cache files
            # are not deployment dependencies and are not loaded at serving time.
            if deployment.source_lineage.get("upstream_fit_bindings") != bind:
                raise ValueError("deployment upstream provenance differs from the fit receipt")
        pair = TinyBertPairCandidate(
            Path(pair_candidate_run_dir).resolve(), frozen_model_dir, encoder_assets,
            threads=threads,
        )
        if pair.result.get("source_parent_result_sha256") != bind.get("baseline_result_sha256"):
            raise ValueError("pairwise serving bundle is not descended from the exact residual-fit baseline result")
        if pair.bindings.head_sha256 != bind.get("baseline_head_sha256"):
            raise ValueError("pairwise serving head is not the one used by the residual fit")
        if pair.bindings.crossencoder_files_sha256.get("model.safetensors") != bind.get("pair_model_sha256"):
            raise ValueError("pairwise cross-encoder checkpoint differs from the residual fit")
        pair_source = pair.result.get("source_parent_result")
        parent_result_path = root / "runs/context_policy_live_demo_20261021/crossencoder_tinybert_diag_v2/result.json"
        if not pair_source or Path(pair_source).name != parent_result_path.name or not parent_result_path.is_file() or _sha(parent_result_path) != bind.get("baseline_result_sha256"):
            raise ValueError("pairwise serving result parent no longer matches the residual fit")

        os.environ.update({
            "OMP_NUM_THREADS": str(threads), "MKL_NUM_THREADS": str(threads),
            "VECLIB_MAXIMUM_THREADS": str(threads), "TOKENIZERS_PARALLELISM": "false",
        })
        import torch
        torch.set_num_threads(threads)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            if torch.get_num_interop_threads() != 1:
                raise
        self._torch = torch
        self.model = _ResidualSet(torch).cpu()
        try:
            state = torch.load(self.state_path, map_location="cpu", weights_only=True)
        except TypeError as exc:
            raise RuntimeError("installed torch lacks safe weights_only loading") from exc
        if not isinstance(state, dict) or set(state) != set(self.model.state_dict()):
            raise ValueError("selected residual state keys disagree with the reviewed architecture")
        expected_state = self.model.state_dict()
        for key, value in state.items():
            if value.shape != expected_state[key].shape or not torch.isfinite(value).all():
                raise ValueError(f"invalid residual parameter: {key}")
        self.model.load_state_dict(state, strict=True)
        self.model.eval()
        self.base_candidate = pair
        from .encoder import FeatureEncoder
        self.encoder = FeatureEncoder(encoder_assets, threads=threads)
        self.threshold = THRESHOLD
        self.bindings = RuntimeBindings(
            version=VERSION,
            plan_sha256=plan_sha,
            fit_receipt_sha256=_sha(self.receipt_path),
            artifact_manifest_sha256=_sha(self.artifact_path),
            selected_state_sha256=_sha(self.state_path),
            baseline_result_sha256=bind["baseline_result_sha256"],
            baseline_head_sha256=bind["baseline_head_sha256"],
            pair_model_sha256=bind["pair_model_sha256"],
            trainer_sha256=bind["trainer_sha256"],
            threshold=self.threshold,
            selected_epoch=3,
        )

    def predict(self, cases: Sequence[Case]) -> tuple[dict[str, list[int]], dict[str, list[float]]]:
        if len({c.example_id for c in cases}) != len(cases):
            raise ValueError("case IDs must be unique")
        if not cases:
            return {}, {}
        empty = [c for c in cases if not c.instructions]
        active = [c for c in cases if c.instructions]
        predictions = {c.example_id: [] for c in empty}
        scores = {c.example_id: [] for c in empty}
        if not active:
            return predictions, scores

        # This is the same frozen 3,074-feature encoder and pair model as the
        # selected epoch-3 baseline. Every source rule remains in original order.
        batch = self.encoder.encode_cases(active, batch_size=16)
        x = np.asarray(batch.X, dtype=np.float64)
        offsets = np.asarray(batch.offsets, dtype=np.int64)
        expected_counts = np.asarray([len(c.instructions) for c in active], dtype=np.int64)
        if x.shape != (int(expected_counts.sum()), 3074) or not np.array_equal(np.diff(offsets), expected_counts):
            raise RuntimeError("frozen profile feature rows are not aligned with original rules")
        pair_logits = self.base_candidate._pair_logits(active)
        if pair_logits.shape != (len(x),) or not np.isfinite(pair_logits).all():
            raise RuntimeError("frozen epoch-3 pair logits are missing or nonfinite")
        p = self.base_candidate
        z_base = (x - p.base_mean) / p.base_scale
        z_pair = ((pair_logits - p.extra_mean[0]) / p.extra_scale[0]).reshape(-1, 1)
        augmented = np.column_stack((z_base, z_pair))
        base_logits = augmented @ p.coef[0] + float(p.intercept[0])
        if augmented.shape != (len(x), FEATURE_DIM) or not np.isfinite(base_logits).all():
            raise RuntimeError("epoch-3 baseline logits are misaligned")

        probs_by_id: dict[str, list[float]] = {}
        with self._torch.inference_mode():
            for start in range(0, len(active), self.batch_size):
                group = active[start:start + self.batch_size]
                nmax = max(len(c.instructions) for c in group)
                xx = np.zeros((len(group), nmax, FEATURE_DIM), dtype=np.float32)
                bb = np.zeros((len(group), nmax), dtype=np.float32)
                pad = np.ones((len(group), nmax), dtype=bool)
                for row, case in enumerate(group):
                    a, b = int(offsets[start + row]), int(offsets[start + row + 1])
                    n = len(case.instructions)
                    xx[row, :n] = augmented[a:b].astype(np.float32)
                    bb[row, :n] = base_logits[a:b].astype(np.float32)
                    pad[row, :n] = False
                residual = self.model(self._torch.from_numpy(xx), self._torch.from_numpy(pad))
                prob = self._torch.sigmoid(self._torch.from_numpy(bb) + residual).cpu().numpy()
                for row, case in enumerate(group):
                    n = len(case.instructions)
                    local = np.asarray(prob[row, :n], dtype=np.float64)
                    if not np.isfinite(local).all():
                        raise RuntimeError(f"nonfinite probabilities for {case.example_id}")
                    probs_by_id[case.example_id] = local.tolist()
                    scores[case.example_id] = local.tolist()
                    predictions[case.example_id] = np.flatnonzero(local >= self.threshold).astype(int).tolist()
        if set(probs_by_id) != {c.example_id for c in active}:
            raise RuntimeError("residual candidate did not return every active case")
        return predictions, scores

