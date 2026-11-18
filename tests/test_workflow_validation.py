import unittest
from unittest.mock import patch

from force_workflow import run_workflow


class WorkflowValidationTest(unittest.TestCase):
    def config(self):
        return {
            "job": {"project_name": "test"},
            "runtime": {"process_folder": "/unused"},
            "processing": {
                "mode": "UDF",
                "execute": True,
                "mosaic": True,
            },
            "quality_validation": {"enabled": True},
        }

    @patch("force_workflow.validate_configured_outputs")
    @patch("force_workflow.mosaicing", return_value=["/results/summary.tif"])
    @patch("force_workflow.force_process")
    @patch("force_workflow.create_folder_structure")
    def test_validates_completed_mosaic(
        self, create_folders, force_process, mosaicing, validate
    ):
        config = self.config()

        run_workflow(config)

        validate.assert_called_once_with(config, ["/results/summary.tif"])

    @patch("force_workflow.validate_configured_outputs")
    @patch("force_workflow.mosaicing", return_value=["/results/summary.tif"])
    @patch("force_workflow.force_process")
    @patch("force_workflow.create_folder_structure")
    def test_dry_run_does_not_validate_stale_outputs(
        self, create_folders, force_process, mosaicing, validate
    ):
        config = self.config()
        config["processing"]["execute"] = False

        run_workflow(config)

        validate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
