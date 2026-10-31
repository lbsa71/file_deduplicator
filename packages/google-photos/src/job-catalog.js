// Serializable contract metadata; tools/sync-job-contracts.mjs mirrors it to Python.
const read = (label, fields = {}, result = "page") => ({
  label,
  version: 1,
  effect: "read",
  fields,
  result,
});
const write = (label, fields) => ({
  label,
  version: 1,
  effect: "write",
  fields,
  result: "mutation",
});
export const CATALOG = {
  "inventory-counts": read("Inventory counts", {}, "counts"),
  "library-page": read("Library page", { cursor: "cursor?" }),
  "favorites-page": read("Favorites page", { cursor: "cursor?" }),
  "albums-page": read("Albums page", { cursor: "cursor?" }),
  "album-members": read("Album members", { albumId: "id", cursor: "cursor?" }),
  "photo-details": read(
    "Photo details / Takeout URL",
    { photoUrl: "photoUrl" },
    "detail",
  ),
  "trash-page": read("Trash page", { cursor: "cursor?" }),
  "storage-quota": read("Storage quota", {}, "quota"),
  "hash-candidates": read(
    "Opaque hash candidates",
    { hashes: "hashes" },
    "matches",
  ),
  "download-link": read(
    "Original download reference",
    { photoUrl: "photoUrl" },
    "download",
  ),
  "favorite-set": write("Set favorite", {
    photoUrl: "photoUrl",
    value: "bool",
  }),
  "archive-set": write("Set archive", { photoUrl: "photoUrl", value: "bool" }),
  trash: write("Move test photo to Trash", { photoUrl: "photoUrl" }),
  restore: write("Restore test photo", { photoUrl: "photoUrl" }),
  "album-create": write("Create test album", { title: "title" }),
  "album-add": write("Add photo to test album", {
    photoUrl: "photoUrl",
    albumId: "id",
  }),
  "album-remove": write("Remove photo from test album", {
    photoUrl: "photoUrl",
    albumId: "id",
  }),
  "description-set": write("Set description", {
    photoUrl: "photoUrl",
    description: "text",
  }),
  "timestamp-set": write("Set timestamp", {
    photoUrl: "photoUrl",
    timestampSec: "epoch",
    timezoneSec: "timezone",
  }),
  "location-set": write("Set location", {
    photoUrl: "photoUrl",
    centerE7: "coordinates",
    visible1E7: "coordinates",
    visible2E7: "coordinates",
    scale: "scale",
    placeId: "id",
  }),
  "location-clear": write("Clear manually added location", {
    photoUrl: "photoUrl",
  }),
  "reconcile-write": read(
    "Reconcile unknown write",
    { originalJobId: "id" },
    "reconciliation",
  ),
};
