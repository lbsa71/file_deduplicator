import test from "node:test";
import assert from "node:assert/strict";
import { JobDiagnostics } from "../src/job-diagnostics.js";
import { envelope, item } from "./fixtures.js";
test("job diagnostics preserve RPC structure, redact values and bound retained evidence", () => {
  const diagnostic = new JobDiagnostics(
    { id: "job-a", operation: "inventory-counts" },
    () => 1000,
  );
  diagnostic.phase("library");
  diagnostic.read(
    { rpc: "lcxiM", data: [null] },
    { status: 200, body: envelope("lcxiM", [[item("PRIVATE_MEDIA_ID")]]) },
  );
  const data = diagnostic.snapshot();
  assert.equal(data.entries[0].response.rpcResponses[0].rpc, "lcxiM");
  assert.equal(data.events[0].phase, "library");
  assert.ok(!JSON.stringify(data).includes("PRIVATE_"));
  for (let i = 0; i < 50; i++)
    diagnostic.read(
      { rpc: "lcxiM", data: [] },
      { status: 200, body: "x".repeat(1100000) },
    );
  assert.ok(diagnostic.snapshot().entries.length <= 8);
  assert.equal(diagnostic.snapshot().limited, true);
  assert.throws(() => diagnostic.phase("PRIVATE_TOKEN"));
});

test("bounded diagnostics retain the latest failed read and a controlled parser rule", () => {
  const d = new JobDiagnostics({ id: "job-a", operation: "inventory-counts" });
  for (let i = 0; i < 12; i++)
    d.read(
      { rpc: "lcxiM", data: [] },
      { status: 200, body: envelope("lcxiM", [[item("old-" + i)]]) },
    );
  d.read(
    { rpc: "VrseUb", data: ["PRIVATE_ID"] },
    { status: 200, body: "not-json-PRIVATE_TOKEN" },
  );
  d.failure(Object.assign(new Error("Invalid RPC JSON"), { code: "PROTOCOL" }));
  const result = d.snapshot();
  assert.equal(result.entries.at(-1).rpc, "VrseUb");
  assert.equal(result.failure.rule, "RPC_JSON");
  assert.equal(result.limited, true);
  assert.ok(!JSON.stringify(result).includes("PRIVATE_"));
});

test("read diagnostics expose only fixed transport error codes", () => {
  const d = new JobDiagnostics({ id: "a", operation: "inventory-counts" });
  d.read({ rpc: "VrseUb", data: [] }, { error: "UNQUALIFIED" });
  assert.equal(d.snapshot().entries[0].transportError, "UNQUALIFIED");
  d.read({ rpc: "VrseUb", data: [] }, { error: "PRIVATE_TOKEN" });
  assert.ok(!JSON.stringify(d.snapshot()).includes("PRIVATE_"));
});
