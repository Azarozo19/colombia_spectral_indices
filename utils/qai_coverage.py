"""Summarize FORCE QAI coverage without inflating the bit-packed rasters."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
import rasterio


QAI_PATTERN = re.compile(
    r"^(?P<date>\d{8})_LEVEL2_(?P<sensor>SEN2[ABCD])_QAI\.tif$"
)
PROFILE_NAMES = ("strict", "balanced", "exploratory")


def profile_valid_masks(qai):
    """Return valid-pixel masks for the supported QAI screening profiles."""
    qai = qai.astype(np.uint16, copy=False)
    nodata = (qai & 1) != 0
    cloud = (qai & 6) >> 1
    shadow = (qai & 8) != 0
    snow = (qai & 16) != 0
    subzero = (qai & 256) != 0
    saturation = (qai & 512) != 0
    base = nodata | snow | subzero | saturation
    return {
        "strict": ~(base | (cloud != 0) | shadow),
        "balanced": ~(base | (cloud >= 2) | shadow),
        "exploratory": ~(base | (cloud >= 2)),
    }


def _flag_counts(qai):
    qai = qai.astype(np.uint16, copy=False)
    observed = (qai & 1) == 0
    cloud = (qai & 6) >> 1
    return observed, {
        "observed": int(observed.sum()),
        "cloud_clear": int((observed & (cloud == 0)).sum()),
        "cloud_buffer": int((observed & (cloud == 1)).sum()),
        "cloud_opaque": int((observed & (cloud == 2)).sum()),
        "cloud_cirrus": int((observed & (cloud == 3)).sum()),
        "cloud_shadow": int((observed & ((qai & 8) != 0)).sum()),
        "snow": int((observed & ((qai & 16) != 0)).sum()),
        "water": int((observed & ((qai & 32) != 0)).sum()),
        "subzero": int((observed & ((qai & 256) != 0)).sum()),
        "saturation": int((observed & ((qai & 512) != 0)).sum()),
    }


def discover_qai_files(ard_dir, tiles=None, date_from=None, date_to=None):
    ard_dir = Path(ard_dir).expanduser().resolve()
    if not ard_dir.is_dir():
        raise FileNotFoundError(f"ARD directory does not exist: {ard_dir}")
    selected_tiles = set(tiles or [])
    start = date.fromisoformat(date_from) if date_from else None
    end = date.fromisoformat(date_to) if date_to else None
    if start and end and start > end:
        raise ValueError("date_from cannot be later than date_to")

    files = []
    for path in sorted(ard_dir.glob("X*_Y*/*_QAI.tif")):
        if selected_tiles and path.parent.name not in selected_tiles:
            continue
        match = QAI_PATTERN.match(path.name)
        if match is None:
            continue
        acquisition = date.fromisoformat(
            f"{match.group('date')[:4]}-{match.group('date')[4:6]}-{match.group('date')[6:]}"
        )
        if start and acquisition < start:
            continue
        if end and acquisition > end:
            continue
        files.append(path)
    if not files:
        raise FileNotFoundError("No matching FORCE QAI rasters were found")
    return files


def _histogram_median(histogram):
    total = sum(histogram.values())
    if total == 0:
        return 0.0
    targets = ((total - 1) // 2, total // 2)
    values = []
    cumulative = 0
    target_index = 0
    for value, count in sorted(histogram.items()):
        cumulative += count
        while target_index < 2 and cumulative > targets[target_index]:
            values.append(value)
            target_index += 1
    return float(sum(values) / len(values))


def _coverage_summary(counts, eligible):
    values = counts[eligible]
    denominator = int(values.size)
    if denominator == 0:
        return {
            "eligible_pixel_count": 0,
            "coverage_at_least_1_pct": 0.0,
            "coverage_at_least_3_pct": 0.0,
            "mean_valid_observations": 0.0,
            "median_valid_observations": 0.0,
            "maximum_valid_observations": 0,
            "valid_count_histogram": {},
        }
    histogram_array = np.bincount(values.astype(np.int64))
    histogram = {
        str(index): int(count)
        for index, count in enumerate(histogram_array)
        if count
    }
    return {
        "eligible_pixel_count": denominator,
        "coverage_at_least_1_pct": round(float((values >= 1).mean() * 100), 4),
        "coverage_at_least_3_pct": round(float((values >= 3).mean() * 100), 4),
        "mean_valid_observations": round(float(values.mean()), 4),
        "median_valid_observations": float(np.median(values)),
        "maximum_valid_observations": int(values.max()),
        "valid_count_histogram": histogram,
    }


def analyze_qai_files(paths, ard_dir=None):
    paths = [Path(path).resolve() for path in paths]
    ard_dir = Path(ard_dir).resolve() if ard_dir is not None else None
    grouped = defaultdict(list)
    for path in paths:
        grouped[path.parent.name].append(path)

    tile_rows = []
    observation_rows = []
    global_flags = defaultdict(int)
    global_histograms = {name: defaultdict(int) for name in PROFILE_NAMES}
    global_eligible = 0

    for tile_id, tile_paths in sorted(grouped.items()):
        count_arrays = None
        eligible = None
        for path in sorted(tile_paths):
            with rasterio.open(path) as src:
                qai = src.read(1).astype(np.uint16, copy=False)
            if count_arrays is None:
                count_arrays = {
                    name: np.zeros(qai.shape, dtype=np.uint16)
                    for name in PROFILE_NAMES
                }
                eligible = np.zeros(qai.shape, dtype=bool)
            elif qai.shape != eligible.shape:
                raise ValueError(f"QAI grid shape differs within tile {tile_id}: {path}")

            observed, flags = _flag_counts(qai)
            eligible |= observed
            for name, value in flags.items():
                global_flags[name] += value
            masks = profile_valid_masks(qai)
            accepted = {}
            observed_count = max(flags["observed"], 1)
            for name, mask in masks.items():
                count_arrays[name] += mask.astype(np.uint16)
                accepted[name] = round(float(mask.sum() * 100 / observed_count), 4)

            match = QAI_PATTERN.match(path.name)
            relative = str(path.relative_to(ard_dir)) if ard_dir else str(path)
            observation_rows.append({
                "tile_id": tile_id,
                "date": match.group("date") if match else None,
                "sensor": match.group("sensor") if match else None,
                "path": relative,
                "observed_pixel_count": flags["observed"],
                "accepted_pct": accepted,
            })

        assert count_arrays is not None and eligible is not None
        profile_rows = {
            name: _coverage_summary(counts, eligible)
            for name, counts in count_arrays.items()
        }
        tile_rows.append({
            "tile_id": tile_id,
            "observation_count": len(tile_paths),
            "profiles": profile_rows,
        })
        global_eligible += int(eligible.sum())
        for name, summary in profile_rows.items():
            for value, count in summary["valid_count_histogram"].items():
                global_histograms[name][int(value)] += count

    profile_summary = {}
    for name, histogram in global_histograms.items():
        at_least_1 = sum(count for value, count in histogram.items() if value >= 1)
        at_least_3 = sum(count for value, count in histogram.items() if value >= 3)
        total_observations = sum(value * count for value, count in histogram.items())
        profile_summary[name] = {
            "eligible_pixel_count": global_eligible,
            "coverage_at_least_1_pct": round(
                100 * at_least_1 / max(global_eligible, 1), 4
            ),
            "coverage_at_least_3_pct": round(
                100 * at_least_3 / max(global_eligible, 1), 4
            ),
            "mean_valid_observations": round(
                total_observations / max(global_eligible, 1), 4
            ),
            "median_valid_observations": _histogram_median(histogram),
            "maximum_valid_observations": max(histogram, default=0),
            "valid_count_histogram": {
                str(value): count for value, count in sorted(histogram.items())
            },
        }

    observed_total = max(global_flags["observed"], 1)
    flag_percentages = {
        name: round(100 * count / observed_total, 4)
        for name, count in sorted(global_flags.items())
        if name != "observed"
    }
    return {
        "schema_version": 1,
        "qai_file_count": len(paths),
        "tile_count": len(grouped),
        "profiles": profile_summary,
        "qai_flag_pct_of_observed_pixel_observations": flag_percentages,
        "tiles": tile_rows,
        "observations": observation_rows,
    }


def write_report(report, output_path):
    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return output_path
