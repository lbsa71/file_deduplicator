import { chromium } from "@playwright/test";
const browser = await chromium.launch({
  headless: true,
  args: [
    "--no-sandbox",
    ...(process.env.PHOTOFLOW_TEST_RESOLVE
      ? ["--host-resolver-rules=" + process.env.PHOTOFLOW_TEST_RESOLVE]
      : []),
  ],
});
const page = await browser.newPage({
  ignoreHTTPSErrors: process.env.PHOTOFLOW_TEST_INSECURE === "1",
  viewport: { width: 1440, height: 1000 },
});
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.goto(process.env.PHOTOFLOW_TEST_URL || "https://192.168.1.4:8443");
await page.getByLabel("Linux username").fill(process.env.PHOTOFLOW_TEST_USER);
await page
  .getByLabel("Password", { exact: true })
  .fill(process.env.PHOTOFLOW_TEST_PASSWORD);
await page.getByRole("button", { name: "Sign in", exact: true }).click();
await page.locator(".tile").first().waitFor({ timeout: 60000 });
await page.locator(".tile img").first().waitFor({ timeout: 60000 });
await page.screenshot({ path: "/tmp/photoflow-desktop.png" });
const records = await page.evaluate(async () =>
  (await fetch("/api/v1/photos")).json(),
);
const still = records.items.find((record) =>
  /\.(jpe?g|png|heic)$/i.test(record.path),
);
if (!still) throw Error("No still image on the first page");
const tile = page.locator(`[data-record-id="${still.id}"]`);
await tile.scrollIntoViewIfNeeded();
await tile.locator("img").waitFor({ timeout: 60000 });
if (process.env.PHOTOFLOW_TEST_PREVIEW_FALLBACK === "1") {
  await page.route(`**/photos/${still.id}/variants/2048`, (route) =>
    route.fulfill({
      status: 415,
      contentType: "application/json",
      body: '{"state":"failed"}',
    }),
  );
}
const fullPreview = page.waitForResponse(
  (response) =>
    response.url().endsWith(`/photos/${still.id}/variants/2048`) &&
    response.status() ===
      (process.env.PHOTOFLOW_TEST_PREVIEW_FALLBACK === "1" ? 415 : 200),
  { timeout: 60000 },
);
await tile.locator("button").click();
await page.locator(".viewer").waitFor();
const previewResponse = await fullPreview;
if (
  process.env.PHOTOFLOW_TEST_PREVIEW_FALLBACK !== "1" &&
  !previewResponse.headers()["content-type"].startsWith("image/webp")
) {
  throw Error("Viewer did not receive a browser-ready image");
}
await page.locator(".viewer img").waitFor({ timeout: 60000 });
if (process.env.PHOTOFLOW_TEST_PREVIEW_FALLBACK === "1") {
  await page.locator('.viewer img[title="Showing smaller preview"]').waitFor();
}
await page.keyboard.press("Escape");
if (await page.locator(".viewer").count())
  throw Error("Escape did not close viewer");
await page.setViewportSize({ width: 390, height: 844 });
await page.screenshot({ path: "/tmp/photoflow-mobile.png" });
if (errors.length) throw Error(errors.join("\n"));
console.log(
  "Browser smoke passed: Linux login, timeline, image, viewer, Escape, mobile; no page errors",
);
await browser.close();
