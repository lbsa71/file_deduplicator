import { PassiveRecorder, sanitizeReadEvidence } from "./lib/capture.js";
import { GooglePhotosClient } from "./lib/client.js";
import { pageRequest, createPageTransport } from "./lib/browser.js";
import { inspectSelection } from "./lib/inspection.js";
import { installDesktopWorker } from "./desktop.js";
import { sanitizeReadDiagnostic } from "./diagnostics.js";
let tabId = null,
  recorder = null,
  inflight = new Set(),
  busy = false,
  report = null;
async function photoTab(id) {
  const tab = await chrome.tabs.get(id);
  if (!tab.url || new URL(tab.url).origin !== "https://photos.google.com")
    throw new Error("Select a Google Photos tab");
  return tab;
}
async function evaluate(id, fn, arg) {
  await photoTab(id);
  const results = await chrome.scripting.executeScript({
    target: { tabId: id },
    world: "MAIN",
    injectImmediately: true,
    func: fn,
    args: [arg],
  });
  if (results.length !== 1 || results[0].frameId !== 0)
    throw new Error("Unexpected browser frame");
  return results[0].result;
}
const desktop = installDesktopWorker(evaluate);
async function stop() {
  if (tabId !== null) {
    const id = tabId;
    tabId = null;
    await Promise.allSettled([...inflight]);
    try {
      await chrome.debugger.detach({ tabId: id });
    } catch {
      /* Already detached by navigation or user. */
    }
  }
  if (recorder)
    await chrome.storage.session.set({ capture: recorder.export() });
}
chrome.debugger.onEvent.addListener((source, method, params) => {
  if (source.tabId !== tabId || !recorder) return;
  const task = recorder.event(method, params).catch(() => {
    recorder.invalidate();
    report = { error: "Capture event could not be recorded" };
  });
  inflight.add(task);
  task.finally(() => inflight.delete(task));
});
chrome.debugger.onDetach.addListener((source) => {
  if (source.tabId === tabId) {
    tabId = null;
    recorder.invalidate();
    report = {
      error:
        "Capture detached; start a new capture before relying on completeness",
    };
    void chrome.storage.session.set({ capture: recorder.export() });
  }
});
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (
    sender.id !== chrome.runtime.id ||
    !sender.url?.startsWith(chrome.runtime.getURL(""))
  )
    return false;
  (async () => {
    switch (message.action) {
      case "worker-diagnostics":
      case "worker-pair":
      case "worker-status":
      case "worker-disconnect":
      case "worker-connect":
        return await desktop.command(message.action, message);
      case "status":
        return {
          recording: tabId !== null,
          busy,
          report,
          count: recorder?.export().entries.length ?? 0,
        };
      case "start": {
        if (tabId !== null || busy)
          throw new Error("A capture or inspection is already active");
        await photoTab(message.tabId);
        const id = message.tabId;
        await chrome.debugger.attach({ tabId: id }, "1.3");
        try {
          await chrome.debugger.sendCommand({ tabId: id }, "Network.enable", {
            maxTotalBufferSize: 8 * 1024 * 1024,
            maxResourceBufferSize: 1024 * 1024,
            maxPostDataSize: 65536,
          });
        } catch (e) {
          await chrome.debugger.detach({ tabId: id });
          throw e;
        }
        recorder = new PassiveRecorder({
          send: (method, params) =>
            chrome.debugger.sendCommand({ tabId: id }, method, params),
        });
        tabId = id;
        report = null;
        await chrome.storage.session.remove(["capture", "readInspection"]);
        return { recording: true };
      }
      case "stop":
        await stop();
        return { recording: false };
      case "export": {
        if (tabId !== null) throw new Error("Stop capture before exporting");
        const stored = await chrome.storage.session.get([
          "capture",
          "readInspection",
        ]);
        const capture =
          recorder?.export() ??
          stored.capture ??
          (stored.readInspection
            ? {
                schemaVersion: 1,
                kind: "google-photos-sanitized-capture",
                complete: false,
                entries: [],
                pending: 0,
              }
            : null);
        const exported = capture && {
          ...capture,
          ...(stored.readInspection
            ? { readInspection: stored.readInspection }
            : {}),
        };
        if (
          exported &&
          new TextEncoder().encode(JSON.stringify(exported)).length >
            8 * 1024 * 1024
        )
          throw new Error("Capture export limit exceeded");
        return { capture: exported };
      }
      case "identity":
        return await evaluate(message.tabId, pageRequest, {
          operation: "identity",
        });
      case "inspect": {
        if (busy) throw new Error("Inspection already active");
        busy = true;
        try {
          await chrome.storage.session.remove("readInspection");
          const identity = await evaluate(message.tabId, pageRequest, {
            operation: "identity",
          });
          if (
            !identity?.account ||
            identity.account !== message.selection?.account
          ) {
            const error = new Error("Account mismatch");
            error.diagnostic = { code: "ACCOUNT" };
            throw error;
          }
          const result = await inspectSelection(
            message.selection,
            createPageTransport({
              evaluate: (fn, arg) => evaluate(message.tabId, fn, arg),
            }),
          );
          await chrome.storage.session.set({ readInspection: result.evidence });
          report = result.summary;
          if (!result.summary.complete) {
            const error = new Error("Inspection stopped");
            error.diagnostic = result.diagnostic;
            throw error;
          }
          return result.summary;
        } finally {
          busy = false;
        }
      }
      case "inventory": {
        if (busy) throw new Error("Inspection already active");
        busy = true;
        let diagnostic = null;
        let lastRead = null;
        try {
          await chrome.storage.session.remove("readInspection");
          const identity = await evaluate(message.tabId, pageRequest, {
            operation: "identity",
          });
          if (!identity?.account) {
            diagnostic = sanitizeReadDiagnostic({ code: identity?.error });
            throw new Error("Sign in to Google Photos first");
          }
          const client = new GooglePhotosClient({
            account: identity.account,
            transport: createPageTransport({
              evaluate: async (fn, arg) => {
                const result = await evaluate(message.tabId, fn, arg);
                lastRead = { request: arg, response: result };
                if (result?.error)
                  diagnostic = sanitizeReadDiagnostic({
                    ...result.diagnostic,
                    code: result.error,
                  });
                return result;
              },
            }),
          });
          const inventory = await client.inventory(),
            favorites = await client.favorites(),
            albums = await client.albums();
          // Counts only; this is a protocol probe, not a retention-ready snapshot.
          report = {
            photos: inventory.items.length,
            favorites: favorites.items.length,
            albums: albums.items.length,
            complete: true,
            retentionReady: false,
          };
          return report;
        } catch (error) {
          if (lastRead) {
            let evidence;
            try {
              evidence = sanitizeReadEvidence(
                lastRead.request,
                lastRead.response,
                error,
              );
            } catch {
              evidence = {
                kind: "google-photos-read-failure",
                complete: false,
                response: { bodyOmitted: true },
              };
            }
            await chrome.storage.session.set({ readInspection: evidence });
          }
          const failure = new Error("Read inspection stopped");
          failure.diagnostic =
            diagnostic ?? sanitizeReadDiagnostic({ code: error?.code });
          throw failure;
        } finally {
          busy = false;
        }
      }
      default:
        throw new Error("Unsupported capture command");
    }
  })().then(
    (result) => sendResponse({ ok: true, result }),
    (error) =>
      sendResponse({
        ok: false,
        error:
          "Operation stopped. Check the Google Photos tab, sign-in, and protocol compatibility.",
        diagnostic: sanitizeReadDiagnostic(error?.diagnostic),
      }),
  );
  return true;
});
