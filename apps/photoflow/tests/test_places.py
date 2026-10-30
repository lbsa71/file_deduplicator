import copy
import unittest
from photoflow.model import Record
from photoflow.metadata import resolve
from photoflow.places import hierarchy, coordinate_resolution


class PlaceTests(unittest.TestCase):
    def record(self, embedded=None, documents=()):
        record = Record.create(
            "00000000-0000-0000-0000-000000000001", "test", "inbox/photo.jpg"
        )
        record.data["stages"]["embedded_metadata"] = {"result": embedded or {}}
        record.data["sources"][0]["documents"] = [
            {
                "kind": "takeout",
                "relative_path": f"inbox/{i}.json",
                "sha256": str(i),
                "document": doc,
            }
            for i, doc in enumerate(documents)
        ]
        return record

    def test_coordinate_agreement_preserves_sources_and_signed_gps(self):
        record = self.record(
            {
                "GPS:GPSLatitude": 33.9,
                "GPS:GPSLatitudeRef": "S",
                "GPS:GPSLongitude": 18.4,
                "GPS:GPSLongitudeRef": "E",
            },
            [{"geoData": {"latitude": -33.90001, "longitude": 18.40001}}],
        )
        result = resolve(record)
        self.assertEqual(result["location"], {"latitude": -33.9, "longitude": 18.4})
        self.assertEqual(result["location_status"], "agreed")
        self.assertEqual(len(result["provenance"]["location"]), 2)

    def test_conflict_does_not_guess_or_average_and_human_can_resolve(self):
        record = self.record(
            {"Composite:GPSLatitude": 59.3, "Composite:GPSLongitude": 18.0},
            [{"geoData": {"latitude": 59.9, "longitude": 10.7}}],
        )
        result = resolve(record)
        self.assertIsNone(result["location"])
        self.assertEqual(result["location_status"], "conflict")
        record.data["overrides"]["location"] = {"latitude": 59.3, "longitude": 18.0}
        self.assertEqual(resolve(record)["location_status"], "human")

    def test_placeholder_invalid_and_latest_takeout_revision(self):
        record = self.record(
            documents=[
                {"geoData": {"latitude": 0, "longitude": 0, "altitude": 0}},
                {"geoDataExif": {"latitude": 59.3, "longitude": 18.0}},
            ]
        )
        self.assertEqual(resolve(record)["location"]["latitude"], 59.3)
        for value in (float("nan"), float("inf"), True, 200):
            record.data["overrides"]["location"] = {"latitude": value, "longitude": 0}
            with self.assertRaises(ValueError):
                resolve(record)

    def test_hierarchy_is_ordered_unique_and_includes_continent(self):
        self.assertEqual(
            hierarchy(
                {"city": "Stockholm", "region": "Stockholm", "country_code": "SE"}
            ),
            ["Stockholm", "Sweden", "Europe"],
        )
        self.assertEqual(
            hierarchy({"city": "Bergen", "region": "Vestland", "country_code": "NO"}),
            ["Bergen", "Vestland", "Norway", "Europe"],
        )

    def test_geocoded_result_survives_resolution_but_not_a_coordinate_change(self):
        record = self.record(
            {"Composite:GPSLatitude": 59.3, "Composite:GPSLongitude": 18.0}
        )
        location = resolve(record)["location"]
        record.data["stages"]["place"] = {
            "result": {
                "location": location,
                "components": {"city": "Stockholm", "country_code": "SE"},
                "hierarchy": ["Stockholm", "Sweden", "Europe"],
                "provider": "fixture",
                "method": "nearest_settlement",
                "distance_km": 1,
            }
        }
        original = copy.deepcopy(record.data["sources"])
        self.assertEqual(resolve(record)["place"], ["Stockholm", "Sweden", "Europe"])
        self.assertEqual(record.data["sources"], original)
        record.data["overrides"]["location"] = {"latitude": 60, "longitude": 20}
        self.assertEqual(resolve(record)["place"], [])
        record.data["overrides"]["place"] = ["Summer cottage", "Sweden", "Europe"]
        self.assertEqual(resolve(record)["place"][0], "Summer cottage")


if __name__ == "__main__":
    unittest.main()


class EnrichmentTests(unittest.TestCase):
    def test_pipeline_caches_locations_and_unchanged_pass_does_no_place_work(self):
        import json
        from datetime import datetime, timezone
        from photoflow.runner import Runner, Config
        from tests.fakes import MemoryFS, FakeClock, FakeIds, MetadataReader

        class Geocoder:
            version = "fixture-v1"
            calls = []

            def lookup_many(self, locations):
                self.calls.append(locations)
                return [
                    {"city": "Stockholm", "country_code": "SE", "distance_km": 1}
                    for _ in locations
                ]

        fs = MemoryFS()
        fs.put(".photoflow/library.json", b'{"schema_version":1,"library_id":"test"}')
        fs.put("inbox/a.jpg", b"a")
        fs.put("inbox/b.jpg", b"b")
        for name in ("a", "b"):
            fs.put(
                f"inbox/{name}.jpg.json",
                b'{"geoData":{"latitude":59.3,"longitude":18.0}}',
            )
        clock = FakeClock(datetime(2026, 10, 30, tzinfo=timezone.utc))
        ids = FakeIds()
        reader = MetadataReader()
        geocoder = Geocoder()

        def run():
            return Runner(
                fs,
                clock,
                ids,
                reader,
                Config(settle_seconds=0, move_files=False),
                geocoder=geocoder,
            ).run()

        self.assertFalse(run().errors)
        self.assertEqual(len(geocoder.calls), 1)
        self.assertEqual(len(geocoder.calls[0]), 1)
        before = fs.read_bytes("inbox/a.jpg.photo.json")
        self.assertEqual(
            json.loads(before)["resolved"]["place"], ["Stockholm", "Sweden", "Europe"]
        )
        self.assertFalse(run().errors)
        self.assertEqual(len(geocoder.calls), 1)
        self.assertEqual(before, fs.read_bytes("inbox/a.jpg.photo.json"))
        # A new record at an already cached coordinate needs no external lookup.
        fs.put("inbox/c.jpg", b"c")
        fs.put("inbox/c.jpg.json", b'{"geoData":{"latitude":59.3,"longitude":18.0}}')
        self.assertFalse(run().errors)
        self.assertEqual(len(geocoder.calls), 1)

    def test_offline_adapter_preserves_input_and_returns_hierarchy_components(self):
        import tempfile, json
        from pathlib import Path
        from unittest.mock import patch
        from photoflow.geocoder import ExifToolGeocoder

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "Geolocation.dat").write_bytes(b"dataset")
            with patch("photoflow.geocoder.subprocess.run") as run:
                run.return_value.returncode = 0
                run.return_value.stdout = json.dumps(
                    [
                        {
                            "GeolocationCity": "Stockholm",
                            "GeolocationCountryCode": "SE",
                            "GeolocationDistance": 2,
                        }
                    ]
                )
                provider = ExifToolGeocoder("/example/exiftool", tmp)
                self.assertEqual(
                    provider.lookup_many([{"latitude": 59.3, "longitude": 18}]),
                    [{"city": "Stockholm", "country_code": "SE", "distance_km": 2}],
                )
                self.assertIn("geolocation=59.3,18", run.call_args.kwargs["input"])
