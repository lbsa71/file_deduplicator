# ADR 0002: Place hierarchies from preserved coordinate observations

Status: Accepted — 2026-10-30

## Decision

Resolve embedded EXIF/QuickTime GPS and Takeout `geoData`/`geoDataExif` into
`resolved.location`. Preserve every observation with its source. Compare every
pair using great-circle distance with a versioned 250-metre agreement threshold.
Large disagreements yield `location_status: conflict` and no automatic coordinate.
Human location corrections override observations; null explicitly clears location.
Takeout's zero coordinate placeholders are treated as missing. EXIF coordinates on
the equator/prime meridian remain valid. Validate finite WGS84 coordinates and
hemisphere references; never average conflicting observations.

Add an optional PlaceEnrichment pipeline stage after exact duplicate provenance
merging. Use ExifTool offline geolocation with a pinned GeoNames-derived database.
The installed extended database is Geolocation500-20260407.zip, SHA-256
`f8ec998c9fcbd46b054886af97f3dd5f65df564ab3d57d08b5919b954e2acac3`.
Provider identity includes the database digest and adapter/radius version.
Queries are batched in one process per chunk, with no image reads or network
requests. Cache successful and empty results under `.photoflow/place-cache.json`
by library identity, provider version and exact coordinates. Unchanged stage
checkpoints avoid repeated queries and sidecar writes. Failures remain retryable
and do not prevent basic metadata ingestion. Filesystem, provider, clock and IDs
are injected for behavioural tests.

Store place as an ordered specific-to-broad array, for example:

```json
{"place":["Stockholm","Stockholms Kommun","Sweden","Europe"]}
```

Include subregion and region when available, suppress repeated identical names,
and append canonical country and continent from the bundled GeoNames country
table. Country-to-continent classification is a country grouping, not a point
containment test for transcontinental countries. Keep components, lookup source,
method, distance and attribution in `resolved.place_details` and the stage result.
Place enrichment never replaces capture coordinates with a settlement centre.

The lookup is an approximate nearest-settlement association, capped at 100 km;
it does not certify administrative boundary containment. Coordinates without a
matching settlement remain available and the place array stays empty. Conflicts
are visible in maintenance filters. GeoNames attribution accompanies portable
results and the viewer. Manual place hierarchy overrides survive subsequent
scans; clearing an override resumes automatic resolution. Editing unrelated
fields must not freeze an automatically derived place as a manual correction.

## Query and UI

Index every hierarchy element as a `place` membership in the existing disposable
SQLite projection. A Place selector offers searchable checkboxes with contextual
counts; values within Place combine with OR and other dimensions combine with
AND. Thus `Stockholm OR Norway` and `Europe AND Ellen` work without creating real
folders. Counts represent distinct records per label; city/country/continent
counts overlap. URLs use repeated `place` parameters, retained through saved
views, login return, viewer links, reload and batch selection snapshots.

The viewer displays the ordered hierarchy and approximate-match attribution.
Metadata editing and reviewed batches can set/reset manual place hierarchies.
Maintenance filters include missing place names, missing resolved coordinates,
and coordinate conflicts. Existing user values and raw imported source documents
remain preserved. A metadata-only first backfill uses cached extraction evidence
and must report zero media moves and zero content hashes.

## Delivery and follow-up

Tests cover source agreement/conflicts, hemisphere signs, invalid values and
placeholders, stale place invalidation after coordinate correction, hierarchy
order/continents, unchanged-run caching, exact hierarchy member queries, mixed
city/country OR selections, URL persistence and browser selection. Test real
offline lookups with public Stockholm and Oslo coordinates before backfill.

Detailed addresses, boundary-polygon containment, personal named areas and an
optional hosted geocoder are follow-up adapters. They do not block local place
filtering. No hosted API is configured or called by this implementation.

## Sources and deployment

- [ExifTool geolocation](https://exiftool.org/geolocation.html)
- [Extended database](https://exiftool.org/Geolocation500-20260407.zip)
- [GeoNames country/continent table](https://download.geonames.org/export/dump/countryInfo.txt)
- [GeoNames attribution and data terms](https://www.geonames.org/export/)

CLI: `photoflow run ROOT --exiftool --places --geodir DIRECTORY`; `--no-move` is
appropriate for backfills. Web scanning reads `PHOTOFLOW_GEODIR` at its application
boundary. The host uses `/opt/photoflow-geolocation/Geolocation500`; database files
are root-owned and readable by the service. The catalogue and place cache are
rebuildable; enriched sidecars retain the resolved hierarchy and evidence.
