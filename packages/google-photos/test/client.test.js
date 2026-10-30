import test from "node:test";
import assert from "node:assert/strict";
import {
  GooglePhotosClient,
  decodeEnvelope,
  ProtocolError,
} from "../src/index.js";
import { ACCOUNT, envelope, item, album, harness } from "./fixtures.js";

test("RPC framing checks identity, duplicate envelopes, and malformed success bodies", () => {
  assert.deepEqual(decodeEnvelope(envelope("EzkLib", [[], null]), "EzkLib"), [
    [],
    null,
  ]);
  const framed =
    ")]}'\n" +
    Buffer.byteLength(JSON.stringify([["wrb.fr", "EzkLib", "[[]]"]])) +
    "\n" +
    JSON.stringify([["wrb.fr", "EzkLib", "[[]]"]]);
  assert.deepEqual(decodeEnvelope(framed, "EzkLib"), [[]]);
  for (const body of [
    "",
    "<html>Login</html>",
    envelope("other", [[]]),
    envelope("EzkLib", null),
    envelope("EzkLib", [[]]) + envelope("EzkLib", [[]]),
    '[ ["er", "EzkLib", 403] ]',
  ]) {
    assert.throws(() => decodeEnvelope(body, "EzkLib"), ProtocolError);
  }
});

test("inventory includes archive, validates pages, and returns an explicit complete snapshot", async () => {
  const h = harness();
  const responses = [
    h.reply("lcxiM", [[item()], "cursor-b", "1700000000000"]),
    h.reply("lcxiM", [[item("media-b")], null, "1690000000000"]),
  ];
  const client = new GooglePhotosClient({
    account: ACCOUNT,
    transport: async (req) => {
      h.calls.push(req);
      return responses.shift();
    },
    now: () => 1000,
  });
  const result = await client.inventory();
  assert.equal(result.complete, true);
  assert.equal(result.account, ACCOUNT);
  assert.equal(result.items.length, 2);
  assert.equal(result.items[0].favorite, null);
  assert.equal(h.calls[0].data[5], 3);
  assert.equal(h.calls[1].data[0], "cursor-b");
});

test("a failed later page cannot yield a partial inventory or send further requests", async () => {
  const h = harness();
  const responses = [
    h.reply("lcxiM", [[item()], "next", "1700000000000"]),
    new Error("private-token-do-not-log"),
  ];
  const client = new GooglePhotosClient({
    account: ACCOUNT,
    transport: async (req) => {
      h.calls.push(req);
      const v = responses.shift();
      if (v instanceof Error) throw v;
      return v;
    },
  });
  await assert.rejects(
    client.inventory(),
    (e) => e.code === "TRANSPORT" && !e.message.includes("private-token"),
  );
  assert.equal(h.calls.length, 2);
  await assert.rejects(client.albums(), (e) => e.code === "CIRCUIT_OPEN");
  assert.equal(h.calls.length, 2);
});

test("cursor loops, duplicate items, malformed pages, changed account and missing flags fail safely", async () => {
  for (const mode of ["loop", "duplicate", "shape", "account", "flag"]) {
    const h = harness();
    let n = 0;
    const client = new GooglePhotosClient({
      account: ACCOUNT,
      transport: async (req) => {
        h.calls.push(req);
        n++;
        if (mode === "account")
          return h.reply(req.rpc, [[], null], { account: "another-account" });
        if (mode === "shape") return h.reply(req.rpc, {});
        if (mode === "flag")
          return h.reply(req.rpc, [[item("a", "false")], null]);
        return h.reply(req.rpc, [
          [item(mode === "loop" ? `m${n}` : "same")],
          mode === "loop" ? "again" : n === 1 ? "next" : null,
        ]);
      },
    });
    await assert.rejects(client.favorites(), ProtocolError);
    assert.ok(h.calls.length <= 2);
  }
});

test("album members retain album-scoped IDs and verify the requested album identity", async () => {
  const h = harness();
  const responses = [
    h.reply("Z5xsfc", [[album()], null]),
    h.reply("snAcKc", [
      null,
      [item("album-item")],
      "",
      ["album-a", "Fixture album"],
    ]),
  ];
  const c = new GooglePhotosClient({
    account: ACCOUNT,
    transport: async (r) => {
      h.calls.push(r);
      return responses.shift();
    },
  });
  const albums = await c.albums();
  assert.equal(albums.items[0].shared, false);
  const members = await c.albumItems("album-a");
  assert.equal(members.items[0].namespace, "album-item");
  assert.equal(members.albumId, "album-a");
  const wrong = new GooglePhotosClient({
    account: ACCOUNT,
    transport: async () =>
      h.reply("snAcKc", [null, [], "", ["different", "Fixture"]]),
  });
  await assert.rejects(wrong.albumItems("album-a"), ProtocolError);
});

test("item details verify target, preserve unknown favorite and album membership", async () => {
  const h = harness([
    { account: ACCOUNT, status: 200, body: envelope("VrseUb", [item()]) },
  ]);
  const c = new GooglePhotosClient({
    account: ACCOUNT,
    transport: h.transport,
  });
  const result = await c.item("media-a");
  assert.equal(result.favorite, null);
  const bad = new GooglePhotosClient({
    account: ACCOUNT,
    transport: async () => h.reply("VrseUb", [item("wrong")]),
  });
  await assert.rejects(bad.item("media-a"), ProtocolError);
});

test("hash matches are candidates, not absence or SHA-256 identity evidence", async () => {
  const h = harness();
  const c = new GooglePhotosClient({
    account: ACCOUNT,
    transport: async (r) => h.reply("swbisb", [[["opaque-hash", item()]]]),
  });
  const found = await c.hashCandidates(["opaque-hash"]);
  assert.equal(found.absenceProven, false);
  assert.equal(found.items.length, 1);
  const empty = new GooglePhotosClient({
    account: ACCOUNT,
    transport: async (r) => h.reply("swbisb", [[]]),
  });
  assert.equal(
    (await empty.hashCandidates(["opaque-hash"])).absenceProven,
    false,
  );
  const malformed = new GooglePhotosClient({
    account: ACCOUNT,
    transport: async (r) => h.reply("swbisb", []),
  });
  await assert.rejects(
    malformed.hashCandidates(["opaque-hash"]),
    ProtocolError,
  );
});

test("invalid IDs and unknown operations send no requests; no public raw RPC escape hatch", async () => {
  const h = harness();
  const c = new GooglePhotosClient({
    account: ACCOUNT,
    transport: h.transport,
  });
  for (const id of ["", null, [], {}, "x\nsecret"])
    await assert.rejects(c.item(id));
  assert.equal(c.call, undefined);
  assert.equal(h.calls.length, 0);
});
