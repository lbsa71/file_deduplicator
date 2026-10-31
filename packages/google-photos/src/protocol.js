import {
  array,
  identifier,
  knownBoolean,
  requireThat,
  text,
  ProtocolError,
} from "./errors.js";
export const PROTOCOL_VERSION = "gptk-3.3.0-strict-1";
export const UPSTREAM_COMMIT = "6db9ab355e4797327e4078cf87a2b6994d36cf73";
const bytes = (value) => new TextEncoder().encode(value).length;

// Independent parser; positional field knowledge attributed in THIRD_PARTY_NOTICES.
export function decodeEnvelope(body, expectedRpc) {
  requireThat(
    typeof body === "string" && bytes(body) <= 16 * 1024 * 1024,
    "Invalid response size",
  );
  let lines = body
    .replace(/^\)\]\}'(?:\r?\n)?/, "")
    .split(/\r?\n/)
    .filter((s) => s.trim());
  const found = [];
  for (let i = 0; i < lines.length; i++) {
    let line = lines[i];
    if (/^\d+$/.test(line.trim())) {
      const length = Number(line);
      line = lines[++i];
      requireThat(
        typeof line === "string" &&
          ([bytes(line), bytes(line) + 1].includes(length) ||
            // Live Photos frames use UTF-16 code units plus two, including
            // ASCII trailer frames. Preserve the existing byte-length forms.
            length === line.length + 2),
        "Invalid RPC frame length",
      );
    }
    let records;
    try {
      records = JSON.parse(line);
    } catch {
      throw new ProtocolError("Invalid RPC JSON");
    }
    for (const record of array(records, "RPC envelope")) {
      array(record, "RPC record");
      if (record[0] === "di" || record[0] === "af.httprm") continue;
      requireThat(
        record[0] === "wrb.fr" && record[1] === expectedRpc,
        "Unexpected RPC identity or error",
      );
      requireThat(typeof record[2] === "string", "Missing RPC payload");
      let value;
      try {
        value = JSON.parse(record[2]);
      } catch {
        throw new ProtocolError("Invalid RPC payload JSON");
      }
      requireThat(
        Array.isArray(value) && value.length > 0,
        "Missing RPC payload structure",
      );
      found.push(value);
    }
  }
  requireThat(found.length === 1, "Expected exactly one RPC response");
  return found[0];
}

function extensions(row) {
  const candidates = row.filter(
    (v) =>
      v &&
      typeof v === "object" &&
      !Array.isArray(v) &&
      ["163238866", "225032867", "146008172"].some((k) => Object.hasOwn(v, k)),
  );
  requireThat(candidates.length <= 1, "Ambiguous media extension fields");
  return candidates[0] ?? {};
}
export function parseItem(row, namespace = "library-media") {
  array(row, "media");
  const extra = extensions(row);
  const favorite = extra[163238866];
  if (favorite !== undefined) array(favorite, "favorite field");
  const trash = extra[225032867];
  if (trash !== undefined) array(trash, "trash field");
  const timestamp = trash?.[0];
  requireThat(
    timestamp == null || (Number.isSafeInteger(timestamp) && timestamp >= 0),
    "Invalid trash timestamp",
  );
  return {
    namespace,
    mediaKey: identifier(row[0], "media key"),
    dedupKey: identifier(row[3], "dedup key"),
    favorite: knownBoolean(favorite?.[0], "favorite"),
    trashTimestamp: timestamp ?? null,
    companion: extra[146008172] === undefined ? null : true,
  };
}
export function parseAlbum(row) {
  array(row, "album");
  const fields = row.at(-1)?.[72930366];
  array(fields, "album fields");
  const count = fields[3];
  requireThat(Number.isSafeInteger(count) && count >= 0, "Invalid album count");
  return {
    namespace: "album",
    albumId: identifier(row[0], "album ID"),
    title: text(fields[1], "album title"),
    itemCount: count,
    shared: knownBoolean(fields[4], "shared flag"),
  };
}
export function parsePage(data, kind, expectedAlbum) {
  array(data, "page");
  const isAlbum = kind === "albumItems";
  const offset = isAlbum ? 1 : 0;
  requireThat(data.length > offset, "Missing items field");
  const rows = array(data[offset], "page items");
  const cursor = data[offset + 1];
  // Protobuf JSON omits trailing fields. Explicit null/empty and omitted trailing
  // cursor are terminal only after the items array has been validated.
  requireThat(
    cursor == null || typeof cursor === "string",
    "Invalid continuation token",
  );
  if (cursor) identifier(cursor, "continuation token");
  if (isAlbum)
    requireThat(
      array(data[3], "album context")[0] === expectedAlbum,
      "Wrong album identity",
    );
  return {
    items: rows.map((row) =>
      kind === "albums"
        ? parseAlbum(row)
        : parseItem(row, isAlbum ? "album-item" : "library-media"),
    ),
    next: cursor || null,
  };
}
export function parseDetails(data, expectedMedia, extended = false) {
  const row = array(data[0], "item details");
  requireThat(row[0] === expectedMedia, "Wrong media identity");
  if (!extended) return parseItem(row);
  const albums = row[19];
  requireThat(
    albums == null || Array.isArray(albums),
    "Invalid album membership",
  );
  return {
    namespace: "library-media",
    mediaKey: identifier(row[0]),
    dedupKey: identifier(row[11]),
    filename: text(row[2], "filename"),
    albums: albums == null ? null : albums.map(parseAlbum),
    size: row[5],
  };
}

export function readRequest(kind, args = {}) {
  const cursor = args.cursor ?? null;
  if (cursor !== null) identifier(cursor, "cursor");
  switch (kind) {
    case "inventory":
      return { rpc: "lcxiM", data: [cursor, null, 500, null, 1, 3] };
    case "favorites":
      return { rpc: "EzkLib", data: ["Favorites", [[5, "8", 0, 9]], cursor] };
    case "albums":
      return {
        rpc: "Z5xsfc",
        data: [cursor, null, null, null, 1, null, null, 100, [2], 5],
      };
    case "albumItems":
      return {
        rpc: "snAcKc",
        data: [identifier(args.albumId, "album ID"), cursor, null, null],
      };
    case "trash":
      return { rpc: "zy0IHe", data: [cursor] };
    case "item":
      return {
        rpc: "VrseUb",
        data: [identifier(args.mediaKey, "media key"), null, null, null, null],
      };
    case "details":
      return {
        rpc: "fDcn4b",
        data: [identifier(args.mediaKey, "media key"), 1, null, null, 1],
      };
    case "hashCandidates": {
      requireThat(
        Array.isArray(args.hashes) &&
          args.hashes.length > 0 &&
          args.hashes.length <= 100,
        "Expected 1–100 opaque hashes",
        "INPUT",
      );
      args.hashes.forEach((v) => identifier(v, "opaque hash"));
      requireThat(
        new Set(args.hashes).size === args.hashes.length,
        "Repeated hashes",
        "INPUT",
      );
      return { rpc: "swbisb", data: [args.hashes, null, 3, 0] };
    }
    default:
      throw new ProtocolError("Unsupported read operation", "INPUT");
  }
}

export function mutationRequest(operation, target) {
  requireThat(
    target?.namespace === "library-media",
    "Mutation requires a library media identity",
    "INPUT",
  );
  identifier(target.mediaKey, "media key");
  const key = identifier(target.dedupKey, "dedup key");
  switch (operation.type) {
    case "favorite":
      requireThat(
        typeof operation.value === "boolean",
        "Favorite requires a boolean",
        "INPUT",
      );
      return { rpc: "Ftfh0", data: [[[null, key]], [operation.value ? 1 : 2]] };
    case "trash":
      return { rpc: "XwAOJf", data: [null, 1, [key], 3] };
    case "restore":
      return { rpc: "XwAOJf", data: [null, 3, [key], 2] };
    default:
      throw new ProtocolError("Unsupported mutation", "INPUT");
  }
}
