"""Save the latest run's summary.json as a baseline for future regression comparisons."""

from __future__ import annotations

import shutil
import sys
from datetime import datetime
from pathlib import Path


def save_baseline(
    reports_dir: Path,
    baselines_dir: Path,
    *,
    tag: str | None = None,
) -> Path:
    """Copy reports/<latest>/summary.json → baselines/<tag-or-timestamp>.json.

    Scans *reports_dir* for the most-recently modified sub-directory that
    contains a ``summary.json``.  If *reports_dir* itself has a
    ``summary.json`` it is used directly.

    Default tag: today's date in YYYY-MM-DD.

    Returns the path to the saved baseline file.
    """
    # Locate the summary.json to promote
    summary_path: Path | None = None
    direct = reports_dir / "summary.json"
    if direct.is_file():
        summary_path = direct
    else:
        candidates = sorted(
            (
                d / "summary.json"
                for d in reports_dir.iterdir()
                if d.is_dir() and (d / "summary.json").is_file()
            ),
            key=lambda p: p.stat().st_mtime,
        )
        if candidates:
            summary_path = candidates[-1]

    if summary_path is None:
        raise FileNotFoundError(
            f"No summary.json found under {reports_dir}. "
            "Run the report generator first."
        )

    # Determine destination tag
    if tag is None:
        tag = datetime.now().strftime("%Y-%m-%d")

    baselines_dir.mkdir(parents=True, exist_ok=True)
    dest = baselines_dir / f"{tag}.json"
    shutil.copy2(summary_path, dest)
    return dest


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "save"
    if cmd == "save":
        out = save_baseline(
            Path("reports"),
            Path("baselines"),
            tag=sys.argv[2] if len(sys.argv) > 2 else None,
        )
        print(f"Baseline saved: {out}")
    elif cmd == "list":
        for p in sorted(Path("baselines").glob("*.json")):
            print(p.name)
