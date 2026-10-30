// Read-only deployment check. Credentials come from the calling environment.
import { chromium, expect } from "@playwright/test";
const base = (
  process.env.PHOTOFLOW_TEST_URL || "https://photos.lbsa71.net"
).replace(/\/$/, "");
const browser = await chromium.launch({
  headless: true,
  args: ["--no-sandbox"],
});
const context = await browser.newContext();
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
try {
  await page.goto(base + "/photos");
  await page.getByLabel("Linux username").fill(process.env.PHOTOFLOW_TEST_USER);
  await page
    .getByLabel("Password", { exact: true })
    .fill(process.env.PHOTOFLOW_TEST_PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.locator(".grid .tile").first()).toBeVisible({
    timeout: 60000,
  });
  const response = await context.request.get(base + "/api/v1/facets");
  expect(response.ok()).toBeTruthy();
  const facets = await response.json();
  const person = facets.people.find((x) => x.count > 0);
  expect(person).toBeTruthy();
  const query = "/photos?person=" + encodeURIComponent(person.value);
  await page.goto(base + query);
  await expect(page.locator(".heading [role=status]")).toHaveText(
    `${person.count.toLocaleString()} matching photographs and videos`,
    { timeout: 60000 },
  );
  await expect(
    page
      .getByRole("group", { name: "People", exact: true })
      .locator('input[type="checkbox"]:checked'),
  ).toHaveCount(1);
  await page.reload();
  await expect(page.locator(".heading [role=status]")).toHaveText(
    `${person.count.toLocaleString()} matching photographs and videos`,
    { timeout: 60000 },
  );
  const photo = page.locator(".grid .photo-link").first();
  const href = await photo.getAttribute("href");
  expect(href).toContain("person=");
  await photo.click();
  await expect(page.locator(".viewer")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".viewer")).toHaveCount(0);
  expect(new URL(page.url()).searchParams.get("person")).toBe(person.value);
  await page.getByRole("link", { name: "Favorites", exact: true }).click();
  await page.waitForURL(base + "/favorites");
  await expect(page.locator(".query-filters")).toBeVisible();
  expect(errors).toEqual([]);
  console.log(
    JSON.stringify({
      public_query: "passed",
      canonical_photos: facets.total,
      people: facets.people.length,
      filtered_count: person.count,
      mutations: 0,
    }),
  );
} finally {
  await browser.close();
}
