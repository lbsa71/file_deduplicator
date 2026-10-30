import { cp, mkdir, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const root = new URL("../", import.meta.url),
  out = new URL("dist/capture-extension/", root);
await rm(out, { recursive: true, force: true });
await mkdir(out, { recursive: true });
await cp(new URL("capture-extension/", root), out, { recursive: true });
await cp(new URL("src/", root), new URL("lib/", out), { recursive: true });
await cp(new URL("LICENSE", root), new URL("LICENSE", out));
await cp(
  new URL("THIRD_PARTY_NOTICES.md", root),
  new URL("THIRD_PARTY_NOTICES.md", out),
);
console.log(fileURLToPath(out));
