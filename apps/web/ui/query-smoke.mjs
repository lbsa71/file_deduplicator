import { chromium, expect } from "@playwright/test";
import { createHash } from "node:crypto";

// This test intentionally performs batch mutations. Only the disposable fixture
// is accepted; an accidentally inherited production URL fails before login.
const base = (
  process.env.PHOTOFLOW_TEST_URL || "https://127.0.0.1:8098"
).replace(/\/$/, "");
const url = new URL(base);
if (
  url.protocol !== "https:" ||
  !["127.0.0.1", "localhost"].includes(url.hostname)
)
  throw Error("query-smoke only runs against the disposable localhost fixture");
const browser = await chromium.launch({
  headless: true,
  args: ["--no-sandbox"],
});
const context = await browser.newContext({
  ignoreHTTPSErrors: true,
  viewport: { width: 1440, height: 1000 },
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
const count = async (n) =>
  expect(page.locator(".heading [role=status]")).toHaveText(
    `${n} matching photographs and videos`,
  );
const dialog = () => page.locator("dialog.workspace-modal");
const people = () => page.getByRole("group", { name: "People", exact: true });
async function read(path) {
  const response = await context.request.get(base + "/api/v1" + path);
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json();
}
async function originals(items) {
  const hashes = {};
  for (const item of items) {
    const response = await context.request.get(
      base + "/api/v1/photos/" + item.id + "/original",
    );
    expect(response.ok()).toBeTruthy();
    hashes[item.id] = createHash("sha256")
      .update(await response.body())
      .digest("hex");
  }
  return hashes;
}
async function renderedPreview() {
  const image = page.locator(".grid .tile").first().locator("img");
  await expect(image).toBeVisible({ timeout: 30000 });
  await expect
    .poll(() =>
      image.evaluate((element) => element.complete && element.naturalWidth > 0),
    )
    .toBe(true);
}
async function noHorizontalOverflow() {
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      ),
    )
    .toBeLessThanOrEqual(1);
}

try {
  await page.goto(base + "/photos");
  await page
    .getByLabel("Linux username")
    .fill(process.env.PHOTOFLOW_TEST_USER || "fixture");
  await page
    .getByLabel("Password", { exact: true })
    .fill(process.env.PHOTOFLOW_TEST_PASSWORD || "fixture-local-only");
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await count(108);
  const before = await read("/photos?limit=200");
  expect(before.total).toBe(108);
  const hashes = await originals(before.items);
  await expect(page.locator(".grid .tile")).toHaveCount(100);
  await renderedPreview();
  await noHorizontalOverflow();

  // A delayed selection response belongs to the query at the time of the click.
  // Changing the query while it is in flight must not select the old result set.
  let releaseSelection, selectionReceived;
  const heldSelection = new Promise((resolve) => {
    releaseSelection = resolve;
  });
  const receivedSelection = new Promise((resolve) => {
    selectionReceived = resolve;
  });
  const selectionURL = "**/api/v1/selections";
  await page.route(selectionURL, async (route) => {
    const response = await route.fetch();
    selectionReceived();
    await heldSelection;
    await route.fulfill({ response });
  });
  await page
    .getByRole("button", { name: "Select all 108 matching", exact: true })
    .click();
  await receivedSelection;
  await people()
    .getByRole("checkbox", { name: /^Ellen/ })
    .check();
  await count(72);
  releaseSelection();
  await expect(
    page.getByRole("button", { name: "Select all 72 matching", exact: true }),
  ).toBeEnabled();
  await expect(page.locator(".selection")).toHaveCount(0);
  await page.unroute(selectionURL);
  await page
    .getByRole("button", { name: "Clear filters", exact: true })
    .click();
  await count(108);

  await people()
    .getByRole("checkbox", { name: /^Ellen/ })
    .check();
  await count(72);
  await people()
    .getByRole("checkbox", { name: /^Viktor/ })
    .check();
  await count(108);
  const anyURL = page.url();
  await page.getByLabel("People match mode").selectOption("all");
  await count(36);
  const allURL = page.url();
  expect(allURL).not.toBe(anyURL);
  await page.reload();
  await count(36);
  await expect(page.getByLabel("People match mode")).toHaveValue("all");
  await expect(
    people().getByRole("checkbox", { name: /^Ellen/ }),
  ).toBeChecked();
  await page.goBack();
  await count(108);
  expect(page.url()).toBe(anyURL);
  await page.goForward();
  await count(36);

  await page
    .getByLabel("Capture date from", { exact: true })
    .fill("2009-01-01");
  await page
    .getByLabel("Capture date through", { exact: true })
    .fill("2009-12-31");
  await page.getByRole("button", { name: "Apply dates", exact: true }).click();
  await count(18);
  await page
    .getByRole("group", { name: "Favourites", exact: true })
    .getByRole("radio", { name: "Yes", exact: true })
    .check();
  await count(9);
  await page.reload();
  await count(9);
  await expect(
    page.getByLabel("Capture date from", { exact: true }),
  ).toHaveValue("2009-01-01");

  await page.getByRole("button", { name: "Save view", exact: true }).click();
  await dialog().getByLabel("Name", { exact: true }).fill("Together in 2009");
  await dialog().getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog()).toHaveCount(0);
  await page.goto(base + "/photos");
  await count(108);
  await page
    .getByRole("link", { name: "Together in 2009", exact: true })
    .click();
  await count(9);
  await page
    .getByRole("button", { name: "Manage Together in 2009", exact: true })
    .click();
  await dialog().getByLabel("Name", { exact: true }).fill("Family favourites");
  await dialog().getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog()).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "Family favourites", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Clear filters", exact: true })
    .click();
  await count(108);
  await page
    .getByRole("button", { name: "Manage Family favourites", exact: true })
    .click();
  await dialog()
    .getByRole("checkbox", { name: "Replace filters with the current view" })
    .check();
  await dialog().getByRole("button", { name: "Save", exact: true }).click();
  await expect(dialog()).toHaveCount(0);
  await people()
    .getByRole("checkbox", { name: /^Ellen/ })
    .check();
  await count(72);
  await page
    .getByRole("link", { name: "Family favourites", exact: true })
    .click();
  await count(108);
  await page
    .getByRole("button", { name: "Manage Family favourites", exact: true })
    .click();
  await dialog()
    .getByRole("button", { name: "Delete saved view", exact: true })
    .click();
  await expect(dialog()).toHaveCount(0);
  await expect(
    page.getByRole("link", { name: "Family favourites", exact: true }),
  ).toHaveCount(0);

  await page
    .getByRole("button", { name: "Select all 108 matching", exact: true })
    .click();
  await expect(page.locator(".selection strong")).toHaveText("108 selected");
  await page
    .getByRole("button", { name: "Batch actions", exact: true })
    .click();
  await dialog()
    .getByLabel("Labels — one per line", { exact: true })
    .fill("Reviewed");
  await dialog()
    .getByRole("button", { name: "Preview changes", exact: true })
    .click();
  await expect(dialog().locator(".batch-preview")).toHaveCount(5);
  await expect(dialog()).toContainText("Original");
  await expect(dialog()).toContainText("Reviewed");
  await dialog()
    .getByRole("button", { name: "Apply to 108 photos", exact: true })
    .click();
  await expect(dialog().getByRole("status")).toHaveText(
    "108 updated · 0 conflicts · 0 failed",
    { timeout: 60000 },
  );
  await dialog().getByRole("button", { name: "Done", exact: true }).click();
  await expect(dialog()).toHaveCount(0);
  const after = await read("/photos?limit=200");
  expect(after.total).toBe(108);
  const prior = new Map(before.items.map((item) => [item.id, item.metadata]));
  for (const item of after.items) {
    expect(item.metadata.tags).toEqual(["Original", "Reviewed"]);
    expect(item.metadata.people).toEqual(prior.get(item.id).people);
    expect(item.metadata.albums).toEqual(prior.get(item.id).albums);
  }
  expect(await originals(after.items)).toEqual(hashes);
  expect(await read("/views")).toEqual({ items: [] });
  expect(errors).toEqual([]);
  await page.screenshot({
    path: "/tmp/photoflow-query-smoke.png",
    fullPage: false,
  });
  await noHorizontalOverflow();
  await page.setViewportSize({ width: 360, height: 800 });
  await page.goto(base + "/photos");
  await count(108);
  await renderedPreview();
  await noHorizontalOverflow();
  await page.screenshot({
    path: "/tmp/photoflow-query-mobile.png",
    fullPage: false,
  });
  await page.locator(".query-filters > summary").click();
  await expect(page.locator(".query-filters")).toHaveAttribute("open", "");
  await noHorizontalOverflow();
  await page.screenshot({
    path: "/tmp/photoflow-query-mobile-filters.png",
    fullPage: false,
  });
  expect(errors).toEqual([]);
  console.log(
    "Query UX passed: rendered thumbnails; people Any/All; dates/favourites; reload/Back/Forward; saved-view CRUD; stale selection response rejected; frozen all-pages selection; reviewed batch adds labels to 108 photos; original bytes and people preserved; desktop and 360px layouts without horizontal overflow.",
  );
} finally {
  await browser.close();
}
