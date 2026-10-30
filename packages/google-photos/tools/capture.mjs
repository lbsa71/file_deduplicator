import { chromium } from "playwright";
import { open, stat } from "node:fs/promises";
import { resolve } from "node:path";
import { PassiveRecorder } from "../src/capture.js";
const args = process.argv.slice(2),
  option = (name) => args[args.indexOf(name) + 1];
if (!args.includes("--cdp") || !args.includes("--out"))
  throw new Error(
    "Usage: node tools/capture.mjs --cdp http://127.0.0.1:9222 --out capture.json",
  );
const endpoint = new URL(option("--cdp"));
if (
  !["http:", "ws:"].includes(endpoint.protocol) ||
  !["127.0.0.1", "localhost", "[::1]"].includes(endpoint.hostname) ||
  endpoint.username ||
  endpoint.password ||
  endpoint.search
)
  throw new Error(
    "Use an authenticated browser endpoint forwarded to loopback; remote endpoints are not accepted",
  );
const output = resolve(option("--out"));
try {
  await stat(output);
  throw new Error("Output already exists");
} catch (e) {
  if (e.code !== "ENOENT") throw e;
}
const browser = await chromium.connectOverCDP(endpoint.toString());
const pages = browser
  .contexts()
  .flatMap((c) => c.pages())
  .filter((p) => {
    try {
      return new URL(p.url()).origin === "https://photos.google.com";
    } catch {
      return false;
    }
  });
if (pages.length !== 1)
  throw new Error(
    "Keep exactly one Google Photos tab open in this browser profile",
  );
const session = await pages[0].context().newCDPSession(pages[0]);
const recorder = new PassiveRecorder({
    send: (method, params) => session.send(method, params),
  }),
  pending = new Set();
for (const method of [
  "Network.requestWillBeSent",
  "Network.responseReceived",
  "Network.loadingFinished",
  "Network.loadingFailed",
])
  session.on(method, (params) => {
    const task = recorder
      .event(method, params)
      .catch(() => recorder.invalidate());
    pending.add(task);
    task.finally(() => pending.delete(task));
  });
await session.send("Network.enable", {
  maxTotalBufferSize: 8 * 1024 * 1024,
  maxResourceBufferSize: 1024 * 1024,
  maxPostDataSize: 65536,
});
console.log(
  "Passive capture attached. Perform one disposable-photo interaction; press Ctrl-C to save sanitized results.",
);
let stopping = false;
async function stop() {
  if (stopping) return;
  stopping = true;
  await session.send("Network.disable");
  await Promise.allSettled([...pending]);
  await session.detach();
  // Exclusive output creation: never overwrite earlier evidence.
  const handle = await open(output, "wx", 0o600);
  try {
    await handle.writeFile(JSON.stringify(recorder.export(), null, 2) + "\n");
    await handle.sync();
  } finally {
    await handle.close();
  }
  console.log(
    `Saved ${recorder.export().entries.length} sanitized requests to ${output}`,
  );
  // Exit disconnects this client's socket without closing the user's browser.
  process.exit(0);
}
process.on(
  "SIGINT",
  () =>
    void stop().catch(() => {
      console.error("Capture save failed");
      process.exit(1);
    }),
);
process.on("SIGTERM", () => void stop().catch(() => process.exit(1)));
