import { chromium } from "playwright";
import { mkdtemp, rm, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";
import assert from "node:assert/strict";
import { envelope, item, album, ACCOUNT } from "../test/fixtures.js";
import { assertSourceNotInstallable } from "./source-install-smoke.mjs";
await assertSourceNotInstallable();
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
        body: envelope(
          rpc,
          url.searchParams.get("probe") === "oversized"
            ? ["x".repeat(1024 * 1024 + 1)]
            : data,
        ),
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
  await worker.evaluate(async () => {
    await chrome.storage.session.set({
      capture: {
        entries: [{ padding: "x".repeat(8 * 1024 * 1024) }],
        complete: false,
      },
      readInspection: { kind: "google-photos-read-failure", complete: false },
    });
  });
  assert.equal(
    (await command("export")).ok,
    false,
    "Combined export must retain the 8 MiB limit",
  );
  await worker.evaluate(() =>
    chrome.storage.session.remove(["capture", "readInspection"]),
  );
  async function waitForCapture(count) {
    const deadline = Date.now() + 10000;
    while (Date.now() < deadline) {
      const status = await command("status");
      assert.equal(status.ok, true);
      if (status.result.count >= count) return;
      await delay(25);
    }
    throw new Error(
      `Capture did not reach ${count} entries before the deadline`,
    );
  }
  // A tab-hosted popup needs an explicit synthetic active-tab context. The real
  // popup uses the user's active Photos tab, not its own extension document.
  await panel.evaluate((tabId) => {
    const query = chrome.tabs.query.bind(chrome.tabs);
    chrome.tabs.query = (options) =>
      options.active ? Promise.resolve([{ id: tabId }]) : query(options);
  }, tabId);
  await panel.locator("#identity").click();
  await panel.waitForFunction(() =>
    document.querySelector("#status").textContent.includes("fixture-account"),
  );
  assert.deepEqual(JSON.parse(await panel.locator("#status").textContent()), {
    account: ACCOUNT,
  });
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
  await waitForCapture(2);
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
  await waitForCapture(5);
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
  // Exercise the actual popup download path, keeping the synthetic capture in
  // this test's disposable profile directory.
  const downloaded = panel.waitForEvent("download");
  await panel.locator("#export").click();
  const download = await downloaded;
  const downloadPath = join(profile, "synthetic.capture.json");
  await download.saveAs(downloadPath);
  assert.deepEqual(JSON.parse(await readFile(downloadPath, "utf8")), capture);

  // A bounded recording may observe the request yet omit the structured body.
  // That is incomplete evidence, even when all observed HTTP requests succeed.
  assert.equal((await command("start")).ok, true);
  await page.evaluate(async () => {
    await fetch("/_/PhotosUi/data/batchexecute?rpcids=VrseUb&probe=oversized", {
      method: "POST",
      body: new URLSearchParams({
        "f.req": JSON.stringify([
          [["VrseUb", '["synthetic-media"]', null, "generic"]],
        ]),
      }),
    });
  });
  await waitForCapture(1);
  await command("stop");
  const omitted = (await command("export")).result.capture;
  assert.equal(omitted.entries.length, 1);
  assert.equal(omitted.complete, false);
  assert.equal(omitted.entries[0].response.bodyOmitted, true);
  assert.equal(typeof omitted.entries[0].response.captureError, "string");
  assert.equal(actualRequests, 6, "An omitted body must not trigger a replay");

  await page.evaluate(
    (body) => {
      window.fetch = async () => new Response(body, { status: 200 });
    },
    ")]}'\n1\n" +
      envelope("lcxiM", [[item("PRIVATE_MEDIA")], "PRIVATE_CURSOR"]).split(
        "\n",
      )[2],
  );
  const protocolFailure = await command("inventory");
  assert.equal(protocolFailure.ok, false);
  assert.equal(protocolFailure.diagnostic.code, "PROTOCOL");
  const evidence = (await command("export")).result.capture.readInspection;
  assert.equal(evidence.rule, "RPC_FRAME_LENGTH");
  assert.equal(evidence.response.rpcResponses[0].rpc, "lcxiM");
  assert.ok(!JSON.stringify(evidence).includes("PRIVATE_"));
  assert.equal(actualRequests, 6, "Read evidence must not replay a request");

  await page.evaluate(() => {
    window.fetch = async () =>
      new Response(
        new ReadableStream({
          start(controller) {
            controller.error(new TypeError("PRIVATE_RESPONSE_FAILURE"));
          },
        }),
        { status: 200 },
      );
  });
  await panel.locator("#inventory").click();
  await panel.waitForFunction(() =>
    document.querySelector("#status").textContent.includes("response body"),
  );
  const readFailure = await panel.locator("#status").textContent();
  assert.ok(readFailure.includes("TypeError"));
  assert.ok(!readFailure.includes("PRIVATE_"));
  assert.equal(
    actualRequests,
    6,
    "A failed response must not trigger another read",
  );

  // Exercise the actual popup handler with a stalled browser injection. This
  // stays inside the synthetic profile and must not issue any photo request.
  await worker.evaluate(() => {
    chrome.scripting.executeScript = () => new Promise(() => {});
  });
  await panel.clock.install();
  await panel.locator("#identity").click();
  assert.equal(await panel.locator("#identity").isDisabled(), true);
  await panel.clock.fastForward(10001);
  await panel.waitForFunction(() =>
    document.querySelector("#status").textContent.includes("timed out"),
  );
  assert.equal(await panel.locator("#identity").isDisabled(), false);
  assert.equal(
    actualRequests,
    6,
    "A stalled identity check must not issue or replay traffic",
  );
  console.log(
    JSON.stringify({
      browser: "Chromium",
      browserVersion: context.browser().version(),
      captured: capture.entries.length,
      actualRequests,
      inventory: read.result,
      secretLeak: false,
      downloadVerified: true,
      oversizedCaptureComplete: omitted.complete,
      connectionCheckUi: true,
      connectionTimeoutVerified: true,
      sourceDirectoryRejected: true,
      safeReadDiagnosticVerified: true,
    }),
  );
} finally {
  await context.close();
  await rm(profile, { recursive: true, force: true });
}
