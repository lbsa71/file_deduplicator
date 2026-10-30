"""Pure location reconciliation and hierarchical place labels."""

import json
import math
import re
from functools import lru_cache
from importlib.resources import files

VERSION = "location-v1"
AGREEMENT_METRES = 250


def coordinates(value):
    if not isinstance(value, dict):
        return None
    lat, lon = value.get("latitude"), value.get("longitude")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in (lat, lon)):
        return None
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return None
    result = {"latitude": lat, "longitude": lon}
    altitude = value.get("altitude_m")
    if type(altitude) in (int, float) and math.isfinite(altitude):
        result["altitude_m"] = altitude
    return result


def distance_metres(a, b):
    lat1, lat2 = map(math.radians, (a["latitude"], b["latitude"]))
    dlat = lat2 - lat1
    dlon = math.radians(b["longitude"] - a["longitude"])
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 6371008.8 * 2 * math.asin(min(1, math.sqrt(h)))


def coordinate_resolution(record):
    observations = []

    def add(value, source, field):
        value = coordinates(value)
        if value is not None:
            observation = {"value": value, "source": source, "field": field}
            if observation not in observations:
                observations.append(observation)

    embedded = record.data["stages"].get("embedded_metadata", {}).get("result", {})
    for prefix in ("Composite:", "GPS:", "EXIF:", ""):
        lat, lon = embedded.get(prefix + "GPSLatitude"), embedded.get(
            prefix + "GPSLongitude"
        )
        if coordinates({"latitude": lat, "longitude": lon}):
            # Composite values already include hemisphere; raw EXIF needs refs.
            if prefix != "Composite:":
                lat = (
                    -abs(lat)
                    if str(embedded.get(prefix + "GPSLatitudeRef", ""))
                    .upper()
                    .startswith("S")
                    else lat
                )
                lon = (
                    -abs(lon)
                    if str(embedded.get(prefix + "GPSLongitudeRef", ""))
                    .upper()
                    .startswith("W")
                    else lon
                )
            add(
                {"latitude": lat, "longitude": lon},
                "embedded",
                prefix + "GPSLatitude/GPSLongitude",
            )
            break
    if not observations:
        for key in (
            "Composite:GPSPosition",
            "QuickTime:GPSCoordinates",
            "Keys:GPSCoordinates",
            "GPSCoordinates",
        ):
            value = embedded.get(key)
            if isinstance(value, str) and re.fullmatch(r"[\d+.,\s/\-]+", value):
                parts = re.findall(r"[+-]?\d+(?:\.\d+)?", value)
                if len(parts) >= 2:
                    add(
                        {"latitude": float(parts[0]), "longitude": float(parts[1])},
                        "embedded",
                        key,
                    )
                    break
    for source in record.data["sources"]:
        latest = {(d["relative_path"], d["kind"]): d for d in source["documents"]}
        for doc in latest.values():
            if doc["kind"] == "album":
                continue
            for key in ("geoData", "geoDataExif"):
                value = doc["document"].get(key)
                if not isinstance(value, dict):
                    continue
                # Takeout uses an all-zero structure when no location exists.
                if value.get("latitude") == 0 and value.get("longitude") == 0:
                    continue
                add(
                    value,
                    {
                        "source_id": source["source_id"],
                        "path": doc["relative_path"],
                        "sha256": doc["sha256"],
                    },
                    key,
                )
    if "location" in record.data["overrides"]:
        value = record.data["overrides"]["location"]
        if value is not None and coordinates(value) is None:
            raise ValueError("location must contain finite WGS84 coordinates or null")
        return (
            coordinates(value),
            "human" if value is not None else "cleared",
            observations,
        )
    if not observations:
        return None, "missing", observations
    first = observations[0]["value"]
    # Compare every pair; agreement is not transitive.
    conflict = any(
        distance_metres(a["value"], b["value"]) > AGREEMENT_METRES
        for i, a in enumerate(observations)
        for b in observations[i + 1 :]
    )
    return (
        (None, "conflict", observations)
        if conflict
        else (first, "agreed" if len(observations) > 1 else "observed", observations)
    )


@lru_cache(maxsize=1)
def countries():
    return json.loads(files("photoflow").joinpath("data/countries.json").read_text())[
        "items"
    ]


def hierarchy(components):
    country = countries().get(components.get("country_code"), {})
    values = [
        components.get("city"),
        components.get("subregion"),
        components.get("region"),
        country.get("country") or components.get("country"),
        country.get("continent"),
    ]
    return list(
        dict.fromkeys(v.strip() for v in values if isinstance(v, str) and v.strip())
    )


def resolved_place(record, location):
    result = record.data["stages"].get("place", {}).get("result", {})
    if location is not None and result.get("location") == location:
        return result.get("hierarchy", []), result
    return [], None


class PlaceEnrichment:
    def run(self, batch, ctx):
        if ctx.geocoder is None:
            return
        from .model import input_key, encoded
        from .stages import refine

        path = ".photoflow/place-cache.json"
        try:
            cache = json.loads(ctx.fs.read_bytes(path)) if ctx.fs.exists(path) else {}
        except (ValueError, OSError):
            cache = {}
        if not isinstance(cache, dict):
            cache = {}
        if (
            cache.get("version") != ctx.geocoder.version
            or cache.get("library_id") != ctx.library_id
        ):
            cache = {
                "version": ctx.geocoder.version,
                "library_id": ctx.library_id,
                "items": {},
            }
        entries = cache.get("items", {})
        if not isinstance(entries, dict):
            entries = {}
        if cache.get("checksum") != input_key(entries):
            entries = {}
        entries = {
            key: value for key, value in entries.items() if isinstance(value, dict)
        }
        dirty, candidates, missing = False, [], {}
        for item in batch:
            if item.blocked:
                continue
            location = item.record.data["resolved"].get("location")
            key = input_key([location, ctx.geocoder.version])
            if item.record.data["stages"].get("place", {}).get("input_key") == key:
                continue
            candidates.append((item, location, key))
            if location is not None and key not in entries:
                missing[key] = location
        keys = list(missing)
        for offset in range(0, len(keys), 128):
            chunk = keys[offset : offset + 128]
            try:
                results = ctx.geocoder.lookup_many([missing[k] for k in chunk])
                if len(results) != len(chunk):
                    raise ValueError("Incorrect place result count")
                for key, result in zip(chunk, results):
                    if not isinstance(result, dict):
                        raise ValueError("Invalid place result")
                    entries[key] = result
                dirty = True
            except (ValueError, OSError) as error:
                # Existing metadata remains useful when enrichment is unavailable.
                ctx.summary.warnings.append("place_enrichment: " + str(error))
        for item, location, key in candidates:
            if location is not None and key not in entries:
                continue
            from .content import stable
            from .ports import ChangedError

            try:
                stable(ctx.fs, item.path, item.observed)
            except (OSError, ChangedError) as error:
                ctx.fail(item, error)
                continue
            components = entries.get(key, {})
            labels = hierarchy(components)
            result = {
                "location": location,
                "hierarchy": labels,
                "components": components,
                "provider": ctx.geocoder.version,
                "method": "nearest_settlement",
                "distance_km": components.get("distance_km"),
                "attribution": "GeoNames (https://www.geonames.org/), CC BY 4.0",
            }
            ctx.complete(
                item.record, "place", key, result, version=ctx.geocoder.version
            )
            refine(item.record, ctx)
        if dirty and not ctx.config.dry_run:
            cache["items"] = entries
            cache["checksum"] = input_key(entries)
            ctx.fs.atomic_write(path, encoded(cache))
