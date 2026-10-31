import test from "node:test";
import assert from "node:assert/strict";
import { pageRequest, createPageTransport } from "../src/browser.js";
import { ACCOUNT, envelope } from "./fixtures.js";
const session = {
  oPEP7c: ACCOUNT,
  FdrFJe: "session-secret",
  cfb2h: "build",
  eptZe: "/_/PhotosUi/",
  SNlM0e: "csrf-secret",
};
const request = {
  account: ACCOUNT,
  rpc: "VrseUb",
  data: ["media-a", null, null, null, null],
  operation: "item",
  mode: "read",
};

test("identity inspection returns synchronously without waiting on a page Promise or sending traffic", () => {
  const saved = {
    location: globalThis.location,
    WIZ_global_data: globalThis.WIZ_global_data,
    fetch: globalThis.fetch,
  };
  try {
    globalThis.location = new URL("https://photos.google.com/");
    globalThis.WIZ_global_data = { ...session };
    globalThis.fetch = () => {
      throw new Error("Identity must not send traffic");
    };
    assert.deepEqual(pageRequest({ operation: "identity" }), {
      account: ACCOUNT,
    });
  } finally {
    Object.assign(globalThis, saved);
  }
});
test("browser transport binds origin and account and never exports session values", async () => {
  const saved = {
    location: globalThis.location,
    WIZ_global_data: globalThis.WIZ_global_data,
    fetch: globalThis.fetch,
  };
  try {
    globalThis.location = new URL("https://photos.google.com/");
    globalThis.WIZ_global_data = { ...session };
    let calls = 0;
    globalThis.fetch = async (url, options) => {
      calls++;
      assert.equal(new URL(url).origin, "https://photos.google.com");
      assert.equal(options.credentials, "include");
      return new Response(envelope("VrseUb", [[]]), { status: 200 });
    };
    const result = await pageRequest(request);
    assert.equal(result.status, 200);
    assert.equal(calls, 1);
    assert.ok(!JSON.stringify(result).includes("secret"));
    globalThis.WIZ_global_data.oPEP7c = "other";
    assert.equal((await pageRequest(request)).error, "ACCOUNT");
    assert.equal(calls, 1);
    globalThis.location = new URL("https://evil.example/");
    assert.equal((await pageRequest(request)).error, "ORIGIN");
    assert.equal(calls, 1);
  } finally {
    Object.assign(globalThis, saved);
  }
});
test("account switch during fetch yields an error and there are no retries", async () => {
  const saved = {
    location: globalThis.location,
    WIZ_global_data: globalThis.WIZ_global_data,
    fetch: globalThis.fetch,
  };
  try {
    globalThis.location = new URL("https://photos.google.com/");
    globalThis.WIZ_global_data = { ...session };
    let calls = 0;
    globalThis.fetch = async () => {
      calls++;
      globalThis.WIZ_global_data.oPEP7c = "other";
      return new Response(envelope("VrseUb", [[]]));
    };
    assert.equal((await pageRequest(request)).error, "ACCOUNT");
    assert.equal(calls, 1);
  } finally {
    Object.assign(globalThis, saved);
  }
});
test("read-only browser transport refuses mutations and endpoint substitution", async () => {
  const saved = {
    location: globalThis.location,
    WIZ_global_data: globalThis.WIZ_global_data,
    fetch: globalThis.fetch,
  };
  try {
    globalThis.location = new URL("https://photos.google.com/");
    globalThis.WIZ_global_data = { ...session };
    let calls = 0;
    globalThis.fetch = async () => {
      calls++;
    };
    assert.equal(
      (await pageRequest({ ...request, rpc: "XwAOJf", mode: "write" })).error,
      "UNQUALIFIED",
    );
    globalThis.WIZ_global_data.eptZe = "https://evil.example/";
    assert.equal((await pageRequest(request)).error, "SESSION");
    assert.equal(calls, 0);
  } finally {
    Object.assign(globalThis, saved);
  }
});
test("evaluation adapter reports controlled errors without exposing browser exception content", async () => {
  const transport = createPageTransport({
    evaluate: async () => {
      throw new Error("SECRET_COOKIE");
    },
  });
  await assert.rejects(
    transport(request),
    (e) => e.code === "TRANSPORT" && !e.message.includes("SECRET"),
  );
});

test("failed reads identify a safe transport phase without exposing exception content", async () => {
  const saved = {
    location: globalThis.location,
    WIZ_global_data: globalThis.WIZ_global_data,
    fetch: globalThis.fetch,
  };
  try {
    globalThis.location = new URL("https://photos.google.com/");
    globalThis.WIZ_global_data = { ...session };
    let calls = 0;
    globalThis.fetch = async () => {
      calls++;
      throw new TypeError("PRIVATE_FETCH_TOKEN");
    };
    const result = await pageRequest(request);
    assert.deepEqual(result, {
      error: "TRANSPORT",
      diagnostic: { stage: "fetch", reason: "TypeError" },
    });
    assert.equal(calls, 1);
    assert.ok(!JSON.stringify(result).includes("PRIVATE_"));
  } finally {
    Object.assign(globalThis, saved);
  }
});

test("a response stream failure is distinct from a fetch or parser failure", async () => {
  const saved = {
    location: globalThis.location,
    WIZ_global_data: globalThis.WIZ_global_data,
    fetch: globalThis.fetch,
  };
  try {
    globalThis.location = new URL("https://photos.google.com/");
    globalThis.WIZ_global_data = { ...session };
    let calls = 0;
    globalThis.fetch = async () => {
      calls++;
      return new Response(
        new ReadableStream({
          start(controller) {
            controller.error(new TypeError("PRIVATE_STREAM_URL"));
          },
        }),
        { status: 200 },
      );
    };
    const result = await pageRequest(request);
    assert.deepEqual(result, {
      error: "TRANSPORT",
      diagnostic: { stage: "body", reason: "TypeError" },
    });
    assert.equal(calls, 1);
    assert.ok(!JSON.stringify(result).includes("PRIVATE_"));
  } finally {
    Object.assign(globalThis, saved);
  }
});
