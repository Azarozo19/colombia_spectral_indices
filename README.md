# Colombia FORCE spectral indices

This is a Colombia-specific copy of `SITS_force_playground`. It reads the
existing, validated FORCE Level-2 datacube without modifying it and produces a
quality-screened median composite of selected spectral indices.

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

The default UDF produces four Int16 bands:

| Band | Formula |
|---|---|
| `NDVI_MEDIAN` | `(BROADNIR - RED) / (BROADNIR + RED)` |
| `EVI_MEDIAN` | `2.5 × (BROADNIR - RED) / (BROADNIR + 6×RED - 7.5×BLUE + 1)` |
| `NBR_MEDIAN` | `(BROADNIR - SWIR2) / (BROADNIR + SWIR2)` |
| `NDMI_MEDIAN` | `(BROADNIR - SWIR1) / (BROADNIR + SWIR1)` |

Values are multiplied by 10,000. For example, stored NDVI `6500` means
physical NDVI `0.65`. Nodata is `-9999`.

For each index, the UDF first calculates the value for every accepted
acquisition and then takes the pixel-wise median over the ten-day snapshot.
This is a multi-date clear-pixel composite, not a single-date observation.

## Cloud and quality screening

FORCE applies the following QAI mask before reflectance reaches the UDF:

```text
NODATA CLOUD_OPAQUE CLOUD_BUFFER CLOUD_CIRRUS CLOUD_SHADOW SNOW
SUBZERO SATURATION
```

Cloudy pixels remain in the original ARD but are excluded from the composite.
Pixels with no accepted observation remain nodata.

## Configure the run

Edit [`config.yaml`](config.yaml). The most useful settings are:

```yaml
parameters:
  INDICES: [NDVI, EVI, NBR, NDMI]
  DATE_RANGE: 2025-01-18 2025-01-27
  NTHREAD_READ: 2
  NTHREAD_COMPUTE: 2
  NTHREAD_WRITE: 2
```

Supported indices are `NDVI`, `EVI`, `NBR`, and `NDMI`. Remove unwanted names
to reduce computation and output size. Do not extend the dates beyond the
observations that currently exist in the cube unless new ARD is ingested.

To test a small area first, replace `inputs.aois` with a small GeoJSON,
GeoPackage, or shapefile. The AOI may use another CRS; the pipeline creates a
reprojected copy in EPSG:9377 without changing the source file.

## Environment

Docker must be available to the current user. Create the lightweight host
environment with:

```bash
cd /drive_mount/SITS_force_colombia_indices
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The configured FORCE container must also be available locally. If it is not,
Docker will attempt to pull the pinned image when the pipeline starts.

## Validate the Python code

```bash
cd /drive_mount/SITS_force_colombia_indices
pytest -q
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

The output GeoTIFF retains the four band descriptions, ZSTD compression,
internal overviews, EPSG:9377 alignment, and `SPECTRAL_INDEX_SCALE_FACTOR=0.0001`
metadata.

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
