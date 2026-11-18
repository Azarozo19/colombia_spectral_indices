"""FORCE UDF for quality-screened spectral-index median composites.

FORCE applies ``SCREEN_QAI`` before calling this module. The UDF then computes
each configured index per acquisition and takes the pixel-wise median across
the requested date range. Output values are Int16 scaled by 10000.
"""

from __future__ import annotations

import os
import warnings

import numpy as np


OUTPUT_SCALE = 10000
SUPPORTED_INDICES = ("NDVI", "EVI", "NBR", "NDMI")


def _selected_indices():
    raw = os.environ.get("FORCE_SPECTRAL_INDICES", ",".join(SUPPORTED_INDICES))
    indices = tuple(value.strip().upper() for value in raw.split(",") if value.strip())
    if not indices:
        raise ValueError("FORCE_SPECTRAL_INDICES cannot be empty")
    unknown = sorted(set(indices) - set(SUPPORTED_INDICES))
    if unknown:
        raise ValueError("Unsupported spectral indices: " + ", ".join(unknown))
    if len(set(indices)) != len(indices):
        raise ValueError("FORCE_SPECTRAL_INDICES cannot contain duplicates")
    return indices


def _band_index(bandnames, expected_name):
    decoded = [
        value.decode("utf-8") if isinstance(value, bytes) else str(value)
        for value in bandnames
    ]
    try:
        return decoded.index(expected_name)
    except ValueError as error:
        raise ValueError(
            f"Required FORCE band {expected_name!r} is missing; got {decoded}"
        ) from error


def _safe_ratio(numerator, denominator, valid):
    result = np.full(numerator.shape, np.nan, dtype=np.float32)
    valid = valid & np.isfinite(denominator) & (np.abs(denominator) > 1e-6)
    np.divide(numerator, denominator, out=result, where=valid)
    return result


def _index_stack(inarray, bandnames, nodata, index_name):
    """Return one float32 index stack with shape [dates, rows, columns]."""
    band_lookup = {
        name: _band_index(bandnames, name)
        for name in ("BLUE", "GREEN", "RED", "BROADNIR", "SWIR1", "SWIR2")
    }

    def reflectance(name):
        values = inarray[:, band_lookup[name], :, :]
        return values.astype(np.float32) / OUTPUT_SCALE, values != nodata

    red, red_valid = reflectance("RED")
    bnir, bnir_valid = reflectance("BROADNIR")

    if index_name == "NDVI":
        return _safe_ratio(bnir - red, bnir + red, bnir_valid & red_valid)

    if index_name == "EVI":
        blue, blue_valid = reflectance("BLUE")
        denominator = bnir + 6.0 * red - 7.5 * blue + 1.0
        return _safe_ratio(
            2.5 * (bnir - red),
            denominator,
            bnir_valid & red_valid & blue_valid,
        )

    if index_name == "NBR":
        swir2, swir2_valid = reflectance("SWIR2")
        return _safe_ratio(
            bnir - swir2,
            bnir + swir2,
            bnir_valid & swir2_valid,
        )

    if index_name == "NDMI":
        swir1, swir1_valid = reflectance("SWIR1")
        return _safe_ratio(
            bnir - swir1,
            bnir + swir1,
            bnir_valid & swir1_valid,
        )

    raise ValueError(f"Unsupported spectral index: {index_name}")


def forcepy_init(dates, sensors, bandnames):
    """Return a fixed schema so all Colombian grid tiles can be mosaicked."""
    return [f"{index}_MEDIAN" for index in _selected_indices()]


def forcepy_chunk(inarray, outarray, dates, sensors, bandnames, nodata, nproc):
    """Compute quality-screened median indices for a FORCE processing chunk."""
    outarray[:] = nodata
    for output_index, index_name in enumerate(_selected_indices()):
        observations = _index_stack(inarray, bandnames, nodata, index_name)
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="All-NaN slice encountered")
            median = np.nanmedian(observations, axis=0)

        valid = np.isfinite(median)
        scaled = np.rint(median[valid] * OUTPUT_SCALE)
        scaled = np.clip(scaled, -32767, 32767).astype(np.int16)
        outarray[output_index, valid] = scaled


def forcepy_pixel(inarray, outarray, dates, sensors, bandnames, nodata, nproc):
    """Pixel-mode compatibility entry point; production uses CHUNK mode."""
    forcepy_chunk(
        inarray,
        outarray.reshape((-1, 1, 1)),
        dates,
        sensors,
        bandnames,
        nodata,
        nproc,
    )
