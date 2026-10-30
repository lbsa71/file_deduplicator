"""Offline ExifTool adapter. No image reads or network requests."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess


class ExifToolGeocoder:
    def __init__(self, executable="exiftool", database=None):
        self.executable = shutil.which(executable) or executable
        self.database = (
            Path(database)
            if database
            else Path(self.executable).resolve().parent / "lib/Image/ExifTool"
        )
        digest = hashlib.sha256()
        for name in ("Geolocation.dat", "Geolocation.pm"):
            path = self.database / name
            if path.exists():
                digest.update(path.read_bytes())
            elif name == "Geolocation.dat":
                raise ValueError(
                    "ExifTool geolocation database missing; configure --geodir"
                )
        self.version = "exiftool-offline-v1-max100km:" + digest.hexdigest()

    def lookup_many(self, locations):
        args = []
        for location in locations:
            args.extend(
                [
                    "-api",
                    f"GeoDir={self.database}",
                    "-api",
                    "GeolocMaxDist=100",
                    "-api",
                    f"geolocation={location['latitude']},{location['longitude']}",
                    "-j",
                    "-n",
                    "-execute",
                ]
            )
        try:
            result = subprocess.run(
                [self.executable, "-@", "-"],
                input="\n".join(args) + "\n",
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.SubprocessError as error:
            raise ValueError("Offline geolocation process failed") from error
        if result.returncode not in (0, 1):
            raise ValueError("Offline geolocation failed: " + result.stderr[:300])
        decoder = json.JSONDecoder()
        text = result.stdout
        rows = []
        while text.strip():
            text = text.lstrip()
            value, end = decoder.raw_decode(text)
            if not isinstance(value, list) or len(value) != 1:
                raise ValueError("Unexpected geolocation output")
            raw = value[0]
            fields = {
                "GeolocationCity": "city",
                "GeolocationSubregion": "subregion",
                "GeolocationRegion": "region",
                "GeolocationCountryCode": "country_code",
                "GeolocationCountry": "country",
                "GeolocationDistance": "distance_km",
            }
            rows.append(
                {field: raw[key] for key, field in fields.items() if key in raw}
            )
            text = text[end:]
        if len(rows) != len(locations):
            raise ValueError("Geolocation result count does not match inputs")
        return rows
