const lists = { people: "person", albums: "album", tags: "tag" };
const scopeKeys = ["folder", "duplicates", "favorite", "trash"];
const choices = {
  people_mode: ["any", "all"],
  date: ["any", "known", "unknown"],
  favorite: ["any", "yes", "no"],
  type: ["any", "image", "video"],
  missing: ["any", "people", "albums"],
};

// The URL carries predicates. Defaults are omitted so equivalent queries share a URL.
export function normalizeFilters(value = {}) {
  const result = {};
  for (const key of Object.keys(lists)) {
    const values = Array.isArray(value[key])
      ? [
          ...new Set(
            value[key].filter((v) => typeof v === "string" && v.length),
          ),
        ].sort()
      : [];
    if (values.length) result[key] = values;
  }
  for (const [key, values] of Object.entries(choices)) {
    // Keep malformed URL values so server validation can explain the problem.
    if (value[key] != null && value[key] !== values[0])
      result[key] = value[key];
  }
  for (const key of ["from", "to"])
    if (typeof value[key] === "string" && value[key]) result[key] = value[key];
  return result;
}

export function filtersFromParams(params) {
  const result = {};
  for (const [key, param] of Object.entries(lists))
    result[key] = params.getAll(param);
  for (const key of [...Object.keys(choices), "from", "to"])
    result[key] = params.get(key);
  return normalizeFilters(result);
}

export function appendFilters(params, filters) {
  const normalized = normalizeFilters(filters);
  for (const param of [
    ...Object.values(lists),
    ...Object.keys(choices),
    "from",
    "to",
  ])
    params.delete(param);
  for (const [key, param] of Object.entries(lists))
    for (const value of normalized[key] || []) params.append(param, value);
  for (const key of [...Object.keys(choices), "from", "to"])
    if (normalized[key]) params.set(key, normalized[key]);
  return params;
}

export function queryScope(route) {
  const result = { filters: normalizeFilters(route.filters) };
  if (route.query) result.q = route.query;
  if (route.tab === "Folders") result.folder = route.folder || ".";
  if (route.tab === "Duplicates") result.duplicates = true;
  if (route.tab === "Favorites") result.favorite = true;
  if (route.tab === "Trash") result.trash = true;
  for (const key of scopeKeys)
    if (route.scope && Object.hasOwn(route.scope, key))
      result[key] = route.scope[key];
  return result;
}

export function scopeFromParams(params) {
  const result = {};
  for (const key of scopeKeys) {
    const value = params.get("scope_" + key);
    if (value !== null)
      result[key] =
        key === "folder"
          ? value
          : value === "true"
            ? true
            : value === "false"
              ? false
              : value;
  }
  return result;
}

export function appendScope(params, scope = {}) {
  for (const key of scopeKeys)
    if (Object.hasOwn(scope, key))
      params.set("scope_" + key, String(scope[key]));
  return params;
}

export function queryParams(route) {
  const params = new URLSearchParams();
  const scope = queryScope(route);
  for (const key of ["duplicates", "favorite", "trash"])
    if (Object.hasOwn(scope, key) && typeof scope[key] !== "boolean")
      throw Error(`Invalid scope_${key}; use true or false.`);
  if (
    Object.hasOwn(scope, "folder") &&
    (typeof scope.folder !== "string" || !scope.folder)
  )
    throw Error("Invalid scope_folder.");
  for (const [key, value] of Object.entries(scope))
    params.set(key, key === "filters" ? JSON.stringify(value) : String(value));
  return params;
}

export function filterChips(filters) {
  const f = normalizeFilters(filters),
    result = [];
  for (const key of Object.keys(lists)) {
    for (const value of f[key] || [])
      result.push({
        key: key + ":" + value,
        label: `${key === "people" ? "Person" : key === "albums" ? "Album" : "Tag"}: ${value}`,
        filters: normalizeFilters({
          ...f,
          [key]: f[key].filter((v) => v !== value),
          ...(key === "people" && f[key].length === 1
            ? { people_mode: "any" }
            : {}),
        }),
      });
  }
  const labels = {
    from: (v) => `From ${v}`,
    to: (v) => `Through ${v}`,
    date: (v) => (v === "known" ? "Date known" : "Date unknown"),
    favorite: (v) => (v === "yes" ? "Favourites only" : "Not favourited"),
    type: (v) => (v === "image" ? "Images" : "Videos"),
    missing: (v) => (v === "people" ? "No people labels" : "No album labels"),
  };
  for (const [key, label] of Object.entries(labels))
    if (f[key]) {
      const next = { ...f };
      delete next[key];
      result.push({
        key,
        label:
          choices[key] && !choices[key].includes(f[key])
            ? `Invalid ${key}: ${f[key]}`
            : label(f[key]),
        filters: normalizeFilters(next),
      });
    }
  return result;
}
