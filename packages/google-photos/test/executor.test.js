import test from "node:test";
import assert from "node:assert/strict";
import {
  MutationExecutor,
  MemoryJournal,
  PROTOCOL_VERSION,
  UnknownOutcomeError,
} from "../src/index.js";
import { ACCOUNT, envelope } from "./fixtures.js";
const sha = "a".repeat(64);
const plan = () => ({
  id: "operation-1",
  account: ACCOUNT,
  type: "favorite",
  value: true,
  target: {
    namespace: "library-media",
    mediaKey: "media-a",
    dedupKey: "dedup-a",
  },
  revision: "revision-1",
  sha256: sha,
});
const observed = () => ({
  account: ACCOUNT,
  mediaKey: "media-a",
  dedupKey: "dedup-a",
  revision: "revision-1",
  sha256: sha,
  favorite: false,
  trashed: false,
  curatedAlbum: false,
  localVerified: true,
  backupVerified: true,
  companionsVerified: true,
  metadataVerified: true,
  owned: true,
});
const qualified = {
  account: ACCOUNT,
  protocolVersion: PROTOCOL_VERSION,
  operations: ["favorite", "trash", "restore"],
  expiresAt: 2000,
  evidenceSha256: "b".repeat(64),
};
function setup(overrides = {}) {
  const journal = new MemoryJournal(),
    calls = [],
    state = observed();
  const args = {
    account: ACCOUNT,
    journal,
    now: () => 1000,
    qualification: qualified,
    inspect: async () => ({ ...state }),
    transport: async (r) => {
      calls.push(r);
      state.favorite = true;
      return { account: ACCOUNT, status: 200, body: envelope("Ftfh0", [[]]) };
    },
    ...overrides,
  };
  return { executor: new MutationExecutor(args), journal, calls, state, args };
}
test("writes are disabled without account-bound, current qualification", async () => {
  for (const qualification of [
    undefined,
    { ...qualified, account: "other" },
    { ...qualified, expiresAt: 999 },
    { ...qualified, operations: [] },
    { ...qualified, evidenceSha256: "" },
  ]) {
    const h = setup({ qualification });
    await assert.rejects(h.executor.execute(plan()));
    assert.equal(h.calls.length, 0);
  }
});
test("verified write is journaled before sending, has exact RPC and target, and cannot replay", async () => {
  const h = setup();
  const original = h.args.transport;
  const executor = new MutationExecutor({
    ...h.args,
    transport: async (r) => {
      assert.equal((await h.journal.get("operation-1")).state, "sent");
      return original(r);
    },
  });
  assert.equal((await executor.execute(plan())).state, "verified");
  assert.equal(h.calls[0].rpc, "Ftfh0");
  assert.deepEqual(h.calls[0].data, [[[null, "dedup-a"]], [1]]);
  assert.equal((await executor.execute(plan())).state, "verified");
  assert.equal(h.calls.length, 1);
});
test("lost acknowledgement persists unknown outcome and blocks subsequent writes after restart", async () => {
  const h = setup({
    transport: async () => {
      throw new Error("secret");
    },
  });
  await assert.rejects(h.executor.execute(plan()), UnknownOutcomeError);
  assert.equal((await h.journal.get("operation-1")).state, "unknown");
  const restarted = new MutationExecutor(h.args);
  await assert.rejects(
    restarted.execute({ ...plan(), id: "operation-2" }),
    (e) => e.code === "UNRESOLVED",
  );
});
test("an HTTP 200 with no verified side effect is unknown, with no write retry", async () => {
  let writes = 0;
  const h = setup({
    transport: async () => {
      writes++;
      return { account: ACCOUNT, status: 200, body: envelope("Ftfh0", [[]]) };
    },
  });
  await assert.rejects(h.executor.execute(plan()), UnknownOutcomeError);
  assert.equal(writes, 1);
});
test("changed local revision, account, or remote identity cannot send a mutation", async () => {
  for (const field of [
    "account",
    "mediaKey",
    "dedupKey",
    "revision",
    "sha256",
  ]) {
    const h = setup({
      inspect: async () => ({ ...observed(), [field]: "changed" }),
    });
    await assert.rejects(h.executor.execute(plan()));
    assert.equal(h.calls.length, 0);
  }
});
test("trash requires every preservation fact, no favorites/curated albums, and ownership", async () => {
  for (const patch of [
    { favorite: true },
    { favorite: null },
    { curatedAlbum: true },
    { curatedAlbum: null },
    { owned: false },
    { backupVerified: false },
    { metadataVerified: false },
    { companionsVerified: false },
    { localVerified: false },
  ]) {
    const h = setup({ inspect: async () => ({ ...observed(), ...patch }) });
    await assert.rejects(
      h.executor.execute({ ...plan(), type: "trash", value: undefined }),
    );
    assert.equal(h.calls.length, 0);
  }
});
test("intent cannot be reused for different targets or changed operation", async () => {
  const h = setup();
  await h.executor.execute(plan());
  await assert.rejects(
    h.executor.execute({ ...plan(), value: false }),
    (e) => e.code === "INTENT_CONFLICT",
  );
  assert.equal(h.calls.length, 1);
});
test("concurrent writers cannot overlap and a storage error before send prevents the request", async () => {
  const h = setup();
  const release = await h.journal.lock(ACCOUNT);
  await assert.rejects(h.executor.execute(plan()), (e) => e.code === "BUSY");
  await release();
  assert.equal(h.calls.length, 0);
  h.journal.put = async () => {
    throw new Error("disk full");
  };
  await assert.rejects(h.executor.execute(plan()));
  assert.equal(h.calls.length, 0);
});

test("unknown outcome can be reconciled by read-back without resending a write", async () => {
  const h = setup({
    transport: async () => {
      throw new Error("lost response");
    },
  });
  await assert.rejects(h.executor.execute(plan()));
  h.state.favorite = true;
  const restarted = new MutationExecutor(h.args);
  assert.equal((await restarted.reconcile("operation-1")).state, "verified");
  assert.equal((await h.journal.pending(ACCOUNT)).length, 0);
});
test("an inspector cannot mutate the frozen target plan", async () => {
  const h = setup({
    inspect: async (p) => {
      p.target.dedupKey = "wrong-target";
      return observed();
    },
  });
  await assert.rejects(h.executor.execute(plan()));
  assert.equal(h.calls.length, 0);
});
