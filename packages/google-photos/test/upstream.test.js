import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { parsePage, parseDetails } from "../src/protocol.js";
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
