#!/usr/bin/env python3
"""Run the Colombia spectral-index workflow."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[1]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from pipeline.config import load_pipeline_config
from utils.force_utils import force_process
from utils.quality_validation import (
    discover_spectral_outputs,
    validate_configured_outputs,
)
from utils.utils import create_folder_structure, mosaicing


def run_workflow(config: dict) -> None:
    create_folder_structure(config["runtime"]["process_folder"])
    force_process(config)

    output_files = []
    if config["processing"]["mosaic"]:
        output_files = mosaicing(config)

    should_validate = (
        config["processing"]["mode"] == "UDF"
        and config["processing"]["execute"]
        and config["quality_validation"]["enabled"]
    )
    if should_validate:
        if not output_files:
            project_tiles = (
                Path(config["runtime"]["process_folder"])
                / "temp"
                / config["job"]["project_name"]
                / "FORCE"
            )
            output_files = discover_spectral_outputs(project_tiles)
        validate_configured_outputs(config, output_files)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Workflow YAML configuration")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    config = load_pipeline_config(config_path, SOURCE_ROOT)
    run_workflow(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
