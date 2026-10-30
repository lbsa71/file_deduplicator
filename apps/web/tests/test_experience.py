"""HTTP contracts for visual queries, saved views, and reviewed batch work."""

import json
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from photoflow.adapters import NoEmbeddedMetadata, RandomIds, SystemClock
from photoflow.runner import Config, Runner
from photoflow_web.app import create_app


class ExperienceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "library"
        (self.root / ".photoflow").mkdir(parents=True)
        (self.root / ".photoflow/library.json").write_text(
            '{"schema_version":2,"library_id":"test"}'
        )
        (self.root / "inbox").mkdir()
        for i in range(3):
            (self.root / "inbox" / f"{i}.jpg").write_bytes(f"photo-{i}".encode())
        self.role = 2
        self.app = create_app(
            self.root,
            Path(self.temp.name) / "state",
            auth=lambda _: {"ok": True, "uid": 123},
            role_resolver=lambda _: self.role,
        )
        lib = self.app.state.library
        Runner(
            lib.fs,
            SystemClock(),
            RandomIds(),
            NoEmbeddedMetadata(),
            Config(settle_seconds=0),
        ).run()
        lib.rebuild()
        self.items = lib.listing()["items"]
        for i, item in enumerate(self.items):
            lib.metadata(
                item["id"],
                item["revision"],
                {
                    "people": ["Ellen", "Viktor"] if i == 0 else ["Ellen"],
                    "capture_time": f"20{9+i:02d}-06-15T12:00:00Z",
                },
                [],
                "fixture",
            )
        self.client = TestClient(self.app, base_url="https://testserver")
        self.client.__enter__()
        self.login("stefan")

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def login(self, name):
        response = self.client.post(
            "/api/v1/auth/login",
            json={"username": name, "password": "test"},
            headers={"Origin": "https://testserver"},
        )
        self.headers = {
            "Origin": "https://testserver",
            "X-CSRF-Token": response.json()["csrf"],
        }

    def post(self, path, body, **headers):
        return self.client.post(
            "/api/v1" + path, json=body, headers={**self.headers, **headers}
        )

    def test_filters_facets_and_validation(self):
        filters = {"people": ["Ellen", "Viktor"], "people_mode": "all"}
        response = self.client.get(
            "/api/v1/photos", params={"filters": json.dumps(filters)}
        )
        self.assertEqual(response.json()["total"], 1)
        facets = self.client.get(
            "/api/v1/facets", params={"filters": json.dumps(filters)}
        )
        self.assertEqual(facets.status_code, 200)
        self.assertEqual(facets.json()["total"], 1)
        self.assertEqual(
            self.client.get(
                "/api/v1/photos", params={"filters": '{"from":"2020-99-01"}'}
            ).status_code,
            422,
        )

    def test_saved_view_owner_and_revision(self):
        response = self.post(
            "/views",
            {
                "name": "Together",
                "query": {
                    "filters": {"people": ["Viktor", "Ellen"], "people_mode": "all"}
                },
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        view = response.json()
        self.assertEqual(len(self.client.get("/api/v1/views").json()["items"]), 1)
        stale = self.client.patch(
            "/api/v1/views/" + view["id"],
            json={"name": "Changed", "query": view["query"]},
            headers={**self.headers, "If-Match": '"stale"'},
        )
        self.assertEqual(stale.status_code, 409)
        renamed = self.client.patch(
            "/api/v1/views/" + view["id"],
            json={"name": "Renamed"},
            headers={**self.headers, "If-Match": view["revision"]},
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["query"], view["query"])
        view = renamed.json()
        self.login("other")
        self.assertEqual(self.client.get("/api/v1/views").json()["items"], [])
        self.assertEqual(
            self.client.delete(
                "/api/v1/views/" + view["id"],
                headers={**self.headers, "If-Match": view["revision"]},
            ).status_code,
            404,
        )

    def test_reviewed_batch_reports_and_rejects_replay(self):
        selection = self.post(
            "/selections", {"query": {"filters": {"people": ["Ellen"]}}}
        )
        self.assertEqual(selection.status_code, 200, selection.text)
        self.assertEqual(selection.json()["count"], 3)
        plan = self.post(
            "/batch-plans",
            {
                "selection_id": selection.json()["id"],
                "operation": {"action": "metadata", "add": {"tags": ["Reviewed"]}},
            },
        )
        self.assertEqual(plan.status_code, 200, plan.text)
        plan = plan.json()
        response = self.post(
            "/batch-plans/" + plan["id"] + "/execute",
            {},
            **{"If-Match": plan["revision"]},
        )
        self.assertEqual(response.status_code, 202, response.text)
        for _ in range(200):
            job = self.client.get("/api/v1/jobs/" + response.json()["job_id"]).json()
            if job["state"] in ("failed", "succeeded"):
                break
            time.sleep(0.01)
        self.assertEqual(job["state"], "succeeded", job)
        self.assertEqual(job["result"]["succeeded"], 3)
        for item in self.app.state.library.listing()["items"]:
            self.assertIn("Reviewed", item["metadata"]["tags"])
            self.assertIn("Ellen", item["metadata"]["people"])
        replay = self.post(
            "/batch-plans/" + plan["id"] + "/execute",
            {},
            **{"If-Match": plan["revision"]},
        )
        self.assertEqual(replay.status_code, 409)

    def test_reader_can_save_views_but_cannot_plan_edits(self):
        self.role = 1
        self.assertEqual(
            self.post("/views", {"name": "My view", "query": {}}).status_code, 200
        )
        self.assertEqual(
            self.post(
                "/batch-plans",
                {
                    "query": {},
                    "operation": {"action": "metadata", "set": {"favorite": True}},
                },
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post("/api/v1/selections", json={"query": {}}).status_code, 403
        )


if __name__ == "__main__":
    unittest.main()
