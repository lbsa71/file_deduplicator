import { canonicalJSON } from "./browser-journal.js";
import { JOBS, photoKey } from "./jobs.js";
import { decodeEnvelope } from "./protocol.js";
import { requireThat, identifier, UnknownOutcomeError } from "./errors.js";
const freeze = (value) => {
  if (value && typeof value === "object") {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
};
const prefix = "photoflow-test-";
export function pilotRequest(operation, input, photo, member) {
  const key = photo?.dedupKey;
  switch (operation) {
    case "favorite-set":
      return { rpc: "Ftfh0", data: [[[null, key]], [input.value ? 1 : 2]] };
    case "archive-set":
      return {
        rpc: "w7TP3c",
        data: [[[null, [input.value ? 1 : 2], [null, key]]], null, 1],
      };
    case "trash":
      return { rpc: "XwAOJf", data: [null, 1, [key], 3] };
    case "restore":
      return { rpc: "XwAOJf", data: [null, 3, [key], 2] };
    case "album-create":
      return { rpc: "OXvT9d", data: [input.title, null, 2] };
    case "album-add":
      return { rpc: "E1Cajb", data: [[photo.mediaKey], input.albumId] };
    case "album-remove":
      requireThat(
        member?.namespace === "album-item",
        "Album-scoped identity required",
        "PRECONDITION",
      );
      return { rpc: "ycV3Nd", data: [[member.mediaKey]] };
    case "description-set":
      return { rpc: "AQNOFd", data: [null, input.description, key] };
    case "timestamp-set":
      return {
        rpc: "DaSgWe",
        data: [[[key, input.timestampSec, input.timezoneSec]]],
      };
    case "location-set":
      return {
        rpc: "EtUHOe",
        data: [
          [[null, key]],
          [
            2,
            input.centerE7,
            [input.visible1E7, input.visible2E7],
            [null, null, input.scale],
            input.placeId,
          ],
        ],
      };
    case "location-clear":
      return { rpc: "EtUHOe", data: [[[null, key]], [1]] };
    default:
      requireThat(false, "Unsupported pilot operation", "INPUT");
  }
}
// Explicitly isolated synthetic-media pilot. This is not a production retention executor.
export class ToolkitPilot {
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
  async fixture(input, operation) {
    if (operation === "album-create") return null;
    const mediaKey = photoKey(input.photoUrl);
    let photo;
    if (operation === "restore") {
      photo = await this.journal.fixture(this.account, mediaKey);
      requireThat(
        photo,
        "Restore requires an earlier journaled test fixture",
        "PRECONDITION",
      );
      const basic = await this.reader.item(mediaKey);
      requireThat(
        basic.mediaKey === photo.mediaKey && basic.dedupKey === photo.dedupKey,
        "Restoration identity changed",
        "PRECONDITION",
      );
    } else photo = await this.reader.observation(mediaKey);
    requireThat(
      photo.namespace === "library-media" &&
        photo.mediaKey === mediaKey &&
        typeof photo.filename === "string" &&
        photo.filename.startsWith(prefix) &&
        /\.(jpe?g|png|webp|gif|tiff?|heic|avif)$/i.test(photo.filename) &&
        Number.isSafeInteger(photo.size) &&
        photo.size > 0 &&
        photo.size <= 10 * 1024 * 1024,
      "Expected small synthetic test image",
      "PRECONDITION",
    );
    return photo;
  }
  async members(input, photo) {
    const albums = await this.reader.albums();
    const album = albums.items.find((a) => a.albumId === input.albumId);
    requireThat(
      album?.title.startsWith("PhotoFlow test ") && album.shared === false,
      "Expected private disposable test album",
      "PRECONDITION",
    );
    const members = await this.reader.albumItems(input.albumId);
    const matches = members.items.filter((p) => p.dedupKey === photo.dedupKey);
    requireThat(
      matches.length <= 1,
      "Ambiguous album membership",
      "PRECONDITION",
    );
    return matches[0] ?? null;
  }
  async desired(operation, input, photo, createdAlbumId) {
    if (operation === "album-create") {
      requireThat(createdAlbumId, "Creation receipt unavailable", "UNRESOLVED");
      const all = await this.reader.albums();
      return all.items.some(
        (a) =>
          a.albumId === createdAlbumId &&
          a.title === input.title &&
          a.shared === false,
      );
    }
    if (operation === "trash" || operation === "restore") {
      const trash = await this.reader.trash();
      const exists = trash.items.some((p) => p.dedupKey === photo.dedupKey);
      return exists === (operation === "trash");
    }
    if (operation === "album-add" || operation === "album-remove")
      return (
        !!(await this.members(input, photo)) === (operation === "album-add")
      );
    const current = await this.reader.observation(photo.mediaKey);
    requireThat(
      current.dedupKey === photo.dedupKey,
      "Photo identity changed",
      "PRECONDITION",
    );
    if (operation === "favorite-set") {
      if (typeof current.favorite === "boolean")
        return current.favorite === input.value;
      const favorites = await this.reader.favorites();
      return (
        favorites.items.some((p) => p.dedupKey === photo.dedupKey) ===
        input.value
      );
    }
    if (operation === "archive-set") {
      requireThat(
        typeof current.archived === "boolean",
        "Archive state unknown",
        "PRECONDITION",
      );
      return current.archived === input.value;
    }
    if (operation === "description-set")
      return current.description === input.description;
    if (operation === "timestamp-set")
      return (
        current.timestampMs === input.timestampSec * 1000 &&
        current.timezoneMs === input.timezoneSec * 1000
      );
    if (operation === "location-set")
      return (
        JSON.stringify(current.manualLocationE7) ===
        JSON.stringify(input.centerE7)
      );
    if (operation === "location-clear")
      return current.manualLocationE7 === null;
    requireThat(false, "Unsupported postcondition", "INPUT");
  }
  async execute(job) {
    const { id, operation, input: rawInput, testScope: rawScope } = job;
    const input = freeze(structuredClone(rawInput));
    const scope = rawScope && freeze(structuredClone(rawScope));
    identifier(id);
    requireThat(
      JOBS[operation]?.effect === "write",
      "Expected pilot write",
      "INPUT",
    );
    JOBS[operation].validateInput(input);
    requireThat(
      scope?.testOnly === true &&
        scope.account === this.account &&
        scope.jobId === id &&
        scope.operation === operation &&
        Number.isSafeInteger(scope.expiresAt) &&
        scope.expiresAt > this.now() &&
        scope.expiresAt <= this.now() + 3600000 &&
        scope.photoKey === (input.photoUrl ? photoKey(input.photoUrl) : null) &&
        scope.albumId === (input.albumId ?? null),
      "Isolated-account pilot scope required",
      "UNQUALIFIED",
    );
    const plan = Object.freeze({
      id,
      account: this.account,
      operation,
      input: structuredClone(input),
    });
    Object.freeze(plan.input);
    const release = await this.journal.lock(this.account);
    let sent = false,
      record;
    try {
      const old = await this.journal.get(id);
      if (old) {
        requireThat(
          canonicalJSON(old.plan) === canonicalJSON(plan),
          "Pilot intent changed",
          "INTENT_CONFLICT",
        );
        if (old.state === "verified") return old.result;
        requireThat(false, "Reconcile prior pilot outcome", "UNRESOLVED");
      }
      requireThat(
        (await this.journal.pending(this.account)).length === 0,
        "Unresolved pilot write",
        "UNRESOLVED",
      );
      await this.phase("preflight");
      const photo = await this.fixture(input, operation);
      let member = null;
      if (operation === "album-add" || operation === "album-remove")
        member = await this.members(input, photo);
      if (operation === "album-create") {
        const all = await this.reader.albums();
        requireThat(
          !all.items.some((a) => a.title === input.title),
          "Test album title already exists",
          "PRECONDITION",
        );
      } else if (await this.desired(operation, input, photo)) {
        const result = {
          verified: true,
          outcome: "unchanged",
          retentionReady: false,
        };
        await this.journal.put({ plan, photo, state: "verified", result });
        return result;
      }
      record = { plan, photo, member, state: "prepared" };
      await this.journal.put(record);
      await this.phase("sending");
      requireThat(
        scope.expiresAt > this.now(),
        "Pilot scope expired",
        "UNQUALIFIED",
      );
      record.state = "sent";
      await this.journal.put(record);
      sent = true;
      const request = pilotRequest(operation, input, photo, member);
      const response = await this.write({
        ...request,
        operation,
        mode: "write",
        account: this.account,
        testScope: scope,
        targetMediaKey: photo?.mediaKey ?? null,
        targetAlbumId: input.albumId ?? null,
      });
      requireThat(
        response?.account === this.account && response.status === 200,
        "Pilot write not acknowledged",
      );
      const ack = decodeEnvelope(response.body, request.rpc);
      if (operation === "album-create") {
        record.createdAlbumId = identifier(ack[0]?.[0]);
        await this.journal.put(record);
      }
      await this.phase("verifying");
      requireThat(
        await this.desired(operation, input, photo, record.createdAlbumId),
        "Pilot postcondition failed",
      );
      const result = {
        verified: true,
        outcome: "verified",
        retentionReady: false,
        ...(record.createdAlbumId ? { albumId: record.createdAlbumId } : {}),
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
  async reconcile(originalJobId) {
    const release = await (this.journal.readLock ?? this.journal.lock).call(
      this.journal,
      this.account,
    );
    try {
      const record = await this.journal.get(originalJobId);
      requireThat(
        record?.plan?.account === this.account,
        "Unknown pilot intent",
        "UNRESOLVED",
      );
      requireThat(
        await this.desired(
          record.plan.operation,
          record.plan.input,
          record.photo,
          record.createdAlbumId,
        ),
        "Pilot outcome unresolved",
        "UNRESOLVED",
      );
      const result = {
        verified: true,
        outcome: "reconciled",
        retentionReady: false,
        ...(record.createdAlbumId ? { albumId: record.createdAlbumId } : {}),
      };
      await this.journal.put({ ...record, state: "verified", result });
      return {
        verified: true,
        originalJobId,
        retentionReady: false,
        ...(record.createdAlbumId ? { albumId: record.createdAlbumId } : {}),
      };
    } finally {
      await release();
    }
  }
}
