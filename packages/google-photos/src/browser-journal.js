import { requireThat, identifier } from "./errors.js";
import { JOBS } from "./jobs.js";
const checksum = async (text) =>
  Array.from(
    new Uint8Array(
      await globalThis.crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(text),
      ),
    ),
    (b) => b.toString(16).padStart(2, "0"),
  ).join("");
export const canonicalJSON = (value) =>
  JSON.stringify(value, (_key, item) =>
    item && typeof item === "object" && !Array.isArray(item)
      ? Object.fromEntries(
          Object.keys(item)
            .sort()
            .map((key) => [key, item[key]]),
        )
      : item,
  );
// One background service-worker context owns this store. Persisted locks are never stolen.
export class BrowserJournal {
  constructor(storage, { digest = checksum } = {}) {
    this.storage = storage;
    this.digest = digest;
    this.busy = new Set();
  }
  key(id) {
    return "pilot-record:" + id;
  }
  async lock(account) {
    requireThat(!this.busy.has(account), "Pilot writer busy", "BUSY");
    this.busy.add(account);
    const key = "pilot-lock:" + account;
    try {
      requireThat(
        !(await this.storage.get(key))[key],
        "Interrupted pilot lock requires inspection",
        "BUSY",
      );
      await this.storage.set({ [key]: { account } });
    } catch (e) {
      this.busy.delete(account);
      throw e;
    }
    return async () => {
      try {
        await this.storage.remove(key);
      } finally {
        this.busy.delete(account);
      }
    };
  }
  async readLock(account) {
    requireThat(!this.busy.has(account), "Pilot writer busy", "BUSY");
    this.busy.add(account);
    return async () => {
      try {
        if ((await this.pending(account)).length === 0)
          await this.storage.remove("pilot-lock:" + account);
      } finally {
        this.busy.delete(account);
      }
    };
  }
  async decode(key, value) {
    const record = value?.record;
    requireThat(
      value?.schemaVersion === 1 &&
        record?.plan &&
        value.checksum === (await this.digest(canonicalJSON(record))),
      "Corrupt browser journal",
      "STORAGE",
    );
    identifier(record.plan.id);
    identifier(record.plan.account);
    requireThat(
      key === this.key(record.plan.id) &&
        Object.hasOwn(JOBS, record.plan.operation) &&
        JOBS[record.plan.operation].effect === "write",
      "Invalid browser intent",
      "STORAGE",
    );
    JOBS[record.plan.operation].validateInput(record.plan.input);
    requireThat(
      ["fixtures", "selected"].includes(record.plan.targetPolicy ?? "fixtures"),
      "Invalid journal target policy",
      "STORAGE",
    );
    requireThat(
      ["prepared", "sent", "unknown", "verified"].includes(record.state),
      "Invalid browser journal state",
      "STORAGE",
    );
    if (record.state === "verified")
      JOBS[record.plan.operation].validateResult(record.result);
    return record;
  }
  async get(id) {
    const key = this.key(id),
      value = (await this.storage.get(key))[key];
    return value === undefined ? null : this.decode(key, value);
  }
  async put(record) {
    const key = this.key(record.plan.id),
      wrapped = {
        schemaVersion: 1,
        checksum: await this.digest(canonicalJSON(record)),
        record,
      };
    await this.decode(key, wrapped);
    await this.storage.set({ [key]: wrapped });
  }
  async records(account) {
    const all = await this.storage.get(null),
      records = [];
    for (const [key, value] of Object.entries(all)) {
      if (!key.startsWith("pilot-record:")) continue;
      const record = await this.decode(key, value);
      if (record.plan.account === account) records.push(record);
    }
    return records;
  }
  async pending(account) {
    return (await this.records(account)).filter((r) => r.state !== "verified");
  }
  async fixture(account, mediaKey) {
    return (
      (await this.records(account)).find((r) => r.photo?.mediaKey === mediaKey)
        ?.photo ?? null
    );
  }
}
