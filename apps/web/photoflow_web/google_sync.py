"""User-facing sync workflow over the existing durable preparation/commit engine."""

import threading
from .core import Conflict
from .jobs import Deferred

ACTIVE = {"queued", "running"}


class GoogleSync:
    def __init__(self, reconciliation):
        self.r = reconciliation
        self.lock = threading.RLock()

    def allowed(self, owner):
        if not self.r.authorize(owner):
            raise ValueError("Administrator authority required")

    def runs(self, owner):
        before = None
        while True:
            page = self.r.jobs.listing(owner, before=before)
            yield from (job for job in page["items"] if job["owner"] == owner)
            before = page["next_cursor"]
            if before is None:
                break

    def active_pass(self, owner, account):
        for job in self.runs(owner):
            if (
                job["action"] == "google.commit"
                and job["state"] in ACTIVE
                and job["params"].get("account") == account
            ):
                if self.r.manifest(owner, job["params"]["manifestId"])[
                    "capabilities"
                ].get("productionRetention"):
                    return job
        return None

    def root(self, owner, account):
        for job in self.runs(owner):
            if job["params"].get("account") != account:
                continue
            if job["action"] == "google.sync-prepare":
                return job, None
            if job["action"] == "google.commit":
                manifest = self.r.manifest(owner, job["params"]["manifestId"])
                if manifest["capabilities"].get("productionRetention"):
                    return job, manifest
        return None, None

    def status(self, owner):
        connection = self.r.remote.status(owner)
        account = connection["account"]
        value = {
            "state": "idle" if account else "unpaired",
            "enabled": connection.get("pilotTargetPolicy") == "selected",
            "progress": None,
            "totals": None,
            "review": None,
            "jobId": None,
            "paused": False,
        }
        if not account:
            return value
        job, manifest = self.root(owner, account)
        if job:
            value["jobId"] = job["id"]
            if job["action"] == "google.commit":
                value["paused"] = self.r.execution_paused(job)
                counts = self.r.remote.sweep_counts(owner, job["id"])
                value["progress"] = {
                    "processed": counts["processed"],
                    "total": len(manifest["operations"]),
                }
                value["totals"] = {
                    "trashed": counts["trashed"],
                    "retained": manifest["counts"]["remote"]
                    - len(manifest["operations"])
                    + counts["kept"],
                }
                value["state"] = (
                    "running"
                    if job["state"] in ACTIVE
                    else "complete"
                    if job["state"] == "succeeded"
                    else "paused"
                )
                if value["state"] == "running" and value["paused"]:
                    value["state"] = "pausing"
                if value["state"] == "paused" and self.r.now() > manifest["expiresAt"]:
                    value["state"] = "expired"
            elif job["state"] in ACTIVE:
                value["state"] = "preparing"
                for name, phase in [
                    ("sync:local", "local"),
                    ("sync:inventory", "inventory"),
                ]:
                    step = self.r.jobs.step(job["id"], name)
                    if step and step["state"] == "done":
                        child = self.r.jobs.get(step["result"]["id"])
                        value["phase"] = phase
                        value["progress"] = child.get("progress")
                        break
            elif job["state"] == "succeeded":
                manifest = self.r.manifest(owner, job["result"]["manifestId"])
                value["state"] = (
                    "review" if self.r.now() <= manifest["expiresAt"] else "expired"
                )
                if value["state"] == "review":
                    value["review"] = {
                        "manifestId": manifest["id"],
                        "sha256": manifest["sha256"],
                        "expiresAt": manifest["expiresAt"],
                        "trash": len(manifest["operations"]),
                        "keep": manifest["counts"]["remote"]
                        - len(manifest["operations"]),
                        "remote": manifest["counts"]["remote"],
                    }
            else:
                value["state"] = (
                    "expired"
                    if self.r.now() > job["created"] + 86400
                    else "preparation_failed"
                )
        return value

    def prepare(self, owner):
        self.allowed(owner)
        with self.lock:
            account = self.r.account(owner)
            if self.active_pass(owner, account):
                raise Conflict("A sync is already running")
            job, _ = self.root(owner, account)
            if job and job["state"] in ACTIVE:
                if job["action"] == "google.sync-prepare":
                    return job
                raise Conflict("A sync is already running")
            if self.r.remote.status(owner).get("pilotTargetPolicy") != "selected":
                raise ValueError(
                    "This Google account is not enabled for retention sync"
                )
            return self.r.runner.enqueue(
                owner, "google.sync-prepare", {"account": account}, private=True
            )

    def execute_preparation(self, job, context):
        owner = job["owner"]
        if self.r.account(owner) != job["params"]["account"]:
            raise Conflict("Google account changed; prepare a new sync")
        if self.r.now() > job["created"] + 86400:
            raise Conflict("Preparation expired; prepare a new sync")

        def wait(child, phase):
            current = self.r.jobs.get(child["id"])
            context.checkpoint(stage=phase)
            if current["state"] in ACTIVE:
                raise Deferred("waiting_for_preparation", retry_after=1)
            if current["state"] != "succeeded":
                raise ValueError("Sync preparation stopped; prepare a fresh review")
            return current["result"]

        inventory = context.step(
            "sync:inventory",
            lambda: self.r.runner.enqueue(
                owner,
                "google.prepare",
                {"account": job["params"]["account"], "options": self.r.options({})},
                key="sync-inventory:" + job["id"],
                private=True,
            ),
            replay_safe=True,
        )
        source = wait(inventory, "inventory")
        local = context.step(
            "sync:local",
            lambda: self.r.prepare_takeout(owner, source["manifestId"]),
            replay_safe=True,
        )
        return wait(local, "local")
