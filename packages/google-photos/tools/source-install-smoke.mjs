import { chromium } from "playwright";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

// Unkeyed unpacked IDs are derived from the native absolute path. See Chromium's
// components/crx_file/id_util.cc; Windows paths use UTF-16 with an uppercase drive.
export async function assertSourceNotInstallable() {
  let source = fileURLToPath(new URL("../capture-extension/", import.meta.url));
  source = source.replace(/[\\/]$/, "");
  if (process.platform === "win32")
    source = source[0].toUpperCase() + source.slice(1);
  const hash = createHash("sha256")
    .update(
      Buffer.from(source, process.platform === "win32" ? "utf16le" : "utf8"),
    )
    .digest("hex")
    .slice(0, 32);
  const id = [...hash]
    .map((char) => String.fromCharCode(97 + parseInt(char, 16)))
    .join("");
  const profile = await mkdtemp(join(tmpdir(), "google-capture-source-"));
  let context;
  try {
    context = await chromium.launchPersistentContext(profile, {
      headless: true,
      channel: "chromium",
      args: [
        `--disable-extensions-except=${source}`,
        `--load-extension=${source}`,
      ],
    });
    await context.route("https://**/*", (route) => route.abort());
    const page = await context.newPage();
    await assert.rejects(
      page.goto(`chrome-extension://${id}/popup.html`, {
        waitUntil: "domcontentloaded",
        timeout: 5000,
      }),
      /ERR_BLOCKED_BY_CLIENT|ERR_FAILED/,
      "The incomplete source directory must not expose an installable popup",
    );
  } finally {
    if (context) await context.close();
    await rm(profile, { recursive: true, force: true });
  }
}
