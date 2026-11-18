# Colombia FORCE spectral indices

This is a Colombia-specific copy of `SITS_force_playground`. It reads the
existing, validated FORCE Level-2 datacube without modifying it and produces
quality-screened spectral-index summaries plus explicit observation coverage.

## Default input

- ARD: `/opb_mount/force_col_data/colombia_sentinel2_snapshot_2025_01_23/level2`
- Grid: MAGNA-SIRGAS 2018 / Origen-Nacional (`EPSG:9377`)
- Resolution: 10 m
- Dates: 2025-01-18 through 2025-01-27
- Sensors: Sentinel-2A, Sentinel-2B and Sentinel-2C
- AOI: `/drive_mount/force_co/FORCE/aoi/colombia.geojson`
- FORCE: pinned to the same 3.10.04 container used to create the cube

The cube is mounted read-only in practice: all temporary and final products are
written below `/drive_mount/force_co/indices`.

## Products

The default UDF produces four bands per selected index:

| Suffix | Meaning |
|---|---|
| `_MEDIAN` | Median of all accepted observations |
| `_P25` | 25th percentile of accepted observations |
| `_P75` | 75th percentile of accepted observations |
| `_VALID_COUNT` | Number of accepted observations |

The supported indices are:

| Index | Formula |
|---|---|
| `NDVI` | `(BROADNIR - RED) / (BROADNIR + RED)` |
| `EVI` | `2.5 × (BROADNIR - RED) / (BROADNIR + 6×RED - 7.5×BLUE + 1)` |
| `NBR` | `(BROADNIR - SWIR2) / (BROADNIR + SWIR2)` |
| `NDMI` | `(BROADNIR - SWIR1) / (BROADNIR + SWIR1)` |

Index statistics are multiplied by 10,000. For example, stored NDVI `6500`
means physical NDVI `0.65`. `VALID_COUNT` is an unscaled observation count.
Nodata is `-9999`.

The normalized-difference indices require non-negative input reflectance and
are constrained to their physical `[-1, 1]` range. EVI values outside the
conservative `[-1, 1.5]` range are treated as invalid rather than clipped.

For each index, the UDF first calculates the value for every accepted
acquisition and then summarizes the configured date range pixel by pixel.
This is a multi-date clear-pixel composite, not a single-date observation.

## Cloud and quality screening

FORCE applies the following QAI mask before reflectance reaches the UDF:

```text
NODATA CLOUD_OPAQUE CLOUD_BUFFER CLOUD_CIRRUS CLOUD_SHADOW SNOW
SUBZERO SATURATION
```

Cloudy pixels remain in the original ARD but are excluded from the composite.
Index statistics with no accepted observation remain nodata; their
`VALID_COUNT` value is zero.

Before committing to a large run, compare three screening profiles directly
from the cube's QAI rasters:

```bash
python scripts/qai_coverage_report.py \
  --ard-dir /opb_mount/force_col_data/colombia_sentinel2_snapshot_2025_01_23/level2 \
  --tile X0034_Y0036 \
  --date-from 2025-01-01 \
  --date-to 2025-03-31 \
  --output /drive_mount/force_co/qai_coverage_X0034_Y0036.json
```

The report compares:

- `strict`: rejects cloud buffer, opaque cloud, cirrus and cloud shadow;
- `balanced`: allows cloud-buffer pixels but still rejects cloud and shadow;
- `exploratory`: also allows shadow, for diagnosis only.

Use the coverage and valid-observation histograms to choose a policy. For a
production vegetation product, start with `strict`; consider `balanced` only
if visual checks show that the extra coverage is trustworthy.

## Configure the run

Edit [`config.yaml`](config.yaml). The most useful settings are:

```yaml
parameters:
  INDICES: [NDVI, EVI, NBR, NDMI]
  STATISTICS: [MEDIAN, P25, P75, VALID_COUNT]
  DATE_RANGE: 2025-01-18 2025-01-27
  NTHREAD_READ: 2
  NTHREAD_COMPUTE: 2
  NTHREAD_WRITE: 2
```

Remove unwanted indices or statistics to reduce computation and output size.
Keep `VALID_COUNT` whenever automatic quality validation is enabled. Do not
extend the dates beyond observations that exist in the cube unless new ARD is
ingested.

Coverage validation is configured at the top level:

```yaml
quality_validation:
  enabled: true
  minimum_valid_coverage_pct: 95
  minimum_reliable_coverage_pct: 80
  minimum_reliable_observations: 3
  fail_on_threshold: false
```

These defaults are advisory: a run below a threshold still completes and the
report records the failure. Set `fail_on_threshold: true` only when the chosen
targets are mature enough to enforce in an automated pipeline.

To test a small area first, replace `inputs.aois` with a small GeoJSON,
GeoPackage, or shapefile. The AOI may use another CRS; the pipeline creates a
reprojected copy in EPSG:9377 without changing the source file.

## Environment

Docker must be available to the current user. Create the lightweight host
environment with:

```bash
cd /drive_mount/colombia_spectral_indices
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The configured FORCE container must also be available locally. If it is not,
Docker will attempt to pull the pinned image when the pipeline starts.

## Validate the Python code

```bash
cd /drive_mount/colombia_spectral_indices
python -m unittest discover -s tests -v
python pipeline/run.py --config config.yaml
```

The second command performs the actual FORCE run. A national 10 m run is large;
start with a small AOI before processing all of Colombia.

### Interactive debug mode

Set `processing.hold: true` to print every external command and pause before
and after it. Press Enter to execute or continue, and use `Ctrl+C` to abort
before a command. This mode requires an interactive terminal. Set it to
`false` for unattended or orchestrated execution.

## Outputs

FORCE tiles and provenance are written below:

```text
/drive_mount/force_co/indices/temp/colombia_spectral_indices_2025_snapshot/
```

The final national mosaic is written below:

```text
/drive_mount/force_co/indices/results/colombia_spectral_indices_2025_snapshot/
```

The output GeoTIFF retains band descriptions, per-band scales and units, ZSTD
compression, internal overviews, EPSG:9377 alignment, and
`SPECTRAL_INDEX_SCALE_FACTOR=0.0001` metadata. After a successful UDF run, the
pipeline writes this machine-readable validation report:

```text
<process_folder>/results/<project_name>/quality_validation.json
```

It checks the expected band schema, physical ranges, percentile ordering,
nodata consistency, coverage with at least one valid observation, and coverage
with the configured reliable-observation count.

An existing output can also be checked independently:

```bash
python scripts/validate_spectral_outputs.py \
  --input /path/to/results/or/summary.tif \
  --indices NDVI \
  --output /path/to/quality_validation.json
```

To keep only per-tile products and skip the potentially expensive national
mosaic, set:

```yaml
processing:
  mosaic: false
```

## Important limitations

- The source cube is a January 2025 snapshot, not a full seasonal time series.
- The median uses only quality-screened observations available at each pixel.
- Persistently cloudy pixels can remain nodata.
- This workflow does not alter, delete, or reprocess the Level-2 ARD.

## License

The copied workflow retains the original GPL-3.0 license. FORCE is developed by
David Frantz and should be cited according to the `CITEME` information stored
with the datacube.
