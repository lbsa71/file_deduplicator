import test from "node:test";
import assert from "node:assert/strict";
import { syncPresentation, canStartSync } from "./google-sync.js";
const review = {
  state: "review",
  review: {
    manifestId: "a".repeat(32),
    sha256: "b".repeat(64),
    trash: 12,
    keep: 50,
    expiresAt: 2000,
  },
};
test("only a current exact reviewed plan enables the Trash action", () => {
  assert.equal(canStartSync(review, 1000), true);
  for (const bad of [
    { ...review, state: "interrupted" },
    { ...review, review: { ...review.review, expiresAt: 999 } },
    { ...review, review: { ...review.review, sha256: "wrong" } },
    { ...review, review: { ...review.review, trash: 0 } },
  ])
    assert.equal(canStartSync(bad, 1000), false);
});
test("a stopped pass offers a fresh inventory without per-write repair", () => {
  const view = syncPresentation({ state: "paused" }, 1000);
  assert.equal(view.action, "prepare");
  assert.equal(view.label, "Prepare fresh pass");
  assert.equal(syncPresentation({ state: "pausing" }, 1000).action, null);
});
test("preparation, recovery and expired reviews have clear distinct actions", () => {
  assert.equal(
    syncPresentation({ state: "preparing", phase: "local" }, 1000).title,
    "Checking local copies",
  );
  assert.equal(syncPresentation({ state: "expired" }, 1000).action, "prepare");
  assert.equal(
    syncPresentation({ state: "preparation_failed" }, 1000).action,
    "prepare",
  );
  assert.equal(
    syncPresentation({ state: "paused" }, 1000).label,
    "Prepare fresh pass",
  );
  assert.equal(syncPresentation({ state: "surprise" }, 1000).action, null);
});
test("zero eligible photos finish at the review without a misleading write action", () => {
  const empty = { ...review, review: { ...review.review, trash: 0 } };
  assert.equal(syncPresentation(empty, 1000).title, "Everything is kept");
  assert.equal(syncPresentation(empty, 1000).action, "prepare");
});
