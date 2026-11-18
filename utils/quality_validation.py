"""Validate spectral-index summary rasters and report observation coverage."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import numpy as np
import rasterio


INDEX_LIMITS = {
    "NDVI": (-10000, 10000),
    "NBR": (-10000, 10000),
    "NDMI": (-10000, 10000),
    "EVI": (-10000, 15000),
}
STATISTICS = ("MEDIAN", "P25", "P75", "VALID_COUNT")


def discover_spectral_outputs(input_path):
    input_path = Path(input_path).expanduser().resolve()
    if input_path.is_file():
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(f"Spectral output path does not exist: {input_path}")
    outputs = []
    for path in sorted(input_path.rglob("*.tif")):
        try:
            with rasterio.open(path) as src:
                descriptions = tuple(src.descriptions)
        except rasterio.errors.RasterioIOError:
            continue
        if any(
            description and description.endswith("_VALID_COUNT")
            for description in descriptions
        ):
            outputs.append(path)
    if not outputs:
        raise FileNotFoundError(
            f"No spectral summary GeoTIFFs with VALID_COUNT bands found: {input_path}"
        )
    return outputs


def _band_schema(descriptions):
    schema = defaultdict(dict)
    for band_index, description in enumerate(descriptions, start=1):
        if not description:
            continue
        for statistic in STATISTICS:
            suffix = f"_{statistic}"
            if description.endswith(suffix):
                index_name = description[: -len(suffix)]
                schema[index_name][statistic] = band_index
                break
    return dict(schema)


def validate_spectral_outputs(
    paths,
    *,
    expected_indices,
    expected_statistics,
    minimum_valid_coverage_pct=95.0,
    minimum_reliable_coverage_pct=80.0,
    minimum_reliable_observations=3,
):
    paths = [Path(path).resolve() for path in paths]
    expected_indices = [str(value).upper() for value in expected_indices]
    expected_statistics = [str(value).upper() for value in expected_statistics]
    if "VALID_COUNT" not in expected_statistics:
        raise ValueError(
            "expected_statistics must include VALID_COUNT to measure coverage"
        )
    histograms = {index: defaultdict(int) for index in expected_indices}
    file_rows = []
    errors = []

    for path in paths:
        file_errors = set()
        with rasterio.open(path) as src:
            schema = _band_schema(src.descriptions)
            nodata = src.nodata
            for index_name in expected_indices:
                actual = schema.get(index_name, {})
                missing = sorted(set(expected_statistics) - set(actual))
                if missing:
                    file_errors.add(
                        f"{index_name} missing bands: {', '.join(missing)}"
                    )
                    continue
                for _, window in src.block_windows(actual["VALID_COUNT"]):
                    count = src.read(actual["VALID_COUNT"], window=window)
                    eligible = (
                        count != nodata
                        if nodata is not None
                        else np.ones(count.shape, dtype=bool)
                    )
                    if np.any(count[eligible] < 0):
                        file_errors.add(
                            f"{index_name}_VALID_COUNT contains negatives"
                        )
                    values = count[eligible].astype(np.int64)
                    values = np.maximum(values, 0)
                    bincount = (
                        np.bincount(values)
                        if values.size
                        else np.array([], dtype=int)
                    )
                    for observation_count, pixel_count in enumerate(bincount):
                        if pixel_count:
                            histograms[index_name][observation_count] += int(
                                pixel_count
                            )

                    data_by_statistic = {
                        statistic: src.read(actual[statistic], window=window)
                        for statistic in expected_statistics
                        if statistic != "VALID_COUNT"
                    }
                    has_observation = eligible & (count >= 1)
                    for statistic, data in data_by_statistic.items():
                        if nodata is not None and np.any(
                            has_observation & (data == nodata)
                        ):
                            file_errors.add(
                                f"{index_name}_{statistic} has nodata where "
                                "VALID_COUNT >= 1"
                            )
                        limits = INDEX_LIMITS.get(index_name)
                        valid = has_observation.copy()
                        if nodata is not None:
                            valid &= data != nodata
                        if limits and np.any(valid):
                            minimum = int(data[valid].min())
                            maximum = int(data[valid].max())
                            if minimum < limits[0] or maximum > limits[1]:
                                file_errors.add(
                                    f"{index_name}_{statistic} contains values "
                                    f"outside {limits[0]}..{limits[1]}"
                                )

                    if all(
                        name in data_by_statistic
                        for name in ("P25", "MEDIAN", "P75")
                    ):
                        p25 = data_by_statistic["P25"]
                        median = data_by_statistic["MEDIAN"]
                        p75 = data_by_statistic["P75"]
                        comparable = has_observation.copy()
                        if nodata is not None:
                            comparable &= (
                                (p25 != nodata)
                                & (median != nodata)
                                & (p75 != nodata)
                            )
                        if np.any(
                            comparable
                            & ((p25 > median) | (median > p75))
                        ):
                            file_errors.add(
                                f"{index_name} violates P25 <= MEDIAN <= P75"
                            )

        sorted_file_errors = sorted(file_errors)
        file_rows.append({"path": str(path), "errors": sorted_file_errors})
        errors.extend(f"{path}: {message}" for message in sorted_file_errors)

    indices = {}
    threshold_failures = []
    for index_name, histogram in histograms.items():
        total = sum(histogram.values())
        at_least_one = sum(count for value, count in histogram.items() if value >= 1)
        reliable = sum(
            count
            for value, count in histogram.items()
            if value >= minimum_reliable_observations
        )
        valid_pct = 100 * at_least_one / max(total, 1)
        reliable_pct = 100 * reliable / max(total, 1)
        index_row = {
            "eligible_pixel_count": total,
            "coverage_at_least_1_pct": round(valid_pct, 4),
            f"coverage_at_least_{minimum_reliable_observations}_pct": round(
                reliable_pct, 4
            ),
            "mean_valid_observations": round(
                sum(value * count for value, count in histogram.items())
                / max(total, 1),
                4,
            ),
            "maximum_valid_observations": max(histogram, default=0),
            "valid_count_histogram": {
                str(value): count for value, count in sorted(histogram.items())
            },
        }
        indices[index_name] = index_row
        if valid_pct < minimum_valid_coverage_pct:
            threshold_failures.append(
                f"{index_name} valid coverage {valid_pct:.2f}% is below "
                f"{minimum_valid_coverage_pct:.2f}%"
            )
        if reliable_pct < minimum_reliable_coverage_pct:
            threshold_failures.append(
                f"{index_name} coverage with at least "
                f"{minimum_reliable_observations} observations "
                f"({reliable_pct:.2f}%) is below "
                f"{minimum_reliable_coverage_pct:.2f}%"
            )

    return {
        "schema_version": 1,
        "accepted": not errors and not threshold_failures,
        "file_count": len(paths),
        "thresholds": {
            "minimum_valid_coverage_pct": minimum_valid_coverage_pct,
            "minimum_reliable_coverage_pct": minimum_reliable_coverage_pct,
            "minimum_reliable_observations": minimum_reliable_observations,
        },
        "indices": indices,
        "threshold_failures": threshold_failures,
        "errors": errors,
        "files": file_rows,
    }


def write_validation_report(report, output_path):
    output_path = Path(output_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return output_path


def validate_configured_outputs(config, output_files):
    quality = config["quality_validation"]
    report = validate_spectral_outputs(
        output_files,
        expected_indices=config["parameters"]["INDICES"],
        expected_statistics=config["parameters"]["STATISTICS"],
        minimum_valid_coverage_pct=quality["minimum_valid_coverage_pct"],
        minimum_reliable_coverage_pct=quality[
            "minimum_reliable_coverage_pct"
        ],
        minimum_reliable_observations=quality[
            "minimum_reliable_observations"
        ],
    )
    report_path = (
        Path(config["runtime"]["process_folder"])
        / "results"
        / config["job"]["project_name"]
        / "quality_validation.json"
    )
    write_validation_report(report, report_path)
    print(
        json.dumps(
            {
                "accepted": report["accepted"],
                "indices": report["indices"],
                "threshold_failures": report["threshold_failures"],
                "errors": report["errors"],
                "report": str(report_path),
            },
            indent=2,
            sort_keys=True,
        )
    )
    if quality["fail_on_threshold"] and not report["accepted"]:
        raise RuntimeError(f"Spectral quality validation failed: {report_path}")
    return report_path, report
