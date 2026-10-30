import { queryScope } from "./query.js";

export function batchOperation(draft) {
  const { action, field, mode, value = "" } = draft;
  if (action === "labels") {
    const values = [
      ...new Set(
        value
          .split("\n")
          .map((v) => v.trim())
          .filter(Boolean),
      ),
    ];
    if (mode === "reset") return { action: "metadata", reset: [field] };
    if (!values.length && mode !== "replace")
      throw Error("Enter at least one label.");
    return {
      action: "metadata",
      [mode === "replace" ? "set" : mode]: { [field]: values },
    };
  }
  if (action === "favorite")
    return value === "reset"
      ? { action: "metadata", reset: ["favorite"] }
      : { action: "metadata", set: { favorite: value === "yes" } };
  if (action === "date")
    return mode === "reset"
      ? { action: "metadata", reset: ["capture_time"] }
      : { action: "metadata", set: { capture_time: value || null } };
  if (action === "move") {
    if (!value) throw Error("Choose a destination folder.");
    return { action: "move", folder_id: value };
  }
  return { action };
}
export function routeFromScope(scope) {
  const route = {
    tab: scope.trash
      ? "Trash"
      : scope.folder
        ? "Folders"
        : scope.favorite
          ? "Favorites"
          : scope.duplicates
            ? "Duplicates"
            : "Photos",
    query: scope.q || "",
    folder: scope.folder || ".",
    filters: scope.filters || {},
    offset: 0,
    photoId: null,
    login: false,
    next: null,
    scope: {},
  };
  const implicit = queryScope(route);
  for (const [key, fallback] of Object.entries({
    folder: null,
    duplicates: false,
    favorite: false,
    trash: false,
  })) {
    const wanted = scope[key] ?? fallback;
    if (wanted !== (implicit[key] ?? fallback)) route.scope[key] = wanted;
  }
  return route;
}
