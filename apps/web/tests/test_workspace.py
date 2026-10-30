import tempfile
import unittest
from pathlib import Path

from photoflow_web.core import Conflict, Library, atomic
from photoflow_web.workspace import Workspace


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        atomic(
            self.root / ".photoflow/library.json",
            {"schema_version": 2, "library_id": "test"},
        )
        self.library = Library(self.root, self.root / "state")
        self.now = 1000
        self.workspace = Workspace(self.library, clock=lambda: self.now)

    def tearDown(self):
        self.temp.cleanup()

    def photo(self, name="photo.jpg", **metadata):
        upload = self.library.new_upload("alice", name, 3, None)
        self.library.chunk(upload["id"], "alice", 0, b"abc")
        committed = self.library.finish_upload(upload["id"], "alice")
        self.library.rebuild()
        record = self.library.get(committed["record_id"])
        if metadata:
            record = self.library.metadata(
                record["record_id"], record["revision"], metadata, [], "alice"
            )
        return record

    def target(self, record):
        return {"id": record["record_id"], "revision": record["revision"]}

    def test_saved_views_survive_rebuild_and_are_private_and_revision_checked(self):
        view = self.workspace.create_view(
            "alice", "Family holidays", {"filters": {"people": ["Viktor"]}}
        )
        self.library.rebuild()
        self.assertEqual(self.workspace.list_views("alice")["items"][0], view)
        self.assertEqual(self.workspace.list_views("bob"), {"items": []})
        with self.assertRaises(KeyError):
            self.workspace.update_view("bob", view["id"], view["revision"], "Other", {})
        updated = self.workspace.update_view(
            "alice", view["id"], view["revision"], "Viktor", {"q": "Christmas"}
        )
        with self.assertRaises(Conflict):
            self.workspace.delete_view("alice", view["id"], view["revision"])
        self.workspace.delete_view("alice", updated["id"], updated["revision"])
        self.assertEqual(self.workspace.list_views("alice"), {"items": []})

    def test_invalid_query_or_name_is_not_persisted(self):
        for query in (
            {"filters": {"people_mode": "maybe"}},
            {"folder": "../outside"},
            {"offset": 100},
            {"trash": "false"},
        ):
            with self.assertRaises(ValueError):
                self.workspace.create_view("alice", "Name", query)
        with self.assertRaises(ValueError):
            self.workspace.create_view("alice", "   ", {})
        self.assertEqual(self.workspace.list_views("alice"), {"items": []})

    def test_saved_root_folder_scope_roundtrips_without_becoming_timeline(self):
        view = self.workspace.create_view(
            "alice", "All physical files", {"folder": "."}
        )
        self.assertEqual(view["query"]["folder"], ".")
        reopened = self.workspace.list_views("alice")["items"][0]
        self.assertEqual(reopened["query"]["folder"], ".")

    def test_selection_freezes_ids_and_revisions_before_plan(self):
        first = self.photo("first.jpg", people=["Viktor"])
        selection = self.workspace.create_selection(
            "alice", query={"filters": {"people": ["Viktor"]}}
        )
        second = self.photo("second.jpg", people=["Viktor"])
        plan = self.workspace.create_plan(
            "alice",
            {"action": "metadata", "set": {"favorite": True}},
            selection_id=selection["id"],
        )
        self.assertEqual(plan["count"], 1)
        result = self.workspace.execute_plan("alice", plan["id"], plan["revision"])
        self.assertEqual(result["succeeded"], 1)
        self.assertTrue(self.library.get(first["record_id"])["resolved"]["favorite"])
        self.assertFalse(
            self.library.get(second["record_id"])["resolved"].get("favorite", False)
        )

    def test_selection_is_private_and_expires(self):
        photo = self.photo()
        selection = self.workspace.create_selection(
            "alice", targets=[self.target(photo)]
        )
        with self.assertRaises(KeyError):
            self.workspace.get_selection("bob", selection["id"])
        self.now += 1801
        with self.assertRaises(Conflict):
            self.workspace.create_plan(
                "alice", {"action": "trash"}, selection_id=selection["id"]
            )

    def test_add_remove_preview_and_execution_preserve_unrelated_labels(self):
        photo = self.photo(people=["Viktor", "Lisa"], albums=["Summer"])
        plan = self.workspace.create_plan(
            "alice",
            {
                "action": "metadata",
                "add": {"people": ["Ellen", "Viktor"]},
                "remove": {"people": ["Lisa"]},
            },
            targets=[self.target(photo)],
        )
        self.assertEqual(plan["preview"][0]["before"]["people"], ["Viktor", "Lisa"])
        self.assertEqual(plan["preview"][0]["after"]["people"], ["Viktor", "Ellen"])
        result = self.workspace.execute_plan("alice", plan["id"], plan["revision"])
        self.assertEqual(result["succeeded"], 1)
        after = self.library.get(photo["record_id"])["resolved"]
        self.assertEqual(after["people"], ["Viktor", "Ellen"])
        self.assertEqual(after["albums"], ["Summer"])
        with self.assertRaises(Conflict):
            self.workspace.execute_plan("alice", plan["id"], plan["revision"])

    def test_conflicting_record_is_skipped_without_overwriting_new_edit(self):
        first = self.photo("first.jpg")
        second = self.photo("second.jpg")
        plan = self.workspace.create_plan(
            "alice",
            {"action": "metadata", "set": {"favorite": True}},
            targets=[self.target(first), self.target(second)],
        )
        self.library.metadata(
            first["record_id"], first["revision"], {"people": ["Ellen"]}, [], "alice"
        )
        result = self.workspace.execute_plan("alice", plan["id"], plan["revision"])
        self.assertEqual(
            (result["succeeded"], result["conflicts"], result["failed"]), (1, 1, 0)
        )
        current = self.library.get(first["record_id"])["resolved"]
        self.assertEqual(current["people"], ["Ellen"])
        self.assertFalse(current.get("favorite", False))

    def test_invalid_operation_rejected_before_any_changes(self):
        photo = self.photo()
        for operation in (
            {"action": []},
            {"action": {}},
            {"action": "metadata", "set": {"favorite": "true"}},
            {"action": "metadata", "set": {"people": ["A"]}, "reset": ["people"]},
            {"action": "metadata", "set": {"capture_time": "not-a-date"}},
            {
                "action": "metadata",
                "add": {"people": ["A"]},
                "remove": {"people": ["A"]},
            },
            {"action": "move", "folder_id": "unknown"},
        ):
            with self.assertRaises(ValueError):
                self.workspace.create_plan(
                    "alice", operation, targets=[self.target(photo)]
                )
        self.assertEqual(
            self.library.get(photo["record_id"])["revision"], photo["revision"]
        )

    def test_move_conflicts_if_destination_was_renamed_after_preview(self):
        photo = self.photo()
        folder = self.library.create_folder(None, "Before", "alice")
        plan = self.workspace.create_plan(
            "alice",
            {"action": "move", "folder_id": folder["id"]},
            targets=[self.target(photo)],
        )
        self.assertEqual(plan["preview"][0]["after"]["folder"], "folders/Before")
        self.library.rename_folder(
            folder["id"], folder["revision"], "After", None, "alice"
        )
        result = self.workspace.execute_plan("alice", plan["id"], plan["revision"])
        self.assertEqual((result["succeeded"], result["conflicts"]), (0, 1))
        self.assertEqual(
            self.library.get(photo["record_id"])["file"]["relative_path"],
            photo["file"]["relative_path"],
        )

    def test_move_revalidates_destination_inside_the_move_lock(self):
        from unittest.mock import patch

        photo = self.photo()
        folder = self.library.create_folder(None, "Before", "alice")
        plan = self.workspace.create_plan(
            "alice",
            {"action": "move", "folder_id": folder["id"]},
            targets=[self.target(photo)],
        )
        original_move = self.library.move

        def concurrent_change(*args, **kwargs):
            # A destination check in Workspace followed by a separate move lock
            # would miss this change. Library.move must check its own snapshot.
            self.library.rename_folder(
                folder["id"], folder["revision"], "After", None, "alice"
            )
            return original_move(*args, **kwargs)

        with patch.object(self.library, "move", side_effect=concurrent_change):
            result = self.workspace.execute_plan("alice", plan["id"], plan["revision"])
        self.assertEqual((result["succeeded"], result["conflicts"]), (0, 1))

    def test_move_succeeds_to_the_unchanged_reviewed_destination(self):
        photo = self.photo()
        folder = self.library.create_folder(None, "Family", "alice")
        plan = self.workspace.create_plan(
            "alice",
            {"action": "move", "folder_id": folder["id"]},
            targets=[self.target(photo)],
        )
        result = self.workspace.execute_plan("alice", plan["id"], plan["revision"])
        self.assertEqual(result["succeeded"], 1)
        path = self.library.get(photo["record_id"])["file"]["relative_path"]
        self.assertEqual(str(Path(path).parent), plan["preview"][0]["after"]["folder"])
        self.assertEqual(self.library.path(path).read_bytes(), b"abc")

    def test_clear_and_reset_have_different_preview(self):
        photo = self.photo(people=["Viktor"])
        photo.pop("revision")
        document = {
            "kind": "takeout",
            "relative_path": "inbox/photo.jpg.json",
            "sha256": "a" * 64,
            "document": {"people": [{"name": "Ellen"}], "unknown": "preserved"},
        }
        photo["sources"][0]["documents"].append(document)
        sidecar = self.library.path(photo["file"]["relative_path"] + ".photo.json")
        atomic(sidecar, photo)
        self.library.put_index(photo, sidecar)
        photo = self.library.get(photo["record_id"])
        clear = self.workspace.create_plan(
            "alice",
            {"action": "metadata", "set": {"people": []}},
            targets=[self.target(photo)],
        )
        reset = self.workspace.create_plan(
            "alice",
            {"action": "metadata", "reset": ["people"]},
            targets=[self.target(photo)],
        )
        self.assertEqual(clear["preview"][0]["after"]["people"], [])
        self.assertEqual(reset["preview"][0]["after"]["people"], ["Ellen"])
        self.assertEqual(reset["operation"]["reset"], ["people"])
        self.assertEqual(
            self.library.get(photo["record_id"])["overrides"]["people"], ["Viktor"]
        )
        self.workspace.execute_plan("alice", reset["id"], reset["revision"])
        current = self.library.get(photo["record_id"])
        self.assertEqual(current["resolved"]["people"], ["Ellen"])
        self.assertEqual(current["sources"][0]["documents"][0], document)

    def test_permissions_are_rechecked_before_each_item(self):
        first = self.photo("first.jpg")
        second = self.photo("second.jpg")
        plan = self.workspace.create_plan(
            "alice",
            {"action": "metadata", "set": {"favorite": True}},
            targets=[self.target(first), self.target(second)],
        )
        allowed = iter([True, False])
        result = self.workspace.execute_plan(
            "alice", plan["id"], plan["revision"], authorize=lambda: next(allowed)
        )
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["failed"], 1)

    def test_batch_trash_and_restore_keep_original_bytes(self):
        photo = self.photo()
        plan = self.workspace.create_plan(
            "alice", {"action": "trash"}, targets=[self.target(photo)]
        )
        self.workspace.execute_plan("alice", plan["id"], plan["revision"])
        trashed = self.library.get(photo["record_id"])
        plan = self.workspace.create_plan(
            "alice", {"action": "restore"}, targets=[self.target(trashed)]
        )
        self.workspace.execute_plan("alice", plan["id"], plan["revision"])
        restored = self.library.get(photo["record_id"])
        self.assertEqual(
            self.library.path(restored["file"]["relative_path"]).read_bytes(), b"abc"
        )

    def test_concurrent_execution_claims_plan_once(self):
        from concurrent.futures import ThreadPoolExecutor

        photo = self.photo()
        plan = self.workspace.create_plan(
            "alice",
            {"action": "metadata", "set": {"favorite": True}},
            targets=[self.target(photo)],
        )

        def execute():
            try:
                return self.workspace.execute_plan(
                    "alice", plan["id"], plan["revision"]
                )["succeeded"]
            except Conflict:
                return "conflict"

        with ThreadPoolExecutor(2) as pool:
            outcomes = list(pool.map(lambda _: execute(), range(2)))
        self.assertCountEqual(outcomes, [1, "conflict"])
        events = self.library.get(photo["record_id"])["history"]
        self.assertEqual(sum(event["type"] == "metadata_edited" for event in events), 1)

    def test_plan_and_frozen_export_targets_are_private(self):
        photo = self.photo()
        selection = self.workspace.create_selection(
            "alice", targets=[self.target(photo)]
        )
        self.assertEqual(
            self.workspace.selection_targets("alice", selection["id"]),
            [self.target(photo)],
        )
        with self.assertRaises(KeyError):
            self.workspace.selection_targets("bob", selection["id"])
        plan = self.workspace.create_plan(
            "alice", {"action": "trash"}, selection_id=selection["id"]
        )
        with self.assertRaises(KeyError):
            self.workspace.execute_plan("bob", plan["id"], plan["revision"])
        self.assertEqual(self.workspace.get_plan("alice", plan["id"])["state"], "ready")
