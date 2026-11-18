import os
import unittest
from unittest.mock import patch

import numpy as np

from utils.templates.colombia_spectral_indices import (
    forcepy_chunk,
    forcepy_init,
)


NODATA = -9999
BANDNAMES = np.array(
    [b"BLUE", b"GREEN", b"RED", b"REDEDGE1", b"REDEDGE2", b"REDEDGE3",
     b"BROADNIR", b"NIR", b"SWIR1", b"SWIR2"]
)


class ColombiaSpectralIndicesTest(unittest.TestCase):
    def test_fixed_output_schema_and_index_values(self):
        # BLUE=.1, GREEN=.2, RED=.2, BROADNIR=.6, SWIR1=.3, SWIR2=.1
        observation = np.array(
            [1000, 2000, 2000, 0, 0, 0, 6000, 5500, 3000, 1000],
            dtype=np.int16,
        ).reshape((1, 10, 1, 1))
        out = np.full((4, 1, 1), NODATA, dtype=np.int16)

        with patch.dict(
            os.environ,
            {"FORCE_SPECTRAL_INDICES": "NDVI,EVI,NBR,NDMI"},
        ):
            self.assertEqual(
                forcepy_init(None, None, BANDNAMES),
                ["NDVI_MEDIAN", "EVI_MEDIAN", "NBR_MEDIAN", "NDMI_MEDIAN"],
            )
            forcepy_chunk(observation, out, None, None, BANDNAMES, NODATA, 1)

        self.assertEqual(out[:, 0, 0].tolist(), [5000, 4878, 7143, 3333])

    def test_nodata_observation_is_ignored_by_median(self):
        valid = np.array(
            [1000, 2000, 2000, 0, 0, 0, 6000, 5500, 3000, 1000],
            dtype=np.int16,
        )
        invalid = np.full(10, NODATA, dtype=np.int16)
        observations = np.stack([valid, invalid]).reshape((2, 10, 1, 1))
        out = np.full((1, 1, 1), NODATA, dtype=np.int16)

        with patch.dict(os.environ, {"FORCE_SPECTRAL_INDICES": "NDVI"}):
            forcepy_chunk(observations, out, None, None, BANDNAMES, NODATA, 1)

        self.assertEqual(out[0, 0, 0], 5000)

    def test_negative_reflectance_does_not_create_extreme_ndvi(self):
        observation = np.array(
            [1000, 2000, -100, 0, 0, 0, 50, 50, 3000, 1000],
            dtype=np.int16,
        ).reshape((1, 10, 1, 1))
        out = np.full((1, 1, 1), NODATA, dtype=np.int16)

        with patch.dict(os.environ, {"FORCE_SPECTRAL_INDICES": "NDVI"}):
            forcepy_chunk(observation, out, None, None, BANDNAMES, NODATA, 1)

        self.assertEqual(out[0, 0, 0], NODATA)


if __name__ == "__main__":
    unittest.main()
