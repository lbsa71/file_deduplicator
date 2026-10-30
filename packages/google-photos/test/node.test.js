import test from "node:test";
import assert from "node:assert/strict";
import {
  mkdtemp,
  rm,
  stat,
  readdir,
  writeFile,
  readFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { FileJournal, openFileSource } from "../src/node.js";
import { createHash } from "node:crypto";
test("durable journal survives restart, locks writers, and exposes unresolved work", async () => {
  const dir = await mkdtemp(join(tmpdir(), "google-journal-"));
  try {
    const journal = new FileJournal(dir),
      release = await journal.lock("account");
    await assert.rejects(
      new FileJournal(dir).lock("account"),
      (e) => e.code === "BUSY",
    );
    const record = {
      plan: { id: "op/../../1", account: "account" },
      state: "sent",
      at: 1000,
    };
    await journal.put(record);
    await release();
    const restarted = new FileJournal(dir);
    assert.deepEqual(await restarted.get(record.plan.id), record);
    assert.equal((await restarted.pending("account")).length, 1);
    for (const p of await readdir(dir))
      assert.equal((await stat(join(dir, p))).mode & 0o777, 0o600);
    await writeFile(join(dir, "bad.json"), "bad");
    await assert.rejects(restarted.pending("account"));
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
test("file upload source hashes exactly the consumed bytes and detects changed or wrong originals", async () => {
  const dir = await mkdtemp(join(tmpdir(), "google-source-"));
  try {
    const path = join(dir, "fixture.jpg"),
      bytes = Buffer.from("fixture original");
    await writeFile(path, bytes);
    const hash = createHash("sha256").update(bytes).digest("hex");
    const source = await openFileSource(path, hash);
    assert.equal(await source.verify(), false);
    const chunks = [];
    for await (const chunk of source.body) chunks.push(chunk);
    assert.deepEqual(Buffer.concat(chunks), bytes);
    assert.equal(await source.verify(), true);
    await writeFile(path, "changed original");
    assert.equal(await source.verify(), false);
    await source.close();
    const wrong = await openFileSource(path, hash);
    for await (const chunk of wrong.body) {
    }
    assert.equal(await wrong.verify(), false);
    await wrong.close();
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("valid JSON corruption cannot turn a pending journal entry into verified success", async () => {
  const dir = await mkdtemp(join(tmpdir(), "google-corrupt-"));
  try {
    const journal = new FileJournal(dir);
    const release = await journal.lock("account");
    await journal.put({
      plan: { id: "op", account: "account" },
      state: "sent",
      at: 1,
    });
    await release();
    const path = join(
      dir,
      (await readdir(dir)).find((n) => n.endsWith(".json")),
    );
    await writeFile(
      path,
      (await readFile(path, "utf8")).replace("sent", "verified"),
    );
    await assert.rejects(journal.get("op"));
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});
