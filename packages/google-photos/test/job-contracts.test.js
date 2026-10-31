import test from "node:test";
import assert from "node:assert/strict";
import { JOBS, capabilities } from "../src/jobs.js";
import { item, album } from "./fixtures.js";
import { parseItem, parseAlbum } from "../src/protocol.js";
test("every registered operation rejects extra inputs and advertises its own version", () => {
  assert.equal(Object.keys(JOBS).length, 22);
  for (const [name, spec] of Object.entries(JOBS)) {
    assert.throws(() => spec.validateInput({ arbitraryRpc: "anything" }));
    assert.ok(
      capabilities().some(
        (c) => c.operation === name && c.version === spec.version,
      ),
    );
  }
});
test("result contracts preserve unknown flags and reject wrong namespaces or missing detail facts", () => {
  const media = parseItem(item());
  JOBS["library-page"].validateResult({
    items: [media],
    next: null,
    complete: true,
    retentionReady: false,
  });
  assert.throws(() =>
    JOBS["album-members"].validateResult({
      items: [media],
      next: null,
      complete: true,
      retentionReady: false,
    }),
  );
  assert.throws(() =>
    JOBS["photo-details"].validateResult({
      photo: { ...media },
      retentionReady: false,
    }),
  );
  JOBS["albums-page"].validateResult({
    items: [parseAlbum(album())],
    next: null,
    complete: true,
    retentionReady: false,
  });
});
