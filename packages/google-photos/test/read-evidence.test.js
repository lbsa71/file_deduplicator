import test from "node:test";
import assert from "node:assert/strict";
import * as capture from "../src/capture.js";
import { envelope, item } from "./fixtures.js";

test("failed read evidence preserves sanitized payload and framing without private values", () => {
  const body = envelope("lcxiM", [[item("PRIVATE_MEDIA")], "PRIVATE_CURSOR"]);
  const evidence = capture.sanitizeReadEvidence(
    {
      rpc: "lcxiM",
      data: ["PRIVATE_CURSOR", null, 500],
      account: "PRIVATE_ACCOUNT",
    },
    { account: "PRIVATE_ACCOUNT", status: 200, body },
    new Error("Invalid RPC frame length"),
  );
  assert.equal(evidence.kind, "google-photos-read-failure");
  assert.equal(evidence.complete, false);
  assert.equal(evidence.rule, "RPC_FRAME_LENGTH");
  assert.equal(evidence.response.bodyOmitted, false);
  assert.equal(evidence.response.rpcResponses[0].rpc, "lcxiM");
  assert.equal(
    evidence.request.data[0],
    evidence.response.rpcResponses[0].data[1],
  );
  assert.equal(evidence.framing.xssiPrefix, true);
  assert.equal(
    evidence.framing.lines[0].utf8Bytes,
    Buffer.byteLength(body.split("\n")[2]),
  );
  assert.ok(!JSON.stringify(evidence).includes("PRIVATE_"));
});

test("failed read evidence omits oversized or unparseable bodies and unrecognized errors", () => {
  for (const body of ["PRIVATE_BAD_JSON", "é".repeat(600000)]) {
    const evidence = capture.sanitizeReadEvidence(
      { rpc: "lcxiM", data: [] },
      { status: 200, body },
      new Error("PRIVATE_ERROR_URL"),
    );
    assert.equal(evidence.complete, false);
    assert.equal(evidence.rule, undefined);
    assert.equal(evidence.response.bodyOmitted, true);
    assert.ok(!JSON.stringify(evidence).includes("PRIVATE_"));
    assert.ok(JSON.stringify(evidence).length < 4096);
  }
});

test("numeric response data cannot be exported as a frame length", () => {
  const evidence = capture.sanitizeReadEvidence(
    { rpc: "lcxiM", data: [] },
    { status: 200, body: "12345678" },
    new Error("Invalid RPC envelope"),
  );
  assert.ok(!JSON.stringify(evidence).includes("12345678"));
  assert.equal(evidence.framing.lines[0].declaredLength, undefined);
});
