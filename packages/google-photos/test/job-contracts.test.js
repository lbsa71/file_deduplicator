import test from "node:test";
import assert from "node:assert/strict";
import { JOBS, capabilities } from "../src/jobs.js";
import { item, album } from "./fixtures.js";
import { parseItem, parseAlbum } from "../src/protocol.js";
test("opaque dedup keys accept colon segments without broadening media identifiers", () => {
  const result = (field, value) => ({
    items: [{ ...parseItem(item()), [field]: value }],
    next: null,
    complete: true,
    retentionReady: false,
  });
  JOBS["library-page"].validateResult(result("dedupKey", "opaque-key:revision_1"));
  for (const invalid of ["", ":a", "a:", "a::b", "a/b", "a b", "a\n", "a.b", "a%3Ab", "a".repeat(257)])
    assert.throws(() => JOBS["library-page"].validateResult(result("dedupKey", invalid)));
  assert.throws(() => JOBS["library-page"].validateResult(result("mediaKey", "media:revision")));
});
test("every registered operation rejects extra inputs and advertises its own version", () => {
  assert.equal(Object.keys(JOBS).length, 23);
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
