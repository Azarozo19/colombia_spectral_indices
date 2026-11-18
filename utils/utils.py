import os
import re
import subprocess
import glob
import math
from collections import defaultdict
import rasterio
OVERVIEW_RESAMPLING_METHODS = {
    "nearest",
    "average",
    "rms",
    "gauss",
    "cubic",
    "cubicspline",
    "lanczos",
    "average_mp",
    "average_magphase",
    "mode",
}


def validate_overview_options(levels, resampling):
    """Validate and normalize GDAL overview settings."""
    normalized_resampling = str(resampling).lower()
    if normalized_resampling not in OVERVIEW_RESAMPLING_METHODS:
        raise ValueError(
            "overview_resampling must be one of: "
            + ", ".join(sorted(OVERVIEW_RESAMPLING_METHODS))
        )

    try:
        normalized_levels = tuple(int(level) for level in levels)
    except (TypeError, ValueError) as error:
        raise ValueError("overview_levels must contain integers") from error
    if not normalized_levels:
        raise ValueError("overview_levels cannot be empty when overviews are enabled")
    if any(level <= 1 for level in normalized_levels):
        raise ValueError("every overview level must be greater than 1")
    if tuple(sorted(set(normalized_levels))) != normalized_levels:
        raise ValueError("overview_levels must be unique and strictly increasing")
    return normalized_levels, normalized_resampling


def build_internal_overviews(filename, levels, resampling):
    """Build and verify internal GeoTIFF pyramids for responsive GIS display."""
    levels, resampling = validate_overview_options(levels, resampling)
    subprocess.run(
        [
            "gdaladdo",
            "--config", "GDAL_NUM_THREADS", "ALL_CPUS",
            "-r", resampling,
            filename,
            *(str(level) for level in levels),
        ],
        check=True,
    )

    with rasterio.open(filename) as src:
        # GDAL creates integer-sized overview rasters. For dimensions that are
        # not divisible by the requested level, Rasterio reports the effective
        # decimation factor after that rounding. Example: 3000 / ceil(3000 /
        # 128) = 125, so a valid requested level 128 is reported as 125.
        expected_levels = [
            int(round(src.width / math.ceil(src.width / level)))
            for level in levels
        ]
        for band_index in range(1, src.count + 1):
            actual_levels = src.overviews(band_index)
            if actual_levels != expected_levels:
                raise ValueError(
                    f"Band {band_index} overview verification failed: "
                    f"expected {expected_levels}, got {actual_levels}"
                )


def create_folder_structure(process_folder):
    process_folder = os.path.abspath(os.path.expanduser(process_folder))
    folder_structure = [
        process_folder,
        os.path.join(process_folder, 'data'),
        os.path.join(process_folder, 'results'),
        os.path.join(process_folder, 'temp'),
        os.path.join(process_folder, 'temp', '_mask'),
    ]

    for path in folder_structure:
        if not os.path.exists(path):
            os.makedirs(path)
            print(f"Created folder: {path}")
        else:
            print(f"Folder already exists: {path}")


def mosaic_rasters(input_files, output_filename, output_options=None):
    if not input_files:
        raise ValueError("Cannot build a mosaic without input rasters")

    output_options = output_options or {}
    compression = str(output_options.get("compression", "ZSTD")).upper()
    interleave = str(output_options.get("interleave", "BAND")).upper()
    zstd_level = int(output_options.get("zstd_level", 15))
    block_size = int(output_options.get("block_size", 512))
    predictor = int(output_options.get("predictor", 2))
    max_z_error = float(output_options.get("max_z_error", 0))
    scale_factor = float(output_options.get("scale_factor", 0.0001))
    build_overviews = bool(output_options.get("build_overviews", True))
    overview_levels = output_options.get(
        "overview_levels", [2, 4, 8, 16, 32, 64, 128]
    )
    overview_resampling = output_options.get("overview_resampling", "average")

    if compression not in {"ZSTD", "LERC_ZSTD"}:
        raise ValueError("compression must be ZSTD or LERC_ZSTD")
    if interleave not in {"BAND", "PIXEL"}:
        raise ValueError("interleave must be BAND or PIXEL")
    if not 1 <= zstd_level <= 22:
        raise ValueError("zstd_level must be between 1 and 22")
    if block_size <= 0 or block_size % 16:
        raise ValueError("block_size must be a positive multiple of 16")
    if predictor not in {1, 2}:
        raise ValueError("predictor must be 1 or 2 for integer output")
    if max_z_error != 0:
        raise ValueError("max_z_error must be 0 for lossless output")
    if build_overviews:
        overview_levels, overview_resampling = validate_overview_options(
            overview_levels,
            overview_resampling,
        )

    input_files = sorted(input_files)
    vrt_path = output_filename.replace(".tif", "_tmp.vrt")
    partial_output = output_filename.replace(".tif", ".partial.tif")

    # Read the output schema once and reject heterogeneous inputs before GDAL
    # spends time constructing a partial mosaic.
    with rasterio.open(input_files[0]) as src:
        source_band_descriptions = tuple(src.descriptions)
        expected_source_count = src.count

    if any(description is None for description in source_band_descriptions):
        raise ValueError("Every FORCE UDF output band must have a description")
    band_descriptions = source_band_descriptions
    expected_count = expected_source_count

    errors = []
    for f in input_files:
        with rasterio.open(f) as src:
            if src.count != expected_source_count:
                errors.append(
                    f"{f}: expected {expected_source_count} bands, got {src.count}"
                )
            elif tuple(src.descriptions) != source_band_descriptions:
                errors.append(f"{f}: band descriptions do not match the reference")
        if len(errors) == 10:
            break

    if errors:
        details = "\n".join(errors)
        raise ValueError(
            "Cannot mosaic rasters with inconsistent band schemas. "
            "Normalize the inputs first.\n" + details
        )

    try:
        subprocess.run([
            "gdalbuildvrt",
            "-srcnodata", "-9999",
            "-vrtnodata", "-9999",
            "-overwrite",
            vrt_path,
            *input_files
        ], check=True)

        # Write to a temporary sibling and replace the destination only after
        # translation and metadata updates complete successfully.
        translate_command = [
            "gdal_translate",
            "-of",  "GTiff",
            # Preserve FORCE's Int16 values and nodata. Physical index values
            # equal the stored value multiplied by 0.0001.
            "-mo", f"SPECTRAL_INDEX_SCALE_FACTOR={scale_factor:g}",
            "-co", f"COMPRESS={compression}",
            "-co", f"INTERLEAVE={interleave}",
            "-co", f"ZSTD_LEVEL={zstd_level}",
            "-co",  "TILED=YES",
            "-co", f"BLOCKXSIZE={block_size}",
            "-co", f"BLOCKYSIZE={block_size}",
            "-co",  "BIGTIFF=IF_SAFER",
            "-co", "NUM_THREADS=ALL_CPUS",
            vrt_path,
            partial_output
        ]
        if compression == "ZSTD":
            translate_command[-2:-2] = ["-co", f"PREDICTOR={predictor}"]
        else:
            translate_command[-2:-2] = [
                "-co", f"MAX_Z_ERROR={max_z_error:g}"
            ]
        subprocess.run(translate_command, check=True)

        with rasterio.open(partial_output, "r+") as dst:
            if dst.count != expected_count:
                raise ValueError(
                    f"Mosaic has {dst.count} bands; expected {expected_count}"
                )
            for i, desc in enumerate(band_descriptions, start=1):
                dst.set_band_description(i, desc)
            dst.scales = tuple(
                1.0 if desc.endswith("_VALID_COUNT") else scale_factor
                for desc in band_descriptions
            )
            dst.units = tuple(
                "observations" if desc.endswith("_VALID_COUNT") else "1"
                for desc in band_descriptions
            )

        if build_overviews:
            build_internal_overviews(
                partial_output,
                overview_levels,
                overview_resampling,
            )

        os.replace(partial_output, output_filename)

        # PAM sidecars can retain descriptions and statistics from an older
        # file after the GeoTIFF is atomically replaced. Those stale values
        # override the correct internal metadata in GDAL/QGIS.
        auxiliary_metadata = output_filename + ".aux.xml"
        if os.path.exists(auxiliary_metadata):
            os.remove(auxiliary_metadata)
    finally:
        if os.path.exists(vrt_path):
            os.remove(vrt_path)
        if os.path.exists(partial_output):
            os.remove(partial_output)


def build_udf_output_name(force_basename, index, metric):
    """Build a readable UDF mosaic name while preserving FORCE time ranges.

    Example:
        2018-2018_001-365_HL_UDF_SEN2L_PYP.tif
        -> 2018-2018_001-365_NBR_MEDIAN.tif
    """
    stem, extension = os.path.splitext(force_basename)
    parts = stem.split("_")
    if len(parts) < 2:
        raise ValueError(
            f"Cannot extract year and DOY ranges from FORCE filename: {force_basename}"
        )

    def clean(value):
        cleaned = re.sub(r"[^A-Za-z0-9-]+", "-", str(value)).strip("-")
        if not cleaned:
            raise ValueError("Output index and metric names cannot be empty")
        return cleaned.upper()

    return f"{parts[0]}_{parts[1]}_{clean(index)}_{clean(metric)}{extension}"


def build_delivery_output_path(project_folder, aoi_path, product_name):
    """Keep the product name inside the original AOI-named directory."""
    return os.path.join(project_folder, os.path.basename(aoi_path), product_name)


def mosaicing(config):
    process_folder = config['runtime']['process_folder']
    project_name = config['job']['project_name']
    aois = config['inputs']['aois']
    temp_folder = process_folder + "/temp"
    proc_folder = process_folder + "/results/" + project_name
    os.makedirs(proc_folder, exist_ok=True)
    if config['processing']['mode'].upper() == "UDF":
        tif_folder = "PYP"
    else:
        tif_folder = "TSS"

    output_files = []
    for aoi in aois:
        aoi_name = os.path.splitext(os.path.basename(aoi))[0]
        # colect all tif files
        file_lst = sorted(glob.glob(f"{temp_folder}/{project_name}/FORCE/{aoi_name}/tiles_tss/X*/{tif_folder}/*.tif"))
        print(file_lst)
        if not file_lst:
            raise RuntimeError(
                f"No FORCE {tif_folder} tiles were produced for AOI {aoi_name}"
            )
        mosaics = defaultdict(list)
        for f in file_lst:
            tif_name = os.path.basename(f)
            mosaics[tif_name].append(f)
        # iterate over lists
        for mosaic_files in mosaics.values():
            base = os.path.basename(mosaic_files[0])
            if config['processing']['mode'].upper() == "UDF":
                product_label = "-".join(config['parameters']['INDICES'])
                statistics = config['parameters'].get(
                    'STATISTICS', ['MEDIAN', 'P25', 'P75', 'VALID_COUNT']
                )
                metric_label = statistics[0] if len(statistics) == 1 else 'SUMMARY'
                base = build_udf_output_name(
                    base,
                    product_label,
                    metric_label,
                )
            output_filename = build_delivery_output_path(proc_folder, aoi, base)
            os.makedirs(os.path.dirname(output_filename), exist_ok=True)
            mosaic_rasters(
                mosaic_files,
                output_filename,
                config.get("mosaic_output"),
            )
            output_files.append(output_filename)
    return output_files
