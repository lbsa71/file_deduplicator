import test from "node:test";
import assert from "node:assert/strict";
import { parseRoute, routeURL } from "./routes.js";
import {
  normalizeFilters,
  filtersFromParams,
  appendFilters,
  filterChips,
  queryScope,
  queryParams,
} from "./query.js";

test("equivalent filter selections have one canonical representation", () => {
  assert.deepEqual(
    normalizeFilters({
      people: ["Viktor", "Ellen", "Viktor"],
      people_mode: "any",
      tags: [],
      favorite: "any",
      missing: "any",
      ignored: true,
    }),
    { people: ["Ellen", "Viktor"] },
  );
});

test("URL filters preserve labels literally and round-trip all query dimensions", () => {
  const filters = normalizeFilters({
    people: ["Ellen & Viktor", "Åsa"],
    people_mode: "all",
    albums: ["Jul #1 / 2009"],
    tags: ["family"],
    from: "2009-01-01",
    to: "2010-12-31",
    date: "known",
    favorite: "no",
    type: "video",
    missing: "albums",
  });
  const params = appendFilters(new URLSearchParams("q=Jul"), filters);
  assert.equal(params.get("q"), "Jul");
  assert.deepEqual(
    filtersFromParams(new URLSearchParams(params.toString())),
    filters,
  );
});

test("date filters preserve explicit bounds for server validation", () => {
  assert.deepEqual(
    normalizeFilters({ date: "unknown", from: "2009-01-01", to: "2010-12-31" }),
    { date: "unknown", from: "2009-01-01", to: "2010-12-31" },
  );
  assert.equal(normalizeFilters({ from: "2009-02-30" }).from, "2009-02-30");
});

test("invalid filter enums reach server validation without silently broadening", () => {
  const filters = filtersFromParams(
    new URLSearchParams("favorite=maybe&people_mode=both"),
  );
  assert.deepEqual(filters, { people_mode: "both", favorite: "maybe" });
  assert.equal(
    queryScope({ tab: "Photos", filters }).filters.favorite,
    "maybe",
  );
});

test("removing chips changes only the intended predicate", () => {
  const f = {
    people: ["Ellen", "Viktor"],
    people_mode: "all",
    from: "2009-01-01",
    favorite: "yes",
  };
  const chips = filterChips(f);
  assert.deepEqual(chips.find((c) => c.key === "people:Ellen").filters, {
    people: ["Viktor"],
    people_mode: "all",
    from: "2009-01-01",
    favorite: "yes",
  });
  assert.equal(
    chips.find((c) => c.key === "favorite").label,
    "Favourites only",
  );
  assert.equal(chips.find((c) => c.key === "from").filters.people_mode, "all");
  assert.deepEqual(
    filterChips({ people: ["Ellen"], people_mode: "all" })[0].filters,
    {},
  );
});

test("API scope keeps selection filters and collection scope together", () => {
  const route = {
    tab: "Folders",
    folder: "folders/Family",
    query: "pic",
    filters: { people: ["Ellen"] },
    offset: 100,
  };
  assert.deepEqual(queryScope(route), {
    q: "pic",
    folder: "folders/Family",
    filters: { people: ["Ellen"] },
  });
  assert.equal(queryParams(route).get("filters"), '{"people":["Ellen"]}');
  assert.equal(queryScope({ tab: "Trash", filters: {} }).trash, true);
  assert.equal(queryScope({ tab: "Duplicates", filters: {} }).duplicates, true);
});

test("people match mode can be chosen before selecting people", () => {
  assert.deepEqual(normalizeFilters({ people_mode: "all" }), {
    people_mode: "all",
  });
});

test("the library folder root keeps its physical-occurrence scope", () => {
  assert.equal(
    queryScope({ tab: "Folders", folder: ".", filters: {} }).folder,
    ".",
  );
  assert.equal(
    queryParams({ tab: "Folders", folder: ".", filters: {} }).get("folder"),
    ".",
  );
  assert.equal(
    queryScope({ tab: "Photos", folder: ".", filters: {} }).folder,
    undefined,
  );
});

test("place hierarchy selections persist and combine by OR", () => {
  const route = parseRoute("/photos?place=Stockholm&place=Norway");
  assert.deepEqual(route.filters.place, ["Norway", "Stockholm"]);
  assert.deepEqual(queryScope(route).filters.place, ["Norway", "Stockholm"]);
  assert.equal(routeURL(route), "/photos?place=Norway&place=Stockholm");
  assert.equal(filterChips(route.filters)[0].label, "Place: Norway");
});
