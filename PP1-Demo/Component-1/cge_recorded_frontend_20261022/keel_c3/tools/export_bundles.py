"""Export every stored run the Keel debug viewer can open to static JSON (what GET /api/bundle returns).

Run from the root of the keel-mvp repository, with its virtualenv:
    python <path>/export_bundles.py <out_dir>

Writes <out_dir>/conversations.json (GET /api/conversations, eval split marked blocked) and
<out_dir>/bundles/<conv>/<run>.json (chat) or <out_dir>/bundles/<conv>/swe.json (SWE trajectories).
Conversations of the frozen eval split are listed but NOT exported (the viewer refuses them by default).
Reads only; nothing in the repository is changed.
"""

import json
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))


def _one(job):
    conv, run, out = job
    from mvp.viz.bundle import build_bundle
    b = build_bundle(conv, run) if run else build_bundle(conv)
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(b, default=str), encoding="utf-8")
    return conv, run, p.stat().st_size


def main(out_dir: str) -> None:
    from mvp.viz.bundle import list_conversations
    out = Path(out_dir).resolve()
    convs = list_conversations()
    for c in convs:
        c["blocked"] = c["split"] == "eval"
    (out / "bundles").mkdir(parents=True, exist_ok=True)
    (out / "conversations.json").write_text(json.dumps(convs, indent=1), encoding="utf-8")
    jobs = []
    for c in convs:
        if c["blocked"]:
            continue
        if c["kind"] == "chat":
            jobs += [(c["id"], r, str(out / "bundles" / c["id"] / f"{r}.json")) for r in c["runs"]]
        else:
            jobs.append((c["id"], None, str(out / "bundles" / c["id"] / "swe.json")))
    total, failed = 0, []
    with ProcessPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_one, j): j for j in jobs}
        for i, f in enumerate(futs, 1):
            try:
                _, _, n = f.result()
                total += n
            except Exception as e:  # keep going; report at the end
                failed.append({"conv": futs[f][0], "run": futs[f][1], "error": f"{type(e).__name__}: {e}"})
            if i % 50 == 0:
                print(f"{i}/{len(jobs)}", flush=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    manifest = {"exported_at": datetime.now(timezone.utc).isoformat(), "source_commit": commit,
                "conversations": len(convs), "bundles": len(jobs) - len(failed), "bytes": total, "failed": failed}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in manifest.items() if k != "failed"}), "failed:", len(failed))


if __name__ == "__main__":
    main(sys.argv[1])
