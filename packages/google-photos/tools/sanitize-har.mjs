import { readFile, open, stat } from "node:fs/promises";
import { CaptureSanitizer } from "../src/capture.js";
const [input, output] = process.argv.slice(2);
if (!input || !output)
  throw new Error(
    "Usage: node tools/sanitize-har.mjs input.har output.capture.json",
  );
if ((await stat(input)).size > 64 * 1024 * 1024)
  throw new Error("HAR exceeds 64 MiB; capture a smaller interaction");
const har = JSON.parse(await readFile(input, "utf8"));
if (!Array.isArray(har.log?.entries)) throw new Error("Invalid HAR");
const sanitizer = new CaptureSanitizer(),
  entries = [];
for (const entry of har.log.entries) {
  const url = new URL(entry.request.url);
  if (
    url.protocol !== "https:" ||
    ![
      "photos.google.com",
      "photoslibrary.googleapis.com",
      "photosdata-pa.googleapis.com",
      "upload.google.com",
      "upload.video.google.com",
      "clients6.google.com",
    ].includes(url.hostname)
  )
    continue;
  const headers = (rows) =>
    Object.fromEntries((rows ?? []).map((r) => [r.name, r.value]));
  entries.push({
    request: sanitizer.request({
      ...entry.request,
      headers: headers(entry.request.headers),
      postData: entry.request.postData?.text,
    }),
    response: sanitizer.response(
      {
        status: entry.response.status,
        mimeType: entry.response.content?.mimeType,
        headers: headers(entry.response.headers),
      },
      entry.response.content?.encoding === "base64"
        ? undefined
        : entry.response.content?.text,
    ),
  });
}
const file = await open(output, "wx", 0o600);
try {
  await file.writeFile(
    JSON.stringify(
      {
        schemaVersion: 1,
        kind: "google-photos-sanitized-capture",
        complete: false,
        source: "har",
        entries,
      },
      null,
      2,
    ) + "\n",
  );
} finally {
  await file.close();
}
console.log(
  `Saved ${entries.length} sanitized requests. Original HAR remains private; completeness is unproved.`,
);
