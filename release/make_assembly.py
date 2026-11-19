#!/usr/bin/env python3
"""Create a manifest-verified source assembly for release/run_demo.py.

    python release/make_assembly.py --out /var/tmp/horus-assembly [--ref HEAD]
    python release/run_demo.py --root /var/tmp/horus-assembly/assembly --out ... --live ...

Exports the committed tree (`git archive`, so no uncommitted or ignored file can slip in) to OUT/assembly and
writes OUT/assembly-manifest.json (format horus.git-assembly/1) with the SHA-256 of every file. At the end of a
run, run_demo.py re-hashes every listed file and fails the run on any mismatch.
"""
import argparse
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parent.parent)
    a = ap.parse_args()
    dst = a.out / "assembly"
    if dst.exists():
        raise SystemExit(f"{dst} exists; choose a new --out")
    commit = subprocess.check_output(["git", "-C", str(a.repo), "rev-parse", a.ref], text=True).strip()
    raw = subprocess.check_output(["git", "-C", str(a.repo), "archive", "--format=tar", commit])
    dst.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        tf.extractall(dst, filter="data")
    files = {p.relative_to(dst).as_posix(): {"sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(dst.rglob("*")) if p.is_file()}
    man = {"format": "horus.git-assembly/1", "source": f"git archive {commit[:7]} ({a.ref})", "files": files}
    (a.out / "assembly-manifest.json").write_text(json.dumps(man, indent=1) + "\n", encoding="utf-8")
    print(f"{dst}: {len(files)} files, manifest {a.out / 'assembly-manifest.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
