import test from "node:test";
import assert from "node:assert/strict";
import { CaptureSanitizer, PassiveRecorder } from "../src/capture.js";
import { envelope, item } from "./fixtures.js";

test("capture preserves protocol structure and consistent opaque identities without credentials or photo text", () => {
  const s = new CaptureSanitizer();
  const req = s.request({
    url: "https://photos.google.com/u/0/_/PhotosUi/data/batchexecute?rpcids=VrseUb&f.sid=SECRET",
    method: "POST",
    headers: { Cookie: "COOKIE", Authorization: "Bearer TOKEN" },
    postData: new URLSearchParams({
      at: "CSRF",
      "f.req": JSON.stringify([
        [
          [
            "VrseUb",
            JSON.stringify(["private-photo-id", null]),
            null,
            "generic",
          ],
        ],
      ]),
    }).toString(),
  });
  const res = s.response(
    { status: 200, mimeType: "application/json" },
    envelope("VrseUb", [item("private-photo-id")]),
  );
  const serialized = JSON.stringify({ req, res });
  for (const secret of [
    "SECRET",
    "COOKIE",
    "TOKEN",
    "CSRF",
    "private-photo-id",
    "example.invalid",
  ])
    assert.ok(!serialized.includes(secret), secret);
  assert.equal(req.rpcRequests[0].rpc, "VrseUb");
  assert.equal(req.rpcRequests[0].data[0], res.rpcResponses[0].data[0][0]);
  assert.equal(res.rpcResponses[0].data[0][15]["163238866"], undefined);
});
test("upload bytes and opaque upload tokens are never exported", () => {
  const s = new CaptureSanitizer();
  const req = s.request({
    url: "https://photos.google.com/upload?upload_id=secret",
    method: "POST",
    headers: { "Content-Type": "image/jpeg", "X-Goog-Upload-Offset": "0" },
    postData: "PRIVATE_BINARY",
  });
  const res = s.response(
    { status: 200, mimeType: "application/octet-stream" },
    "PRIVATE_UPLOAD_TOKEN",
  );
  assert.ok(!JSON.stringify({ req, res }).includes("PRIVATE"));
  assert.equal(req.bodyOmitted, true);
  assert.equal(res.bodyOmitted, true);
});
test("malformed structured bodies produce omitted markers without exporting raw data", () => {
  const s = new CaptureSanitizer();
  const res = s.response(
    { status: 200, mimeType: "application/json" },
    "bad PRIVATE_CONTENT",
  );
  assert.equal(res.bodyOmitted, true);
  assert.ok(!JSON.stringify(res).includes("PRIVATE_CONTENT"));
});
test("passive recorder never replays requests after body retrieval failure", async () => {
  const commands = [];
  const r = new PassiveRecorder({
    send: async (method) => {
      commands.push(method);
      throw new Error("body unavailable");
    },
    now: () => 1,
  });
  await r.event("Network.requestWillBeSent", {
    requestId: "a",
    type: "XHR",
    request: {
      url: "https://photos.google.com/_/PhotosUi/data/batchexecute?rpcids=VrseUb",
      method: "POST",
    },
  });
  await r.event("Network.responseReceived", {
    requestId: "a",
    response: { status: 200, mimeType: "application/json" },
  });
  await r.event("Network.loadingFinished", {
    requestId: "a",
    encodedDataLength: 10,
  });
  assert.deepEqual(commands, ["Network.getResponseBody"]);
  assert.equal(r.export().entries[0].response.bodyOmitted, true);
});
test("binary responses and unrelated hosts are not read, bounded capture marks incompleteness", async () => {
  const commands = [];
  const r = new PassiveRecorder({
    send: async (m) => commands.push(m),
    now: () => 1,
    maxEntries: 1,
  });
  for (const id of ["a", "b"]) {
    await r.event("Network.requestWillBeSent", {
      requestId: id,
      type: "XHR",
      request: { url: "https://photos.google.com/upload", method: "POST" },
    });
    await r.event("Network.responseReceived", {
      requestId: id,
      response: { status: 200, mimeType: "image/jpeg" },
    });
    await r.event("Network.loadingFinished", {
      requestId: id,
      encodedDataLength: 100,
    });
  }
  assert.equal(commands.length, 0);
  assert.equal(r.export().complete, false);
});

test("detachment, missing responses, and byte limits cannot produce a complete capture", async () => {
  const r = new PassiveRecorder({
    send: async () => ({ body: "{}" }),
    maxBytes: 100,
    now: () => 0,
  });
  await r.event("Network.requestWillBeSent", {
    requestId: "a",
    type: "XHR",
    request: { url: "https://photos.google.com/upload", method: "POST" },
  });
  await r.event("Network.loadingFinished", {
    requestId: "a",
    encodedDataLength: 0,
  });
  assert.equal(r.export().complete, false);
  r.invalidate();
  assert.equal(r.export().complete, false);
});

test("export cannot race an in-flight response-body retrieval", async () => {
  let resolve;
  const r = new PassiveRecorder({
    send: () =>
      new Promise((r) => {
        resolve = r;
      }),
    now: () => 0,
  });
  await r.event("Network.requestWillBeSent", {
    requestId: "a",
    type: "XHR",
    request: {
      url: "https://photos.google.com/_/PhotosUi/data/batchexecute?rpcids=VrseUb",
      method: "POST",
    },
  });
  await r.event("Network.responseReceived", {
    requestId: "a",
    response: { status: 200, mimeType: "application/json" },
  });
  const pending = r.event("Network.loadingFinished", {
    requestId: "a",
    encodedDataLength: 100,
  });
  assert.equal(r.export().complete, false);
  resolve({ body: envelope("VrseUb", [item()]) });
  await pending;
  assert.equal(r.export().complete, true);
});

test("malformed protocol responses mark the capture incomplete", async () => {
  const r = new PassiveRecorder({
    send: async () => ({ body: "not-json" }),
    now: () => 0,
  });
  await r.event("Network.requestWillBeSent", {
    requestId: "a",
    type: "XHR",
    request: {
      url: "https://photos.google.com/_/PhotosUi/data/batchexecute",
      method: "POST",
    },
  });
  await r.event("Network.responseReceived", {
    requestId: "a",
    response: { status: 200, mimeType: "application/json" },
  });
  await r.event("Network.loadingFinished", {
    requestId: "a",
    encodedDataLength: 8,
  });
  assert.equal(r.export().complete, false);
});
