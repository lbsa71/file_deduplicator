import test from "node:test";
import assert from "node:assert/strict";
import { parseRoute, routeURL, safeReturnURL } from "./routes.js";
const id = "99b8980a-6721-4641-b41c-3d81e81c3b5d";
test("photo deep link retains folder search context", () => {
  const route = parseRoute(
    `https://photos.test/photos/${id}?view=folders&path=folders%2FFamily&q=Alma&offset=100`,
  );
  assert.equal(route.photoId, id);
  assert.equal(route.tab, "Folders");
  assert.equal(route.folder, "folders/Family");
  assert.equal(route.query, "Alma");
  assert.equal(route.offset, 100);
  assert.deepEqual(parseRoute("https://photos.test" + routeURL(route)), route);
});
test("folder URLs preserve unicode and reserved characters", () => {
  const route = {
    ...parseRoute("/folders"),
    folder: "folders/Jul & nyår #1",
    query: "Alma & Stefan",
  };
  const roundtrip = parseRoute(routeURL(route));
  assert.equal(roundtrip.folder, route.folder);
  assert.equal(roundtrip.query, route.query);
});
test("main views are addressable", () => {
  for (const [path, tab] of [
    ["/photos", "Photos"],
    ["/favorites", "Favorites"],
    ["/duplicates", "Duplicates"],
    ["/trash", "Trash"],
    ["/activity", "Activity"],
    ["/folders", "Folders"],
  ])
    assert.equal(parseRoute(path).tab, tab);
});
test("invalid page offsets are safely reset", () => {
  for (const offset of ["-1", "Infinity", "abc", "1.5", "9007199254740992"])
    assert.equal(parseRoute("/photos?offset=" + offset).offset, 0);
});
test("return URLs stay inside recognized UI routes", () => {
  for (const value of [
    "https://evil.test",
    "//evil.test",
    "/\\evil.test",
    "/api/v1/photos",
    "/missing",
  ])
    assert.equal(safeReturnURL(value), "/photos");
  assert.equal(
    safeReturnURL("/photos/" + id + "?q=Alma"),
    "/photos/" + id + "?q=Alma",
  );
});
test("trailing slash variants retain the requested view", () => {
  assert.equal(parseRoute("/favorites/").tab, "Favorites");
  assert.equal(parseRoute("/folders/").tab, "Folders");
  assert.equal(parseRoute("/folders/photos/2000/09/").folder, "photos/2000/09");
  assert.equal(parseRoute("/photos/" + id + "/").photoId, id);
  assert.equal(parseRoute("/login/?next=%2Ffavorites").login, true);
});
