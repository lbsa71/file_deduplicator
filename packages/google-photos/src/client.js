import { ProtocolError, requireThat, identifier, array } from "./errors.js";
import {
  PROTOCOL_VERSION,
  decodeEnvelope,
  parsePage,
  parseItem,
  parseDetails,
  readRequest,
} from "./protocol.js";

export class GooglePhotosClient {
  #transport;
  #account;
  #now;
  #failed = false;
  #maxPages;
  #maxItems;
  constructor({
    account,
    transport,
    now = Date.now,
    maxPages = 10000,
    maxItems = 1000000,
  }) {
    this.#account = identifier(account, "account");
    requireThat(
      typeof transport === "function",
      "Transport is required",
      "INPUT",
    );
    requireThat(
      Number.isInteger(maxPages) &&
        maxPages > 0 &&
        Number.isInteger(maxItems) &&
        maxItems > 0,
      "Invalid inventory limits",
      "INPUT",
    );
    this.#transport = transport;
    this.#now = now;
    this.#maxPages = maxPages;
    this.#maxItems = maxItems;
  }
  get account() {
    return this.#account;
  }
  get failed() {
    return this.#failed;
  }
  async #read(kind, args = {}) {
    const request = readRequest(kind, args);
    requireThat(
      !this.#failed,
      "Client disabled after a protocol/transport failure",
      "CIRCUIT_OPEN",
    );
    try {
      let response;
      try {
        response = await this.#transport({
          ...request,
          account: this.#account,
          operation: kind,
          mode: "read",
        });
      } catch {
        throw new ProtocolError("Read transport failed", "TRANSPORT");
      }
      requireThat(
        response?.account === this.#account,
        "Response account changed",
        "ACCOUNT",
      );
      requireThat(
        response.status === 200,
        "Read request did not succeed",
        "HTTP",
      );
      return decodeEnvelope(response.body, request.rpc);
    } catch (error) {
      this.#failed = true;
      throw error;
    }
  }
  async #pages(kind, args = {}) {
    const items = [],
      seen = new Set(),
      cursors = new Set();
    let cursor = null;
    try {
      for (let n = 0; n < this.#maxPages; n++) {
        const page = parsePage(
          await this.#read(kind, { ...args, cursor }),
          kind,
          args.albumId,
        );
        for (const item of page.items) {
          const id = item.mediaKey ?? item.albumId;
          requireThat(!seen.has(id), "Duplicate identity in enumeration");
          seen.add(id);
          items.push(item);
        }
        requireThat(
          items.length <= this.#maxItems,
          "Inventory exceeds configured limit",
        );
        if (page.next === null)
          return {
            account: this.#account,
            protocolVersion: PROTOCOL_VERSION,
            complete: true,
            observedAt: this.#now(),
            ...(args.albumId ? { albumId: args.albumId } : {}),
            items,
          };
        requireThat(!cursors.has(page.next), "Repeated pagination cursor");
        cursors.add(page.next);
        cursor = page.next;
      }
      throw new ProtocolError("Pagination exceeds configured limit");
    } catch (error) {
      this.#failed = true;
      throw error;
    }
  }
  async page(kind, args = {}) {
    requireThat(
      ["inventory", "favorites", "albums", "albumItems", "trash"].includes(
        kind,
      ),
      "Unsupported page kind",
      "INPUT",
    );
    const page = parsePage(
      await this.#read(kind, { ...args, limit: 50 }),
      kind,
      args.albumId,
    );
    requireThat(page.items.length <= 500, "Page exceeds inspection limit");
    return { ...page, complete: page.next === null, retentionReady: false };
  }
  async quota() {
    const data = await this.#read("quota"),
      row = array(data[6], "quota");
    requireThat(
      [row[0], row[1], row[3]].every((v) => Number.isSafeInteger(v) && v >= 0),
      "Unknown storage quota",
    );
    requireThat(row[0] <= row[1] && row[3] <= row[0], "Invalid storage quota");
    return { used: row[0], total: row[1], photosUsed: row[3] };
  }
  async downloadLink(mediaKey) {
    const data = await this.#read("downloadLink", { mediaKey });
    requireThat(
      typeof data[0] === "string" && data[0].length <= 8192,
      "Unknown download reference",
    );
    const url = new URL(data[0]);
    requireThat(
      url.protocol === "https:" &&
        !url.username &&
        !url.password &&
        ["photos.google.com", "googleusercontent.com"].some(
          (h) => url.hostname === h || url.hostname.endsWith("." + h),
        ),
      "Unapproved download host",
    );
    return { url: url.href };
  }
  async observation(mediaKey) {
    const basicData = await this.#read("item", { mediaKey });
    const basic = parseDetails(basicData, mediaKey);
    const extendedData = await this.#read("details", { mediaKey });
    const extended = parseDetails(extendedData, mediaKey, true);
    const row = extendedData[0];
    requireThat(
      basic.dedupKey === extended.dedupKey,
      "Conflicting photo identities",
    );
    const nullableNumber = (value) => {
      requireThat(
        value == null || Number.isSafeInteger(value),
        "Invalid timestamp",
      );
      return value ?? null;
    };
    const coordinates = (value) => {
      if (value == null) return null;
      requireThat(
        Array.isArray(value) &&
          value.length === 2 &&
          value.every(Number.isSafeInteger) &&
          Math.abs(value[0]) <= 900000000 &&
          Math.abs(value[1]) <= 1800000000,
        "Invalid E7 coordinates",
      );
      return value;
    };
    requireThat(
      row[1] == null || typeof row[1] === "string",
      "Invalid description",
    );
    let manualLocationE7 = row[13];
    if (manualLocationE7 !== null && manualLocationE7 !== undefined) {
      requireThat(
        Array.isArray(manualLocationE7) && Array.isArray(manualLocationE7[0]),
        "Unknown manual location",
      );
      manualLocationE7 = coordinates(manualLocationE7[0]);
    }
    return {
      ...basic,
      ...extended,
      archived:
        basicData[0][13] === true
          ? true
          : basicData[0][13] === false
            ? false
            : null,
      description: row[1] ?? null,
      timestampMs: nullableNumber(row[3]),
      timezoneMs: nullableNumber(row[4]),
      locationE7: coordinates(row[13]?.[0] ?? row[9]?.[0]),
      manualLocationE7,
    };
  }
  inventory() {
    return this.#pages("inventory");
  }
  favorites() {
    return this.#pages("favorites");
  }
  albums() {
    return this.#pages("albums");
  }
  albumItems(albumId) {
    return this.#pages("albumItems", { albumId });
  }
  trash() {
    return this.#pages("trash");
  }
  async item(mediaKey) {
    identifier(mediaKey);
    try {
      return parseDetails(await this.#read("item", { mediaKey }), mediaKey);
    } catch (e) {
      this.#failed = true;
      throw e;
    }
  }
  async details(mediaKey) {
    identifier(mediaKey);
    try {
      return parseDetails(
        await this.#read("details", { mediaKey }),
        mediaKey,
        true,
      );
    } catch (e) {
      this.#failed = true;
      throw e;
    }
  }
  async hashCandidates(hashes) {
    try {
      const data = await this.#read("hashCandidates", { hashes });
      const rows = array(data[0], "hash matches");
      const seen = new Set();
      const items = rows.map((row) => {
        array(row, "hash match");
        requireThat(hashes.includes(row[0]), "Unexpected hash match");
        const media = parseItem(row[1]);
        const key = `${row[0]}:${media.mediaKey}`;
        requireThat(!seen.has(key), "Duplicate hash match");
        seen.add(key);
        return { hash: row[0], ...media };
      });
      return { account: this.#account, items, absenceProven: false };
    } catch (e) {
      this.#failed = true;
      throw e;
    }
  }
}
