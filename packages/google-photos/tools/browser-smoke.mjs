import { chromium } from "playwright";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
import { envelope, item, album, ACCOUNT } from "../test/fixtures.js";
const extension = fileURLToPath(
  new URL("../dist/capture-extension", import.meta.url),
);
const profile = await mkdtemp(join(tmpdir(), "google-capture-browser-"));
const context = await chromium.launchPersistentContext(profile, {
  headless: true,
  channel: "chromium",
  args: [
    `--disable-extensions-except=${extension}`,
    `--load-extension=${extension}`,
  ],
});
try {
  let actualRequests = 0;
  await context.route("https://photos.google.com/**", async (route) => {
    const request = route.request(),
      url = new URL(request.url());
    if (url.pathname.endsWith("/batchexecute")) {
      actualRequests++;
      const rpc = url.searchParams.get("rpcids");
      let data;
      if (rpc === "lcxiM") data = [[item()], null, "1700000000000"];
      else if (rpc === "EzkLib") data = [[item("media-a", true)], null];
      else if (rpc === "Z5xsfc") data = [[album()], null];
      else if (rpc === "VrseUb") data = [item("PRIVATE_PHOTO_ID")];
      else throw new Error(`Unexpected fixture RPC: ${rpc}`);
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: envelope(rpc, data),
      });
    }
    if (url.pathname === "/upload") {
      actualRequests++;
      return route.fulfill({
        status: 200,
        contentType: "application/octet-stream",
        body: "PRIVATE_UPLOAD_TOKEN",
      });
    }
    return route.fulfill({
      status: 200,
      contentType: "text/html",
      body: `<!doctype html><title>Fixture Google Photos</title><h1>Disposable fixture</h1><script>window.WIZ_global_data=${JSON.stringify({ oPEP7c: ACCOUNT, FdrFJe: "PRIVATE_SESSION", cfb2h: "build", eptZe: "/_/PhotosUi/", SNlM0e: "PRIVATE_CSRF" })}</script>`,
    });
  });
  // No real Google request is permitted by this test.
  const page = await context.newPage();
  await page.goto("https://photos.google.com/");
  const worker =
    context.serviceWorkers()[0] ??
    (await context.waitForEvent("serviceworker"));
  const extensionId = new URL(worker.url()).hostname;
  const panel = await context.newPage();
  await panel.goto(`chrome-extension://${extensionId}/popup.html`);
  const tabId = await worker.evaluate(async () => {
    const tabs = await chrome.tabs.query({
      url: "https://photos.google.com/*",
    });
    return tabs[0].id;
  });
  const command = (action) =>
    panel.evaluate(
      async ({ action, tabId }) =>
        chrome.runtime.sendMessage({ action, tabId }),
      { action, tabId },
    );
  assert.equal((await command("identity")).result.account, ACCOUNT);
  assert.equal((await command("start")).ok, true);
  await page.evaluate(async () => {
    const payload = new URLSearchParams({
      at: "PRIVATE_CSRF",
      "f.req": JSON.stringify([
        [
          [
            "VrseUb",
            JSON.stringify(["PRIVATE_PHOTO_ID", null]),
            null,
            "generic",
          ],
        ],
      ]),
    });
    await fetch(
      "/_/PhotosUi/data/batchexecute?rpcids=VrseUb&f.sid=PRIVATE_SESSION",
      { method: "POST", body: payload },
    );
    await fetch("/upload?upload_id=PRIVATE_UPLOAD_ID", {
      method: "POST",
      body: "PRIVATE_MEDIA_BYTES",
    });
  });
  await panel.waitForFunction(async () => {
    const s = await chrome.runtime.sendMessage({ action: "status" });
    return s.result.count >= 2;
  });
  const beforeRead = actualRequests;
  const read = await command("inventory");
  assert.equal(read.ok, true, JSON.stringify(read));
  assert.deepEqual(read.result, {
    photos: 1,
    favorites: 1,
    albums: 1,
    complete: true,
    retentionReady: false,
  });
  assert.equal(actualRequests, beforeRead + 3);
  await panel.waitForFunction(async () => {
    const s = await chrome.runtime.sendMessage({ action: "status" });
    return s.result.count >= 5;
  });
  await command("stop");
  const capture = (await command("export")).result.capture;
  assert.equal(capture.entries.length, 5);
  assert.equal(capture.complete, true);
  assert.ok(!JSON.stringify(capture).includes("PRIVATE_"));
  assert.equal(
    actualRequests,
    5,
    "Recorder must never replay observed requests",
  );
  console.log(
    JSON.stringify({
      browser: "Chromium",
      captured: capture.entries.length,
      actualRequests,
      inventory: read.result,
      secretLeak: false,
    }),
  );
} finally {
  await context.close();
  await rm(profile, { recursive: true, force: true });
}
