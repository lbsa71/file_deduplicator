import test from "node:test";
import assert from "node:assert/strict";
import { pairFromPage } from "../src/page-pairing.js";

function harness() {
  const calls = [];
  return {
    calls,
    ports: {
      tabs: async () => [{ id: 4 }, { id: 5 }],
      identity: async (id) => ({ account: id === 5 ? "expected" : "other" }),
      pair: async (message) => {
        calls.push(message);
        return { state: "connecting" };
      },
    },
  };
}
test("page pairing binds the endpoint to the sender and selects the matching Google account", async () => {
  const h = harness();
  const result = await pairFromPage(
    {
      code: "x".repeat(43),
      account: "expected",
      origin: "https://evil.example",
    },
    { url: "https://localhost:8099/photos", frameId: 0, tab: { id: 9 } },
    h.ports,
  );
  assert.deepEqual(result, { state: "connecting" });
  assert.deepEqual(h.calls, [
    { origin: "https://localhost:8099", tabId: 5, code: "x".repeat(43) },
  ]);
});
test("untrusted pages, frames and invalid targets never inspect Google or pair", async () => {
  for (const sender of [
    { url: "https://evil.example/", frameId: 0, tab: { id: 9 } },
    { url: "https://localhost:8099/", frameId: 1, tab: { id: 9 } },
    { url: "http://localhost:8099/", frameId: 0, tab: { id: 9 } },
  ]) {
    const h = harness();
    h.ports.tabs = async () => {
      throw new Error("Must not inspect tabs");
    };
    await assert.rejects(
      pairFromPage(
        { code: "x".repeat(43), account: "expected" },
        sender,
        h.ports,
      ),
    );
    assert.equal(h.calls.length, 0);
  }
});
test("an account mismatch preserves the existing pairing and sends no pair request", async () => {
  const h = harness();
  await assert.rejects(
    pairFromPage(
      { code: "x".repeat(43), account: "missing" },
      { url: "https://localhost:8099/", frameId: 0, tab: { id: 9 } },
      h.ports,
    ),
    (error) => error.diagnostic.code === "PAIR_SESSION",
  );
  assert.equal(h.calls.length, 0);
});
