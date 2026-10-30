import { identifier, requireThat, UnknownOutcomeError } from "./errors.js";
import { validateQualification } from "./executor.js";
// Documented Photos Library API raw upload. Authentication/account verification
// belongs to the injected request adapter. No browser-upload protocol is guessed.
export class OfficialUploader {
  constructor({
    account,
    journal,
    request,
    inspect,
    verifyRemote,
    qualification,
    now = Date.now,
  }) {
    this.account = identifier(account);
    this.journal = journal;
    this.request = request;
    this.inspect = inspect;
    this.verifyRemote = verifyRemote;
    this.qualification = qualification;
    this.now = now;
  }
  async upload(input, source) {
    const { id, account, revision, sha256, filename, mimeType, size } = input;
    for (const value of [id, account, revision]) identifier(value);
    requireThat(account === this.account, "Wrong upload account", "ACCOUNT");
    requireThat(
      typeof sha256 === "string" && /^[a-f0-9]{64}$/.test(sha256),
      "Invalid content hash",
      "INPUT",
    );
    requireThat(
      typeof filename === "string" &&
        filename.length > 0 &&
        filename.length <= 255 &&
        !/[\x00-\x1f/\\]/.test(filename),
      "Invalid upload filename",
      "INPUT",
    );
    requireThat(
      typeof mimeType === "string" &&
        /^(image|video)\/[a-zA-Z0-9.+-]+$/.test(mimeType),
      "Invalid media type",
      "INPUT",
    );
    const max = mimeType.startsWith("image/")
      ? 200 * 1000 * 1000
      : 20 * 1000 * 1000 * 1000;
    requireThat(
      Number.isSafeInteger(size) &&
        size > 0 &&
        size <= max &&
        source?.size === size &&
        typeof source.verify === "function",
      "Invalid upload source or size",
      "INPUT",
    );
    validateQualification(this.qualification, account, "upload", this.now());
    const plan = Object.freeze({
      id,
      account,
      type: "upload",
      revision,
      sha256,
      filename,
      mimeType,
      size,
    });
    const release = await this.journal.lock(account);
    let sent = false;
    try {
      const existing = await this.journal.get(id);
      if (existing) {
        requireThat(
          JSON.stringify(existing.plan) === JSON.stringify(plan),
          "Upload intent changed",
          "INTENT_CONFLICT",
        );
        if (existing.state === "uploaded") return existing;
      }
      requireThat(
        (await this.journal.pending(account)).length === 0,
        "Resolve outstanding operations before uploading",
        "UNRESOLVED",
      );
      const priorUpload = await this.journal.findUpload(account, sha256);
      if (priorUpload) {
        const reused = {
          plan,
          state: "uploaded",
          mediaId: priorUpload.mediaId,
          awaitingMetadata: true,
          linkedOperationId: priorUpload.plan.id,
          at: this.now(),
        };
        await this.journal.put(reused);
        return reused;
      }
      const current = await this.inspect(plan);
      requireThat(
        current?.account === account &&
          current.revision === revision &&
          current.sha256 === sha256 &&
          current.localVerified === true &&
          current.remoteAbsent === true,
        "Upload identity, source, or remote absence is unproved",
        "PRECONDITION",
      );
      await this.journal.put({ plan, state: "bytes-sent", at: this.now() });
      validateQualification(this.qualification, account, "upload", this.now());
      sent = true;
      const uploaded = await this.request({
        account,
        url: "https://photoslibrary.googleapis.com/v1/uploads",
        method: "POST",
        headers: {
          "Content-Type": "application/octet-stream",
          "Content-Length": String(size),
          "X-Goog-Upload-Content-Type": mimeType,
          "X-Goog-Upload-Protocol": "raw",
        },
        body: source.body,
      });
      requireThat(
        uploaded?.account === account && uploaded.status === 200,
        "Upload bytes were not acknowledged",
      );
      const token = identifier(uploaded.body, "upload token");
      requireThat(
        (await source.verify()) === true,
        "Source changed or uploaded bytes did not verify",
      );
      const fresh = await this.inspect(plan);
      requireThat(
        fresh?.account === account &&
          fresh.revision === revision &&
          fresh.sha256 === sha256 &&
          fresh.localVerified === true &&
          fresh.remoteAbsent === true,
        "Upload preconditions changed before creation",
        "PRECONDITION",
      );
      validateQualification(this.qualification, account, "upload", this.now());
      await this.journal.put({ plan, state: "create-sent", at: this.now() });
      validateQualification(this.qualification, account, "upload", this.now());
      const created = await this.request({
        account,
        url: "https://photoslibrary.googleapis.com/v1/mediaItems:batchCreate",
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          newMediaItems: [
            { simpleMediaItem: { fileName: filename, uploadToken: token } },
          ],
        }),
      });
      requireThat(
        created?.account === account && created.status === 200,
        "Media creation was not acknowledged",
      );
      let data;
      try {
        data = JSON.parse(created.body);
      } catch {
        requireThat(false, "Malformed creation response");
      }
      requireThat(
        Array.isArray(data.newMediaItemResults) &&
          data.newMediaItemResults.length === 1,
        "Wrong creation result count",
      );
      const item = data.newMediaItemResults[0];
      requireThat(
        item.uploadToken === token &&
          item.status &&
          typeof item.status === "object" &&
          !Array.isArray(item.status) &&
          (item.status.code === undefined || item.status.code === 0),
        "Media creation failed or returned a different upload",
      );
      const mediaId = identifier(item.mediaItem?.id, "created media ID");
      await this.journal.put({
        plan,
        state: "verify-pending",
        mediaId,
        at: this.now(),
      });
      const verified = await this.verifyRemote(mediaId);
      requireThat(
        verified?.account === account &&
          verified.mediaId === mediaId &&
          verified.exists === true,
        "Created media could not be verified",
      );
      const result = {
        plan,
        state: "uploaded",
        mediaId,
        awaitingMetadata: true,
        at: this.now(),
      };
      await this.journal.put(result);
      return result;
    } catch (error) {
      if (sent) {
        try {
          const prior = await this.journal.get(id);
          await this.journal.put({
            ...prior,
            plan,
            state: "unknown",
            at: this.now(),
          });
        } catch {}
        throw new UnknownOutcomeError();
      }
      throw error;
    } finally {
      await release();
    }
  }
  async reconcile(id) {
    identifier(id);
    validateQualification(
      this.qualification,
      this.account,
      "upload",
      this.now(),
    );
    const release = await this.journal.lock(this.account);
    try {
      const record = await this.journal.get(id);
      requireThat(
        record?.plan?.account === this.account && record.plan.type === "upload",
        "No matching upload intent",
        "ACCOUNT",
      );
      requireThat(
        typeof record.mediaId === "string" && record.mediaId.length > 0,
        "No verified creation receipt; manual identity reconciliation is required",
        "UNRESOLVED",
      );
      const observed = await this.verifyRemote(record.mediaId);
      requireThat(
        observed?.account === this.account &&
          observed.mediaId === record.mediaId &&
          observed.exists === true,
        "Upload presence remains unresolved",
        "UNRESOLVED",
      );
      const done = {
        ...record,
        state: "uploaded",
        awaitingMetadata: true,
        reconciled: true,
        at: this.now(),
      };
      await this.journal.put(done);
      return done;
    } finally {
      await release();
    }
  }
}
