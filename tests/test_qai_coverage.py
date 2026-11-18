import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from utils.qai_coverage import (
    analyze_qai_files,
    discover_qai_files,
    profile_valid_masks,
)


class QaiCoverageTest(unittest.TestCase):
    def test_profiles_relax_cloud_buffer_then_shadow(self):
        qai = np.array([[0, 2], [4, 8]], dtype=np.uint16)

        masks = profile_valid_masks(qai)

        self.assertEqual(int(masks["strict"].sum()), 1)
        self.assertEqual(int(masks["balanced"].sum()), 2)
        self.assertEqual(int(masks["exploratory"].sum()), 3)

    def test_report_compares_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            ard_dir = Path(directory)
            tile_dir = ard_dir / "X0001_Y0002"
            tile_dir.mkdir()
            path = tile_dir / "20250118_LEVEL2_SEN2A_QAI.tif"
            with rasterio.open(
                path,
                "w",
                driver="GTiff",
                width=2,
                height=2,
                count=1,
                dtype="uint16",
                transform=from_origin(0, 2, 1, 1),
                crs="EPSG:9377",
            ) as dst:
                dst.write(np.array([[0, 2], [4, 8]], dtype=np.uint16), 1)

            paths = discover_qai_files(ard_dir, tiles=["X0001_Y0002"])
            report = analyze_qai_files(paths, ard_dir=ard_dir)

        self.assertEqual(report["qai_file_count"], 1)
        self.assertEqual(report["profiles"]["strict"]["coverage_at_least_1_pct"], 25.0)
        self.assertEqual(report["profiles"]["balanced"]["coverage_at_least_1_pct"], 50.0)
        self.assertEqual(report["profiles"]["exploratory"]["coverage_at_least_1_pct"], 75.0)
        self.assertEqual(
            report["observations"][0]["path"],
            "X0001_Y0002/20250118_LEVEL2_SEN2A_QAI.tif",
        )


if __name__ == "__main__":
    unittest.main()
