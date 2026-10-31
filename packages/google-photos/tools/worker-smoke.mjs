// Real extension + HTTPS/WSS server; every Google request uses synthetic fixtures.
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdtemp, cp, readFile, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
import { item, album, envelope, ACCOUNT } from "../test/fixtures.js";
const root = fileURLToPath(new URL("../../../", import.meta.url));
const temp = await mkdtemp(join(tmpdir(), "google-worker-browser-"));
const endpoint = "https://127.0.0.1:8099";
const server = spawn(
  process.env.PHOTOFLOW_TEST_PYTHON || "python3",
  ["apps/web/tests/google_worker_fixture.py"],
  {
    cwd: root,
    env: { ...process.env, PYTHONPATH: "apps/web:apps/photoflow" },
    stdio: ["ignore", "pipe", "pipe"],
  },
);
let errors = "";
server.stderr.on("data", (data) => (errors += data.toString()));
let context;
let ui, panel;
try {
  const extension = join(temp, "extension");
  await cp(new URL("../dist/capture-extension/", import.meta.url), extension, {
    recursive: true,
  });
  const desktop = join(extension, "desktop.js");
  await writeFile(
    desktop,
    (await readFile(desktop, "utf8")).replace(
      "https://photos.lbsa71.net",
      endpoint,
    ),
  );
  const manifest = JSON.parse(
    await readFile(join(extension, "manifest.json"), "utf8"),
  );
  manifest.host_permissions.push(endpoint + "/*");
  await writeFile(join(extension, "manifest.json"), JSON.stringify(manifest));
  context = await chromium.launchPersistentContext(join(temp, "profile"), {
    headless: true,
    channel: "chromium",
    ignoreHTTPSErrors: true,
    args: [
      "--ignore-certificate-errors",
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`,
    ],
  });
  let calls = 0;
  await context.route("https://photos.google.com/**", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith("/batchexecute")) {
      calls++;
      const rpc = url.searchParams.get("rpcids");
      let payload;
      const args = JSON.parse(
        JSON.parse(
          new URLSearchParams(route.request().postData()).get("f.req"),
        )[0][0][1],
      );
      if (rpc === "lcxiM")
        payload = args[0] ? [[item("media-b")], null] : [[item()], "next"];
      else if (rpc === "EzkLib") payload = [[item("media-a", true)], null];
      else if (rpc === "Z5xsfc") payload = [[album()], null];
      else throw Error("Unexpected RPC");
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: envelope(rpc, payload),
      });
    }
    return route.fulfill({
      contentType: "text/html",
      body: `<h1>Synthetic Google Photos</h1><script>window.WIZ_global_data=${JSON.stringify({ oPEP7c: ACCOUNT, FdrFJe: "PRIVATE_SESSION", cfb2h: "build", eptZe: "/_/PhotosUi/", SNlM0e: "PRIVATE_CSRF" })}</script>`,
    });
  });
  let healthy = false;
  for (let n = 0; n < 100; n++) {
    try {
      healthy = (await context.request.get(endpoint + "/healthz")).ok();
      if (healthy) break;
    } catch {}
    await new Promise((r) => setTimeout(r, 100));
  }
  assert.ok(healthy, errors);
  ui = await context.newPage();
  await ui.goto(endpoint + "/login");
  await ui.locator("[name=username]").fill("fixture");
  await ui.locator("[name=password]").fill("fixture-local-only");
  await ui.getByRole("button", { name: "Sign in", exact: true }).click();
  await ui.getByRole("button", { name: /Connect Google Photos/ }).click();
  await ui.getByLabel("Google account", { exact: true }).fill(ACCOUNT);
  await ui
    .getByRole("button", { name: "Create pairing code and open Google Photos" })
    .click();
  await ui.getByLabel("Pairing code", { exact: true }).waitFor();
  const code = await ui
    .getByLabel("Pairing code", { exact: true })
    .inputValue();
  const google = await context.newPage();
  await google.goto("https://photos.google.com/");
  const worker =
    context.serviceWorkers()[0] ??
    (await context.waitForEvent("serviceworker"));
  const tabId = await worker.evaluate(
    async () =>
      (await chrome.tabs.query({ url: "https://photos.google.com/*" }))[0].id,
  );
  panel = await context.newPage();
  await panel.goto(
    `chrome-extension://${new URL(worker.url()).hostname}/popup.html`,
  );
  await panel.evaluate((id) => {
    chrome.tabs.query = async () => [{ id }];
  }, tabId);
  await panel.locator("#pair-code").fill(code);
  await panel.locator("#worker-pair").click();
  await ui
    .getByRole("button", { name: "✓ Google connected", exact: true })
    .waitFor({ timeout: 30000 });
  assert.ok(await ui.getByText(/2 items, 1 favorites, 1 albums/).count());
  assert.equal(calls, 4);
  const [download] = await Promise.all([
    panel.waitForEvent("download"),
    panel.locator("#worker-diagnostics").click(),
  ]);
  const downloaded = JSON.parse(await readFile(await download.path(), "utf8"));
  assert.equal(downloaded.job.operation, "inventory-counts");
  assert.ok(downloaded.events.some((e) => e.phase === "complete"));
  assert.ok(downloaded.entries.length > 0);
  assert.ok(!JSON.stringify(downloaded).includes("PRIVATE_"));
  await ui
    .getByRole("button", { name: "Read inventory counts", exact: true })
    .click();
  await ui.waitForFunction(
    () =>
      document.querySelectorAll(".google-panel li").length === 2 &&
      [...document.querySelectorAll(".google-panel li")].every((e) =>
        e.textContent.includes("succeeded"),
      ),
  );
  assert.equal(calls, 8);
  console.log(
    JSON.stringify({
      pairing: true,
      wss: true,
      jobsCompleted: 2,
      googleRequests: calls,
      phases: true,
      sanitizedDiagnostics: true,
      realGoogleTraffic: false,
    }),
  );
} catch (error) {
  console.error(
    JSON.stringify({
      fixtureErrors: errors,
      popup: panel ? await panel.locator("#status").textContent() : null,
      ui: ui ? await ui.locator(".google-panel").textContent() : null,
    }),
  );
  throw error;
} finally {
  await context?.close();
  server.kill("SIGTERM");
  if (server.exitCode === null)
    await new Promise((resolve) => {
      server.on("exit", resolve);
      setTimeout(() => {
        server.kill("SIGKILL");
        resolve();
      }, 5000).unref();
    });
  await rm(temp, { recursive: true, force: true });
}
