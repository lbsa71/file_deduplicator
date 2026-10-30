import { chromium, expect } from "@playwright/test";
const base = (
  process.env.PHOTOFLOW_TEST_URL || "https://photos.lbsa71.net"
).replace(/\/$/, "");
const id = "99b8980a-6721-4641-b41c-3d81e81c3b5d";
const photo = `/photos/${id}?q=00010005`;
const browser = await chromium.launch({
  headless: true,
  args: [
    "--no-sandbox",
    ...(process.env.PHOTOFLOW_TEST_RESOLVE
      ? ["--host-resolver-rules=" + process.env.PHOTOFLOW_TEST_RESOLVE]
      : []),
  ],
});
const context = await browser.newContext({
  ignoreHTTPSErrors: process.env.PHOTOFLOW_TEST_INSECURE === "1",
});
const page = await context.newPage(),
  errors = [];
page.on("pageerror", (e) => errors.push(e.message));
async function login() {
  await page.getByLabel("Linux username").fill(process.env.PHOTOFLOW_TEST_USER);
  await page
    .getByLabel("Password", { exact: true })
    .fill(process.env.PHOTOFLOW_TEST_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}
try {
  const first = await page.goto(base + photo);
  expect(first.status()).toBe(200);
  await login();
  await expect(page.locator(".viewer")).toBeVisible();
  expect(new URL(page.url()).pathname).toBe("/photos/" + id);
  await expect(page.locator(".details h2")).toHaveText("00010005.JPG");
  await page.reload();
  await expect(page.locator(".viewer")).toBeVisible();
  const copied = await context.newPage();
  await copied.goto(page.url());
  await expect(copied.locator(".viewer")).toBeVisible();
  await copied.close();
  await page.keyboard.press("Escape");
  await page.waitForURL(base + "/photos?q=00010005");
  await expect(page.locator(".viewer")).toHaveCount(0);
  const tile = page.locator(`[data-record-id="${id}"] .photo-link`);
  await expect(tile).toHaveAttribute("href", photo);
  await tile.click();
  await page.waitForURL(base + photo);
  await expect(page.locator(".viewer")).toBeVisible();
  await page.goBack();
  await expect(page.locator(".viewer")).toHaveCount(0);
  await page.goForward();
  await expect(page.locator(".viewer")).toBeVisible();
  await page.goto(base + "/folders/photos/2000/09");
  await expect(page.locator(".folders strong")).toHaveText("photos/2000/09");
  await page.reload();
  await expect(page.locator(".folders strong")).toHaveText("photos/2000/09");
  await page.getByRole("link", { name: "Favorites", exact: true }).click();
  await page.waitForURL(base + "/favorites");
  await page.getByLabel("Search library").fill("Alma");
  await page.waitForURL(base + "/favorites?q=Alma");
  await page.reload();
  await expect(page.getByLabel("Search library")).toHaveValue("Alma");
  await expect(page.locator(".heading h2")).toHaveText("Favorites");
  await page.goto(base + "/photos?q=00010005");
  await page.locator(`[data-record-id="${id}"] .photo-link`).waitFor();
  await context.clearCookies();
  await page.locator(`[data-record-id="${id}"] .photo-link`).click();
  await page.getByRole("button", { name: "Sign in", exact: true }).waitFor();
  expect(new URL(page.url()).pathname).toBe("/photos/" + id);
  await login();
  await expect(page.locator(".viewer")).toBeVisible();
  await context.clearCookies();
  await page.goto(base + "/login?next=" + encodeURIComponent(photo));
  await login();
  await page.waitForURL(base + photo);
  await expect(page.locator(".viewer")).toBeVisible();
  await page.goto(
    base + "/login?next=" + encodeURIComponent("https://example.org/"),
  );
  await page.waitForURL(base + "/photos");
  const missing = await page.evaluate(async () =>
    Promise.all(
      ["/api/v1/missing", "/assets/missing.js"].map(async (url) => {
        const response = await fetch(url);
        return [response.status, response.headers.get("content-type")];
      }),
    ),
  );
  for (const [status, type] of missing) {
    expect(status).toBe(404);
    expect(type).not.toContain("text/html");
  }
  await page.goto(base + "/photos/00000000-0000-0000-0000-000000000000");
  await expect(page.getByRole("alert")).toContainText("Photo unavailable");
  expect(errors).toEqual([]);
  console.log(
    "Routing passed: pasted photo, sign-in return, refresh, new tab, Back/Forward, editable folder URL, persisted search, safe redirect, and genuine 404s",
  );
} finally {
  await browser.close();
}
