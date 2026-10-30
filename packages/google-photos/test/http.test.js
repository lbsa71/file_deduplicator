import test from "node:test";
import assert from "node:assert/strict";
import { createOAuthTransport } from "../src/http.js";
test("OAuth transport validates account and exact endpoint before attaching credentials", async () => {
  let sent = 0;
  const transport = createOAuthTransport({
    account: "a",
    credentials: async () => ({ account: "a", accessToken: "private-token" }),
    fetch: async (url, options) => {
      sent++;
      assert.equal(options.redirect, "error");
      assert.equal(options.headers.Authorization, "Bearer private-token");
      return new Response("ok");
    },
  });
  for (const url of [
    "https://evil.example/",
    "https://photoslibrary.googleapis.com.evil.example/v1/uploads",
    "https://photoslibrary.googleapis.com/v1/albums",
    "https://photoslibrary.googleapis.com/v1/uploads?redirect=evil",
  ])
    await assert.rejects(transport({ account: "a", url, method: "POST" }));
  assert.equal(sent, 0);
  const r = await transport({
    account: "a",
    url: "https://photoslibrary.googleapis.com/v1/uploads",
    method: "POST",
    body: new Uint8Array([1]),
  });
  assert.equal(sent, 1);
  assert.equal(r.account, "a");
  assert.ok(!JSON.stringify(r).includes("private-token"));
});
