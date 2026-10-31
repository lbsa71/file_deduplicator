import { webcrypto } from "node:crypto";
globalThis.crypto ??= webcrypto;
import test from "node:test";
import assert from "node:assert/strict";
import { ToolkitPilot } from "../src/toolkit-pilot.js";
import { BrowserJournal } from "../src/browser-journal.js";
import { envelope, ACCOUNT } from "./fixtures.js";
const photoUrl = "https://photos.google.com/photo/media-a";
function setup() {
  let photo = {
    namespace: "library-media",
    mediaKey: "media-a",
    dedupKey: "dedup-a",
    filename: "photoflow-test-fixture.jpg",
    size: 100,
    favorite: false,
    archived: false,
    description: "",
    timestampMs: 1000,
    timezoneMs: 0,
    manualLocationE7: null,
  };
  let trashed = false;
  let member = null;
  const calls = [];
  const records = {};
  const storage = {
    get: async (k) =>
      structuredClone(k === null ? records : { [k]: records[k] }),
    set: async (data) => Object.assign(records, structuredClone(data)),
    remove: async (k) => {
      delete records[k];
    },
  };
  const journal = new BrowserJournal(storage);
  const albums = [
    { albumId: "album-a", title: "PhotoFlow test existing", shared: false },
  ];
  const reader = {
    observation: async () => structuredClone(photo),
    item: async () => structuredClone(photo),
    albums: async () => ({ items: structuredClone(albums), complete: true }),
    albumItems: async () => ({ items: member ? [member] : [], complete: true }),
    trash: async () => ({ items: trashed ? [photo] : [], complete: true }),
    favorites: async () => ({
      items: photo.favorite ? [photo] : [],
      complete: true,
    }),
  };
  const write = async (request) => {
    calls.push(request);
    const x = request.data;
    if (request.rpc === "Ftfh0") photo.favorite = x[1][0] === 1;
    if (request.rpc === "w7TP3c") photo.archived = x[0][0][1][0] === 1;
    if (request.rpc === "XwAOJf") trashed = x[1] === 1;
    if (request.rpc === "AQNOFd") photo.description = x[1];
    if (request.rpc === "DaSgWe") {
      photo.timestampMs = x[0][0][1] * 1000;
      photo.timezoneMs = x[0][0][2] * 1000;
    }
    if (request.rpc === "EtUHOe")
      photo.manualLocationE7 = x[1][0] === 1 ? null : x[1][1];
    if (request.rpc === "E1Cajb")
      member = {
        namespace: "album-item",
        mediaKey: "album-scoped-a",
        dedupKey: "dedup-a",
      };
    if (request.rpc === "ycV3Nd") {
      assert.deepEqual(x, [["album-scoped-a"]]);
      member = null;
    }
    if (request.rpc === "OXvT9d") {
      albums.push({ albumId: "new-album", title: x[0], shared: false });
      return {
        account: ACCOUNT,
        status: 200,
        body: envelope(request.rpc, [["new-album"]]),
      };
    }
    return {
      account: ACCOUNT,
      status: 200,
      body: envelope(request.rpc, [true]),
    };
  };
  const pilot = new ToolkitPilot({
    account: ACCOUNT,
    reader,
    write,
    journal,
    now: () => 1000,
  });
  const job = (operation, input, id = "test-" + operation) => ({
    id,
    operation,
    input,
    testScope: {
      testOnly: true,
      account: ACCOUNT,
      jobId: id,
      operation,
      expiresAt: 2000,
      photoKey: input.photoUrl ? "media-a" : null,
      albumId: input.albumId ?? null,
    },
  });
  return {
    pilot,
    journal,
    job,
    calls,
    reader,
    write,
    photo,
    setMember: () => {
      member = {
        namespace: "album-item",
        mediaKey: "album-scoped-a",
        dedupKey: "dedup-a",
      };
    },
    setTrashed: () => {
      trashed = true;
    },
  };
}
const cases = [
  ["favorite-set", { photoUrl, value: true }, "Ftfh0"],
  ["archive-set", { photoUrl, value: true }, "w7TP3c"],
  ["trash", { photoUrl }, "XwAOJf"],
  ["album-create", { title: "PhotoFlow test new" }, "OXvT9d"],
  ["album-add", { photoUrl, albumId: "album-a" }, "E1Cajb"],
  ["album-remove", { photoUrl, albumId: "album-a" }, "ycV3Nd"],
  [
    "description-set",
    { photoUrl, description: "Fixture description" },
    "AQNOFd",
  ],
  [
    "timestamp-set",
    { photoUrl, timestampSec: 1700000000, timezoneSec: 3600 },
    "DaSgWe",
  ],
  [
    "location-set",
    {
      photoUrl,
      centerE7: [10000000, 20000000],
      visible1E7: [9000000, 19000000],
      visible2E7: [11000000, 21000000],
      scale: 14,
      placeId: "fixture-place",
    },
    "EtUHOe",
  ],
  ["location-clear", { photoUrl }, "EtUHOe"],
];
for (const [operation, input, rpc] of cases)
  test(
    "isolated pilot " + operation + " verifies read-back and never replays",
    async () => {
      const h = setup();
      if (operation === "album-remove") h.setMember();
      if (operation === "location-clear") h.photo.manualLocationE7 = [1, 2];
      const job = h.job(operation, input);
      const result = await h.pilot.execute(job);
      assert.equal(result.verified, true);
      assert.equal(h.calls.length, 1);
      assert.equal(h.calls[0].rpc, rpc);
      assert.equal((await h.pilot.execute(job)).verified, true);
      assert.equal(h.calls.length, 1);
    },
  );
test("restore uses a journaled fixture and exact identity", async () => {
  const h = setup();
  await h.pilot.execute(h.job("trash", { photoUrl }));
  await h.pilot.execute(h.job("restore", { photoUrl }));
  assert.equal(h.calls.length, 2);
  assert.deepEqual(h.calls[1].data, [null, 3, ["dedup-a"], 2]);
});
test("missing scope, changed account, expired grant and real photo names send no writes", async () => {
  for (const change of [
    { testScope: null },
    { testScope: { testOnly: true, account: "other" } },
    { testScope: { testOnly: true, account: ACCOUNT, expiresAt: 1 } },
  ]) {
    const h = setup();
    await assert.rejects(
      h.pilot.execute({
        ...h.job("favorite-set", { photoUrl, value: true }),
        ...change,
      }),
    );
    assert.equal(h.calls.length, 0);
  }
  const h = setup();
  h.photo.filename = "family.jpg";
  await assert.rejects(h.pilot.execute(h.job("trash", { photoUrl })));
  assert.equal(h.calls.length, 0);
});
test("lost write acknowledgement is unknown and reconciliation performs only reads", async () => {
  const h = setup();
  const pilot = new ToolkitPilot({
    account: ACCOUNT,
    reader: h.reader,
    journal: h.journal,
    now: () => 1000,
    write: async (request) => {
      await h.write(request);
      throw Error("lost acknowledgement");
    },
  });
  const job = h.job("favorite-set", { photoUrl, value: true });
  await assert.rejects(pilot.execute(job), (e) => e.code === "UNKNOWN_OUTCOME");
  assert.equal((await h.journal.get(job.id)).state, "unknown");
  await assert.rejects(
    h.pilot.execute(h.job("description-set", { photoUrl, description: "x" })),
  );
  const result = await h.pilot.reconcile(job.id);
  assert.equal(result.verified, true);
  assert.equal(h.calls.length, 1);
});
test("a persisted browser lock is never stolen after restart", async () => {
  const h = setup();
  await h.journal.storage.set({
    ["pilot-lock:" + ACCOUNT]: { account: ACCOUNT },
  });
  await assert.rejects(h.journal.lock(ACCOUNT), (e) => e.code === "BUSY");
});

test("read adapters cannot mutate the frozen intended change", async () => {
  const h = setup();
  const job = h.job("favorite-set", { photoUrl, value: true });
  const original = h.reader.observation;
  h.reader.observation = async (key) => {
    job.input.value = false;
    return original(key);
  };
  await h.pilot.execute(job);
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].data[1][0], 1);
});

test("corrupt local journal records cannot disappear from pending evidence", async () => {
  const h = setup();
  await h.journal.storage.set({
    "pilot-record:broken": {
      plan: { account: ACCOUNT, id: "broken" },
      state: "sent",
    },
  });
  await assert.rejects(h.journal.pending(ACCOUNT));
});

test("browser journal survives storage key reordering without losing integrity", async () => {
  const h = setup();
  const job = h.job("favorite-set", { photoUrl, value: true });
  await h.pilot.execute(job);
  const raw = await h.journal.storage.get(null);
  const reorder = (v) =>
    Array.isArray(v)
      ? v.map(reorder)
      : v && typeof v === "object"
        ? Object.fromEntries(
            Object.keys(v)
              .sort()
              .reverse()
              .map((k) => [k, reorder(v[k])]),
          )
        : v;
  await h.journal.storage.set(reorder(raw));
  assert.equal((await h.journal.get(job.id)).state, "verified");
  assert.equal((await h.pilot.execute(job)).verified, true);
  assert.equal(h.calls.length, 1);
});

test("explicit selected-target policy permits personal images and private albums, default still requires fixtures", async () => {
  const h = setup();
  h.photo.filename = "Family holiday.jpg";
  h.photo.size = 20 * 1024 * 1024;
  const job = h.job("favorite-set", { photoUrl, value: true });
  job.testScope.targetPolicy = "selected";
  assert.equal((await h.pilot.execute(job)).verified, true);
  assert.equal(h.calls.length, 1);
  const other = setup();
  other.photo.filename = "Family holiday.jpg";
  const denied = other.job("favorite-set", { photoUrl, value: true });
  await assert.rejects(other.pilot.execute(denied));
  assert.equal(other.calls.length, 0);
});
test("unknown target policies do not send writes", async () => {
  const h = setup(),
    job = h.job("favorite-set", { photoUrl, value: true });
  job.testScope.targetPolicy = "anything";
  await assert.rejects(h.pilot.execute(job));
  assert.equal(h.calls.length, 0);
});

test("selected policy permits a selected private album but rejects shared albums", async () => {
  for (const shared of [false, true]) {
    const h = setup();
    h.photo.filename = "Personal.jpg";
    h.reader.albums = async () => ({
      items: [{ albumId: "album-a", title: "Family", shared }],
      complete: true,
    });
    const job = h.job("album-add", { photoUrl, albumId: "album-a" });
    job.testScope.targetPolicy = "selected";
    if (shared) {
      await assert.rejects(h.pilot.execute(job));
      assert.equal(h.calls.length, 0);
    } else {
      assert.equal((await h.pilot.execute(job)).verified, true);
      assert.equal(h.calls.length, 1);
    }
  }
});
test("selected policy still binds exact target and expiry, and cannot change an existing intent policy", async () => {
  for (const change of [{ photoKey: "wrong" }, { expiresAt: 1 }]) {
    const h = setup(),
      job = h.job("favorite-set", { photoUrl, value: true });
    Object.assign(job.testScope, { targetPolicy: "selected" }, change);
    await assert.rejects(h.pilot.execute(job));
    assert.equal(h.calls.length, 0);
  }
  const h = setup(),
    job = h.job("favorite-set", { photoUrl, value: true });
  await h.pilot.execute(job);
  job.testScope.targetPolicy = "selected";
  await assert.rejects(
    h.pilot.execute(job),
    (e) => e.code === "INTENT_CONFLICT",
  );
  assert.equal(h.calls.length, 1);
});
