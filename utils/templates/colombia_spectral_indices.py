"""FORCE UDF for quality-screened spectral-index summary composites.

FORCE applies ``SCREEN_QAI`` before calling this module. The UDF then computes
each configured index per acquisition and summarizes the requested date range.
Index statistics are Int16 scaled by 10000; valid-observation counts are stored
as unscaled Int16 values.
"""

from __future__ import annotations

import os
import warnings

import numpy as np


OUTPUT_SCALE = 10000
SUPPORTED_INDICES = ("NDVI", "EVI", "NBR", "NDMI")
SUPPORTED_STATISTICS = ("MEDIAN", "P25", "P75", "VALID_COUNT")


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


def _selected_statistics():
    raw = os.environ.get(
        "FORCE_SPECTRAL_STATISTICS", ",".join(SUPPORTED_STATISTICS)
    )
    statistics = tuple(
        value.strip().upper() for value in raw.split(",") if value.strip()
    )
    if not statistics:
        raise ValueError("FORCE_SPECTRAL_STATISTICS cannot be empty")
    unknown = sorted(set(statistics) - set(SUPPORTED_STATISTICS))
    if unknown:
        raise ValueError("Unsupported spectral statistics: " + ", ".join(unknown))
    if len(set(statistics)) != len(statistics):
        raise ValueError("FORCE_SPECTRAL_STATISTICS cannot contain duplicates")
    return statistics


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


def _normalized_difference(first, second, valid):
    """Calculate a bounded normalized difference from physical reflectance."""
    valid = valid & (first >= 0) & (second >= 0)
    result = _safe_ratio(first - second, first + second, valid)
    result[(result < -1.0) | (result > 1.0)] = np.nan
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
        return _normalized_difference(bnir, red, bnir_valid & red_valid)

    if index_name == "EVI":
        blue, blue_valid = reflectance("BLUE")
        denominator = bnir + 6.0 * red - 7.5 * blue + 1.0
        result = _safe_ratio(
            2.5 * (bnir - red),
            denominator,
            bnir_valid
            & red_valid
            & blue_valid
            & (bnir >= 0)
            & (red >= 0)
            & (blue >= 0),
        )
        # EVI can exceed one over dense vegetation, but extreme values usually
        # indicate an unstable denominator or residual atmospheric effects.
        result[(result < -1.0) | (result > 1.5)] = np.nan
        return result

    if index_name == "NBR":
        swir2, swir2_valid = reflectance("SWIR2")
        return _normalized_difference(bnir, swir2, bnir_valid & swir2_valid)

    if index_name == "NDMI":
        swir1, swir1_valid = reflectance("SWIR1")
        return _normalized_difference(bnir, swir1, bnir_valid & swir1_valid)

    raise ValueError(f"Unsupported spectral index: {index_name}")


def forcepy_init(dates, sensors, bandnames):
    """Return a fixed schema so all Colombian grid tiles can be mosaicked."""
    return [
        f"{index}_{statistic}"
        for index in _selected_indices()
        for statistic in _selected_statistics()
    ]


def _write_scaled_statistic(out_band, values, nodata):
    out_band[:] = nodata
    valid = np.isfinite(values)
    scaled = np.rint(values[valid] * OUTPUT_SCALE)
    scaled = np.clip(scaled, -32767, 32767).astype(np.int16)
    out_band[valid] = scaled


def forcepy_chunk(inarray, outarray, dates, sensors, bandnames, nodata, nproc):
    """Compute quality-screened index summaries for a FORCE processing chunk."""
    outarray[:] = nodata
    output_index = 0
    statistics = _selected_statistics()
    for index_name in _selected_indices():
        observations = _index_stack(inarray, bandnames, nodata, index_name)
        summaries = {}
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message="All-NaN slice encountered")
            if "MEDIAN" in statistics:
                summaries["MEDIAN"] = np.nanmedian(observations, axis=0)
            percentiles = [
                value
                for name, value in (("P25", 25), ("P75", 75))
                if name in statistics
            ]
            if percentiles:
                percentile_values = np.nanpercentile(
                    observations, percentiles, axis=0
                )
                for percentile, values in zip(percentiles, percentile_values):
                    summaries[f"P{percentile}"] = values

        for statistic in statistics:
            if statistic == "VALID_COUNT":
                count = np.isfinite(observations).sum(axis=0)
                count = np.minimum(count, np.iinfo(np.int16).max).astype(np.int16)
                outarray[output_index] = count
            else:
                _write_scaled_statistic(
                    outarray[output_index], summaries[statistic], nodata
                )
            output_index += 1


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
