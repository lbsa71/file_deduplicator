import test from "node:test";
import assert from "node:assert/strict";
import { decideRetention } from "../src/index.js";
const base = {
  localVerified: true,
  backupVerified: true,
  companionsVerified: true,
  metadata: "verified",
  localFavorite: false,
  remoteFavorite: false,
  localCuratedAlbum: false,
  remoteCuratedAlbum: false,
  remotePresence: "present",
  identityVerified: true,
  remoteComplete: true,
  uploadState: "none",
};
test("every positive rule retains; only fully established unprotected originals are removal candidates", () => {
  assert.equal(decideRetention(base).action, "review-trash");
  for (const k of [
    "localFavorite",
    "remoteFavorite",
    "localCuratedAlbum",
    "remoteCuratedAlbum",
  ])
    assert.equal(decideRetention({ ...base, [k]: true }).action, "keep");
  for (const k of [
    "localVerified",
    "backupVerified",
    "companionsVerified",
    "identityVerified",
    "remoteComplete",
  ])
    assert.notEqual(
      decideRetention({ ...base, [k]: false }).action,
      "review-trash",
    );
});
test("missing Google metadata uploads only after absence is proved, then waits for Takeout without repeat uploads", () => {
  assert.equal(
    decideRetention({ ...base, metadata: "missing", remotePresence: "absent" })
      .action,
    "upload",
  );
  assert.equal(
    decideRetention({ ...base, metadata: "missing" }).action,
    "await-metadata",
  );
  for (const uploadState of ["pending", "unknown", "uploaded"])
    assert.notEqual(
      decideRetention({
        ...base,
        metadata: "missing",
        remotePresence: "absent",
        uploadState,
      }).action,
      "upload",
    );
  assert.equal(
    decideRetention({ ...base, metadata: "missing", remotePresence: "unknown" })
      .action,
    "review",
  );
});
test("invalid or absent facts cannot become negative retention evidence", () => {
  for (const metadata of ["invalid", "ambiguous", undefined])
    assert.equal(decideRetention({ ...base, metadata }).action, "review");
  for (const k of Object.keys(base))
    assert.notEqual(
      decideRetention({ ...base, [k]: undefined }).action,
      "review-trash",
    );
  assert.throws(() => decideRetention({ ...base, remoteFavorite: "false" }));
});
