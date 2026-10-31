import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { decodeEnvelope, parsePage } from "../src/protocol.js";
import { GooglePhotosClient } from "../src/client.js";

const page = JSON.parse(
  await readFile(
    new URL(
      "./fixtures/live/library-first-page.sanitized.json",
      import.meta.url,
    ),
  ),
);
const records = JSON.stringify([
  [
    "wrb.fr",
    "lcxiM",
    JSON.stringify(page),
    null,
    null,
    null,
    "generic",
    "synthetic-é-😀",
  ],
]);
const frame = (line) => `${line.length + 2}\n${line}\n`;
const body =
  ")]}'\n\n" +
  frame(records) +
  frame(JSON.stringify([["di", 1]])) +
  frame(JSON.stringify([["af.httprm", 1]]));

test("observed e trailer follows one verified RPC and cannot hide errors or further records", () => {
  const end = frame(JSON.stringify([["e", 4, null, null, 1000]]));
  assert.deepEqual(decodeEnvelope(body + end, "lcxiM"), page);
  for (const bad of [
    end,
    end + body,
    body + end + end,
    body + end + frame('[["di",1]]'),
    body + frame('[["e",5,null,null,1000]]'),
    body + frame('[["e",4,null,null,"bad"]]'),
    body + frame('[["e",4,null,null]]'),
  ])
    assert.throws(() => decodeEnvelope(bad, "lcxiM"));
});

test("observed UTF-16 frame lengths with two extra units admit Unicode and known trailers", () => {
  assert.notEqual(records.length + 2, Buffer.byteLength(records));
  assert.deepEqual(decodeEnvelope(body, "lcxiM"), page);
  const parsed = parsePage(decodeEnvelope(body, "lcxiM"), "inventory");
  assert.equal(parsed.items.length, 1);
  assert.equal(parsed.items[0].favorite, false);
  assert.equal(parsed.next, page[1]);
});

test("the observed framing convention cannot admit corrupt lengths, wrong RPCs or malformed payloads", async () => {
  for (const malformed of [
    body.replace(String(records.length + 2), String(records.length + 10)),
    body.replace(String(records.length + 2), String(records.length - 1)),
    ")]}'\n\n" + frame(records.replace("lcxiM", "EzkLib")),
    ")]}'\n\n" + frame(JSON.stringify([["wrb.fr", "lcxiM", "not-json"]])),
    body + frame(records),
  ]) {
    let calls = 0;
    const client = new GooglePhotosClient({
      account: "fixture-account",
      transport: async () => {
        calls++;
        return { account: "fixture-account", status: 200, body: malformed };
      },
    });
    await assert.rejects(client.inventory());
    assert.equal(calls, 1, "An invalid first page must not trigger pagination");
  }
});
