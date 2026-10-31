import test from "node:test";
import assert from "node:assert/strict";
import { JobDiagnostics } from "../src/job-diagnostics.js";
import { envelope, item } from "./fixtures.js";
import { JOBS } from "../src/jobs.js";
import { parseItem } from "../src/protocol.js";

test("rejected page identifiers expose only field shape in worker diagnostics", () => {
  const photo = parseItem(item());
  for (const [field, value] of [
    ["dedupKey", "PRIVATE/value+="],
    ["dedupKey", "PRIVATE.value:tag~suffix%"],
    ["mediaKey", "PRIVATE_" + "a".repeat(260)],
  ]) {
    const d = new JobDiagnostics({ id: "job-a", operation: "library-page" });
    let error;
    try {
      JOBS["library-page"].validateResult({
        items: [{ ...photo, [field]: value }],
        next: null,
        complete: true,
        retentionReady: false,
      });
    } catch (failure) {
      error = failure;
    }
    assert.ok(error, "invalid identifiers must still be rejected");
    d.failure(error);
    const result = d.snapshot();
    assert.equal(result.failure.validation.field, field);
    assert.equal(result.failure.validation.expected, "id");
    assert.equal(result.failure.validation.valueType, "string");
    assert.equal(result.failure.validation.length, value.length);
    assert.equal(result.failure.validation.containsPlus, value.includes("+"));
    assert.equal(result.failure.validation.containsSlash, value.includes("/"));
    for (const [flag, character] of [
      ["containsDot", "."],
      ["containsColon", ":"],
      ["containsTilde", "~"],
      ["containsPercent", "%"],
    ])
      assert.equal(result.failure.validation[flag], value.includes(character));
    assert.equal(
      result.failure.validation.containsPadding,
      value.includes("="),
    );
    assert.ok(!JSON.stringify(result).includes("PRIVATE"));
  }
});

test("validation diagnostics do not forward arbitrary error properties", () => {
  const d = new JobDiagnostics({ id: "job-a", operation: "library-page" });
  d.failure(
    Object.assign(new Error("PRIVATE_MESSAGE"), {
      code: "INPUT",
      validation: {
        field: "PRIVATE_FIELD",
        expected: "PRIVATE_EXPECTED",
        value: "PRIVATE_VALUE",
        length: "PRIVATE_LENGTH",
      },
    }),
  );
  assert.ok(!JSON.stringify(d.snapshot()).includes("PRIVATE"));
});
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
