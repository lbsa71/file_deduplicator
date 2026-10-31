import { writeFile, readFile } from "node:fs/promises";
import { CATALOG } from "../src/job-catalog.js";
const target = new URL(
  "../../../apps/web/photoflow_web/google_jobs.json",
  import.meta.url,
);
const content = JSON.stringify(CATALOG, null, 2) + "\n";
if (process.argv.includes("--check")) {
  if ((await readFile(target, "utf8")) !== content)
    throw Error(
      "Google job contracts out of sync; run tools/sync-job-contracts.mjs",
    );
} else await writeFile(target, content);
