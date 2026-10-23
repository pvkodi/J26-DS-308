"""Hash-verified manifest for the small offline Component 4 runtime export.

The research runtime keeps its strict training-input provenance checks. The
deployment export carries the frozen fit receipts and their upstream bindings,
then verifies only the files needed to run inference. This avoids shipping
large training caches while retaining the exact frozen model and code hashes.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class ValidatedDeployment:
    root: Path
    manifest_path: Path
    manifest_sha256: str
    files: dict[str, dict]
    source_lineage: dict

    def require(self, relative: str, path: Path | None = None) -> Path:
        relative_path = Path(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("deployment file path must remain under the runtime root")
        entry = self.files.get(relative_path.as_posix())
        if not isinstance(entry, dict):
            raise ValueError(f"deployment manifest does not bind required file: {relative}")
        target = (path or (self.root / relative_path)).resolve()
        if self.root not in target.parents:
            raise ValueError("deployment file resolved outside the runtime root")
        if not target.is_file():
            raise FileNotFoundError(target)
        if target.stat().st_size != entry.get("bytes") or sha256_file(target) != entry.get("sha256"):
            raise ValueError(f"deployment file hash mismatch: {relative}")
        return target


def load_deployment(value: str | Path | ValidatedDeployment | None) -> ValidatedDeployment | None:
    if value is None:
        return None
    if isinstance(value, ValidatedDeployment):
        return value
    path = Path(value).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = path.read_bytes()
    obj = json.loads(raw)
    if obj.get("schema") != "component4_offline_runtime_manifest_v1":
        raise ValueError("unrecognized Component 4 offline runtime manifest")
    if obj.get("status") != "frozen_deployment_export":
        raise ValueError("offline runtime manifest is not marked frozen")
    files = obj.get("files")
    lineage = obj.get("source_lineage")
    if not isinstance(files, dict) or not files or not isinstance(lineage, dict):
        raise ValueError("offline runtime manifest is missing file or source-lineage bindings")
    root = path.parent.resolve()
    manifest = ValidatedDeployment(root, path, hashlib.sha256(raw).hexdigest(), files, lineage)
    for relative in sorted(files):
        manifest.require(relative)
    return manifest
