import { createGoogleJobHandlers } from "./lib/google-job-handlers.js";
import { BrowserJournal } from "./lib/browser-journal.js";
import { JOB_PROTOCOL_VERSION } from "./lib/jobs.js";
import { DesktopWorker } from "./lib/worker.js";
import { GooglePhotosClient } from "./lib/client.js";
import { pageRequest, createPageTransport } from "./lib/browser.js";
const origin = "https://photos.lbsa71.net";
export function installDesktopWorker(evaluate) {
  let worker = null,
    state = "unpaired",
    backoff = 1000,
    retry = null,
    blocked = false,
    lastCloseCode = null;
  const privateStorage = chrome.storage.local.setAccessLevel({
    accessLevel: "TRUSTED_CONTEXTS",
  });
  const journal = new BrowserJournal(chrome.storage.local);
  async function credentials() {
    await privateStorage;
    return (await chrome.storage.local.get("googleWorker")).googleWorker;
  }
  async function account() {
    const tabs = await chrome.tabs.query({
      url: "https://photos.google.com/*",
    });
    const saved = await credentials();
    for (const tab of tabs) {
      const result = await bounded(() =>
        evaluate(tab.id, pageRequest, { operation: "identity" }),
      );
      if (result?.account === saved?.account)
        return { account: result.account, tabId: tab.id };
    }
    const error = new Error("Google sign-in required");
    error.code = "SESSION";
    throw error;
  }
  async function resume() {
    if (blocked) return;
    if (worker && worker.socket?.readyState <= 1) return;
    const saved = await credentials();
    if (!saved) {
      state = "unpaired";
      return;
    }
    state = "connecting";
    const current = new DesktopWorker({
      account: saved.account,
      token: saved.token,
      origin,
      getAccount: async () => (await account()).account,
      handlers: createGoogleJobHandlers({
        journal,
        readerFactory: async (expected, context) => {
          const selected = await account();
          if (selected.account !== expected)
            throw Object.assign(new Error(), { code: "ACCOUNT" });
          return new GooglePhotosClient({
            account: expected,
            maxPages: context.job.operation === "inventory-counts" ? 10000 : 5,
            maxItems:
              context.job.operation === "inventory-counts" ? 1000000 : 1000,
            transport: createPageTransport({
              evaluate: async (fn, arg) => {
                if (!context.isActive())
                  throw Object.assign(new Error(), { code: "TRANSPORT" });
                const response = await bounded(
                  () => evaluate(selected.tabId, fn, arg),
                  40000,
                );
                context.recordRead(arg, response);
                return response;
              },
            }),
          });
        },
        writeFactory: (expected, context) => async (request) => {
          if (!context.isActive())
            throw Object.assign(new Error(), { code: "TRANSPORT" });
          const selected = await account();
          if (selected.account !== expected)
            throw Object.assign(new Error(), { code: "ACCOUNT" });
          const response = await bounded(
            () => evaluate(selected.tabId, pageRequest, request),
            40000,
          );
          context.recordRead(request, response);
          return response;
        },
      }),
      saveDiagnostics: async (value) => {
        if (worker !== current) return;
        await chrome.storage.session.set({ workerDiagnostics: value });
      },
      saveReceipt: async (result) => {
        if (worker !== current) return;
        state = result.error ? "needs_login" : "connected";
        await chrome.storage.local.set({ googleWorkerReceipt: result });
      },
      onClose: (event) => {
        lastCloseCode = Number.isInteger(event?.code) ? event.code : null;
        if (worker !== current) return;
        if (event?.code === 1008) {
          state = "pairing_required";
          blocked = true;
          return;
        }
        state = "offline";
        clearTimeout(retry);
        retry = setTimeout(() => void resume().catch(() => {}), backoff);
        backoff = Math.min(30000, backoff * 2);
      },
    });
    worker = current;
    current.start();
  }
  function bounded(fn, ms = 10000) {
    return new Promise((resolve, reject) => {
      const timer = setTimeout(
        () =>
          reject(
            Object.assign(new Error("Worker deadline"), { code: "TIMEOUT" }),
          ),
        ms,
      );
      Promise.resolve()
        .then(fn)
        .then(resolve, reject)
        .finally(() => clearTimeout(timer));
    });
  }
  async function stop() {
    clearTimeout(retry);
    const previous = worker;
    worker = null;
    previous?.stop();
    state = "unpaired";
    await chrome.storage.local.remove(["googleWorker", "googleWorkerReceipt"]);
  }
  async function command(action, message) {
    if (action === "worker-diagnostics")
      return {
        capture: (await chrome.storage.session.get("workerDiagnostics"))
          .workerDiagnostics,
      };
    if (action === "worker-status")
      return {
        state,
        paired: !!(await credentials()),
        protocol: JOB_PROTOCOL_VERSION,
        lastCloseCode,
      };
    if (action === "worker-disconnect") {
      await stop();
      return { state };
    }
    if (action === "worker-connect") {
      blocked = false;
      backoff = 1000;
      await resume();
      return { state };
    }
    if (action !== "worker-pair") throw new Error("Unsupported worker action");
    if (
      typeof message.code !== "string" ||
      !/^[A-Za-z0-9_-]{43}$/.test(message.code)
    )
      throw new Error("Invalid pairing code");
    const identity = await bounded(() =>
      evaluate(message.tabId, pageRequest, { operation: "identity" }),
    );
    if (!identity?.account) throw new Error("Google sign-in required");
    const response = await fetch(origin + "/api/v1/google/pair", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: message.code, account: identity.account }),
      credentials: "omit",
      redirect: "error",
      signal: AbortSignal.timeout(10000),
    });
    if (response.status !== 200) throw new Error("Pairing failed");
    const paired = await response.json();
    if (
      paired.account !== identity.account ||
      !/^[-_A-Za-z0-9]{64}$/.test(paired.token) ||
      !/^[a-f0-9]{32}$/.test(paired.worker_id)
    )
      throw new Error("Invalid pairing reply");
    await stop();
    await chrome.storage.local.setAccessLevel({
      accessLevel: "TRUSTED_CONTEXTS",
    });
    await chrome.storage.local.set({ googleWorker: paired });
    blocked = false;
    backoff = 1000;
    await resume();
    return { state };
  }
  chrome.alarms.create("google-worker-reconnect", { periodInMinutes: 1 });
  chrome.alarms.onAlarm.addListener((alarm) => {
    if (alarm.name === "google-worker-reconnect") void resume().catch(() => {});
  });
  chrome.runtime.onStartup.addListener(() => void resume().catch(() => {}));
  void resume().catch(() => {});
  return { command };
}
