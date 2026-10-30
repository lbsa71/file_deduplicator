import unittest
from photoflow.model import Record
from photoflow.metadata import resolve


class FavoriteTests(unittest.TestCase):
    def record(self, documents):
        record = Record.create(
            "00000000-0000-0000-0000-000000000001", "test", "inbox/photo.jpg"
        )
        record.data["sources"][0]["documents"] = [
            {
                "kind": "takeout",
                "relative_path": f"inbox/source-{i}.json",
                "sha256": str(i),
                "document": d,
            }
            for i, d in enumerate(documents)
        ]
        return record

    def test_takeout_favorite_is_aggregated_with_provenance(self):
        result = resolve(self.record([{"favorited": True}]))
        self.assertTrue(result["favorite"])
        self.assertEqual(result["provenance"]["favorite"][0]["field"], "favorited")

    def test_favorite_in_any_source_wins(self):
        self.assertTrue(
            resolve(self.record([{"favorited": False}, {"favorited": True}]))[
                "favorite"
            ]
        )

    def test_explicit_unfavorite_overrides_takeout(self):
        record = self.record([{"favorited": True}])
        record.data["overrides"]["favorite"] = False
        self.assertFalse(resolve(record)["favorite"])
        del record.data["overrides"]["favorite"]
        self.assertTrue(resolve(record)["favorite"])

    def test_invalid_favorite_is_not_treated_as_true(self):
        self.assertFalse(resolve(self.record([{"favorited": "false"}]))["favorite"])
