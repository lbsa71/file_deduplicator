import test from "node:test";
import assert from "node:assert/strict";
import {
  workerOrigin,
  DEFAULT_WORKER_ORIGIN,
  readWorkerOrigin,
  saveWorkerOrigin,
} from "../src/worker-origin.js";

test("the endpoint preference survives failed pairing and does not change paired credentials", async () => {
  const data = {
    googleWorker: { origin: DEFAULT_WORKER_ORIGIN, token: "private" },
  };
  const storage = {
    get: async (key) => ({ [key]: data[key] }),
    set: async (value) => Object.assign(data, value),
  };
  assert.equal(
    await readWorkerOrigin(storage, DEFAULT_WORKER_ORIGIN),
    DEFAULT_WORKER_ORIGIN,
  );
  await saveWorkerOrigin(storage, "https://localhost:8099/");
  assert.equal(
    await readWorkerOrigin(storage, DEFAULT_WORKER_ORIGIN),
    "https://localhost:8099",
  );
  assert.deepEqual(data.googleWorker, {
    origin: DEFAULT_WORKER_ORIGIN,
    token: "private",
  });
  await assert.rejects(saveWorkerOrigin(storage, "http://localhost:8099"));
  assert.equal(await readWorkerOrigin(storage), "https://localhost:8099");
});

test("worker endpoints accept HTTPS origins, including loopback, without URL secrets or paths", () => {
  assert.equal(workerOrigin(undefined), DEFAULT_WORKER_ORIGIN);
  assert.equal(
    workerOrigin("https://localhost:8099/"),
    "https://localhost:8099",
  );
  assert.equal(
    workerOrigin("https://photos.example.org"),
    "https://photos.example.org",
  );
  for (const value of [
    "",
    "http://localhost:8099",
    "https://user:secret@example.org",
    "https://example.org/api",
    "https://example.org/?token=secret",
    "https://example.org/#x",
    "garbage",
    null,
  ]) {
    assert.throws(() => workerOrigin(value));
  }
});
