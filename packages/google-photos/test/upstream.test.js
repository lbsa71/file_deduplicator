import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { parsePage, parseDetails } from "../src/protocol.js";

test("extended details distinguish explicit empty album membership from missing facts", () => {
  const row = Array(33).fill(null);
  row[0] = "control-media";
  row[2] = "control.jpg";
  row[5] = 23467;
  row[11] = "control-dedup";
  // Controlled live upload -> add to a new album -> remove: fDcn4b returns
  // an explicit null at index 19 when the control has no memberships.
  assert.deepEqual(parseDetails([row], row[0], true).albums, []);
  row[19] = [];
  assert.deepEqual(parseDetails([row], row[0], true).albums, []);
  assert.equal(parseDetails([row.slice(0, 19)], row[0], true).albums, null);
  delete row[19];
  assert.equal(parseDetails([row], row[0], true).albums, null);
  for (const invalid of [false, 0, "", {}]) {
    row[19] = invalid;
    assert.throws(() => parseDetails([row], row[0], true), /album membership/);
  }
});
for (const [rpc, kind] of [
  ["lcxiM", "inventory"],
  ["EzkLib", "favorites"],
  ["Z5xsfc", "albums"],
  ["snAcKc", "albumItems"],
  ["zy0IHe", "trash"],
]) {
  test(`strict parser accepts sanitized pinned upstream ${rpc} shape`, async () => {
    const data = JSON.parse(
      await readFile(
        new URL(`./fixtures/upstream/${rpc}.json`, import.meta.url),
      ),
    );
    const page = parsePage(
      data,
      kind,
      kind === "albumItems" ? data[3][0] : undefined,
    );
    assert.equal(page.items.length, 2);
    assert.ok(page.next === null || typeof page.next === "string");
  });
}
for (const [rpc, extended] of [
  ["VrseUb", false],
  ["fDcn4b", true],
])
  test(`strict details parser accepts upstream ${rpc} shape`, async () => {
    const data = JSON.parse(
      await readFile(
        new URL(`./fixtures/upstream/${rpc}.json`, import.meta.url),
      ),
    );
    assert.equal(parseDetails(data, data[0][0], extended).mediaKey, data[0][0]);
  });
