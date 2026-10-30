import { promises as fs, constants } from "node:fs";
import { join } from "node:path";
import { createHash, randomUUID } from "node:crypto";
import { requireThat } from "./errors.js";
const key = (s) => createHash("sha256").update(s).digest("hex");
export class FileJournal {
  constructor(directory) {
    this.directory = directory;
  }
  async lock(account) {
    await fs.mkdir(this.directory, { recursive: true, mode: 0o700 });
    requireThat(
      ((await fs.stat(this.directory)).mode & 0o077) === 0,
      "Journal directory must be private",
      "STORAGE",
    );
    const path = join(this.directory, "writer.lock");
    let handle;
    try {
      handle = await fs.open(path, "wx", 0o600);
    } catch (e) {
      if (e.code === "EEXIST")
        requireThat(
          false,
          "Account writer lock exists; investigate interrupted execution",
          "BUSY",
        );
      throw e;
    }
    await handle.sync();
    return async () => {
      await handle.close();
      await fs.unlink(path);
    };
  }
  async get(id) {
    try {
      const r = await this.#read(`${key(id)}.json`);
      requireThat(
        r?.plan?.id === id && typeof r.state === "string",
        "Corrupt journal",
      );
      return r;
    } catch (e) {
      if (e.code === "ENOENT") return null;
      throw e;
    }
  }
  async #read(name) {
    const raw = await fs.readFile(join(this.directory, name), "utf8");
    requireThat(
      raw.length <= 65536,
      "Journal record exceeds size limit",
      "STORAGE",
    );
    const wrapper = JSON.parse(raw),
      r = wrapper.record;
    requireThat(
      wrapper.schemaVersion === 1 &&
        r?.plan?.id &&
        r.plan.account &&
        typeof r.state === "string" &&
        wrapper.sha256 === key(JSON.stringify(r)) &&
        name === `${key(r.plan.id)}.json`,
      "Corrupt journal",
      "STORAGE",
    );
    requireThat(
      [
        "prepared",
        "sent",
        "verified",
        "unchanged",
        "unknown",
        "reconciled",
        "bytes-sent",
        "create-sent",
        "verify-pending",
        "uploaded",
      ].includes(r.state),
      "Unknown journal state",
      "STORAGE",
    );
    return r;
  }
  async put(record) {
    const path = join(this.directory, `${key(record.plan.id)}.json`),
      temp = join(this.directory, `.${randomUUID()}.tmp`);
    const handle = await fs.open(
      temp,
      constants.O_WRONLY | constants.O_CREAT | constants.O_EXCL,
      0o600,
    );
    try {
      await handle.writeFile(
        JSON.stringify({
          schemaVersion: 1,
          sha256: key(JSON.stringify(record)),
          record,
        }) + "\n",
      );
      await handle.sync();
    } finally {
      await handle.close();
    }
    await fs.rename(temp, path);
    const dir = await fs.open(this.directory, "r");
    try {
      await dir.sync();
    } finally {
      await dir.close();
    }
  }
  async pending(account) {
    const records = [];
    for (const name of await fs.readdir(this.directory))
      if (name.endsWith(".json")) {
        const r = await this.#read(name);
        if (
          r.plan.account === account &&
          !["verified", "unchanged", "reconciled", "uploaded"].includes(r.state)
        )
          records.push(r);
      }
    return records;
  }
  async findUpload(account, sha256) {
    for (const name of await fs.readdir(this.directory))
      if (name.endsWith(".json")) {
        const r = await this.#read(name);
        if (
          r.plan.account === account &&
          r.plan.sha256 === sha256 &&
          r.state === "uploaded"
        )
          return r;
      }
    return null;
  }
}

export async function openFileSource(path, expectedSha256) {
  requireThat(
    typeof expectedSha256 === "string" && /^[a-f0-9]{64}$/.test(expectedSha256),
    "Invalid expected SHA-256",
    "INPUT",
  );
  const handle = await fs.open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  const before = await handle.stat({ bigint: true });
  if (!before.isFile()) {
    await handle.close();
    throw new Error("Upload source must be a regular file");
  }
  requireThat(
    before.size <= BigInt(Number.MAX_SAFE_INTEGER),
    "Source is too large",
    "INPUT",
  );
  let complete = false,
    digest = null,
    started = false;
  const hash = createHash("sha256");
  const body = (async function* () {
    requireThat(!started, "Upload source cannot be replayed", "INPUT");
    started = true;
    let position = 0;
    while (position < Number(before.size)) {
      const buffer = Buffer.alloc(
        Math.min(1024 * 1024, Number(before.size) - position),
      );
      const { bytesRead } = await handle.read(
        buffer,
        0,
        buffer.length,
        position,
      );
      requireThat(bytesRead > 0, "Source truncated during upload");
      const chunk = buffer.subarray(0, bytesRead);
      hash.update(chunk);
      position += bytesRead;
      yield chunk;
    }
    digest = hash.digest("hex");
    complete = true;
  })();
  return {
    size: Number(before.size),
    body,
    async verify() {
      if (!complete || digest !== expectedSha256) return false;
      const after = await handle.stat({ bigint: true });
      return ["size", "mtimeNs", "ctimeNs", "dev", "ino"].every(
        (k) => before[k] === after[k],
      );
    },
    close: () => handle.close(),
  };
}
