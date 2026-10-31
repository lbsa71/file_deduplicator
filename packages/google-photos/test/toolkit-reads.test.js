import test from "node:test";
import assert from "node:assert/strict";
import { GooglePhotosClient } from "../src/client.js";
import { envelope, item, album, ACCOUNT } from "./fixtures.js";
function client(rpc, data) {
  return new GooglePhotosClient({
    account: ACCOUNT,
    transport: async (request) => ({
      account: ACCOUNT,
      status: 200,
      body: envelope(rpc, data),
    }),
  });
}
test("bounded pages retain continuation and namespaces, never claim a full inventory", async () => {
  const page = await client("lcxiM", [[item()], "next"]).page("inventory", {});
  assert.equal(page.next, "next");
  assert.equal(page.complete, false);
  assert.equal(page.items[0].namespace, "library-media");
  const members = await client("snAcKc", [
    null,
    [item()],
    null,
    ["album-a"],
  ]).page("albumItems", { albumId: "album-a" });
  assert.equal(members.items[0].namespace, "album-item");
});
test("quota and download references require explicit valid values", async () => {
  const row = Array(7).fill(null);
  row[6] = [12, 100, null, 10];
  assert.deepEqual(await client("EzwWhf", row).quota(), {
    used: 12,
    total: 100,
    photosUsed: 10,
  });
  await assert.rejects(client("EzwWhf", [[]]).quota());
  assert.equal(
    (
      await client("pLFTfd", [
        "https://photos.google.com/download/test",
      ]).downloadLink("media-a")
    ).url,
    "https://photos.google.com/download/test",
  );
  for (const url of [
    "http://photos.google.com/a",
    "https://evil.invalid/a",
    "https://user:password@photos.google.com/a",
  ])
    await assert.rejects(client("pLFTfd", [url]).downloadLink("media-a"));
});

test("malformed manual location cannot become proof that location was cleared", async () => {
  for (const location of [[], [null], {}]) {
    const row = Array(32).fill(null);
    row[0] = "media-a";
    row[1] = "";
    row[2] = "photoflow-test-fixture.jpg";
    row[3] = 1000;
    row[4] = 0;
    row[5] = 100;
    row[11] = "dedup-media-a";
    row[13] = location;
    row[19] = [];
    const reader = new GooglePhotosClient({
      account: ACCOUNT,
      transport: async (r) => ({
        account: ACCOUNT,
        status: 200,
        body: envelope(r.rpc, [r.rpc === "VrseUb" ? item("media-a") : row]),
      }),
    });
    await assert.rejects(reader.observation("media-a"));
  }
});
