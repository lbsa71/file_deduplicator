import {
  filtersFromParams,
  appendFilters,
  scopeFromParams,
  appendScope,
} from "./query.js";
export const views = {
  Photos: "photos",
  Folders: "folders",
  Favorites: "favorites",
  Duplicates: "duplicates",
  Trash: "trash",
  Activity: "activity",
};
const tabs = Object.fromEntries(
  Object.entries(views).map(([tab, path]) => [path, tab]),
);
const knownPath = (path) => {
  path = path.replace(/\/+$/, "") || "/";
  return (
    path === "/" ||
    Object.values(views).some((view) => path === "/" + view) ||
    /^\/photos\/[^/]+$/.test(path) ||
    /^\/folders\/.+/.test(path)
  );
};
export function safeReturnURL(value) {
  if (
    typeof value !== "string" ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\")
  )
    return "/photos";
  try {
    const url = new URL(value, "https://app.invalid");
    return url.origin === "https://app.invalid" && knownPath(url.pathname)
      ? url.pathname + url.search
      : "/photos";
  } catch {
    return "/photos";
  }
}
export function parseRoute(value) {
  const url = new URL(value, "https://app.invalid"),
    params = url.searchParams;
  const pathname = url.pathname.replace(/\/+$/, "") || "/";
  const folderPath = pathname.match(/^\/folders\/(.+)$/);
  const photo = pathname.match(/^\/photos\/([^/]+)$/);
  let photoId = null;
  if (photo) {
    try {
      photoId = decodeURIComponent(photo[1]);
    } catch {
      photoId = photo[1];
    }
  }
  const offset = Number(params.get("offset") || 0);
  const tab = photo
    ? tabs[params.get("view")] || "Photos"
    : folderPath
      ? "Folders"
      : tabs[pathname.slice(1)] || "Photos";
  let folder = tab === "Folders" ? params.get("path") || "." : ".";
  if (folderPath) {
    try {
      folder = folderPath[1].split("/").map(decodeURIComponent).join("/");
    } catch {
      folder = folderPath[1];
    }
  }
  return {
    tab,
    query: params.get("q") || "",
    filters: filtersFromParams(params),
    scope: scopeFromParams(params),
    folder,
    offset: Number.isSafeInteger(offset) && offset >= 0 ? offset : 0,
    photoId,
    login: pathname === "/login",
    next: pathname === "/login" ? safeReturnURL(params.get("next")) : null,
  };
}
export function routeURL(route) {
  if (route.login) {
    const next = safeReturnURL(route.next);
    return (
      "/login" + (next !== "/photos" ? "?next=" + encodeURIComponent(next) : "")
    );
  }
  const path = route.photoId
    ? "/photos/" + encodeURIComponent(route.photoId)
    : route.tab === "Folders" && route.folder !== "."
      ? "/folders/" + route.folder.split("/").map(encodeURIComponent).join("/")
      : "/" + (views[route.tab] || "photos");
  const params = new URLSearchParams();
  if (route.photoId && route.tab !== "Photos")
    params.set("view", views[route.tab]);
  if (route.photoId && route.tab === "Folders" && route.folder !== ".")
    params.set("path", route.folder);
  if (route.query) params.set("q", route.query);
  if (route.offset) params.set("offset", String(route.offset));
  appendFilters(params, route.filters);
  appendScope(params, route.scope);
  const search = params.toString();
  return path + (search ? "?" + search : "");
}
export function followLink(event, navigate) {
  if (
    event.defaultPrevented ||
    event.button !== 0 ||
    event.metaKey ||
    event.ctrlKey ||
    event.shiftKey ||
    event.altKey
  )
    return;
  event.preventDefault();
  navigate(event.currentTarget.getAttribute("href"));
}
