import { webcrypto } from "node:crypto";
globalThis.crypto ??= webcrypto;
import test from "node:test";
import assert from "node:assert/strict";
import { RetentionTrash } from "../src/retention-trash.js";
import { BrowserJournal } from "../src/browser-journal.js";
import { envelope, ACCOUNT } from "./fixtures.js";
function setup() {
  const data = {},
    calls = [];
  const journal = new BrowserJournal({
    get: async (k) => structuredClone(k === null ? data : { [k]: data[k] }),
    set: async (v) => Object.assign(data, structuredClone(v)),
    remove: async (k) => {
      delete data[k];
    },
  });
  const photo = {
    namespace: "library-media",
    mediaKey: "media-a",
    dedupKey: "dedup-a",
    filename: "real.jpg",
    size: 10,
    favorite: false,
    albums: [],
    companion: null,
  };
  const reader = {
    observation: async () => structuredClone(photo),
    page: async () => ({ items: [photo], next: "more", complete: false }),
  };
  const write = async (r) => {
    calls.push(r);
    return { account: ACCOUNT, status: 200, body: envelope(r.rpc, [true]) };
  };
  const job = {
    id: "sweep-a",
    operation: "trash",
    input: { photoUrl: "https://photos.google.com/photo/media-a" },
    retentionScope: {
      purpose: "owner-authorized-takeout-retention",
      account: ACCOUNT,
      jobId: "sweep-a",
      operation: "trash",
      photoKey: "media-a",
      albumId: null,
      dedupKey: "dedup-a",
      localSha256: "a".repeat(64),
      manifestId: "b".repeat(32),
      manifestSha256: "c".repeat(64),
      expiresAt: 2000,
    },
  };
  return {
    photo,
    reader,
    journal,
    calls,
    job,
    executor: new RetentionTrash({
      account: ACCOUNT,
      reader,
      write,
      journal,
      now: () => 1000,
    }),
  };
}
test("production Trash journals exact scope and verifies positive membership without enumerating all Trash", async () => {
  const x = setup();
  assert.equal((await x.executor.execute(x.job)).outcome, "verified");
  assert.deepEqual(x.calls[0].data, [null, 1, ["dedup-a"], 3]);
  assert.equal(x.calls[0].testScope, undefined);
  assert.equal((await x.journal.get("sweep-a")).state, "verified");
  await x.executor.execute(x.job);
  assert.equal(x.calls.length, 1);
});
for (const protection of [
  { favorite: true },
  { albums: [{ albumId: "album-a" }] },
  { companion: true },
])
  test(
    "changed protection retains photo " + JSON.stringify(protection),
    async () => {
      const x = setup();
      Object.assign(x.photo, protection);
      assert.equal((await x.executor.execute(x.job)).outcome, "unchanged");
      assert.equal(x.calls.length, 0);
    },
  );
for (const invalid of [
  { favorite: null },
  { albums: null },
  { dedupKey: "wrong" },
])
  test(
    "unknown or changed preflight stops " + JSON.stringify(invalid),
    async () => {
      const x = setup();
      Object.assign(x.photo, invalid);
      await assert.rejects(x.executor.execute(x.job));
      assert.equal(x.calls.length, 0);
    },
  );
test("scope mismatch cannot send", async () => {
  const x = setup();
  x.job.retentionScope.photoKey = "wrong";
  await assert.rejects(x.executor.execute(x.job));
  assert.equal(x.calls.length, 0);
});
test("lost postcondition is unknown and cannot retry", async () => {
  const x = setup();
  x.reader.page = async () => ({ items: [], next: null, complete: true });
  await assert.rejects(
    x.executor.execute(x.job),
    (e) => e.code === "UNKNOWN_OUTCOME",
  );
  assert.equal((await x.journal.get("sweep-a")).state, "unknown");
  await assert.rejects(x.executor.execute(x.job));
  assert.equal(x.calls.length, 1);
});
test("Trash identity collision is unknown", async () => {
  const x = setup();
  x.reader.page = async () => ({
    items: [{ ...x.photo, dedupKey: "wrong" }],
    next: null,
    complete: true,
  });
  await assert.rejects(x.executor.execute(x.job));
  assert.equal((await x.journal.get("sweep-a")).state, "unknown");
});

test("pending journal caches verified history and retains newly unknown intents", async () => {
  const x = setup();
  let scans = 0;
  const get = x.journal.storage.get;
  x.journal.storage.get = async (k) => {
    if (k === null) scans++;
    return get(k);
  };
  await x.executor.execute(x.job);
  await x.journal.pending(ACCOUNT);
  await x.journal.pending(ACCOUNT);
  assert.equal(scans, 1);
  const record = await x.journal.get(x.job.id);
  record.state = "unknown";
  await x.journal.put(record);
  assert.equal((await x.journal.pending(ACCOUNT)).length, 1);
  const restarted = new BrowserJournal(x.journal.storage);
  assert.equal((await restarted.pending(ACCOUNT)).length, 1);
});

test("production unknown write reconciles through exact positive Trash proof without replay", async () => {
  const x = setup();
  x.reader.page = async () => ({ items: [], next: null, complete: true });
  await assert.rejects(x.executor.execute(x.job));
  x.reader.page = async () => ({
    items: [x.photo],
    next: "more",
    complete: false,
  });
  const result = await x.executor.reconcile(x.job.id);
  assert.equal(result.originalJobId, x.job.id);
  assert.equal(x.calls.length, 1);
  assert.equal((await x.journal.get(x.job.id)).state, "verified");
});

test("a fresh reviewed pass reevaluates a present photo after lost acknowledgement", async () => {
  const x = setup();
  x.reader.page = async () => ({ items: [], next: null, complete: true });
  await assert.rejects(x.executor.execute(x.job));
  const next = structuredClone(x.job);
  next.id = next.retentionScope.jobId = "next-pass";
  next.retentionScope.manifestId = "d".repeat(32);
  x.reader.page = async () => ({
    items: [x.photo],
    next: null,
    complete: true,
  });
  x.photo.favorite = true;
  assert.equal((await x.executor.execute(next)).outcome, "unchanged");
  assert.equal(x.calls.length, 1);
  assert.equal((await x.journal.get(x.job.id)).state, "unknown");
});

test("a restarted retention writer tolerates its abandoned lock but preserves audit history", async () => {
  const x = setup();
  await x.executor.execute(x.job);
  const old = await x.journal.get(x.job.id);
  await x.journal.put({ ...old, state: "unknown" });
  await x.journal.storage.set({
    ["pilot-lock:" + ACCOUNT]: { account: ACCOUNT },
  });
  const next = structuredClone(x.job);
  next.id = next.retentionScope.jobId = "fresh-pass";
  next.retentionScope.manifestId = "e".repeat(32);
  assert.equal((await x.executor.execute(next)).outcome, "verified");
  assert.equal((await x.journal.get(old.plan.id)).state, "unknown");
});

test("fresh passes cannot bypass a live writer or an unresolved pilot", async () => {
  const x = setup();
  const release = await x.journal.lock(ACCOUNT, { retention: true });
  await assert.rejects(x.executor.execute(x.job), (e) => e.code === "BUSY");
  await release();
  await x.executor.execute(x.job);
  const record = await x.journal.get(x.job.id);
  record.plan.targetPolicy = "selected";
  record.state = "unknown";
  await x.journal.put(record);
  const next = structuredClone(x.job);
  next.id = next.retentionScope.jobId = "next-retention-pass";
  next.retentionScope.manifestId = "e".repeat(32);
  await assert.rejects(
    x.executor.execute(next),
    (e) => e.code === "UNRESOLVED",
  );
  assert.equal(x.calls.length, 1);
});
