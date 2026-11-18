#!/usr/bin/env python3
"""Validate spectral summaries and enforce configurable coverage targets."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from utils.quality_validation import (
    discover_spectral_outputs,
    validate_spectral_outputs,
    write_validation_report,
)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--indices", nargs="+", required=True)
    parser.add_argument(
        "--statistics",
        nargs="+",
        default=["MEDIAN", "P25", "P75", "VALID_COUNT"],
    )
    parser.add_argument("--minimum-valid-coverage", type=float, default=95.0)
    parser.add_argument("--minimum-reliable-coverage", type=float, default=80.0)
    parser.add_argument("--minimum-reliable-observations", type=int, default=3)
    parser.add_argument("--output", required=True)
    parser.add_argument("--fail", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    paths = discover_spectral_outputs(args.input)
    report = validate_spectral_outputs(
        paths,
        expected_indices=args.indices,
        expected_statistics=args.statistics,
        minimum_valid_coverage_pct=args.minimum_valid_coverage,
        minimum_reliable_coverage_pct=args.minimum_reliable_coverage,
        minimum_reliable_observations=args.minimum_reliable_observations,
    )
    output = write_validation_report(report, args.output)
    print(json.dumps({
        "accepted": report["accepted"],
        "indices": report["indices"],
        "threshold_failures": report["threshold_failures"],
        "errors": report["errors"],
        "output": str(output),
    }, indent=2, sort_keys=True))
    return 2 if args.fail and not report["accepted"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
