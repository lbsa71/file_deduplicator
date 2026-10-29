import { chromium } from "@playwright/test";
const browser = await chromium.launch({
  headless: true,
  args: ["--no-sandbox"],
});
const page = await browser.newPage({
  ignoreHTTPSErrors: true,
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
await page.locator(".tile>button").first().click();
await page.locator(".viewer").waitFor();
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
