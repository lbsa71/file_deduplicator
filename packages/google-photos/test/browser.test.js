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

test("pilot browser writes require an unexpired isolated-account scope bound to operation and target", async () => {
  const saved = {
    location: globalThis.location,
    WIZ_global_data: globalThis.WIZ_global_data,
    fetch: globalThis.fetch,
  };
  let calls = 0;
  try {
    globalThis.location = new URL("https://photos.google.com/");
    globalThis.WIZ_global_data = { ...session };
    globalThis.fetch = async () => {
      calls++;
      return new Response(envelope("Ftfh0", [true]), { status: 200 });
    };
    const scope = {
      testOnly: true,
      account: ACCOUNT,
      jobId: "pilot-a",
      operation: "favorite-set",
      expiresAt: Date.now() + 60000,
      photoKey: "media-a",
      albumId: null,
    };
    const request = {
      account: ACCOUNT,
      operation: "favorite-set",
      mode: "write",
      rpc: "Ftfh0",
      data: [[[null, "dedup-a"]], [1]],
      testScope: scope,
      targetMediaKey: "media-a",
      targetAlbumId: null,
    };
    for (const patch of [
      { testScope: null },
      { testScope: { ...scope, account: "other" } },
      { testScope: { ...scope, expiresAt: 1 } },
      { targetMediaKey: "other" },
      { targetAlbumId: "other" },
      { rpc: "XwAOJf" },
    ])
      assert.equal(
        (await pageRequest({ ...request, ...patch })).error,
        "UNQUALIFIED",
      );
    assert.equal(calls, 0);
    assert.equal((await pageRequest(request)).status, 200);
    assert.equal(calls, 1);
  } finally {
    Object.assign(globalThis, saved);
  }
});

test("serialized page requests preserve explicit null target bindings across Chrome injection", async () => {
  const saved = {
    location: globalThis.location,
    WIZ_global_data: globalThis.WIZ_global_data,
    fetch: globalThis.fetch,
  };
  try {
    globalThis.location = new URL("https://photos.google.com/");
    globalThis.WIZ_global_data = { ...session };
    let calls = 0;
    globalThis.fetch = async (_url, options) => {
      calls++;
      assert.deepEqual(
        JSON.parse(
          JSON.parse(new URLSearchParams(options.body).get("f.req"))[0][0][1],
        ),
        ["PhotoFlow test fixture", null, 2],
      );
      return new Response(envelope("OXvT9d", [["album-created"]]));
    };
    const value = {
      account: ACCOUNT,
      rpc: "OXvT9d",
      operation: "album-create",
      mode: "write",
      data: ["PhotoFlow test fixture", null, 2],
      targetMediaKey: null,
      targetAlbumId: null,
      testScope: {
        testOnly: true,
        account: ACCOUNT,
        operation: "album-create",
        jobId: "job",
        expiresAt: Date.now() + 60000,
        photoKey: null,
        albumId: null,
      },
    };
    assert.equal((await pageRequest(JSON.stringify(value))).status, 200);
    assert.equal(calls, 1);
    assert.equal((await pageRequest("{broken")).error, "INPUT");
    assert.equal(calls, 1);
  } finally {
    Object.assign(globalThis, saved);
  }
});
