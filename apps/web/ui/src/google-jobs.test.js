import test from "node:test";
import assert from "node:assert/strict";
import { readSuite, pilotSuite } from "./google-jobs.js";
const target = {
  photoUrl: "https://photos.google.com/photo/media-a",
  albumId: "album-a",
  hashes: ["opaque"],
};
test("one read suite covers selected targets and never contains writes", () => {
  const jobs = readSuite(target);
  assert.deepEqual(
    jobs.map((x) => x.operation),
    [
      "inventory-counts",
      "library-page",
      "favorites-page",
      "albums-page",
      "trash-page",
      "storage-quota",
      "photo-details",
      "download-link",
      "album-members",
      "hash-candidates",
    ],
  );
  assert.equal(readSuite({}).length, 6);
});
test("pilot is finite and restores trash/favorite/archive state without permanent deletion", () => {
  const jobs = pilotSuite(target, {}, 123);
  assert.equal(jobs[0].operation, "album-create");
  assert.equal(jobs.at(-2).operation, "trash");
  assert.equal(jobs.at(-1).operation, "restore");
  assert.ok(jobs.every((x) => !x.operation.includes("delete")));
  assert.deepEqual(
    jobs
      .filter((x) => x.operation === "favorite-set")
      .map((x) => x.input.value),
    [true, false],
  );
  assert.throws(() => pilotSuite({}, {}));
});
