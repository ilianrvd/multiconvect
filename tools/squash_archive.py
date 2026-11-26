"""Guarded monthly squash of branch archive-points (docs/archive_points.md in fogNowcast, "Свиване на клона").

Squashing is the only step that can lose data, so it verifies before and after and stops on any mismatch:
 1. manifest (rows via the same count as `zcat | wc -l`, and SHA-256) of every archive/*.csv.gz, before;
 2. backup tag archive-points-before-squash-<month> on the current tip;
 3. squashed commit (same tree + marker archive/.squashed_through, no parent) pushed to a TEMPORARY branch;
 4. fresh clone of the temporary branch: manifest must be identical, file by file;
 5. only then archive-points is force-updated (with lease on the old tip) and the temporary branch is deleted;
 6. fresh clone of archive-points: manifest checked again; on mismatch archive-points is restored from the tag and we fail;
 7. older backup tags are removed (the newest stays until the next month's squash succeeds).
Runs when the run month is newer than the month in the marker (a failed squash is retried by the next run).
Exit code 0 = squashed or nothing to do, 1 = stopped, branch left as it was.
"""
import argparse
import gzip
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

BRANCH = "archive-points"
TMP_BRANCH = "archive-points-squash-tmp"
TAG_PREFIX = "archive-points-before-squash-"
MARKER = "archive/.squashed_through"


def git(cwd, *args, check=True):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def count_lines(path):
    """Same number as `zcat file | wc -l` (header included)."""
    n = 0
    with gzip.open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            n += chunk.count(b"\n")
    return n


def manifest(root):
    out = {}
    for p in sorted((Path(root) / "archive").glob("*.csv.gz")):
        out[p.name] = (count_lines(p), hashlib.sha256(p.read_bytes()).hexdigest())
    return out


def compare(before, after):
    """Returns a list of human-readable differences (empty = identical)."""
    diffs = []
    for name in sorted(set(before) | set(after)):
        if name not in after:
            diffs.append(f"{name}: missing after")
        elif name not in before:
            diffs.append(f"{name}: unexpected after")
        elif before[name] != after[name]:
            diffs.append(f"{name}: before {before[name][0]} rows, after {after[name][0]} rows (or content differs)")
    return diffs


def read_marker(root):
    p = Path(root) / MARKER
    return p.read_text().strip() if p.exists() else ""


def fresh_clone(remote, branch, dest):
    shutil.rmtree(dest, ignore_errors=True)
    subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--branch", branch, remote, str(dest)], check=True)


def squash(arch, remote, month):
    arch = Path(arch)
    marker = read_marker(arch)
    if marker >= month:
        print(f"squash=skip (marker {marker} >= run month {month})")
        return 0
    before = manifest(arch)
    if not before:
        print("squash=skip (no archive files)")
        return 0
    old_tip = git(arch, "rev-parse", "HEAD")
    tag = f"{TAG_PREFIX}{month}"
    git(arch, "tag", "-f", tag, old_tip)
    git(arch, "push", "--force", "origin", f"refs/tags/{tag}")

    git(arch, "checkout", "--quiet", "--orphan", "squashed-work")
    (arch / MARKER).write_text(month + "\n")
    git(arch, "add", "-A")
    git(arch, "commit", "--quiet", "-m", f"Archive up to month {month} (history squashed, tag {tag} keeps the old tip)")
    new_tip = git(arch, "rev-parse", "HEAD")
    git(arch, "push", "--force", "origin", f"{new_tip}:refs/heads/{TMP_BRANCH}")

    work = Path(tempfile.mkdtemp())
    try:
        fresh_clone(remote, TMP_BRANCH, work / "chk1")
        d = compare(before, manifest(work / "chk1"))
        if d:
            print("STOP: temporary branch differs from archive-points:\n  " + "\n  ".join(d))
            print(f"archive-points is unchanged; temporary branch {TMP_BRANCH} kept for inspection")
            return 1

        git(arch, "push", f"--force-with-lease=refs/heads/{BRANCH}:{old_tip}", "origin", f"{new_tip}:refs/heads/{BRANCH}")
        git(arch, "push", "origin", "--delete", TMP_BRANCH, check=False)

        fresh_clone(remote, BRANCH, work / "chk2")
        d = compare(before, manifest(work / "chk2"))
        if d:
            print("STOP: archive-points differs after squash, restoring from tag:\n  " + "\n  ".join(d))
            git(arch, "push", "--force", "origin", f"{old_tip}:refs/heads/{BRANCH}")
            return 1
    finally:
        shutil.rmtree(work, ignore_errors=True)

    # success: keep only the newest backup tag
    tags = [t for t in git(arch, "ls-remote", "--tags", "origin", f"{TAG_PREFIX}*").splitlines()]
    names = sorted(t.split("refs/tags/")[1] for t in tags if "refs/tags/" in t and not t.endswith("^{}"))
    for old in names[:-1]:
        git(arch, "push", "origin", "--delete", f"refs/tags/{old}", check=False)
    total = sum(v[0] for v in before.values())
    print(f"squash=done files={len(before)} rows={total} tag={tag}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="clone of archive-points (committed and pushed)")
    ap.add_argument("--remote", required=True)
    ap.add_argument("--month", required=True, help="run month YYYY-MM")
    a = ap.parse_args()
    sys.exit(squash(a.dir, a.remote, a.month))


if __name__ == "__main__":
    main()
