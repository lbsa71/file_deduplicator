import test from "node:test";
import assert from "node:assert/strict";
import { batchOperation, routeFromScope } from "./batch.js";
import { queryScope, normalizeFilters } from "./query.js";
import { parseRoute, routeURL } from "./routes.js";

test("label operations preserve names containing commas and separate reset from clear", () => {
  assert.deepEqual(
    batchOperation({
      action: "labels",
      field: "people",
      mode: "add",
      value: "Ellen\nDoe, Jane\nEllen",
    }),
    { action: "metadata", add: { people: ["Ellen", "Doe, Jane"] } },
  );
  assert.deepEqual(
    batchOperation({
      action: "labels",
      field: "tags",
      mode: "reset",
      value: "",
    }),
    { action: "metadata", reset: ["tags"] },
  );
  assert.deepEqual(
    batchOperation({
      action: "labels",
      field: "tags",
      mode: "replace",
      value: "",
    }),
    { action: "metadata", set: { tags: [] } },
  );
  assert.throws(() =>
    batchOperation({ action: "labels", field: "tags", mode: "add", value: "" }),
  );
});
test("favourite no is an explicit false override", () => {
  assert.deepEqual(batchOperation({ action: "favorite", value: "no" }), {
    action: "metadata",
    set: { favorite: false },
  });
  assert.deepEqual(batchOperation({ action: "favorite", value: "reset" }), {
    action: "metadata",
    reset: ["favorite"],
  });
});
test("opening a saved scope restores its predicates and resets pagination", () => {
  const route = routeFromScope({
    folder: "folders/Family",
    q: "Christmas",
    duplicates: true,
    filters: { people: ["Ellen"] },
  });
  assert.equal(route.tab, "Folders");
  assert.equal(route.folder, "folders/Family");
  assert.equal(route.query, "Christmas");
  assert.equal(route.offset, 0);
  assert.deepEqual(route.filters, { people: ["Ellen"] });
});

test("every saved scope combination survives navigation and photo links", () => {
  const canonical = (scope) => ({
    q: "",
    folder: null,
    duplicates: false,
    favorite: false,
    trash: false,
    ...scope,
    filters: normalizeFilters(scope.filters),
  });
  for (const folder of [null, ".", "folders/Family & friends"])
    for (const duplicates of [false, true])
      for (const favorite of [false, true])
        for (const trash of [false, true]) {
          const scope = {
            q: "Ellen",
            folder,
            duplicates,
            favorite,
            trash,
            filters: { people: ["Ellen"], favorite: "no" },
          };
          const route = routeFromScope(scope);
          assert.deepEqual(
            canonical(queryScope(parseRoute(routeURL(route)))),
            canonical(scope),
            JSON.stringify(scope),
          );
          assert.deepEqual(
            canonical(
              queryScope(
                parseRoute(routeURL({ ...route, photoId: "photo-1" })),
              ),
            ),
            canonical(scope),
          );
        }
});

test("ordinary saved view URLs stay concise", () => {
  assert.equal(
    routeURL(routeFromScope({ filters: { people: ["Ellen"] } })),
    "/photos?person=Ellen",
  );
  assert.equal(
    routeURL(routeFromScope({ favorite: true, filters: {} })),
    "/favorites",
  );
  assert.equal(
    routeURL(routeFromScope({ folder: ".", filters: {} })),
    "/folders",
  );
});
