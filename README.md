# wigle-bulk-pull

Bulk-download **your own** WiGLE wardriving data via the v2 API — resume-safe,
incremental, straight to CSV. Stdlib Python only, no dependencies.

## Why

The WiGLE Android app's "DB backup" exports the local collection buffer, not
your archive: rows are pruned as data syncs upstream, so every dump differs
and contains pre-dedup noise. The server-side API is the source of truth.

## Setup

1. Log in at [wigle.net](https://wigle.net), open your account page, copy the
   API **"Encoded for Use"** token.
2. `export WIGLE_AUTH="<that token>"`
   (or set `WIGLE_API_NAME` + `WIGLE_API_TOKEN` and the script encodes them —
   never hardcode credentials in the script)

## Usage

Full pull (1M networks ≈ 10k pages at 100/page — let it run):

```bash
python3 wigle_pull.py --out my_networks.csv
```

Resume after an interruption (progress is tracked in `<out>.state.json`):

```bash
python3 wigle_pull.py --out my_networks.csv --resume
```

Incremental — only networks updated since a date:

```bash
python3 wigle_pull.py --out new_since_oct.csv --since 2026-10-01
```

Sanity check: the script prints `totalResults` from the first page — compare
it to the "discovered" count on your WiGLE stats page.

## What next

Don't load a million rows straight into QGIS. Filter in DuckDB first, then
push only the result set to QGIS as a GeoPackage:

```sql
INSTALL spatial; LOAD spatial;
CREATE TABLE nets AS SELECT * FROM read_csv('my_networks.csv', header=true);

-- open APs near San Antonio, for example:
COPY (
  SELECT * FROM nets
  WHERE trilat BETWEEN 29.2 AND 29.7 AND trilong BETWEEN -98.8 AND -98.3
) TO 'sa_open.gpkg' (FORMAT GDAL, DRIVER 'GPKG');
```

Join the first 3 MAC octets against the IEEE OUI list for manufacturer
filtering (`Espressif` = IoT, `Ruckus` = enterprise, ...).

## License

MIT
