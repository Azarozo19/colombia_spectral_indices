#!/usr/bin/env python3
"""Generate strict/balanced/exploratory FORCE QAI coverage diagnostics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from utils.qai_coverage import analyze_qai_files, discover_qai_files, write_report


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ard-dir", required=True)
    parser.add_argument("--tile", action="append", default=[])
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    ard_dir = Path(args.ard_dir).expanduser().resolve()
    files = discover_qai_files(
        ard_dir,
        tiles=args.tile,
        date_from=args.date_from,
        date_to=args.date_to,
    )
    report = analyze_qai_files(files, ard_dir=ard_dir)
    output = write_report(report, args.output)
    print(json.dumps({
        "qai_file_count": report["qai_file_count"],
        "tile_count": report["tile_count"],
        "profiles": report["profiles"],
        "output": str(output),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
