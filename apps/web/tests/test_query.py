"""Query behaviour against the disposable catalog, without reading originals."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from photoflow.model import Record
from photoflow_web.core import Library


class QueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".photoflow").mkdir()
        (self.root / ".photoflow/library.json").write_text(
            '{"schema_version":2,"library_id":"test"}'
        )
        self.lib = Library(self.root, self.root / "state")
        self.records = {}
        self.add(
            1,
            people=["Ellen"],
            albums=["Summer"],
            capture_time="2009-01-01T00:00:00Z",
            favorite=True,
        )
        self.add(
            2,
            people=["Viktor"],
            albums=["Summer"],
            capture_time="2010-12-31T23:59:59-03:00",
        )
        self.add(
            3,
            people=["Ellen", "Viktor"],
            albums=["Family", "Summer"],
            capture_time="2009-12-31T23:59:59Z",
            tags=["Trip"],
        )
        self.add(4, people=[], albums=[], tags=["Trip"], extension=".MOV")

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, number, extension=".jpg", **metadata):
        ident = str(UUID(int=number))
        record = Record.create(ident, "test", f"photos/{number}{extension}")
        record.data["resolved"] = metadata
        self.records[number] = record
        self.save(number)
        return ident

    def save(self, number):
        record = self.records[number]
        sidecar = self.root / (record.path + ".photo.json")
        sidecar.parent.mkdir(parents=True, exist_ok=True)
        sidecar.write_bytes(record.to_bytes())
        self.lib.put_index(record.data, sidecar)

    def ids(self, **kwargs):
        return {UUID(item["id"]).int for item in self.lib.listing(**kwargs)["items"]}

    def test_people_any_and_all_compose_with_other_facets(self):
        self.assertEqual(self.ids(filters={"people": ["Ellen", "Viktor"]}), {1, 2, 3})
        self.assertEqual(
            self.ids(filters={"people": ["Ellen", "Viktor"], "people_mode": "all"}), {3}
        )
        self.assertEqual(self.ids(filters={"people": ["Ellen"], "tags": ["Trip"]}), {3})
        self.assertEqual(self.ids(filters={"albums": ["Summer", "Family"]}), {1, 2, 3})

    def test_place_matches_any_level_and_unions_countries_with_cities(self):
        self.records[1].data["resolved"]["place"] = ["Stockholm", "Sweden", "Europe"]
        self.records[2].data["resolved"]["place"] = ["Bergen", "Norway", "Europe"]
        self.records[3].data["resolved"]["place"] = ["Uppsala", "Sweden", "Europe"]
        for n in (1, 2, 3):
            self.save(n)
        self.assertEqual(self.ids(filters={"place": ["Stockholm", "Norway"]}), {1, 2})
        self.assertEqual(self.ids(filters={"place": ["Europe"]}), {1, 2, 3})
        self.assertEqual(
            self.ids(filters={"place": ["Sweden"], "people": ["Viktor"]}), {3}
        )
        self.assertEqual(self.ids(filters={"missing": "place"}), {4})
        values = {
            x["value"]: x["count"]
            for x in self.lib.facets(filters={"place": ["Stockholm"]})["place"]
        }
        self.assertEqual(values["Sweden"], 2)
        self.assertEqual(values["Europe"], 3)

    def test_exact_labels_do_not_use_substring_or_sql_pattern_matching(self):
        label = "O'Neil_% 🐈"
        self.add(5, people=[label, label], albums=["Summerish"])
        self.assertEqual(self.ids(filters={"people": [label]}), {5})
        self.assertEqual(self.ids(filters={"albums": ["Summer"]}), {1, 2, 3})

    def test_location_maintenance_filters(self):
        self.records[1].data["resolved"]["location"] = {
            "latitude": 59.3,
            "longitude": 18,
        }
        self.records[2].data["resolved"]["location_status"] = "conflict"
        self.save(1)
        self.save(2)
        self.assertEqual(self.ids(filters={"missing": "location"}), {2, 3, 4})
        self.assertEqual(self.ids(filters={"missing": "location_conflict"}), {2})

    def test_date_range_is_inclusive_in_recorded_calendar_date(self):
        self.assertEqual(
            self.ids(filters={"from": "2009-01-01", "to": "2009-12-31"}), {1, 3}
        )
        self.assertEqual(
            self.ids(filters={"from": "2010-12-31", "to": "2010-12-31"}), {2}
        )
        self.assertEqual(self.ids(filters={"date": "unknown"}), {4})
        self.assertEqual(self.ids(filters={"date": "known"}), {1, 2, 3})

    def test_favourite_type_and_missing_metadata(self):
        self.assertEqual(self.ids(filters={"favorite": "yes"}), {1})
        self.assertEqual(self.ids(filters={"favorite": "no"}), {2, 3, 4})
        self.assertEqual(self.ids(filters={"type": "video"}), {4})
        self.assertEqual(self.ids(filters={"missing": "people"}), {4})
        self.assertEqual(self.ids(filters={"missing": "albums"}), {4})

    def test_video_filter_covers_native_web_video_and_import_formats(self):
        for number, suffix in enumerate(
            (".WEBM", ".3gp", ".mts", ".avi", ".mkv", ".mp4", ".m4v"), 5
        ):
            self.add(number, extension=suffix)
        self.assertEqual(self.ids(filters={"type": "video"}), set(range(4, 12)))
        self.assertEqual(self.ids(filters={"type": "image"}), {1, 2, 3})

    def test_any_facets_show_alternatives_and_distinct_photo_counts(self):
        result = self.lib.facets(filters={"people": ["Ellen"]})
        self.assertEqual(result["total"], 2)
        self.assertEqual(
            result["people"],
            [{"value": "Ellen", "count": 2}, {"value": "Viktor", "count": 2}],
        )
        self.assertEqual(
            result["albums"],
            [{"value": "Family", "count": 1}, {"value": "Summer", "count": 2}],
        )
        result = self.lib.facets(filters={"people": ["Ellen"], "favorite": "yes"})
        self.assertEqual(result["people"], [{"value": "Ellen", "count": 1}])

    def test_all_people_counts_preview_an_additional_constraint_and_keep_zero_selection(
        self,
    ):
        result = self.lib.facets(filters={"people": ["Ellen"], "people_mode": "all"})
        self.assertEqual(
            result["people"],
            [{"value": "Ellen", "count": 2}, {"value": "Viktor", "count": 1}],
        )
        result = self.lib.facets(filters={"people": ["Nobody"], "people_mode": "all"})
        self.assertEqual(result["people"], [{"value": "Nobody", "count": 0}])

    def test_time_distribution_ignores_its_own_range_but_keeps_other_filters(self):
        result = self.lib.facets(
            filters={"people": ["Viktor"], "from": "2009-01-01", "to": "2009-12-31"}
        )
        self.assertEqual(result["total"], 1)
        self.assertEqual(
            result["years"],
            [{"value": "2009", "count": 1}, {"value": "2010", "count": 1}],
        )
        self.assertEqual(result["date_unknown"], 0)
        self.assertEqual(self.lib.facets(filters={"date": "known"})["date_unknown"], 1)

    def test_existing_scope_query_and_duplicate_visibility_are_preserved(self):
        self.records[2].data["duplicate_of"] = {
            "record_id": self.records[1].id,
            "sha256": "0" * 64,
        }
        self.save(2)
        self.assertEqual(self.ids(q="Summer", filters={"people": ["Viktor"]}), {3})
        self.assertEqual(
            self.ids(duplicates=True, filters={"people": ["Viktor"]}), {2, 3}
        )
        self.assertEqual(self.ids(favorite=True), {1})
        self.assertEqual(self.ids(folder="photos"), {1, 2, 3, 4})

    def test_matching_captures_all_ids_and_revisions_beyond_a_page(self):
        for number in range(5, 110):
            self.add(number, people=["Ellen"])
        result = self.lib.matching(filters={"people": ["Ellen"]})
        self.assertEqual(len(result), 107)
        self.assertTrue(all(set(item) == {"id", "revision"} for item in result))
        frozen = list(result)
        self.add(111, people=["Ellen"])
        self.assertEqual(result, frozen)

    def test_query_is_catalog_only_and_metadata_edits_refresh_index(self):
        self.records[1].data["resolved"]["people"] = ["Lisa"]
        self.save(1)
        with patch.object(
            Path, "read_bytes", side_effect=AssertionError("filesystem read")
        ), patch.object(Path, "stat", side_effect=AssertionError("filesystem stat")):
            self.assertEqual(self.ids(filters={"people": ["Ellen"]}), {3})
            self.assertEqual(self.ids(filters={"people": ["Lisa"]}), {1})
            self.assertEqual(self.lib.facets()["total"], 4)
            self.assertEqual(len(self.lib.matching()), 4)

    def test_rebuild_removes_orphan_facet_rows(self):
        (self.root / (self.records[1].path + ".photo.json")).unlink()
        self.lib.rebuild()
        self.assertEqual(self.ids(filters={"people": ["Ellen"]}), {3})
        with self.lib.db() as db:
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM query_labels WHERE id=?",
                    (self.records[1].id,),
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                db.execute(
                    "SELECT count(*) FROM query_properties WHERE id=?",
                    (self.records[1].id,),
                ).fetchone()[0],
                0,
            )

    def test_rebuild_publishes_coherent_batches_while_queries_continue(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event

        for number in range(5, 71):
            self.add(number, people=["Old"])
        for record in self.records.values():
            record.data["resolved"].update(
                people=["New"], capture_time="2020-12-31T12:00:00Z", favorite=True
            )
            (self.root / (record.path + ".photo.json")).write_bytes(record.to_bytes())
        reached, resume = Event(), Event()
        original_index = self.lib.put_index
        calls = 0

        def pause_before_next_batch(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 65:
                reached.set()
                if not resume.wait(timeout=5):
                    raise AssertionError("Test did not resume the rebuild")
            return original_index(*args, **kwargs)

        def read_during_update():
            filters = {"people": ["New"]}
            with self.lib.db() as db:
                rows = db.execute(
                    "SELECT l.metadata,p.data,q.day,q.favorite FROM listing l "
                    "JOIN photos p ON p.id=l.id JOIN query_properties q ON q.id=l.id "
                    "JOIN query_labels x ON x.id=l.id AND x.facet='people' AND x.value='New'"
                ).fetchall()
                for row in rows:
                    self.assertEqual(json.loads(row["metadata"])["people"], ["New"])
                    self.assertEqual(
                        json.loads(row["data"])["resolved"]["people"], ["New"]
                    )
                    self.assertEqual((row["day"], row["favorite"]), ("2020-12-31", 1))
            return (
                self.lib.listing(filters=filters)["total"],
                self.lib.facets(filters=filters)["total"],
                len(self.lib.matching(filters=filters)),
                len(rows),
            )

        with ThreadPoolExecutor(2) as pool, patch.object(
            self.lib, "put_index", side_effect=pause_before_next_batch
        ):
            rebuild = pool.submit(self.lib.rebuild)
            try:
                self.assertTrue(reached.wait(timeout=5))
                reader = pool.submit(read_during_update)
                self.assertEqual(reader.result(timeout=2), (64, 64, 64, 64))
            finally:
                resume.set()
            self.assertEqual(rebuild.result(timeout=5), 70)
        self.assertEqual(read_during_update(), (70, 70, 70, 70))

    def test_validation_rejects_unknown_or_ambiguous_filter_values(self):
        bad = [
            [],
            {"unknown": True},
            {"people": "Ellen"},
            {"people": [7]},
            {"people": [""]},
            {"people_mode": "maybe"},
            {"favorite": True},
            {"date": "missing"},
            {"from": "2009-02-30"},
            {"from": "2009-1-1"},
            {"from": "2010-01-01", "to": "2009-01-01"},
            {"date": "unknown", "from": "2009-01-01"},
        ]
        for filters in bad:
            with self.subTest(filters=filters), self.assertRaises(ValueError):
                self.lib.listing(filters=filters)

    def test_normalization_is_canonical_without_changing_label_spelling(self):
        from photoflow_web.query import normalize_filters

        a = normalize_filters({"people": ["Viktor", "Ellen", "Ellen"]})
        b = normalize_filters({"people": ["Ellen", "Viktor"], "people_mode": "any"})
        self.assertEqual(a, b)
        self.assertEqual(a["people"], ["Ellen", "Viktor"])


if __name__ == "__main__":
    unittest.main()
