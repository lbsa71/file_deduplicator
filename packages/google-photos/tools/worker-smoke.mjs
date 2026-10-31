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
const endpoint = "https://localhost:8100";
const targetPolicy = process.env.PHOTOFLOW_TEST_PILOT_POLICY || "fixtures";
const server = spawn(
  process.env.PHOTOFLOW_TEST_PYTHON || "python3",
  ["apps/web/tests/google_worker_fixture.py"],
  {
    cwd: root,
    env: {
      ...process.env,
      PYTHONPATH: "apps/web:apps/photoflow",
      PHOTOFLOW_WORKER_FIXTURE_PORT: "8100",
      PHOTOFLOW_GOOGLE_PILOT_ACCOUNT: ACCOUNT,
      PHOTOFLOW_GOOGLE_PILOT_TARGET_POLICY: targetPolicy,
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
      ...(process.env.PHOTOFLOW_TEST_PAGE_TLS_ONLY
        ? []
        : ["--ignore-certificate-errors"]),
      `--disable-extensions-except=${extension}`,
      `--load-extension=${extension}`,
    ],
  });
  const fixture = toolkitBrowserFixture({
    personal: targetPolicy === "selected",
  });
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
  const originalInfo = await context.request.get(
    endpoint + "/fixture-original-info",
  );
  assert.ok(originalInfo.ok());
  fixture.state.originalSize = (await originalInfo.json()).size;
  assert.ok(Number.isSafeInteger(fixture.state.originalSize));
  ui = await context.newPage();
  await ui.goto(endpoint + "/login");
  await ui.locator("[name=username]").fill("fixture");
  await ui.locator("[name=password]").fill("fixture-local-only");
  await ui.getByRole("button", { name: "Sign in", exact: true }).click();
  await ui.getByRole("button", { name: /Connect Google Photos/ }).click();
  await ui.getByLabel("Google account", { exact: true }).fill(ACCOUNT);
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
  await panel.getByLabel("PhotoFlow server endpoint").fill(endpoint);
  await panel.evaluate((id) => {
    chrome.tabs.query = async () => [{ id }];
  }, tabId);
  await panel.locator("#pair-code").fill("x".repeat(43));
  await panel.locator("#worker-pair").click();
  await panel.getByText(/PhotoFlow rejected pairing/).waitFor();
  await panel.reload();
  await panel.waitForFunction(
    (origin) => document.querySelector("#worker-origin")?.value === origin,
    endpoint,
  );
  // Normal app UI now performs pairing without opening the extension popup.
  await ui
    .getByRole("button", {
      name: "Connect through installed extension",
      exact: true,
    })
    .click();
  await ui
    .getByRole("button", { name: "✓ Google connected", exact: true })
    .waitFor({ timeout: 30000 });
  await ui.getByText(/2 items, 1 favorites, 1 albums/).waitFor();
  assert.ok(await ui.getByText(/2 items, 1 favorites, 1 albums/).count());
  assert.equal(fixture.calls, 4);
  // Reopening the popup must restore the endpoint bound to this pairing.
  await panel.reload();
  await panel.waitForFunction(
    (origin) =>
      document.querySelector("#worker-origin")?.value === origin &&
      !document.querySelector("#worker-status")?.disabled,
    endpoint,
  );
  await panel.locator("#worker-status").click();
  await panel.waitForFunction((origin) => {
    try {
      return (
        JSON.parse(document.querySelector("#status").textContent).origin ===
        origin
      );
    } catch {
      return false;
    }
  }, endpoint);
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
      "I authorize this finite pilot on the selected photos in the configured account.",
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
  await ui
    .getByLabel("Individual operation", { exact: true })
    .selectOption("download-original");
  await ui
    .getByLabel("Job input JSON", { exact: true })
    .fill(
      JSON.stringify({ photoUrl: "https://photos.google.com/photo/media-a" }),
    );
  for (const count of [29, 30]) {
    await ui
      .getByRole("button", { name: "Queue selected operation", exact: true })
      .click();
    await ui.waitForFunction(
      (count) => {
        const jobs = [...document.querySelectorAll(".google-panel ol>li")];
        return (
          jobs.length === count &&
          jobs.every((e) => e.textContent.includes("succeeded"))
        );
      },
      count,
      { timeout: 30000 },
    );
  }
  const imported = await ui.evaluate(async () => {
    const status = await (await fetch("/api/v1/google/status")).json();
    return Promise.all(
      status.jobs
        .slice(0, 2)
        .map(
          async (job) =>
            (await (await fetch(`/api/v1/google/jobs/${job.id}/result`)).json())
              .result,
        ),
    );
  });
  assert.deepEqual(
    imported.map((r) => r.outcome),
    ["already-present", "imported"],
  );
  assert.equal(imported[0].recordId, imported[1].recordId);
  await ui
    .getByRole("button", { name: "Check local original", exact: true })
    .click();
  const localMatch = ui.getByRole("region", {
    name: "Local original verification",
  });
  await localMatch
    .getByText("Local original verified", { exact: true })
    .waitFor();
  assert.equal(
    await localMatch
      .getByRole("link", { name: "Open local original" })
      .getAttribute("href"),
    `/photos/${imported[0].recordId}`,
  );
  await ui
    .getByLabel("Selected library photo URL", { exact: true })
    .fill("https://photos.google.com/photo/not-mapped");
  assert.equal(
    await localMatch.count(),
    0,
    "old verification must disappear when target changes",
  );
  await ui
    .getByRole("button", { name: "Check local original", exact: true })
    .click();
  await localMatch
    .getByText(
      "No account-bound local mapping. A local copy may still exist.",
      { exact: true },
    )
    .waitFor();
  assert.equal(await localMatch.getByRole("link").count(), 0);
  assert.equal(
    await ui.locator(".google-panel ol>li").count(),
    30,
    "local checks must not queue Google jobs",
  );
  // Exercise preparation/inspection/hash-bound commit through the actual UI.
  // The fixture asset is explicitly expendable; no real Google traffic is sent.
  fixture.state.favorite = false;
  await ui
    .getByText("Prepare and commit reconciliation", { exact: true })
    .click();
  await ui
    .getByLabel("Reconciliation photo URLs", { exact: true })
    .fill("https://photos.google.com/photo/media-a");
  if (targetPolicy === "selected")
    await ui
      .getByText(
        "I confirm the selected photos are non-vital and authorize a Trash pilot.",
        { exact: true },
      )
      .click();
  const beforePrepare = fixture.state.writes.length;
  await ui
    .getByRole("button", { name: "Prepare dry-run manifest", exact: true })
    .click();
  await ui
    .getByRole("button", { name: "Inspect prepared manifest", exact: true })
    .first()
    .waitFor({ timeout: 90000 });
  assert.equal(
    fixture.state.writes.length,
    beforePrepare,
    "Preparation must not mutate Google",
  );
  await ui
    .getByRole("button", { name: "Inspect prepared manifest", exact: true })
    .first()
    .click();
  const preview = ui.getByRole("region", {
    name: "Prepared reconciliation manifest",
  });
  const manifestText = await preview.locator("p").first().textContent();
  const manifestId = manifestText.match(/Manifest ([a-f0-9]{32})/)[1];
  const [manifestDownload] = await Promise.all([
    ui.waitForEvent("download"),
    preview
      .getByRole("button", {
        name: "Download full private manifest",
        exact: true,
      })
      .click(),
  ]);
  const downloadedManifest = await readFile(
    await manifestDownload.path(),
    "utf8",
  );
  const authoritativeManifest = await ui.evaluate(
    async (id) =>
      (
        await fetch(
          "/api/v1/google/reconciliation/manifests/" + id + "/download",
        )
      ).text(),
    manifestId,
  );
  assert.equal(
    downloadedManifest,
    authoritativeManifest,
    "Manifest download must preserve original bytes and large timestamps",
  );

  await preview
    .getByText(
      "I reviewed this manifest and authorize its listed executable operations.",
      { exact: true },
    )
    .click();
  await preview
    .getByRole("button", { name: "Commit reviewed manifest", exact: true })
    .click();
  await ui
    .locator(".google-reconciliation li")
    .filter({ hasText: "google.commit: succeeded" })
    .waitFor({ timeout: 60000 });
  assert.equal(fixture.state.trashed, targetPolicy === "selected");
  assert.equal(
    fixture.state.writes.length,
    beforePrepare + (targetPolicy === "selected" ? 1 : 0),
  );
  if (targetPolicy === "selected") {
    fixture.state.trashed = false;
    assert.ok((await context.request.post(endpoint + "/fixture-takeout")).ok());
    await ui
      .getByText(
        "I confirm the selected photos are non-vital and authorize a Trash pilot.",
        { exact: true },
      )
      .click();
    await ui.getByLabel("Reconciliation photo URLs", { exact: true }).fill("");
    await ui
      .getByRole("button", { name: "Prepare dry-run manifest", exact: true })
      .click();
    await ui
      .locator(".google-reconciliation li")
      .filter({ hasText: "google.prepare: succeeded" })
      .nth(1)
      .waitFor({ timeout: 90000 });
    // Read the synthetic server state to distinguish the new completed command.
    await ui.waitForFunction(
      async () => {
        const j = await (await fetch("/api/v1/google/reconciliation")).json();
        return (
          j.items[0]?.action === "google.prepare" &&
          j.items[0]?.state === "succeeded"
        );
      },
      null,
      { timeout: 90000 },
    );
    await ui
      .getByRole("button", { name: "Inspect prepared manifest", exact: true })
      .first()
      .click();
    await preview
      .getByRole("button", { name: "Prepare Takeout Trash sweep", exact: true })
      .click();
    await ui.waitForFunction(
      async () => {
        const j = await (await fetch("/api/v1/google/reconciliation")).json();
        return (
          j.items[0]?.action === "google.prepare-takeout" &&
          j.items[0]?.state === "succeeded"
        );
      },
      null,
      { timeout: 90000 },
    );
    await ui
      .locator(".google-reconciliation li")
      .filter({ hasText: "google.prepare-takeout: succeeded" })
      .waitFor({ timeout: 90000 });
    await ui
      .getByRole("button", { name: "Inspect prepared manifest", exact: true })
      .first()
      .click();
    await preview
      .locator("pre")
      .filter({ hasText: '"takeout-trash"' })
      .waitFor({ timeout: 30000 });
    assert.match(await preview.textContent(), /takeout-trash/);
    const sweepId = (await preview.locator("p").first().textContent()).match(
      /Manifest ([a-f0-9]{32})/,
    )[1];
    await preview
      .getByText(
        "I reviewed this manifest and authorize its listed executable operations.",
        { exact: true },
      )
      .click();
    await preview
      .getByRole("button", { name: "Commit reviewed manifest", exact: true })
      .click();
    let sweepCommit;
    for (let n = 0; n < 300; n++) {
      const response = await context.request.get(
        endpoint + "/api/v1/google/reconciliation",
      );
      sweepCommit = (await response.json()).items.find(
        (x) => x.action === "google.commit" && x.params.manifestId === sweepId,
      );
      if (
        sweepCommit &&
        ["succeeded", "partial", "failed"].includes(sweepCommit.state)
      )
        break;
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    assert.equal(sweepCommit?.state, "succeeded", JSON.stringify(sweepCommit));
    assert.equal(fixture.state.trashed, true);
    assert.equal(fixture.state.writes.length, beforePrepare + 2);
  }
  if (targetPolicy === "selected") {
    // A separate exact manifest fails before intent, then keeps a newly protected
    // untitled shared-album member when the same worker intent is retried.
    fixture.state.trashed = false;
    async function commands() {
      return (
        await (
          await context.request.get(endpoint + "/api/v1/google/reconciliation")
        ).json()
      ).items;
    }
    async function waitCommand(predicate) {
      let found;
      for (let n = 0; n < 450; n++) {
        found = (await commands()).find(predicate);
        if (found && ["succeeded", "partial", "failed"].includes(found.state))
          return found;
        await new Promise((resolve) => setTimeout(resolve, 200));
      }
      throw new Error(
        "Timed out waiting for exact synthetic command " +
          JSON.stringify(found),
      );
    }
    assert.ok((await context.request.post(endpoint + "/fixture-takeout")).ok());
    const beforeIds = new Set((await commands()).map((j) => j.id));
    await ui
      .getByRole("button", { name: "Prepare dry-run manifest", exact: true })
      .click();
    const source = await waitCommand(
      (j) => j.action === "google.prepare" && !beforeIds.has(j.id),
    );
    assert.equal(source.state, "succeeded");
    await ui
      .locator(`[data-reconciliation-job="${source.id}"]`)
      .getByRole("button", { name: "Inspect prepared manifest", exact: true })
      .click();
    await preview
      .getByRole("button", { name: "Prepare Takeout Trash sweep", exact: true })
      .click();
    const prepared = await waitCommand(
      (j) =>
        j.action === "google.prepare-takeout" &&
        j.params.sourceManifestId === source.id,
    );
    assert.equal(prepared.state, "succeeded");
    await ui
      .locator(`[data-reconciliation-job="${prepared.id}"]`)
      .getByRole("button", { name: "Inspect prepared manifest", exact: true })
      .click();
    await preview.getByText(new RegExp("Manifest " + prepared.id)).waitFor();
    fixture.state.invalidDetails = true;
    await preview
      .getByText(
        "I reviewed this manifest and authorize its listed executable operations.",
        { exact: true },
      )
      .click();
    await preview
      .getByRole("button", { name: "Commit reviewed manifest", exact: true })
      .click();
    const failed = await waitCommand(
      (j) =>
        j.action === "google.commit" && j.params.manifestId === prepared.id,
    );
    assert.equal(failed.state, "partial");
    assert.equal(fixture.state.writes.length, beforePrepare + 2);
    fixture.state.invalidDetails = false;
    fixture.state.member = true;
    fixture.state.untitledMembership = true;
    await ui
      .getByRole("button", { name: "Retry failed preflight", exact: true })
      .click();
    await ui
      .locator(".google-panel ol>li")
      .filter({ hasText: "trash: succeeded — unchanged" })
      .waitFor({ timeout: 30000 });
    await ui
      .locator(`[data-reconciliation-job="${failed.id}"]`)
      .getByRole("button", { name: "Resume interrupted commit", exact: true })
      .click();
    const finished = await waitCommand((j) => j.id === failed.id);
    // retry/resume is asynchronous; require the exact command to finish again.
    let final = finished;
    for (let n = 0; n < 150 && final.state !== "succeeded"; n++) {
      await new Promise((resolve) => setTimeout(resolve, 200));
      final = (await commands()).find((j) => j.id === failed.id);
    }
    assert.equal(final.state, "succeeded", JSON.stringify(final));
    assert.equal(fixture.state.trashed, false);
    assert.equal(fixture.state.writes.length, beforePrepare + 2);
  }
  const completedJobs = await ui.locator(".google-panel ol>li").count();
  console.log(
    JSON.stringify({
      targetPolicy,
      pairing: true,
      pagePairing: true,
      failedPairingPreservesEndpoint: true,
      wss: true,
      jobsCompleted: completedJobs,
      dryRunManifestAndCommit: true,
      preparationDidNotMutateGoogle: true,
      manifestDownloadExactBytes: true,
      fixtureOperationTypes: 23,
      directOriginalImport: true,
      duplicateOriginalSkipped: true,
      accountBoundLocalVerification: true,
      lostWriteReconciledWithoutReplay: true,
      googleRequests: fixture.calls,
      phases: true,
      sanitizedDiagnostics: true,
      productionTakeoutSweep: targetPolicy === "selected",
      preflightRetryPreservesUntitledAlbumMember: targetPolicy === "selected",
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
