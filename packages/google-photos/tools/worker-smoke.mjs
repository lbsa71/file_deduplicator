// Real extension + HTTPS/WSS server; every Google request uses synthetic fixtures.
import { chromium } from "playwright";
import { spawn } from "node:child_process";
import { mkdtemp, cp, readFile, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
import { ACCOUNT } from "../test/fixtures.js";
import { toolkitBrowserFixture } from "../test/toolkit-browser-fixture.js";
const root = fileURLToPath(new URL("../../../", import.meta.url));
const temp = await mkdtemp(join(tmpdir(), "google-worker-browser-"));
const endpoint = "https://127.0.0.1:8099";
const server = spawn(
  process.env.PHOTOFLOW_TEST_PYTHON || "python3",
  ["apps/web/tests/google_worker_fixture.py"],
  {
    cwd: root,
    env: {
      ...process.env,
      PYTHONPATH: "apps/web:apps/photoflow",
      PHOTOFLOW_GOOGLE_TEST_ACCOUNT: ACCOUNT,
    },
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
  const fixture = toolkitBrowserFixture();
  await context.route("https://photos.google.com/**", (route) =>
    fixture.route(route),
  );
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
  assert.equal(fixture.calls, 4);
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
  assert.equal(fixture.calls, 8);
  await ui
    .getByText("Operation workbench and qualification suite", { exact: true })
    .click();
  await ui
    .getByLabel("Selected library photo URL", { exact: true })
    .fill("https://photos.google.com/photo/media-a");
  await ui.getByLabel("Selected album ID", { exact: true }).fill("album-a");
  await ui
    .getByLabel("Optional opaque Google hashes", { exact: true })
    .fill("opaque");
  await ui
    .getByText(
      "I am testing synthetic media in the configured isolated account.",
      { exact: true },
    )
    .click();
  await ui.getByLabel(/Pilot metadata/).fill(
    JSON.stringify({
      timestampSec: 1700001000,
      timezoneSec: 3600,
      location: {
        centerE7: [10000000, 20000000],
        visible1E7: [9000000, 19000000],
        visible2E7: [11000000, 21000000],
        scale: 14,
        placeId: "fixture-place",
      },
    }),
  );
  await ui
    .getByRole("button", {
      name: "Prepare read and write pilot suite",
      exact: true,
    })
    .click();
  await ui
    .getByRole("button", { name: "Queue prepared suite", exact: true })
    .click();
  await ui.waitForFunction(
    () =>
      document.querySelectorAll(".google-panel ol>li").length === 26 &&
      [...document.querySelectorAll(".google-panel ol>li")].every((e) =>
        /: (succeeded|failed|unknown|blocked)/.test(e.textContent),
      ),
    {},
    { timeout: 60000 },
  );
  assert.equal(
    await ui
      .locator(".google-panel ol>li")
      .filter({ hasText: /: (failed|unknown|blocked)/ })
      .count(),
    0,
  );
  assert.equal(fixture.state.trashed, false);
  assert.equal(fixture.state.favorite, false);
  assert.equal(fixture.state.archived, false);
  assert.equal(fixture.state.member, false);
  assert.equal(fixture.state.location, null);
  assert.ok(fixture.state.writes.includes("ycV3Nd"));
  assert.ok(fixture.state.writes.includes("EtUHOe"));
  fixture.state.failNextWrite = true;
  await ui
    .getByLabel("Individual operation", { exact: true })
    .selectOption("favorite-set");
  await ui
    .getByRole("button", { name: "Queue selected operation", exact: true })
    .click();
  await ui.waitForFunction(() =>
    [...document.querySelectorAll(".google-panel ol>li")].some((e) =>
      e.textContent.includes("unknown"),
    ),
  );
  const row = await ui
    .locator(".google-panel ol>li")
    .filter({ hasText: "unknown" })
    .first()
    .getByRole("button", { name: "Download job diagnostics" });
  const [failedDownload] = await Promise.all([
    ui.waitForEvent("download"),
    row.click(),
  ]);
  const failed = JSON.parse(
    await readFile(await failedDownload.path(), "utf8"),
  );
  const writesBefore = fixture.state.writes.length;
  await ui
    .getByLabel("Individual operation", { exact: true })
    .selectOption("reconcile-write");
  await ui
    .getByLabel("Job input JSON", { exact: true })
    .fill(JSON.stringify({ originalJobId: failed.job.id }));
  await ui
    .getByRole("button", { name: "Queue selected operation", exact: true })
    .click();
  await ui.waitForFunction(
    () =>
      document.querySelectorAll(".google-panel ol>li").length === 28 &&
      [...document.querySelectorAll(".google-panel ol>li")].every((e) =>
        e.textContent.includes("succeeded"),
      ),
    {},
    { timeout: 30000 },
  );
  assert.equal(fixture.state.writes.length, writesBefore);
  console.log(
    JSON.stringify({
      pairing: true,
      wss: true,
      jobsCompleted: 28,
      fixtureOperationTypes: 22,
      lostWriteReconciledWithoutReplay: true,
      googleRequests: fixture.calls,
      phases: true,
      sanitizedDiagnostics: true,
      realGoogleTraffic: false,
    }),
  );
} catch (error) {
  if (panel)
    console.error(
      JSON.stringify(
        await panel.evaluate(async () => ({
          diagnostics: (await chrome.storage.session.get("workerDiagnostics"))
            .workerDiagnostics,
        })),
      ),
    );
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
