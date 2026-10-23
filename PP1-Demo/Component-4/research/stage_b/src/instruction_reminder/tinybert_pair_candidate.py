"""Isolated CPU serving adapter for the one-epoch TinyBERT pairwise candidate.

This adapter is explicitly development-only. It loads the candidate's frozen
cross-encoder and augmented logistic head without replacing or mutating the
production CPUSelector. The complete ordered instruction profile is always
passed to the existing 3,074-feature encoder; the trained pair logit is
appended as the 3,075th feature. No labels, source IDs, API outputs, or metadata
enter prediction.
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
from .encoder import FeatureEncoder, UnsupportedInput
from .model import CPUSelector


CANDIDATE_VERSION = "tinybert_pairwise_nlsi_dev_v1"
BASE_FEATURE_DIM = 3074
AUGMENTED_FEATURE_DIM = 3075
MAX_PAIR_TOKENS = 512


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _tree_hashes(root: Path) -> dict[str, str]:
    if not root.is_dir():
        raise FileNotFoundError(f"candidate cross-encoder directory does not exist: {root}")
    return {
        str(p.relative_to(root)): _sha256(p)
        for p in sorted(root.rglob("*"))
        if p.is_file() and ".cache" not in p.parts
    }


def _stable_sigmoid(logits: np.ndarray) -> np.ndarray:
    result = np.empty_like(logits, dtype=np.float64)
    positive = logits >= 0
    result[positive] = 1.0 / (1.0 + np.exp(-logits[positive]))
    exp_values = np.exp(logits[~positive])
    result[~positive] = exp_values / (1.0 + exp_values)
    return result


@dataclass(frozen=True)
class CandidateBindings:
    candidate_version: str
    result_sha256: str
    head_sha256: str
    crossencoder_files_sha256: dict[str, str]
    frozen_config_sha256: str
    frozen_head_sha256: str
    encoder_asset_hashes: dict[str, str]
    threshold: float
    feature_dimensions: int


class TinyBertPairCandidate:
    """Development-only selector using frozen full-profile features + pair logit.

    `run_dir` is the completed diagnostic directory containing `result.json`,
    `candidate_augmented_head.npz`, and `crossencoder/`. Its independent
    candidate artifacts are validated on load. The production model directory
    and its files are read-only inputs.
    """

    def __init__(
        self,
        run_dir: str | Path,
        frozen_model_dir: str | Path,
        encoder_assets: str | Path,
        threads: int = 4,
        batch_size: int = 32,
    ) -> None:
        if threads < 1 or batch_size < 1:
            raise ValueError("threads and batch_size must be positive")
        self.run_dir = Path(run_dir).resolve()
        self.frozen_model_dir = Path(frozen_model_dir).resolve()
        self.encoder_assets = Path(encoder_assets).resolve()
        self.threads = threads
        self.batch_size = batch_size

        result_path = self.run_dir / "result.json"
        head_path = self.run_dir / "candidate_augmented_head.npz"
        crossencoder_dir = self.run_dir / "crossencoder"
        for path in (result_path, head_path):
            if not path.is_file():
                raise FileNotFoundError(f"candidate artifact missing: {path}")
        self.result = json.loads(result_path.read_text(encoding="utf-8"))
        if self.result.get("status") != "complete":
            raise ValueError("candidate result must have status=complete")
        if self.result.get("production_unchanged") is not True:
            raise ValueError("candidate receipt does not certify the production selector stayed unchanged")
        if self.result.get("target_calls") != 0 or self.result.get("test_inputs_or_labels_read") is not False:
            raise ValueError("candidate receipt violates its development-only no-target/no-test scope")
        expected_feature = self.result.get("feature", "")
        if "3074" not in expected_feature or "appended" not in expected_feature:
            raise ValueError("candidate receipt does not describe the expected appended pairwise feature")

        source_model = self.result.get("source_model", {})
        if source_model.get("repo") != "cross-encoder/ms-marco-TinyBERT-L2-v2":
            raise ValueError("candidate receipt is not bound to the planned TinyBERT cross-encoder")
        if source_model.get("revision") != "81d1926f67cb8eee2c2be17ca9f793c7c3bd20cc":
            raise ValueError("candidate receipt has an unexpected source model revision")

        self.base_selector = CPUSelector.load(self.frozen_model_dir, self.encoder_assets, threads=threads)
        if self.base_selector.mean.shape != (BASE_FEATURE_DIM,):
            raise ValueError(f"frozen selector must expose {BASE_FEATURE_DIM} base features")
        result_bindings = self.result.get("bindings", {})
        for binding_name, local_path in (
            ("frozen_config", self.frozen_model_dir / "config.json"),
            ("frozen_head", self.frozen_model_dir / "head.npz"),
        ):
            if result_bindings.get(binding_name) != _sha256(local_path):
                raise ValueError(f"candidate receipt is bound to a different {binding_name}")
        self.base_encoder: FeatureEncoder | None = None

        artifacts = self.result.get("candidate_artifacts", {})
        recorded_head = artifacts.get("head_sha256")
        actual_head = _sha256(head_path)
        if recorded_head != actual_head:
            raise ValueError("candidate augmented-head checksum mismatch")
        # Artifact paths in receipts are provenance from the machine that ran
        # training. Resolve the files from this bundle and bind them by their
        # content hashes; absolute recorded paths must not make a copied bundle
        # un-loadable on another host.
        recorded_head_path = artifacts.get("head")
        if recorded_head_path and Path(recorded_head_path).name != head_path.name:
            raise ValueError("candidate receipt names a different augmented-head file")
        recorded_encoder_path = artifacts.get("crossencoder_dir")
        if recorded_encoder_path and Path(recorded_encoder_path).name != crossencoder_dir.name:
            raise ValueError("candidate receipt names a different cross-encoder directory")
        crossencoder_hashes = _tree_hashes(crossencoder_dir)
        expected_crossencoder_hashes = artifacts.get("crossencoder_files_sha256")
        if not isinstance(expected_crossencoder_hashes, dict) or expected_crossencoder_hashes != crossencoder_hashes:
            raise ValueError("candidate receipt is missing or disagrees with the trained cross-encoder file hashes")
        trained_weight_hash = crossencoder_hashes.get("model.safetensors")
        source_weight_hash = source_model.get("weight_sha256")
        if not trained_weight_hash or not source_weight_hash or trained_weight_hash == source_weight_hash:
            raise ValueError("candidate checkpoint is not bound to changed fine-tuned weights")

        # The v2 serving bundle has a parent training receipt. Its absolute
        # source path is historical provenance only; bind the nearby parent
        # receipt by SHA-256 so the bundle remains portable as a directory.
        parent_result_source = self.result.get("source_parent_result")
        parent_result_sha = self.result.get("source_parent_result_sha256")
        if parent_result_source or parent_result_sha:
            if not parent_result_source or Path(parent_result_source).name != "result.json":
                raise ValueError("candidate parent receipt provenance must name result.json")
            parent_result_path = self.run_dir.parent / "result.json"
            if not parent_result_path.is_file() or _sha256(parent_result_path) != parent_result_sha:
                raise ValueError("candidate bundle is not bound to the adjacent parent training receipt")

        arrays = np.load(head_path, allow_pickle=False)
        required = {
            "coef", "intercept", "base_scaler_mean", "base_scaler_scale",
            "extra_mean", "extra_scale",
        }
        if set(arrays.files) != required:
            raise ValueError(f"candidate head fields must be exactly {sorted(required)}")
        self.coef = np.asarray(arrays["coef"], dtype=np.float64)
        self.intercept = np.asarray(arrays["intercept"], dtype=np.float64).reshape(-1)
        self.base_mean = np.asarray(arrays["base_scaler_mean"], dtype=np.float64).reshape(-1)
        self.base_scale = np.asarray(arrays["base_scaler_scale"], dtype=np.float64).reshape(-1)
        self.extra_mean = np.asarray(arrays["extra_mean"], dtype=np.float64).reshape(-1)
        self.extra_scale = np.asarray(arrays["extra_scale"], dtype=np.float64).reshape(-1)
        if self.coef.shape != (1, AUGMENTED_FEATURE_DIM) or self.intercept.shape != (1,):
            raise ValueError("augmented candidate head must be a binary 3,075-feature logistic head")
        if self.base_mean.shape != (BASE_FEATURE_DIM,) or self.base_scale.shape != (BASE_FEATURE_DIM,):
            raise ValueError("candidate head base scaler has the wrong feature dimension")
        if self.extra_mean.shape != (1,) or self.extra_scale.shape != (1,):
            raise ValueError("candidate pair-score scaler must have one train-fitted dimension")
        if not np.array_equal(self.base_mean, self.base_selector.mean) or not np.array_equal(self.base_scale, self.base_selector.scale):
            raise ValueError("candidate does not preserve the frozen selector's exact base scaler")
        for name, arr in (("coef", self.coef), ("intercept", self.intercept),
                          ("base scaler mean", self.base_mean), ("base scaler scale", self.base_scale),
                          ("pair-score mean", self.extra_mean), ("pair-score scale", self.extra_scale)):
            if not np.isfinite(arr).all():
                raise ValueError(f"candidate {name} contains a nonfinite value")
        if np.any(self.base_scale <= 0) or np.any(self.extra_scale <= 0):
            raise ValueError("candidate scaler contains a nonpositive scale")

        self.threshold = float(self.result.get("head_refit", {}).get("threshold", -1))
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError("candidate receipt has an invalid frozen threshold")

        # Mirror the training process's text-only Mac runtime guard before BERT
        # class resolution; optional multimedia native extensions are unused.
        os.environ.update({
            "USE_TF": "0",
            "USE_FLAX": "0",
            "TOKENIZERS_PARALLELISM": "false",
            "RAYON_NUM_THREADS": "1",
            "OMP_NUM_THREADS": str(threads),
            "MKL_NUM_THREADS": str(threads),
            "VECLIB_MAXIMUM_THREADS": str(threads),
        })
        # Import the local Transformers runtime only after all artifact bindings validate.
        import transformers.utils.import_utils as import_utils
        import_utils._librosa_available = False
        import_utils._torchvision_available = False
        import_utils._torchaudio_available = False
        import_utils._cv2_available = False
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        torch.set_num_threads(threads)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            if torch.get_num_interop_threads() != 1:
                raise
        self._torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(crossencoder_dir), local_files_only=True, use_fast=True
        )
        self.cross_encoder = AutoModelForSequenceClassification.from_pretrained(
            str(crossencoder_dir), local_files_only=True, use_safetensors=True
        )
        self.cross_encoder.to("cpu")
        self.cross_encoder.eval()
        model_config = self.cross_encoder.config
        if int(getattr(model_config, "num_labels", -1)) != 1:
            raise ValueError("pair cross-encoder must emit one relevance logit")
        if getattr(model_config, "max_position_embeddings", MAX_PAIR_TOKENS) < MAX_PAIR_TOKENS:
            raise ValueError("candidate model position limit is below the declared 512-token pair cap")

        self.bindings = CandidateBindings(
            candidate_version=CANDIDATE_VERSION,
            result_sha256=_sha256(result_path),
            head_sha256=actual_head,
            crossencoder_files_sha256=crossencoder_hashes,
            frozen_config_sha256=_sha256(self.frozen_model_dir / "config.json"),
            frozen_head_sha256=_sha256(self.frozen_model_dir / "head.npz"),
            encoder_asset_hashes=self.base_selector.config["assets_sha256"],
            threshold=self.threshold,
            feature_dimensions=AUGMENTED_FEATURE_DIM,
        )

    def _pair_logits(self, cases: Sequence[Case]) -> np.ndarray:
        torch = self._torch
        contexts: list[str] = []
        rules: list[str] = []
        for case in cases:
            if not isinstance(case.context, str) or not case.context.strip():
                raise UnsupportedInput(f"case {case.example_id!r} has empty context")
            if not case.instructions:
                raise UnsupportedInput(f"case {case.example_id!r} has no candidate instructions")
            for instruction in case.instructions:
                if not isinstance(instruction.text, str) or not instruction.text.strip():
                    raise UnsupportedInput(f"case {case.example_id!r} has an empty instruction")
                contexts.append(case.context)
                rules.append(instruction.text)

        # Explicitly inspect full pair lengths with no truncation. If any pair is
        # beyond the trained 512-token limit, reject the whole case batch; never
        # silently shorten a context or a standing instruction at serving time.
        lengths: list[int] = []
        for start in range(0, len(rules), self.batch_size):
            encoded = self.tokenizer(
                contexts[start:start + self.batch_size],
                rules[start:start + self.batch_size],
                add_special_tokens=True,
                truncation=False,
                padding=False,
            )
            lengths.extend(len(ids) for ids in encoded["input_ids"])
        if len(lengths) != len(rules):
            raise RuntimeError("cross-encoder pair length check lost candidate rows")
        over = [(i, n) for i, n in enumerate(lengths) if n > MAX_PAIR_TOKENS]
        if over:
            case_index = 0
            for idx, case in enumerate(cases):
                next_index = case_index + len(case.instructions)
                offending = [(j - case_index, n) for j, n in over if case_index <= j < next_index]
                if offending:
                    raise UnsupportedInput(
                        f"case {case.example_id!r} has pair lengths above {MAX_PAIR_TOKENS} tokens "
                        f"(instruction_index,length={offending}); no truncation performed"
                    )
                case_index = next_index
            raise UnsupportedInput(f"{len(over)} candidate pairs exceed {MAX_PAIR_TOKENS} tokens; no truncation performed")

        outputs: list[np.ndarray] = []
        with torch.inference_mode():
            for start in range(0, len(rules), self.batch_size):
                end = start + self.batch_size
                batch = self.tokenizer(
                    contexts[start:end], rules[start:end],
                    return_tensors="pt", padding=True, truncation=False,
                )
                if int(batch["input_ids"].shape[1]) > MAX_PAIR_TOKENS:
                    raise RuntimeError("tokenizer length changed after no-truncation preflight")
                batch = {k: v.to("cpu") for k, v in batch.items()}
                logits = self.cross_encoder(**batch).logits.reshape(-1).cpu().numpy().astype(np.float64)
                if logits.shape != (min(self.batch_size, len(rules) - start),) or not np.isfinite(logits).all():
                    raise RuntimeError("cross-encoder returned misaligned or nonfinite pair logits")
                outputs.append(logits)
        return np.concatenate(outputs) if outputs else np.zeros(0, dtype=np.float64)

    def predict(
        self,
        cases: Sequence[Case],
        batch_size: int = 16,
        encoder: FeatureEncoder | None = None,
    ) -> tuple[dict[str, list[int]], dict[str, list[float]]]:
        """Return candidate index sets and probabilities in original input order."""
        if len({case.example_id for case in cases}) != len(cases):
            raise ValueError("cases must have unique example IDs")
        if not cases:
            return {}, {}
        empty = [case for case in cases if not case.instructions]
        nonempty = [case for case in cases if case.instructions]
        predictions: dict[str, list[int]] = {case.example_id: [] for case in empty}
        scores: dict[str, list[float]] = {case.example_id: [] for case in empty}
        if not nonempty:
            return predictions, scores

        active_encoder = encoder or self.base_encoder
        if active_encoder is None:
            active_encoder = FeatureEncoder(self.encoder_assets, threads=self.threads)
            self.base_encoder = active_encoder
        feature_batch = active_encoder.encode_cases(nonempty, batch_size=batch_size)
        x = np.asarray(feature_batch.X, dtype=np.float64)
        offsets = np.asarray(feature_batch.offsets, dtype=np.int64)
        expected = np.asarray([len(case.instructions) for case in nonempty], dtype=np.int64)
        if x.shape != (int(expected.sum()), BASE_FEATURE_DIM):
            raise RuntimeError("frozen full-profile feature rows are not aligned to candidates")
        if offsets.shape != (len(nonempty) + 1,) or offsets[0] != 0 or offsets[-1] != len(x):
            raise RuntimeError("frozen feature offsets are malformed")
        if not np.array_equal(np.diff(offsets), expected) or not np.isfinite(x).all():
            raise RuntimeError("frozen features are misaligned or nonfinite")

        pair_logits = self._pair_logits(nonempty)
        if pair_logits.shape != (len(x),):
            raise RuntimeError("pairwise scores do not align one-to-one with source candidates")
        z_base = (x - self.base_mean) / self.base_scale
        z_pair = ((pair_logits - self.extra_mean[0]) / self.extra_scale[0]).reshape(-1, 1)
        augmented = np.column_stack((z_base, z_pair))
        if augmented.shape != (len(x), AUGMENTED_FEATURE_DIM) or not np.isfinite(augmented).all():
            raise RuntimeError("augmented features are invalid")
        logits = augmented @ self.coef[0] + self.intercept[0]
        probs = _stable_sigmoid(logits)
        if not np.isfinite(probs).all():
            raise RuntimeError("candidate probability conversion returned nonfinite values")

        for row_index, case in enumerate(nonempty):
            start, end = int(offsets[row_index]), int(offsets[row_index + 1])
            local = probs[start:end]
            scores[case.example_id] = local.astype(float).tolist()
            predictions[case.example_id] = np.flatnonzero(local >= self.threshold).astype(int).tolist()
        return predictions, scores

    def optimize(self, context, instructions, original, max_added_tokens=None, token_counter=None):
        """Use the existing exact-copy renderer without touching production code."""
        from .api import ReminderOptimizer
        return ReminderOptimizer(self).optimize(
            context=context,
            instructions=instructions,
            original=original,
            max_added_tokens=max_added_tokens,
            token_counter=token_counter,
        )
