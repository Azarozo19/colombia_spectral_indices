import argparse
from pathlib import Path

from utils.utils import create_folder_structure, mosaicing
from utils.force_utils import force_process
from utils.quality_validation import (
    discover_spectral_outputs,
    validate_configured_outputs,
)


def run_workflow(config):
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    from pipeline.config import load_pipeline_config

    source_root = Path(__file__).resolve().parent
    config = load_pipeline_config(Path(args.config).expanduser().resolve(), source_root)
    run_workflow(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
