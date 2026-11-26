"""Stage 3: append one run's per-point rows to archive/YYYY-MM.csv.gz (docs/archive_points.md in fogNowcast).

Append-only: new rows are added as a new gzip member, existing rows are never changed. A row is identified by
(run, valid, point, model); rows already present are skipped, so re-running the same run adds nothing.
Nothing is ever deleted (decision 2026-11-25). Squashing the branch is a separate guarded step: tools/squash_archive.py.
Prints `added=<n>` and `new_month=true|false`.
"""
import argparse
import csv
import gzip
import io
from pathlib import Path

COLUMNS = ["run", "valid", "lead_h", "point", "model", "t", "td", "wind_kt", "wind_dir",
           "cloud_low_pct", "model_elev_m"]


def read_rows(path):
    with gzip.open(path, "rt", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def key(r):
    return (r["run"], r["valid"], r["point"], r["model"])


def append_rows(new_rows, archive_dir):
    """Returns (added, new_month_file_created). new_rows must all belong to one run month."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    months = {r["run"][:7] for r in new_rows}
    if len(months) != 1:
        raise ValueError(f"rows span several run months: {months}")
    month = months.pop()
    path = archive_dir / f"{month}.csv.gz"
    existing = set()
    created = not path.exists()
    if not created:
        existing = {key(r) for r in read_rows(path)}
    fresh = [r for r in new_rows if key(r) not in existing]
    if fresh:
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\n")
        if created:
            w.writerow(COLUMNS)
        for r in fresh:
            w.writerow([r[c] for c in COLUMNS])
        with open(path, "ab") as raw:
            raw.write(gzip.compress(buf.getvalue().encode("utf-8"), mtime=0))
    return len(fresh), created and bool(fresh), month


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", required=True, help="CSV from tools/points_run.py")
    ap.add_argument("--dir", required=True, help="archive directory")
    a = ap.parse_args()
    with open(a.rows, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit("no rows")
    d = Path(a.dir)
    added, new_month, month = append_rows(rows, d)
    # sanity: the file must read back and contain every new key
    back = {key(r) for r in read_rows(d / f"{month}.csv.gz")}
    missing = [key(r) for r in rows if key(r) not in back]
    if missing:
        raise SystemExit(f"archive verification failed, {len(missing)} rows missing")
    print(f"added={added}")
    print(f"new_month={'true' if new_month else 'false'}")


if __name__ == "__main__":
    main()
