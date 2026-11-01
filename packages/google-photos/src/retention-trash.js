import { canonicalJSON } from "./browser-journal.js";
import { JOBS, photoKey } from "./jobs.js";
import { requireThat, identifier, UnknownOutcomeError } from "./errors.js";
import { decodeEnvelope } from "./protocol.js";
// Production authority is distinct from disposable qualification pilots. Only
// the server's immutable Takeout sweep can issue this exact-target capability.
export class RetentionTrash {
  constructor({
    account,
    reader,
    write,
    journal,
    now = Date.now,
    phase = async () => {},
  }) {
    Object.assign(this, { account, reader, write, journal, now, phase });
  }
  async inTrash(photo) {
    let cursor = null;
    const seen = new Set();
    for (let n = 0; n < 10000; n++) {
      const page = await this.reader.page("trash", { cursor });
      const matches = page.items.filter(
        (p) => p.mediaKey === photo.mediaKey || p.dedupKey === photo.dedupKey,
      );
      requireThat(
        matches.length <= 1 &&
          matches.every(
            (p) =>
              p.mediaKey === photo.mediaKey && p.dedupKey === photo.dedupKey,
          ),
        "Trash identity collision",
        "PRECONDITION",
      );
      if (matches.length === 1) return true;
      if (page.next === null) return false;
      requireThat(!seen.has(page.next), "Trash cursor loop", "PROTOCOL");
      seen.add(page.next);
      cursor = page.next;
    }
    requireThat(false, "Trash verification limit", "PROTOCOL");
  }
  async reconcile(originalJobId) {
    const release = await this.journal.readLock(this.account);
    try {
      const record = await this.journal.get(originalJobId);
      requireThat(
        record?.plan?.account === this.account &&
          record.plan.targetPolicy === "takeout-retention" &&
          record.plan.operation === "trash" &&
          record.kept !== true,
        "Unknown retention intent",
        "UNRESOLVED",
      );
      requireThat(
        await this.inTrash(record.photo),
        "Retention outcome unresolved",
        "UNRESOLVED",
      );
      const result = {
        verified: true,
        outcome: "reconciled",
        retentionReady: false,
      };
      await this.journal.put({ ...record, state: "verified", result });
      return { verified: true, originalJobId, retentionReady: false };
    } finally {
      await release();
    }
  }
  async execute(raw) {
    const job = structuredClone(raw),
      scope = job.retentionScope;
    identifier(job.id);
    JOBS.trash.validateInput(job.input);
    requireThat(
      job.operation === "trash" &&
        scope?.purpose === "owner-authorized-takeout-retention" &&
        scope.account === this.account &&
        scope.jobId === job.id &&
        scope.operation === "trash" &&
        scope.photoKey === photoKey(job.input.photoUrl) &&
        scope.albumId === null &&
        typeof scope.dedupKey === "string" &&
        scope.dedupKey.length > 0 &&
        /^[a-f0-9]{64}$/.test(scope.localSha256) &&
        /^[a-f0-9]{32}$/.test(scope.manifestId) &&
        /^[a-f0-9]{64}$/.test(scope.manifestSha256) &&
        Number.isSafeInteger(scope.expiresAt) &&
        scope.expiresAt > this.now() &&
        scope.expiresAt <= this.now() + 3600000,
      "Exact Takeout retention authority required",
      "UNQUALIFIED",
    );
    const plan = {
      id: job.id,
      account: this.account,
      operation: "trash",
      input: job.input,
      targetPolicy: "takeout-retention",
      retentionScope: Object.fromEntries(
        [
          "purpose",
          "manifestId",
          "manifestSha256",
          "localSha256",
          "dedupKey",
        ].map((k) => [k, scope[k]]),
      ),
    };
    // Expiry is lease metadata; immutable decision identity excludes renewal.

    const release = await this.journal.lock(this.account, { retention: true });
    let sent = false,
      record;
    try {
      const previous = await this.journal.get(job.id);
      if (previous) {
        requireThat(
          canonicalJSON(previous.plan) === canonicalJSON(plan),
          "Retention intent changed",
          "INTENT_CONFLICT",
        );
        requireThat(
          previous.state === "verified",
          "Reconcile prior retention outcome",
          "UNRESOLVED",
        );
        return previous.result;
      }
      requireThat(
        (await this.journal.pending(this.account)).every(
          (r) =>
            r.plan.targetPolicy === "takeout-retention" &&
            r.plan.retentionScope.manifestId !== scope.manifestId,
        ),
        "Unresolved Google write",
        "UNRESOLVED",
      );
      await this.phase("preflight");
      const photo = await this.reader.observation(scope.photoKey);
      requireThat(
        photo.namespace === "library-media" &&
          photo.mediaKey === scope.photoKey &&
          photo.dedupKey === scope.dedupKey &&
          typeof photo.favorite === "boolean" &&
          Array.isArray(photo.albums),
        "Retention identity or protection unknown",
        "PRECONDITION",
      );
      if (photo.favorite || photo.albums.length || photo.companion === true) {
        const result = {
          verified: true,
          outcome: "unchanged",
          retentionReady: false,
        };
        await this.journal.put({
          plan,
          photo,
          state: "verified",
          result,
          kept: true,
        });
        return result;
      }
      const recoveryPhoto = Object.fromEntries(
        ["namespace", "mediaKey", "dedupKey", "filename", "size"].map((k) => [
          k,
          photo[k],
        ]),
      );
      record = { plan, photo: recoveryPhoto, state: "prepared" };
      await this.journal.put(record);
      await this.phase("sending");
      // The original scope stays intact for the page's independent validation.
      requireThat(
        raw.retentionScope.expiresAt > this.now(),
        "Retention scope expired",
        "UNQUALIFIED",
      );
      record.state = "sent";
      await this.journal.put(record);
      sent = true;
      const response = await this.write({
        rpc: "XwAOJf",
        data: [null, 1, [photo.dedupKey], 3],
        mode: "write",
        operation: "trash",
        account: this.account,
        retentionScope: raw.retentionScope,
        targetMediaKey: photo.mediaKey,
        targetAlbumId: null,
      });
      requireThat(
        response?.account === this.account && response.status === 200,
        "Trash not acknowledged",
      );
      decodeEnvelope(response.body, "XwAOJf");
      await this.phase("verifying");
      requireThat(await this.inTrash(photo), "Trash postcondition unverified");
      const result = {
        verified: true,
        outcome: "verified",
        retentionReady: false,
      };
      await this.journal.put({ ...record, state: "verified", result });
      return result;
    } catch (error) {
      if (sent) {
        try {
          await this.journal.put({ ...record, state: "unknown" });
        } catch {}
        throw new UnknownOutcomeError();
      }
      throw error;
    } finally {
      await release();
    }
  }
}
