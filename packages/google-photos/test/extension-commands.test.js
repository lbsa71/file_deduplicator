import test from "node:test";
import assert from "node:assert/strict";
import { setImmediate as flush } from "node:timers/promises";
import { createCommandClient } from "../capture-extension/commands.js";

function harness({ query, send } = {}) {
  const calls = [];
  const timers = new Map();
  let timerId = 0;
  const command = createCommandClient({
    chrome: {
      tabs: {
        query: async (options) => {
          calls.push("tabs");
          return query ? query(options) : [{ id: 7 }];
        },
      },
      runtime: {
        sendMessage: async (message) => {
          calls.push(message);
          return send
            ? send(message)
            : { ok: true, result: { account: "test-account" } };
        },
      },
    },
    setTimeout: (callback) => {
      const id = ++timerId;
      timers.set(id, callback);
      return id;
    },
    clearTimeout: (id) => timers.delete(id),
  });
  return {
    command,
    calls,
    expire: () => {
      for (const callback of [...timers.values()]) callback();
    },
    timers,
  };
}

test("a stalled connection check reaches a timeout without retrying or issuing another command", async () => {
  const h = harness({ send: () => new Promise(() => {}) });
  let outcome = "waiting";
  const result = h.command("identity").then(
    () => {
      outcome = "success";
    },
    (error) => {
      outcome = error.message;
    },
  );
  await flush();
  h.expire();
  await flush();
  assert.match(outcome, /timed out/i);
  assert.deepEqual(h.calls, ["tabs", { action: "identity", tabId: 7 }]);
  assert.equal(h.timers.size, 0);
  await result;
});

test("a stalled tab lookup times out before any message can be sent", async () => {
  const h = harness({ query: () => new Promise(() => {}) });
  let outcome = "waiting";
  const result = h.command("identity").catch((error) => {
    outcome = error.message;
  });
  h.expire();
  await flush();
  assert.match(outcome, /timed out/i);
  assert.deepEqual(h.calls, ["tabs"]);
  await result;
});

test("a tab lookup that completes after timeout cannot send a late command", async () => {
  let resolve;
  const h = harness({
    query: () =>
      new Promise((done) => {
        resolve = done;
      }),
  });
  let outcome = "waiting";
  const result = h.command("start").catch((error) => {
    outcome = error.message;
  });
  h.expire();
  await flush();
  assert.match(outcome, /timed out/i);
  resolve([{ id: 7 }]);
  await flush();
  assert.deepEqual(h.calls, ["tabs"]);
  await result;
});

test("missing or malformed extension replies produce a controlled error", async () => {
  for (const response of [
    undefined,
    null,
    {},
    { ok: "yes" },
    { ok: true, result: null },
  ]) {
    const h = harness({ send: () => response });
    await assert.rejects(h.command("identity"), /could not be verified/i);
  }
});

test("browser exception details and untrusted errors are not displayed", async () => {
  for (const send of [
    () => {
      throw new Error("PRIVATE_TOKEN");
    },
    () => ({ ok: false, error: "PRIVATE_TOKEN" }),
  ]) {
    const h = harness({ send });
    await assert.rejects(
      h.command("identity"),
      (error) =>
        !error.message.includes("PRIVATE_TOKEN") &&
        /could not be verified/i.test(error.message),
    );
  }
});

test("successful connection checks return the result and release their deadline", async () => {
  const h = harness();
  assert.deepEqual(await h.command("identity"), { account: "test-account" });
  assert.equal(h.timers.size, 0);
});

test("missing or invalid active tabs cannot send an extension command", async () => {
  for (const tabs of [[], [{ id: "7" }], [{ id: -1 }]]) {
    const h = harness({ query: () => tabs });
    await assert.rejects(h.command("identity"), /could not be verified/i);
    assert.deepEqual(h.calls, ["tabs"]);
    assert.equal(h.timers.size, 0);
  }
});

test("read failures expose only allowlisted diagnostic codes and phases", async () => {
  const h = harness({
    send: () => ({
      ok: false,
      error: "PRIVATE_TOKEN",
      diagnostic: {
        code: "TRANSPORT",
        stage: "body",
        reason: "TypeError",
        details: "PRIVATE_URL",
      },
    }),
  });
  await assert.rejects(
    h.command("inventory"),
    (error) =>
      /response body/i.test(error.message) &&
      /TypeError/.test(error.message) &&
      !error.message.includes("PRIVATE_"),
  );
  assert.deepEqual(h.calls, ["tabs", { action: "inventory", tabId: 7 }]);
  const unknown = harness({
    send: () => ({
      ok: false,
      diagnostic: {
        code: "PRIVATE_TOKEN",
        stage: "PRIVATE_STAGE",
        reason: "PRIVATE_REASON",
      },
    }),
  });
  await assert.rejects(
    unknown.command("inventory"),
    (error) =>
      /could not be verified/i.test(error.message) &&
      !error.message.includes("PRIVATE_"),
  );
});

test("selected inspection forwards explicit selection and prevents command envelope overrides", async () => {
  const h = harness();
  const selection = {
    account: "a",
    albumUrl: "https://photos.google.com/album/b",
    photoUrl: "https://photos.google.com/photo/c",
    action: "start",
    tabId: 999,
  };
  await h.command("inspect", selection);
  assert.deepEqual(h.calls[1], {
    action: "inspect",
    tabId: 7,
    selection: {
      account: "a",
      albumUrl: selection.albumUrl,
      photoUrl: selection.photoUrl,
    },
  });
});
