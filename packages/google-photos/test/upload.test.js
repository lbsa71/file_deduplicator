import test from "node:test";
import assert from "node:assert/strict";
import {
  OfficialUploader,
  MemoryJournal,
  PROTOCOL_VERSION,
} from "../src/index.js";
const account = "fixture-account",
  sha = "a".repeat(64);
const plan = {
  id: "upload-1",
  account,
  revision: "revision-1",
  sha256: sha,
  filename: "fixture.jpg",
  mimeType: "image/jpeg",
  size: 3,
};
function setup(overrides = {}) {
  const calls = [],
    journal = new MemoryJournal();
  const args = {
    account,
    journal,
    now: () => 1000,
    qualification: {
      account,
      protocolVersion: PROTOCOL_VERSION,
      operations: ["upload"],
      expiresAt: 2000,
      evidenceSha256: "b".repeat(64),
    },
    inspect: async () => ({
      account,
      revision: plan.revision,
      sha256: sha,
      remoteAbsent: true,
      localVerified: true,
    }),
    verifyRemote: async (id) => ({ account, mediaId: id, exists: true }),
    request: async (req) => {
      calls.push(req);
      if (req.url.endsWith("/uploads"))
        return { account, status: 200, body: "fixture-upload-token" };
      return {
        account,
        status: 200,
        body: JSON.stringify({
          newMediaItemResults: [
            {
              uploadToken: "fixture-upload-token",
              status: {},
              mediaItem: {
                id: "remote-a",
                productUrl: "https://photos.google.com/photo/remote-a",
              },
            },
          ],
        }),
      };
    },
    ...overrides,
  };
  const source = {
    body: new Uint8Array([1, 2, 3]),
    size: 3,
    verify: async () => true,
  };
  return { args, calls, journal, source, uploader: new OfficialUploader(args) };
}
test("upload verifies its receipt and remote existence, then waits for metadata without sending again", async () => {
  const h = setup();
  const result = await h.uploader.upload(plan, h.source);
  assert.equal(result.state, "uploaded");
  assert.equal(result.awaitingMetadata, true);
  assert.equal(result.mediaId, "remote-a");
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[0].headers["X-Goog-Upload-Protocol"], "raw");
  assert.equal((await h.uploader.upload(plan, h.source)).state, "uploaded");
  assert.equal(h.calls.length, 2);
  assert.equal((await h.journal.pending(account)).length, 0);
});
test("unknown presence, missing qualification, or wrong source prevents any upload", async () => {
  for (const overrides of [
    { qualification: null },
    {
      inspect: async () => ({
        account,
        revision: plan.revision,
        sha256: sha,
        remoteAbsent: null,
        localVerified: true,
      }),
    },
  ]) {
    const h = setup(overrides);
    await assert.rejects(h.uploader.upload(plan, h.source));
    assert.equal(h.calls.length, 0);
  }
  const h = setup();
  await assert.rejects(h.uploader.upload(plan, { ...h.source, size: 4 }));
  assert.equal(h.calls.length, 0);
});
test("changed source after byte transfer cannot create a library item", async () => {
  const h = setup();
  await assert.rejects(
    h.uploader.upload(plan, { ...h.source, verify: async () => false }),
  );
  assert.equal(h.calls.length, 1);
  assert.equal((await h.journal.get(plan.id)).state, "unknown");
});
test("lost creation response persists uncertainty and never automatically reuploads", async () => {
  const h = setup();
  let writes = 0;
  h.args.request = async (req) => {
    writes++;
    if (writes === 1)
      return { account, status: 200, body: "fixture-upload-token" };
    throw new Error("timeout");
  };
  const first = new OfficialUploader(h.args);
  await assert.rejects(
    first.upload(plan, h.source),
    (e) => e.code === "UNKNOWN_OUTCOME",
  );
  await assert.rejects(
    new OfficialUploader(h.args).upload(plan, h.source),
    (e) => e.code === "UNRESOLVED",
  );
  assert.equal(writes, 2);
});
test("wrong upload token, per-item error, and wrong remote identity reject apparent success", async () => {
  for (const result of [
    { uploadToken: "wrong", status: {}, mediaItem: { id: "r" } },
    {
      uploadToken: "fixture-upload-token",
      status: { code: 13 },
      mediaItem: { id: "r" },
    },
    { uploadToken: "fixture-upload-token", status: {}, mediaItem: {} },
  ]) {
    let n = 0;
    const h = setup({
      request: async () => ({
        account,
        status: 200,
        body:
          ++n === 1
            ? "fixture-upload-token"
            : JSON.stringify({ newMediaItemResults: [result] }),
      }),
    });
    await assert.rejects(h.uploader.upload(plan, h.source));
  }
  const h = setup({
    verifyRemote: async () => ({ account, mediaId: "different", exists: true }),
  });
  await assert.rejects(h.uploader.upload(plan, h.source));
});
test("a new operation ID cannot upload the same account/content again while awaiting metadata", async () => {
  const h = setup();
  await h.uploader.upload(plan, h.source);
  const again = await h.uploader.upload({ ...plan, id: "upload-2" }, h.source);
  assert.equal(again.mediaId, "remote-a");
  assert.equal(again.linkedOperationId, "upload-1");
  assert.equal(h.calls.length, 2);
});

test("creation receipt can be reconciled after a failed read-back without reuploading", async () => {
  const h = setup({
    verifyRemote: async () => {
      throw new Error("read unavailable");
    },
  });
  await assert.rejects(h.uploader.upload(plan, h.source));
  assert.equal((await h.journal.get(plan.id)).mediaId, "remote-a");
  const retry = new OfficialUploader({
    ...h.args,
    verifyRemote: async (id) => ({ account, mediaId: id, exists: true }),
  });
  assert.equal((await retry.reconcile(plan.id)).state, "uploaded");
  assert.equal(h.calls.length, 2);
});

test("qualification expiring during journal persistence stops the next network write", async () => {
  for (const state of ["bytes-sent", "create-sent"]) {
    let now = 1000;
    const h = setup({ now: () => now });
    const put = h.journal.put.bind(h.journal);
    h.journal.put = async (record) => {
      await put(record);
      if (record.state === state) now = 3000;
    };
    await assert.rejects(h.uploader.upload(plan, h.source));
    assert.equal(h.calls.length, state === "bytes-sent" ? 0 : 1);
    assert.equal((await h.journal.pending(account)).length, 1);
  }
});
