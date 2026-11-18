import tempfile
import unittest
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from utils.quality_validation import (
    discover_spectral_outputs,
    validate_spectral_outputs,
)


class QualityValidationTest(unittest.TestCase):
    def test_validates_schema_ranges_and_observation_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.tif"
            arrays = np.array(
                [
                    [[5000, 2000], [-9999, -9999]],
                    [[4000, 1000], [-9999, -9999]],
                    [[6000, 3000], [-9999, -9999]],
                    [[3, 1], [0, -9999]],
                ],
                dtype=np.int16,
            )
            with rasterio.open(
                path,
                "w",
                driver="GTiff",
                width=2,
                height=2,
                count=4,
                dtype="int16",
                nodata=-9999,
                transform=from_origin(0, 2, 1, 1),
                crs="EPSG:9377",
            ) as dst:
                dst.write(arrays)
                for band, name in enumerate(
                    ("NDVI_MEDIAN", "NDVI_P25", "NDVI_P75", "NDVI_VALID_COUNT"),
                    start=1,
                ):
                    dst.set_band_description(band, name)

            paths = discover_spectral_outputs(directory)
            report = validate_spectral_outputs(
                paths,
                expected_indices=["NDVI"],
                expected_statistics=["MEDIAN", "P25", "P75", "VALID_COUNT"],
                minimum_valid_coverage_pct=60,
                minimum_reliable_coverage_pct=30,
                minimum_reliable_observations=3,
            )

        self.assertTrue(report["accepted"])
        self.assertEqual(report["indices"]["NDVI"]["eligible_pixel_count"], 3)
        self.assertEqual(report["indices"]["NDVI"]["coverage_at_least_1_pct"], 66.6667)
        self.assertEqual(report["indices"]["NDVI"]["coverage_at_least_3_pct"], 33.3333)


if __name__ == "__main__":
    unittest.main()
