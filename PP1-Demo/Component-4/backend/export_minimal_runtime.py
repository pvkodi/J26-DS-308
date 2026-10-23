#!/usr/bin/env python3
"""Export only the hash-bound files needed by Component 4's offline CPU selector.

This exports a new Stage-B root; it does not modify or delete the research tree.
The source fit receipts are copied as lineage, while large training inputs and
feature caches are omitted from runtime loading.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil


COMPONENT = Path(__file__).resolve().parents[1]
STAGE_SOURCE = COMPONENT / "research/stage_b"
RUNTIME_CODES = (
    "src/instruction_reminder/__init__.py",
    "src/instruction_reminder/data.py",
    "src/instruction_reminder/encoder.py",
    "src/instruction_reminder/model.py",
    "src/instruction_reminder/metrics.py",
    "src/instruction_reminder/renderer.py",
    "src/instruction_reminder/api.py",
    "src/instruction_reminder/tinybert_pair_candidate.py",
    "src/instruction_reminder/residual_set_attention_candidate.py",
    "src/instruction_reminder/joint_correction_plans.py",
    "src/instruction_reminder/runtime_deployment.py",
)
RUNTIME_FILES = (
    *RUNTIME_CODES,
    "assets/encoder",
    "assets/qwen2_5_7b_kaggle_v1_tokenizer",
    "models/applicability_nlsi_full_profile_seed20261021_v1/config.json",
    "models/applicability_nlsi_full_profile_seed20261021_v1/head.npz",
    "runs/residual_set_attention_20261022/experiment_plan_v2.json",
    "runs/residual_set_attention_20261022/fit_v2/fit_receipt.json",
    "runs/residual_set_attention_20261022/fit_v2/artifact_manifest.json",
    "runs/residual_set_attention_20261022/fit_v2/selected_state.pt",
    "runs/context_policy_live_demo_20261021/crossencoder_tinybert_diag_v2/result.json",
    "runs/context_policy_live_demo_20261021/crossencoder_tinybert_diag_v2/serving_selected_epoch3",
    "runs/joint_correction_planner_20261022/stage_b_cooperative_runtime_v2/runtime_manifest.json",
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_allowlist(destination: Path) -> None:
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"destination must be new or empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for relative in RUNTIME_FILES:
        source = STAGE_SOURCE / relative
        target = destination / relative
        if not source.exists():
            raise FileNotFoundError(source)
        if source.is_dir():
            shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def build_manifest(destination: Path) -> dict:
    fit_root = STAGE_SOURCE / "runs/residual_set_attention_20261022"
    plan = fit_root / "experiment_plan_v2.json"
    fit_dir = fit_root / "fit_v2"
    receipt = json.loads((fit_dir / "fit_receipt.json").read_text(encoding="utf-8"))
    artifact = json.loads((fit_dir / "artifact_manifest.json").read_text(encoding="utf-8"))
    source_files = {}
    for path in sorted(destination.rglob("*")):
        if path.is_file() and path.name != "runtime_deployment_manifest.json":
            rel = path.relative_to(destination).as_posix()
            source_files[rel] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    excluded = [
        "runs/nlsi_full_profile_seed20261021_v1/splits/train.jsonl",
        "runs/nlsi_full_profile_seed20261021_v1/splits/validation.jsonl",
        "runs/nlsi_full_profile_seed20261021_v1/splits/split_manifest.json",
        "runs/representation_ablation_20261021/train_validation_features.npz",
        "runs/context_policy_live_demo_20261021/crossencoder_tinybert_diag_v2/epoch_3/scores.npz",
        "runs/context_policy_live_demo_20261021/crossencoder_tinybert_diag_v2/epoch_3/augmented_head.npz",
        "runs/context_policy_live_demo_20261021/crossencoder_tinybert_diag_v2/epoch_3/crossencoder/model.safetensors",
        "all training, evaluation, source-dataset, target-output, and notebook artifacts",
    ]
    return {
        "schema": "component4_offline_runtime_manifest_v1",
        "status": "frozen_deployment_export",
        "runtime": "frozen residual-set-attention Stage-B selector; CPU only; no target generation",
        "files": source_files,
        "source_lineage": {
            "fit_plan_sha256": sha256_file(plan),
            "fit_receipt_sha256": sha256_file(fit_dir / "fit_receipt.json"),
            "artifact_manifest_sha256": sha256_file(fit_dir / "artifact_manifest.json"),
            "selected_state_sha256": sha256_file(fit_dir / "selected_state.pt"),
            "upstream_fit_bindings": receipt["bindings"],
            "upstream_fit_binding_sha256": sha256_bytes(json.dumps(
                receipt["bindings"], sort_keys=True, separators=(",", ":")).encode("utf-8")),
            "source_artifact_files": artifact["files"],
            "excluded_from_runtime": excluded,
            "note": "Original upstream fit hashes remain in the copied fit receipt. The large upstream training inputs and feature caches are preserved in research, not loaded by this deployment export.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True,
                        help="new directory receiving research/stage_b minimal runtime files")
    args = parser.parse_args()
    output_root = args.output_root.expanduser().resolve()
    stage_destination = output_root / "research/stage_b"
    copy_allowlist(stage_destination)
    manifest = build_manifest(stage_destination)
    manifest_path = stage_destination / "runtime_deployment_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    total = sum(item["bytes"] for item in manifest["files"].values()) + manifest_path.stat().st_size
    print(json.dumps({
        "status": "exported",
        "output_root": str(output_root),
        "stage_b_root": str(stage_destination),
        "manifest_path": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "file_count": len(manifest["files"]) + 1,
        "total_bytes": total,
        "largest_files": sorted(
            ({"path": name, **entry} for name, entry in manifest["files"].items()),
            key=lambda row: row["bytes"], reverse=True
        )[:8],
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
