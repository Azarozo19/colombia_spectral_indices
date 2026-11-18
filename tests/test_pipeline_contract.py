import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pipeline.config import normalize_config
from utils.force_utils import docker_command, run_command


class PipelineContractTest(unittest.TestCase):
    def base_config(self, udf_path):
        return {
            "job": {"project_name": "colombia_indices_test"},
            "runtime": {
                "process_folder": "/drive_mount/process",
                "force_ard_dir": "/force/C1/L2/ard",
                "force_grid_epsg": 9377,
                "force_image": "davidfrantz/force:test",
                "docker_cmd": "docker",
                "mounts": ["/drive_mount:/drive_mount", "/force:/force"],
            },
            "inputs": {"aois": ["/data/colombia.geojson"]},
            "processing": {
                "mode": "udf",
                "execute": True,
                "mosaic": True,
                "hold": False,
            },
            "parameters": {
                "FILE_PYTHON": udf_path,
                "INDICES": ["NDVI", "NBR"],
                "STATISTICS": ["MEDIAN", "P25", "P75", "VALID_COUNT"],
                "SCREEN_QAI": "NODATA CLOUD_OPAQUE CLOUD_SHADOW",
            },
        }

    def test_relative_udf_is_resolved_against_source_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            source_root = Path(directory)
            udf = source_root / "utils" / "templates" / "udf.py"
            udf.parent.mkdir(parents=True)
            udf.write_text("# udf\n", encoding="utf-8")

            config = normalize_config(
                self.base_config("utils/templates/udf.py"), source_root
            )

            self.assertEqual(config["processing"]["mode"], "UDF")
            self.assertEqual(config["parameters"]["FILE_PYTHON"], str(udf))

    def test_interactive_hold_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            source_root = Path(directory)
            udf = source_root / "udf.py"
            udf.write_text("# udf\n", encoding="utf-8")
            config = self.base_config(str(udf))
            config["processing"]["hold"] = True

            normalized = normalize_config(config, source_root)

            self.assertTrue(normalized["processing"]["hold"])

    @patch("utils.force_utils.subprocess.run")
    @patch("utils.force_utils.input", create=True)
    @patch("utils.force_utils.sys.stdin.isatty", return_value=True)
    def test_hold_pauses_before_and_after_command(
        self, isatty, input_mock, subprocess_run
    ):
        run_command(["force-higher-level", "/work/tsa.prm"], hold=True)

        self.assertEqual(input_mock.call_count, 2)
        subprocess_run.assert_called_once_with(
            ["force-higher-level", "/work/tsa.prm"], check=True
        )

    def test_docker_command_uses_configured_image_and_mounts(self):
        config = self.base_config("/source/udf.py")

        command = docker_command(config, "force-higher-level", "/work/tsa.prm")

        self.assertEqual(command[:3], ["docker", "run", "--rm"])
        self.assertIn("/drive_mount:/drive_mount", command)
        self.assertIn("/force:/force", command)
        self.assertIn("davidfrantz/force:test", command)
        self.assertEqual(command[-2:], ["force-higher-level", "/work/tsa.prm"])
        self.assertNotIn("sudo", command)
        self.assertIn("FORCE_SPECTRAL_INDICES=NDVI,NBR", command)
        self.assertIn(
            "FORCE_SPECTRAL_STATISTICS=MEDIAN,P25,P75,VALID_COUNT", command
        )

    def test_validation_requires_valid_count(self):
        with tempfile.TemporaryDirectory() as directory:
            source_root = Path(directory)
            udf = source_root / "udf.py"
            udf.write_text("# udf\n", encoding="utf-8")
            config = self.base_config(str(udf))
            config["parameters"]["STATISTICS"] = ["MEDIAN"]

            with self.assertRaisesRegex(ValueError, "include VALID_COUNT"):
                normalize_config(config, source_root)


if __name__ == "__main__":
    unittest.main()
