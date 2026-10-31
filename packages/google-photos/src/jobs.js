import { requireThat } from "./errors.js";
import { CATALOG } from "./job-catalog.js";
export const JOB_PROTOCOL_VERSION = 2;
const phases = Object.freeze([
  "checking",
  "library",
  "favorites",
  "albums",
  "reading",
  "preflight",
  "sending",
  "verifying",
  "complete",
  "failed",
]);
export function photoKey(value) {
  requireThat(
    typeof value === "string" && value.length <= 4096,
    "Invalid photo URL",
    "INPUT",
  );
  const u = new URL(value);
  requireThat(
    u.origin === "https://photos.google.com" &&
      !u.username &&
      !u.password &&
      !u.search &&
      !u.hash,
    "Invalid photo URL",
    "INPUT",
  );
  const match = u.pathname.match(/^\/(?:u\/\d+\/)?photo\/([A-Za-z0-9_-]+)$/);
  requireThat(match, "Expected library photo URL", "INPUT");
  return match[1];
}
export function validateField(type, value) {
  const base = type.replace(/\?$/, "");
  if (type.endsWith("?") && value == null) return;
  if (base === "photoUrl") {
    photoKey(value);
    return;
  }
  const rules = {
    id: () => typeof value === "string" && /^[A-Za-z0-9_-]{1,256}$/.test(value),
    cursor: () =>
      typeof value === "string" &&
      value.length > 0 &&
      value.length <= 4096 &&
      !/[\s\x00-\x1f]/.test(value),
    bool: () => typeof value === "boolean",
    text: () =>
      typeof value === "string" &&
      value.length <= 2048 &&
      !/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(value),
    title: () =>
      typeof value === "string" &&
      value.startsWith("PhotoFlow test ") &&
      value.length <= 200,
    epoch: () =>
      Number.isSafeInteger(value) &&
      value >= -2208988800 &&
      value <= 4102444800,
    timezone: () => Number.isSafeInteger(value) && Math.abs(value) <= 50400,
    scale: () => Number.isSafeInteger(value) && value >= 0 && value <= 25,
    coordinates: () =>
      Array.isArray(value) &&
      value.length === 2 &&
      value.every(Number.isSafeInteger) &&
      Math.abs(value[0]) <= 900000000 &&
      Math.abs(value[1]) <= 1800000000,
    hashes: () =>
      Array.isArray(value) &&
      value.length > 0 &&
      value.length <= 20 &&
      new Set(value).size === value.length &&
      value.every(
        (v) =>
          typeof v === "string" &&
          v.length > 0 &&
          v.length <= 256 &&
          !/[\s\x00-\x1f]/.test(v),
      ),
  };
  requireThat(rules[base]?.(), "Invalid job field", "INPUT");
}
function input(spec, value) {
  requireThat(
    value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      Object.keys(value).every((k) => Object.hasOwn(spec.fields, k)),
    "Invalid job input",
    "INPUT",
  );
  for (const [key, type] of Object.entries(spec.fields))
    validateField(type, value[key]);
}
function keys(value, names) {
  requireThat(
    value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      Object.keys(value).every((k) => names.includes(k)),
    "Unexpected result fields",
  );
}
function number(value, min = 0, max = Number.MAX_SAFE_INTEGER) {
  requireThat(
    Number.isSafeInteger(value) && value >= min && value <= max,
    "Invalid result number",
  );
}
function media(value, namespace) {
  keys(value, [
    "namespace",
    "mediaKey",
    "dedupKey",
    "favorite",
    "trashTimestamp",
    "companion",
  ]);
  requireThat(
    Object.keys(value).length === 6 && value.namespace === namespace,
    "Wrong media namespace",
  );
  fieldId(value.mediaKey);
  fieldId(value.dedupKey);
  for (const name of ["favorite", "companion"])
    requireThat(
      value[name] === null || typeof value[name] === "boolean",
      "Unknown media flag",
    );
  if (value.trashTimestamp !== null) number(value.trashTimestamp);
}
function fieldId(value) {
  validateField("id", value);
}
function album(value) {
  keys(value, ["namespace", "albumId", "title", "itemCount", "shared"]);
  requireThat(
    Object.keys(value).length === 5 &&
      value.namespace === "album" &&
      typeof value.title === "string" &&
      value.title.length <= 8192 &&
      (value.shared === null || typeof value.shared === "boolean"),
    "Invalid album",
  );
  fieldId(value.albumId);
  number(value.itemCount, 0, 1000000);
}
export function validateResult(kind, result, operation) {
  requireThat(
    result && typeof result === "object" && !Array.isArray(result),
    "Invalid job result",
  );
  if (kind === "counts") {
    requireThat(
      Object.keys(result).length === 5 &&
        result.complete === true &&
        result.retentionReady === false &&
        ["photos", "favorites", "albums"].every(
          (k) =>
            Number.isSafeInteger(result[k]) &&
            result[k] >= 0 &&
            result[k] <= 1000000,
        ) &&
        result.favorites <= result.photos,
      "Invalid counts result",
    );
    return;
  }
  requireThat(result.retentionReady === false, "Invalid retention evidence");
  if (kind === "page") {
    keys(result, ["items", "next", "complete", "retentionReady"]);
    requireThat(
      Object.keys(result).length === 4 &&
        Array.isArray(result.items) &&
        result.items.length <= 500 &&
        typeof result.complete === "boolean" &&
        result.complete === (result.next === null),
      "Invalid page result",
    );
    validateField("cursor?", result.next);
    result.items.forEach((value) =>
      operation === "albums-page"
        ? album(value)
        : media(
            value,
            operation === "album-members" ? "album-item" : "library-media",
          ),
    );
  } else if (kind === "detail") {
    keys(result, ["photo", "retentionReady"]);
    requireThat(Object.keys(result).length === 2, "Invalid photo result");
    const photo = result.photo;
    const extra = [
      "filename",
      "albums",
      "size",
      "archived",
      "description",
      "timestampMs",
      "timezoneMs",
      "locationE7",
      "manualLocationE7",
    ];
    keys(photo, [
      ...extra,
      "namespace",
      "mediaKey",
      "dedupKey",
      "favorite",
      "trashTimestamp",
      "companion",
    ]);
    media(
      Object.fromEntries(
        Object.entries(photo).filter(([k]) => !extra.includes(k)),
      ),
      "library-media",
    );
    requireThat(
      typeof photo.filename === "string" && photo.filename.length <= 8192,
      "Invalid filename",
    );
    number(photo.size);
    if (photo.albums != null) {
      requireThat(
        Array.isArray(photo.albums) && photo.albums.length <= 500,
        "Invalid memberships",
      );
      photo.albums.forEach(album);
    }
    for (const k of ["timestampMs", "timezoneMs"])
      if (photo[k] != null) number(photo[k], -Number.MAX_SAFE_INTEGER);
    for (const k of ["locationE7", "manualLocationE7"])
      if (photo[k] != null) validateField("coordinates", photo[k]);
    requireThat(
      photo.archived == null || typeof photo.archived === "boolean",
      "Invalid archive flag",
    );
    requireThat(
      photo.description == null ||
        (typeof photo.description === "string" &&
          photo.description.length <= 65536),
      "Invalid description",
    );
  } else if (kind === "quota") {
    keys(result, ["used", "total", "photosUsed", "retentionReady"]);
    requireThat(Object.keys(result).length === 4, "Invalid quota");
    ["used", "total", "photosUsed"].forEach((k) => number(result[k]));
    requireThat(
      result.photosUsed <= result.used && result.used <= result.total,
      "Invalid quota result",
    );
  } else if (kind === "matches") {
    keys(result, ["items", "absenceProven", "retentionReady"]);
    requireThat(
      Object.keys(result).length === 3 &&
        result.absenceProven === false &&
        Array.isArray(result.items) &&
        result.items.length <= 100,
      "Invalid hash candidates",
    );
    for (const item of result.items) {
      validateField("cursor", item.hash);
      media(
        Object.fromEntries(Object.entries(item).filter(([k]) => k !== "hash")),
        "library-media",
      );
    }
  } else if (kind === "download") {
    keys(result, ["mediaKey", "available", "retentionReady"]);
    requireThat(
      Object.keys(result).length === 3 && result.available === true,
      "Invalid download result",
    );
    fieldId(result.mediaKey);
  } else if (kind === "mutation") {
    keys(result, ["verified", "outcome", "albumId", "retentionReady"]);
    requireThat(
      result.verified === true &&
        ["verified", "unchanged", "reconciled"].includes(result.outcome),
      "Unverified mutation result",
    );
    if (operation === "album-create" || result.albumId !== undefined)
      fieldId(result.albumId);
  } else if (kind === "reconciliation") {
    keys(result, ["verified", "originalJobId", "retentionReady", "albumId"]);
    requireThat(
      [3, 4].includes(Object.keys(result).length) && result.verified === true,
      "Invalid reconciliation",
    );
    fieldId(result.originalJobId);
    if (result.albumId !== undefined) fieldId(result.albumId);
  } else requireThat(false, "Unknown result kind");
}
export const JOBS = Object.freeze(
  Object.fromEntries(
    Object.entries(CATALOG).map(([name, spec]) => [
      name,
      Object.freeze({
        ...spec,
        phases,
        validateInput: (value) => input(spec, value),
        validateResult: (value) => validateResult(spec.result, value, name),
      }),
    ]),
  ),
);
export const capabilities = () =>
  Object.entries(JOBS).map(([operation, spec]) => ({
    operation,
    version: spec.version,
  }));
