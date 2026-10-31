import test from "node:test";
import assert from "node:assert/strict";
import { DesktopWorker } from "../src/worker.js";
function setup(run) {
  const sent = [];
  const handlers = {};
  const socket = {
    readyState: 1,
    addEventListener: (k, fn) => (handlers[k] = fn),
    send: (s) => sent.push(JSON.parse(s)),
    close: () => {
      socket.closed = true;
    },
  };
  let ticks;
  const worker = new DesktopWorker({
    account: "account-a",
    token: "secret",
    origin: "https://photos.lbsa71.net",
    connect: () => socket,
    runInventory:
      run ??
      (async () => ({
        photos: 10,
        favorites: 2,
        albums: 1,
        complete: true,
        retentionReady: false,
      })),
    getAccount: async () => "account-a",
    saveReceipt: async () => {},
    setInterval: (fn) => {
      ticks = fn;
      return 1;
    },
    clearInterval: () => {},
  });
  return { worker, socket, sent, handlers, tick: () => ticks() };
}
const job = {
  type: "job",
  id: "job-a",
  lease: "lease-a",
  operation: "inventory-counts",
  version: 1,
  input: {},
  account: "account-a",
};
test("worker authenticates on WSS, executes only bounded read operation and returns a receipt", async () => {
  const h = setup();
  h.worker.start();
  h.handlers.open();
  await h.worker.receive({
    type: "welcome",
    account: "account-a",
    protocol: 2,
  });
  await h.worker.receive(job);
  assert.deepEqual(
    h.sent.filter((m) => m.type !== "progress").map((m) => m.type),
    ["auth", "heartbeat", "result"],
  );
  assert.equal(h.sent.find((m) => m.type === "result").result.photos, 10);
  assert.equal(
    h.sent.find((m) => m.type === "result").result.retentionReady,
    false,
  );
  await h.tick();
  assert.equal(h.sent.at(-1).type, "heartbeat");
  h.worker.stop();
  assert.equal(h.socket.closed, true);
});
test("unknown operations, changed accounts and jobs before authentication never invoke Google", async () => {
  for (const patch of [{ operation: "trash" }, { account: "other" }]) {
    let calls = 0;
    const h = setup(async () => {
      calls++;
    });
    h.worker.start();
    await h.worker.receive({
      type: "welcome",
      account: "account-a",
      protocol: 2,
    });
    await assert.rejects(h.worker.receive({ ...job, ...patch }));
    assert.equal(calls, 0);
  }
  const h = setup();
  h.worker.start();
  await assert.rejects(h.worker.receive(job));
});
test("duplicate delivery cannot run a read twice and failed reads emit only controlled codes", async () => {
  let calls = 0;
  const h = setup(async () => {
    calls++;
    throw new Error("PRIVATE_TOKEN");
  });
  h.worker.start();
  await h.worker.receive({
    type: "welcome",
    account: "account-a",
    protocol: 2,
  });
  await h.worker.receive(job);
  await h.worker.receive(job);
  assert.equal(calls, 1);
  assert.equal(h.sent.find((m) => m.type === "result").error, "PROTOCOL");
  assert.ok(!JSON.stringify(h.sent).includes("PRIVATE_TOKEN"));
});

test("a reconnected worker reports readiness from the matching session without a photo job", async () => {
  let reads = 0;
  const h = setup(async () => {
    reads++;
  });
  h.worker.start();
  await h.worker.receive({
    type: "welcome",
    account: "account-a",
    protocol: 2,
  });
  assert.deepEqual(h.sent.at(-1), {
    type: "heartbeat",
    account: "account-a",
    ready: true,
  });
  assert.equal(reads, 0);
  h.worker.getAccount = async () => "other";
  await h.worker.heartbeat();
  assert.equal(h.sent.at(-1).ready, false);
  h.worker.getAccount = async () => "account-a";
  await h.worker.heartbeat();
  assert.equal(h.sent.at(-1).ready, true);
  assert.equal(reads, 0);
});

test("matching identity alone does not clear a failed job", async () => {
  const h = setup(async () => {
    throw new Error("read failed");
  });
  h.worker.start();
  await h.worker.receive({
    type: "welcome",
    account: "account-a",
    protocol: 2,
  });
  await h.worker.receive(job);
  await h.worker.heartbeat();
  assert.equal(h.sent.at(-1).ready, false);
});
