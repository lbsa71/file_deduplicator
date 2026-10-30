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
      postData: new URLSearchParams({
        "f.req": JSON.stringify([
          [["VrseUb", JSON.stringify(["media-a"]), null, "generic"]],
        ]),
      }).toString(),
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

test("omitted structured response bodies cannot produce complete evidence or replay traffic", async (t) => {
  const postData = new URLSearchParams({
    "f.req": JSON.stringify([
      [["VrseUb", JSON.stringify(["media-a"]), null, "generic"]],
    ]),
  }).toString();
  for (const fixture of [
    {
      name: "encoded size limit",
      encodedDataLength: 1024 * 1024 + 1,
      calls: 0,
    },
    {
      name: "decoded size limit",
      encodedDataLength: 100,
      body: " ".repeat(1024 * 1024 + 1),
      calls: 1,
    },
    {
      name: "base64 text body",
      encodedDataLength: 100,
      body: "PRIVATE_BASE64_BODY",
      base64Encoded: true,
      calls: 1,
    },
    { name: "missing text body", encodedDataLength: 100, calls: 1 },
  ]) {
    await t.test(fixture.name, async () => {
      const commands = [];
      const recorder = new PassiveRecorder({
        send: async (method) => {
          commands.push(method);
          return { body: fixture.body, base64Encoded: fixture.base64Encoded };
        },
        now: () => 0,
      });
      await recorder.event("Network.requestWillBeSent", {
        requestId: "a",
        type: "Fetch",
        request: {
          url: "https://photos.google.com/_/PhotosUi/data/batchexecute?rpcids=VrseUb",
          method: "POST",
          postData,
        },
      });
      await recorder.event("Network.responseReceived", {
        requestId: "a",
        response: { status: 200, mimeType: "application/json" },
      });
      await recorder.event("Network.loadingFinished", {
        requestId: "a",
        encodedDataLength: fixture.encodedDataLength,
      });
      const capture = recorder.export();
      assert.equal(capture.complete, false);
      assert.equal(capture.pending, 0);
      assert.equal(capture.entries.length, 1);
      assert.equal(capture.entries[0].response.bodyOmitted, true);
      assert.equal(typeof capture.entries[0].response.captureError, "string");
      assert.deepEqual(
        commands,
        Array(fixture.calls).fill("Network.getResponseBody"),
      );
      assert.ok(!JSON.stringify(capture).includes("PRIVATE_BASE64_BODY"));
    });
  }
});

test("missing, oversized, and malformed RPC request bodies mark evidence incomplete", async (t) => {
  for (const postData of [
    undefined,
    " ".repeat(1024 * 1024 + 1),
    "f.req=PRIVATE_BAD_JSON",
  ]) {
    await t.test(
      postData === undefined
        ? "missing"
        : postData.length > 1024 * 1024
          ? "oversized"
          : "malformed",
      async () => {
        const commands = [];
        const recorder = new PassiveRecorder({
          send: async (method) => {
            commands.push(method);
            return { body: envelope("VrseUb", [item()]) };
          },
          now: () => 0,
        });
        await recorder.event("Network.requestWillBeSent", {
          requestId: "a",
          type: "Fetch",
          request: {
            url: "https://photos.google.com/_/PhotosUi/data/batchexecute?rpcids=VrseUb",
            method: "POST",
            hasPostData: true,
            postData,
          },
        });
        await recorder.event("Network.responseReceived", {
          requestId: "a",
          response: { status: 200, mimeType: "application/json" },
        });
        await recorder.event("Network.loadingFinished", {
          requestId: "a",
          encodedDataLength: 100,
        });
        const capture = recorder.export();
        assert.equal(capture.complete, false);
        assert.equal(capture.entries[0].request.bodyOmitted, true);
        assert.equal(typeof capture.entries[0].request.captureError, "string");
        assert.deepEqual(commands, ["Network.getResponseBody"]);
        assert.ok(!JSON.stringify(capture).includes("PRIVATE_BAD_JSON"));
      },
    );
  }
});
