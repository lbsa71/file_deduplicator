import test from "node:test";
import assert from "node:assert/strict";
import { inspectSelection } from "../src/inspection.js";
import { ACCOUNT, envelope, item } from "./fixtures.js";
const selection = {
  account: ACCOUNT,
  albumUrl: "https://photos.google.com/album/album-a",
  photoUrl: "https://photos.google.com/photo/media-a",
};
function setup() {
  const calls = [];
  const transport = async (r) => {
    calls.push(r);
    const detail = Array(20).fill(null);
    detail[0] = "media-a";
    detail[2] = "PRIVATE_FILENAME";
    detail[5] = 3;
    detail[11] = "dedup-media-a";
    detail[19] = [];
    return {
      account: ACCOUNT,
      status: 200,
      body: envelope(
        r.rpc,
        r.rpc === "snAcKc"
          ? [null, [item("album-item-a")], null, ["album-a"]]
          : r.rpc === "VrseUb"
            ? [item()]
            : [detail],
      ),
    };
  };
  return { calls, transport };
}
test("selection reads only the exact album and photo and exports sanitized evidence", async () => {
  const h = setup();
  const result = await inspectSelection(selection, h.transport);
  assert.equal(h.calls.length, 3);
  assert.deepEqual(
    h.calls.map((r) => r.operation),
    ["albumItems", "item", "details"],
  );
  assert.equal(result.summary.albumMembers, 1);
  assert.equal(result.summary.retentionReady, false);
  assert.equal(result.evidence.complete, true);
  assert.ok(!JSON.stringify(result).includes("PRIVATE_FILENAME"));
  assert.ok(!JSON.stringify(result).includes("media-a"));
});
test("malformed selection cannot send requests", async () => {
  for (const patch of [
    { account: "" },
    { albumUrl: "https://evil.invalid/album/a" },
    { photoUrl: "https://photos.google.com/photo/a?auth=secret" },
    { photoUrl: "https://photos.google.com/album/a/photo/b" },
  ]) {
    const h = setup();
    await assert.rejects(
      inspectSelection({ ...selection, ...patch }, h.transport),
    );
    assert.equal(h.calls.length, 0);
  }
});
test("account or detail identity mismatch stops dependent reads with sanitized evidence", async () => {
  const h = setup();
  let n = 0;
  const result = await inspectSelection(selection, async (r) => {
    const reply = await h.transport(r);
    if (++n === 2) reply.account = "other";
    return reply;
  });
  assert.equal(result.evidence.complete, false);
  assert.equal(h.calls.length, 2);
  assert.ok(!JSON.stringify(result).includes("media-a"));
});
test("oversized albums stop before photo reads and bounded pagination never claims completion", async () => {
  const h = setup();
  const result = await inspectSelection(selection, async (r) => {
    h.calls.push(r);
    return {
      account: ACCOUNT,
      status: 200,
      body: envelope(r.rpc, [
        null,
        [item("m" + h.calls.length)],
        "cursor" + h.calls.length,
        ["album-a"],
      ]),
    };
  });
  assert.equal(result.evidence.complete, false);
  assert.equal(h.calls.length, 2);
});

test("conflicting basic and extended identities cannot yield successful inspection", async () => {
  const h = setup();
  const result = await inspectSelection(selection, async (r) => {
    const response = await h.transport(r);
    if (r.operation === "details") {
      const row = Array(20).fill(null);
      row[0] = "media-a";
      row[2] = "name";
      row[11] = "different-dedup";
      response.body = envelope(r.rpc, [row]);
    }
    return response;
  });
  assert.equal(result.summary.complete, false);
  assert.equal(result.evidence.complete, false);
  assert.equal(h.calls.length, 3);
});
