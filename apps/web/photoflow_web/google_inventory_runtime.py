"""Durable background orchestration and private API for Google inventories."""

import asyncio, json
from fastapi import HTTPException, Request
from photoflow.ports import BusyError
from .core import Conflict, load
from .google_contracts import check
from .google_inventory import GoogleInventories
from .jobs import Cancelled, Deferred, JobCoordinator, JobStore


class InventoryRuntime:
    def __init__(self, library, workers, authorize):
        self.library, self.workers = library, workers
        self.inventories = GoogleInventories(library, workers)
        self.store = JobStore(library.state / "google-inventory-operations", library.id)
        self.coordinator = JobCoordinator(self.store, self.execute,
                                          lambda job: authorize(job["owner"]), library.available)
        self.notify = lambda: None

    def execute(self, job, context):
        check(job["action"] == "google-inventory")
        value = job["params"]
        context.checkpoint("google-inventory")
        try:
            data = self.inventories.advance(job["owner"], value["account"], value["inventoryId"])
        except BusyError:
            raise Deferred("waiting_for_library") from None
        except OSError:
            if not self.library.available():
                raise Deferred("waiting_for_storage") from None
            raise
        self.notify()
        context.checkpoint("google-inventory", data["pages"], None)
        if data["state"] == "complete":
            return data
        if data["state"] == "cancelled":
            raise Cancelled()
        if data["state"] == "incomplete":
            raise ValueError("Inventory stopped: " + data["error"])
        raise Deferred("waiting_for_google_worker")

    def register(self, owner, account, ident):
        return self.coordinator.enqueue(owner, "google-inventory", {"account": account, "inventoryId": ident},
                                        key="google-inventory:" + ident, private=True)

    def start(self, loop, wake):
        self.notify = lambda: loop.call_soon_threadsafe(wake)
        # Portable manifests recover run intent even if command storage was lost.
        if self.library.available():
            for path in self.inventories.directory.glob("*/manifest.json"):
                data = load(self.inventories.path(path.parent.name))
                if data["state"] == "running":
                    self.inventories.read(data["owner"], data["account"], data["id"])
                    self.register(data["owner"], data["account"], data["id"])
        self.coordinator.start()

    def close(self):
        self.coordinator.close()
        self.notify = lambda: None

    def create(self, owner, account):
        result = self.inventories.create(owner, account)
        self.register(owner, account, result["id"])
        return result

    def status(self, owner, account, ident):
        result = self.inventories.get(owner, account, ident)
        with self.store.db() as db:
            row = db.execute("SELECT data FROM commands WHERE owner=? AND request_key=?", (owner, "google-inventory:" + ident)).fetchone()
        command = json.loads(row[0]) if row else None
        result["background"] = {key: command.get(key) for key in ("id", "state", "waiting_reason", "error_code", "error", "progress")} if command else None
        return result

    def resume(self, owner, account, ident):
        data = self.inventories.get(owner, account, ident)
        if data["state"] != "running":
            raise Conflict("Terminal inventories require a new full traversal")
        command = self.register(owner, account, ident)
        if command["state"] in ("failed", "partial", "cancelled"):
            self.store.retry(command["id"])
            self.coordinator.wake()
        return self.status(owner, account, ident)

    def cancel(self, owner, account, ident):
        result = self.inventories.cancel(owner, account, ident)
        with self.store.db() as db:
            row = db.execute("SELECT id FROM commands WHERE owner=? AND request_key=?", (owner, "google-inventory:" + ident)).fetchone()
        if row:
            self.store.cancel(row[0])
        return result


def install_inventory_routes(app, library, workers, session, authorize, wake):
    runtime = InventoryRuntime(library, workers, authorize)
    app.state.google_inventory_runtime = runtime
    app.state.google_inventories = runtime.inventories
    app.state.google_inventory_wake = wake

    def paired(req, account, write=False):
        owner = session(req, 3, write)["username"]
        current = workers.status(owner)["account"]
        if not current or current != account:
            raise HTTPException(409, "Refresh the paired Google account before inventory work")
        return owner

    @app.post("/api/v1/google/inventories")
    async def create(req: Request, body: dict):
        session(req, 3, True)
        check(set(body) == {"account"})
        owner = paired(req, body["account"], True)
        result = await asyncio.to_thread(runtime.create, owner, body["account"])
        paired(req, body["account"], True)
        return result

    @app.get("/api/v1/google/inventories")
    async def listing(req: Request, account: str):
        owner = paired(req, account)
        result = await asyncio.to_thread(runtime.inventories.list, owner, account)
        paired(req, account)
        return result

    @app.get("/api/v1/google/inventories/{ident}")
    async def detail(ident: str, req: Request, account: str):
        owner = paired(req, account)
        result = await asyncio.to_thread(runtime.status, owner, account, ident)
        paired(req, account)
        return result

    @app.post("/api/v1/google/inventories/{ident}/cancel")
    async def cancel(ident: str, req: Request, body: dict):
        session(req, 3, True)
        check(set(body) == {"account"})
        owner = paired(req, body["account"], True)
        return await asyncio.to_thread(runtime.cancel, owner, body["account"], ident)

    @app.post("/api/v1/google/inventories/{ident}/resume")
    async def resume(ident: str, req: Request, body: dict):
        session(req, 3, True)
        check(set(body) == {"account"})
        owner = paired(req, body["account"], True)
        return await asyncio.to_thread(runtime.resume, owner, body["account"], ident)
