import React, { useState as S, useEffect as E } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
import { parseRoute, routeURL, followLink } from "./routes.js";
import { queryScope, queryParams } from "./query.js";
import { Filters, FilterChips } from "./filters.jsx";
import { SavedViews, BatchDialog } from "./workspace.jsx";
function App() {
  const [user, setUser] = S(null),
    [error, X] = S(""),
    [items, I] = S([]),
    [total, T] = S(0),
    [folders, G] = S([]),
    [registered, R] = S([]),
    [view, setView] = S(null),
    [busy, W] = S(""),
    [jobs, J] = S([]),
    [selected, C] = S(new Map()),
    [selection, setSelection] = S(null),
    [batchOpen, setBatchOpen] = S(null),
    [facets, setFacets] = S({}),
    [loading, setLoading] = S(false),
    [scanMode, setScanMode] = S("reconcile"),
    [editing, K] = S(null),
    [trashFolders, H] = S([]);
  const authRef = React.useRef(null);
  function U(value) {
    if (value?.username !== authRef.current?.username) {
      clearSelection();
      setBatchOpen(null);
      I([]);
      T(0);
      setFacets({});
    }
    authRef.current = value;
    setUser(value);
  }
  const [route, setRoute] = S(() => parseRoute(window.location.href));
  const routeRef = React.useRef(route),
    loadSequence = React.useRef(0),
    refresh = React.useRef(null),
    pendingScroll = React.useRef(null);
  const { tab, query, folder, offset, filters = {} } = route;
  const filterKey = JSON.stringify(filters);
  const scopeKey = JSON.stringify(route.scope || {});
  const selectionCount = selection?.count ?? selected.size;
  function clearSelection() {
    C(new Map());
    setSelection(null);
  }
  function filterChange(value) {
    updateRoute(
      { filters: value, offset: 0, photoId: null },
      { scroll: window.scrollY },
    );
  }
  function collectionKey(value) {
    return routeURL({ ...value, photoId: null, login: false, next: null });
  }
  function prepareCollection(current, next, scroll) {
    if (
      collectionKey({ ...current, offset: 0 }) !==
      collectionKey({ ...next, offset: 0 })
    )
      clearSelection();
    if (collectionKey(current) !== collectionKey(next)) {
      loadSequence.current++;
      pendingScroll.current = scroll;
    }
  }
  function navigate(value, options = {}) {
    const next = typeof value === "string" ? parseRoute(value) : value;
    const url = routeURL(next),
      current = routeRef.current;
    if (url === window.location.pathname + window.location.search) return;
    history.replaceState(
      { ...history.state, scroll: window.scrollY },
      "",
      window.location.href,
    );
    history[options.replace ? "replaceState" : "pushState"](
      {
        viewerBackground: options.viewerBackground || null,
        scroll: options.scroll || 0,
      },
      "",
      url,
    );
    prepareCollection(current, next, options.scroll || 0);
    routeRef.current = next;
    setRoute(next);
    X("");
    if (!next.photoId) setView(null);
    if (!next.photoId && !current.photoId)
      window.scrollTo(0, options.scroll || 0);
  }
  function updateRoute(patch, options = {}) {
    navigate(
      { ...routeRef.current, ...patch, login: false, next: null },
      options,
    );
  }
  function Q(value) {
    updateRoute(
      { query: value, photoId: null, offset: 0 },
      { replace: !!routeRef.current.query },
    );
  }
  function F(value) {
    updateRoute({ tab: "Folders", folder: value, photoId: null, offset: 0 });
  }
  function O(value) {
    updateRoute({ offset: value, photoId: null });
  }
  function closePhoto() {
    const current = routeRef.current;
    if (!current.photoId) {
      setView(null);
      return;
    }
    const background = { ...current, photoId: null };
    if (history.state?.viewerBackground === routeURL(background))
      history.back();
    else
      navigate(background, {
        replace: true,
        scroll: history.state?.scroll || 0,
      });
  }
  function V(value) {
    if (value === null) closePhoto();
    else setView(value);
  }
  E(() => {
    const old = history.scrollRestoration;
    history.scrollRestoration = "manual";
    const pop = () => {
      const next = parseRoute(window.location.href);
      const current = routeRef.current;
      prepareCollection(current, next, history.state?.scroll || 0);
      routeRef.current = next;
      setRoute(next);
      if (current.photoId !== next.photoId || !next.photoId) setView(null);
      X("");
      requestAnimationFrame(() =>
        window.scrollTo(0, history.state?.scroll || 0),
      );
    };
    window.addEventListener("popstate", pop);
    if (window.location.pathname === "/")
      navigate(routeRef.current, { replace: true });
    return () => {
      window.removeEventListener("popstate", pop);
      history.scrollRestoration = old;
    };
  }, []);
  E(() => {
    if (user && route.login)
      navigate(route.next || "/photos", { replace: true });
  }, [user, route.login, route.next]);
  E(() => {
    let cancelled = false;
    setView(null);
    if (user && route.photoId)
      api("/photos/" + encodeURIComponent(route.photoId))
        .then((value) => {
          if (!cancelled) setView(value);
        })
        .catch((error) => {
          if (!cancelled) X("Photo unavailable: " + error.message);
        });
    return () => {
      cancelled = true;
    };
  }, [user, route.photoId]);
  async function api(path, method = "GET", body, revision) {
    const requestUser = authRef.current;
    let r = await fetch("/api/v1" + path, {
      method,
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(requestUser ? { "X-CSRF-Token": requestUser.csrf } : {}),
        ...(revision ? { "If-Match": `"${revision}"` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!r.ok) {
      if (
        r.status === 401 &&
        requestUser &&
        authRef.current === requestUser &&
        path !== "/auth/login"
      ) {
        U(null);
        setView(null);
      }
      let e = await r.json().catch(() => ({ detail: r.statusText }));
      throw Error(
        typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail),
      );
    }
    return r.status === 204 ? null : r.json();
  }
  async function load() {
    if (!user) return;
    const sequence = ++loadSequence.current;
    setLoading(true);
    try {
      let p = queryParams(routeRef.current);
      p.set("offset", String(offset));
      p.set("limit", "100");
      const [d, directories, trash, jobs, library, facetData] =
        await Promise.all([
          api("/photos?" + p),
          tab === "Folders"
            ? api("/folders?path=" + encodeURIComponent(folder))
            : null,
          tab === "Trash" ? api("/trash/folders") : null,
          tab === "Activity" ? api("/jobs") : null,
          api("/library"),
          tab !== "Activity"
            ? api("/facets?" + queryParams(routeRef.current))
            : null,
        ]);
      if (sequence !== loadSequence.current) return;
      I(d.items);
      T(d.total);
      if (facetData) setFacets(facetData);
      if (directories) G(directories.items);
      if (trash) H(trash.items);
      if (jobs) J(jobs.items);
      R(library.folders);
      if (pendingScroll.current !== null)
        requestAnimationFrame(() => {
          if (
            sequence === loadSequence.current &&
            pendingScroll.current !== null
          ) {
            window.scrollTo(0, pendingScroll.current);
            pendingScroll.current = null;
          }
        });
    } catch (e) {
      if (sequence === loadSequence.current) {
        I([]);
        T(0);
        G([]);
        setFacets({});
        X(e.message);
      }
    } finally {
      if (sequence === loadSequence.current) setLoading(false);
    }
  }
  refresh.current = load;
  E(() => {
    let close = (e) => {
      if (e.key === "Escape") {
        K(null);
        V(null);
      }
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, []);
  E(() => {
    api("/auth/session")
      .then((value) => {
        if (!authRef.current) U(value);
      })
      .catch(() => {});
  }, []);
  E(() => {
    if (user) load();
  }, [user, tab, query, folder, offset, filterKey, scopeKey]);
  async function act(fn) {
    try {
      X("");
      W("Working…");
      let r = await fn();
      if (r?.job_id) {
        for (let n = 0; n < 600; n++) {
          let j = await api("/jobs/" + r.job_id);
          if (j.state === "failed") throw Error(j.error);
          if (j.state === "succeeded") break;
          await new Promise((r) => setTimeout(r, 500));
        }
      }
      await refresh.current();
    } catch (e) {
      X(e.message);
    } finally {
      W("");
    }
  }
  function open(id) {
    const current = routeRef.current;
    navigate(
      { ...current, photoId: id },
      {
        viewerBackground: routeURL({ ...current, photoId: null }),
        scroll: window.scrollY,
      },
    );
  }
  async function edit(d) {
    K(d);
  }
  async function upload(files) {
    await act(async () => {
      let saved = JSON.parse(localStorage.getItem("photoflow-uploads") || "{}"),
        batch = saved.batch || crypto.randomUUID().replaceAll("-", "");
      saved.batch = batch;
      for (let f of [...files].sort(
        (a, b) =>
          Number(!a.name.endsWith(".json")) - Number(!b.name.endsWith(".json")),
      )) {
        W("Uploading " + f.name);
        let key = f.name + ":" + f.size + ":" + f.lastModified,
          up = saved[key]
            ? await api("/uploads/" + saved[key])
            : await api("/uploads", "POST", {
                name: f.name,
                size: f.size,
                batch_id: batch,
                folder_id: registered.find((x) => x.path === folder)?.id,
              });
        saved[key] = up.id;
        localStorage.setItem("photoflow-uploads", JSON.stringify(saved));
        for (let start = 0; start < up.offset; start += 8 * 1024 ** 2) {
          let bytes = await f
              .slice(start, Math.min(start + 8 * 1024 ** 2, up.offset))
              .arrayBuffer(),
            hash = [
              ...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)),
            ]
              .map((v) => v.toString(16).padStart(2, "0"))
              .join("");
          if (hash !== up.chunks[String(start)])
            throw Error("Reselected file differs from uploaded bytes");
        }
        if (up.state !== "committed") {
          for (let start = up.offset; start < f.size; start += 8 * 1024 ** 2) {
            let r = await fetch("/api/v1/uploads/" + up.id + "/chunks", {
              method: "PUT",
              headers: {
                "X-CSRF-Token": user.csrf,
                "Upload-Offset": String(start),
              },
              body: f.slice(start, start + 8 * 1024 ** 2),
            });
            if (!r.ok)
              throw Error(
                "Upload paused: reselect these files to resume. " + f.name,
              );
          }
          await api("/uploads/" + up.id + "/finish", "POST", {});
        }
      }
      let result = await api(
        "/upload-batches/" + batch + "/process",
        "POST",
        {},
      );
      localStorage.removeItem("photoflow-uploads");
      return result;
    });
  }
  async function trash(d) {
    if (confirm("Move this occurrence to Trash? Other retained copies remain."))
      await act(async () => {
        V(null);
        return api("/photos/" + d.record_id, "DELETE", undefined, d.revision);
      });
  }
  async function bulk(action) {
    if (action === "download") {
      await act(async () => {
        let r = await api(
          "/exports",
          "POST",
          selection
            ? { selection_id: selection.id }
            : { ids: [...selected.keys()] },
        );
        for (let n = 0; n < 600; n++) {
          let j = await api("/jobs/" + r.job_id);
          if (j.state === "failed") throw Error(j.error);
          if (j.state === "succeeded") {
            window.location.href = j.result.download_url;
            break;
          }
          await new Promise((r) => setTimeout(r, 500));
        }
      });
    }
  }
  if (!user)
    return (
      <main className="login">
        <h1>
          PhotoFlow<span>Your photographs, at home.</span>
        </h1>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            let d = new FormData(e.target);
            try {
              U(await api("/auth/login", "POST", Object.fromEntries(d)));
            } catch (e) {
              X(e.message);
            }
          }}
        >
          <label>
            Linux username
            <input name="username" autoComplete="username" required />
          </label>
          <label>
            Password
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
            />
          </label>
          <button>Sign in</button>
          <p role="alert">{error}</p>
        </form>
      </main>
    );
  return (
    <>
      <aside>
        <h1>PhotoFlow</h1>
        {[
          "Photos",
          "Folders",
          "Favorites",
          "Duplicates",
          "Trash",
          "Activity",
        ].map((t) => (
          <a
            href={routeURL({
              ...route,
              tab: t,
              query: "",
              filters: {},
              scope: {},
              folder: ".",
              offset: 0,
              photoId: null,
              login: false,
            })}
            className={"nav-link " + (tab === t ? "active" : "")}
            onClick={(event) =>
              followLink(event, (url) => {
                navigate(url);
                clearSelection();
              })
            }
            key={t}
          >
            {t}
          </a>
        ))}
        <footer>
          {user.username}
          <button
            onClick={() =>
              act(async () => {
                await api("/auth/logout", "POST", {});
                U(null);
                I([]);
                setView(null);
                navigate(
                  "/login?next=" +
                    encodeURIComponent(routeURL(routeRef.current)),
                  { replace: true },
                );
              })
            }
          >
            Sign out
          </button>
        </footer>
      </aside>
      <main>
        <header>
          <input
            aria-label="Search library"
            placeholder="Search people, albums, filenames…"
            value={query}
            onChange={(e) => {
              Q(e.target.value);
              O(0);
            }}
          />
          {user.role >= 2 && (
            <label className="button">
              Upload
              <input
                type="file"
                multiple
                hidden
                onChange={(e) => upload(e.target.files)}
              />
            </label>
          )}
          {user.role >= 3 && (
            <div className="maintenance-controls">
              <select
                aria-label="Whole-library maintenance"
                value={scanMode}
                onChange={(e) => setScanMode(e.target.value)}
              >
                <option value="reconcile">Scan library</option>
                <option value="metadata">Re-extract all metadata</option>
                <option value="verify">Verify all originals</option>
                <option value="catalog">Rebuild catalog</option>
                <option value="thumbnails">Warm all thumbnails</option>
              </select>
              <button
                onClick={() =>
                  act(() => api("/scans", "POST", { mode: scanMode }))
                }
                disabled={!!busy}
                title="Applies to the entire library, independently of filters and selection"
              >
                Rescan
              </button>
            </div>
          )}
        </header>
        <section className="heading">
          <div>
            <h2>{tab}</h2>
            <small role="status">
              {loading
                ? "Updating results…"
                : `${total.toLocaleString()} matching photographs and videos`}
            </small>
          </div>
          <span>{busy}</span>
        </section>
        {error && (
          <div className="error" role="alert" onClick={() => X("")}>
            {error} ×
          </div>
        )}
        {tab !== "Activity" && (
          <div className="selection-options">
            <button
              disabled={loading || !!selection || !items.length}
              onClick={() =>
                C(
                  (s) =>
                    new Map([...s, ...items.map((d) => [d.id, d.revision])]),
                )
              }
            >
              Select page
            </button>
            <button
              disabled={loading || !total || !!busy}
              onClick={() =>
                act(async () => {
                  const expected = collectionKey({
                      ...routeRef.current,
                      offset: 0,
                    }),
                    owner = authRef.current;
                  const s = await api("/selections", "POST", {
                    query: queryScope(routeRef.current),
                  });
                  if (
                    owner === authRef.current &&
                    expected ===
                      collectionKey({ ...routeRef.current, offset: 0 })
                  ) {
                    setSelection(s);
                    C(new Map());
                  }
                })
              }
            >
              Select all {total.toLocaleString()} matching
            </button>
            {selectionCount > 0 && (
              <button onClick={clearSelection}>Clear selection</button>
            )}
          </div>
        )}
        {selectionCount > 0 && (
          <div className="selection">
            <strong>{selectionCount.toLocaleString()} selected</strong>
            {selection && (
              <small>Fixed selection · expires in 30 minutes</small>
            )}
            <button
              disabled={selectionCount > 1000 || tab === "Trash" || !!busy}
              title={
                selectionCount > 1000
                  ? "Exports support up to 1,000 photos and 20 GiB per ZIP"
                  : ""
              }
              onClick={() => bulk("download")}
            >
              Download ZIP
            </button>
            {selectionCount > 1000 && (
              <small>ZIP export: up to 1,000 photos per download</small>
            )}
            {user.role >= 2 && (
              <button
                disabled={!!busy || loading}
                onClick={() =>
                  setBatchOpen({
                    selection: selection
                      ? { selection_id: selection.id }
                      : {
                          targets: [...selected].map(([id, revision]) => ({
                            id,
                            revision,
                          })),
                        },
                    count: selectionCount,
                    trashed: tab === "Trash",
                  })
                }
              >
                Batch actions
              </button>
            )}
          </div>
        )}
        {tab === "Folders" && (
          <section className="folders">
            <button
              onClick={() =>
                F(
                  folder === "."
                    ? "."
                    : folder.split("/").slice(0, -1).join("/") || ".",
                )
              }
            >
              ↑ Parent
            </button>
            <strong>{folder === "." ? "Library" : folder}</strong>
            {user.role >= 2 && registered.find((f) => f.path === folder) && (
              <>
                <button
                  onClick={() => {
                    let f = registered.find((f) => f.path === folder),
                      name = prompt("Rename folder", f.name);
                    if (name)
                      act(() =>
                        api(
                          "/folders/" + f.id,
                          "PATCH",
                          { name, parent_id: f.parent_id },
                          f.revision,
                        ),
                      );
                  }}
                >
                  Rename
                </button>
                <button
                  onClick={() => {
                    let f = registered.find((f) => f.path === folder);
                    if (
                      confirm(
                        "Move this entire folder and all contents to Trash?",
                      )
                    )
                      act(async () => {
                        let r = await api(
                          "/folders/" + f.id,
                          "DELETE",
                          undefined,
                          f.revision,
                        );
                        F("folders");
                        return r;
                      });
                  }}
                >
                  Trash folder
                </button>
              </>
            )}
            {user.role >= 2 && (
              <button
                onClick={() => {
                  let name = prompt("New folder name");
                  if (name)
                    act(() =>
                      api("/folders", "POST", {
                        name,
                        parent_id: registered.find((f) => f.path === folder)
                          ?.id,
                      }),
                    );
                }}
              >
                New folder
              </button>
            )}
            <div>
              {folders.map((f) => (
                <a
                  className="folder-link"
                  key={f.path}
                  href={routeURL({
                    ...route,
                    tab: "Folders",
                    folder: f.path,
                    offset: 0,
                    photoId: null,
                  })}
                  onClick={(event) => followLink(event, navigate)}
                >
                  📁 {f.name}
                </a>
              ))}
            </div>
          </section>
        )}
        {tab === "Trash" &&
          trashFolders.map((t) => (
            <div className="folders" key={t.folder.id}>
              📁 {t.folder.path}{" "}
              <button
                onClick={() =>
                  act(() =>
                    api(
                      "/trash/folders/" + t.folder.id + "/restore",
                      "POST",
                      {},
                    ),
                  )
                }
              >
                Restore entire folder
              </button>
            </div>
          ))}
        {tab === "Activity" ? (
          <section>
            {jobs.map((j) => (
              <article key={j.id}>
                <b>{j.action}</b> — {j.state}
                <p>{j.error}</p>
                {j.result && (
                  <details>
                    <summary>Result</summary>
                    <pre>{JSON.stringify(j.result, null, 2)}</pre>
                  </details>
                )}
                <small>{new Date(j.created * 1000).toLocaleString()}</small>
              </article>
            ))}
            <button onClick={load}>Refresh</button>
          </section>
        ) : (
          <div className="query-layout">
            <div className="query-sidebar">
              <SavedViews
                api={api}
                scope={queryScope(route)}
                navigate={navigate}
                username={user.username}
              />
              <Filters
                filters={filters}
                onChange={filterChange}
                facets={facets}
                busy={loading}
              />
            </div>
            <div className="query-results" aria-busy={loading}>
              <FilterChips filters={filters} onChange={filterChange} />
              {Object.keys(route.scope || {}).length > 0 && (
                <div
                  className="filter-chips"
                  aria-label="Additional collection constraints"
                >
                  {Object.entries(route.scope).map(([key, value]) => (
                    <button
                      key={key}
                      onClick={() => {
                        const scope = { ...route.scope };
                        delete scope[key];
                        updateRoute({ scope, offset: 0, photoId: null });
                      }}
                    >
                      {key === "folder"
                        ? `Folder: ${value}`
                        : key === "favorite"
                          ? value
                            ? "Favourites only"
                            : "All favourite states"
                          : key === "duplicates"
                            ? value
                              ? "Include retained copies"
                              : "Canonical photos"
                            : value
                              ? "Trashed photos"
                              : "Active photos"}{" "}
                      ×
                    </button>
                  ))}
                </div>
              )}
              {!loading && !items.length && (
                <p className="empty-results">
                  No photos match this view. Adjust a filter or clear the
                  search.
                </p>
              )}
              <section className="grid">
                {items.map((d) => (
                  <article className="tile" key={d.id} data-record-id={d.id}>
                    <input
                      aria-label="Select photo"
                      type="checkbox"
                      checked={!!selection || selected.has(d.id)}
                      disabled={loading || !!selection}
                      onChange={(e) =>
                        C((s) => {
                          let n = new Map(s);
                          e.target.checked
                            ? n.set(d.id, d.revision)
                            : n.delete(d.id);
                          return n;
                        })
                      }
                    />
                    <a
                      className="photo-link"
                      href={routeURL({ ...route, photoId: d.id })}
                      onClick={(event) => followLink(event, () => open(d.id))}
                    >
                      {tab === "Trash" ? (
                        <div className="placeholder">In trash</div>
                      ) : (
                        <Thumb id={d.id} />
                      )}
                      <div className="caption">
                        {d.metadata.title ||
                          d.metadata.people?.join(", ") ||
                          d.metadata.capture_time?.slice(0, 10) ||
                          "Undated"}
                        {d.metadata.favorite ? " ♥" : ""}
                      </div>
                    </a>
                  </article>
                ))}
              </section>
              <nav className="pages">
                <button
                  disabled={!offset}
                  onClick={() => O(Math.max(0, offset - 100))}
                >
                  Previous
                </button>
                <span>{Math.floor(offset / 100) + 1}</span>
                <button
                  disabled={offset + 100 >= total}
                  onClick={() => O(offset + 100)}
                >
                  Next
                </button>
              </nav>
            </div>
          </div>
        )}
      </main>
      {batchOpen && (
        <BatchDialog
          api={api}
          selection={batchOpen.selection}
          count={batchOpen.count}
          folders={registered}
          trashed={batchOpen.trashed}
          onClose={() => setBatchOpen(null)}
          onDone={() => {
            clearSelection();
            refresh.current();
          }}
        />
      )}
      {view && (
        <div className="viewer" role="dialog" aria-modal="true">
          <button className="close" onClick={() => V(null)}>
            Close ×
          </button>
          <div className="picture">
            {view.lifecycle === "trashed" ? (
              <p>Restore this photo to view its original.</p>
            ) : /\.(mov|mp4|m4v|webm)$/i.test(view.file.relative_path) ? (
              <video
                controls
                src={"/api/v1/photos/" + view.record_id + "/original"}
              />
            ) : (
              <Thumb id={view.record_id} level={2048} />
            )}
          </div>
          <section className="details">
            <h2>{view.resolved.title || view.sources[0].original_filename}</h2>
            <p>{view.resolved.description}</p>
            <p>{view.resolved.capture_time}</p>
            <p>{view.resolved.people?.join(", ")}</p>
            <p>{view.resolved.albums?.join(", ")}</p>
            <small>{view.file.relative_path}</small>
            <div className="actions">
              <a
                href={
                  "/api/v1/photos/" + view.record_id + "/original?download=true"
                }
              >
                Download original
              </a>
              <a href={"/api/v1/photos/" + view.record_id + "/sidecar"}>
                Download metadata
              </a>
              {user.role >= 2 &&
                (view.lifecycle === "trashed" ? (
                  <button
                    onClick={() =>
                      act(async () => {
                        V(null);
                        return api(
                          "/trash/" + view.record_id + "/restore",
                          "POST",
                          {},
                          view.revision,
                        );
                      })
                    }
                  >
                    Restore
                  </button>
                ) : (
                  <>
                    <button onClick={() => edit(view)}>Edit metadata</button>
                    <button
                      onClick={() =>
                        act(async () => {
                          let r = await api(
                            "/photos/" + view.record_id + "/metadata",
                            "PATCH",
                            { set: { favorite: !view.resolved.favorite } },
                            view.revision,
                          );
                          V(null);
                          return r;
                        })
                      }
                    >
                      Favorite ♥
                    </button>
                    <button
                      onClick={() => {
                        let f = prompt(
                          "Destination folder ID:\n" +
                            registered
                              .map((f) => f.path + " → " + f.id)
                              .join("\n"),
                        );
                        if (f)
                          act(async () => {
                            V(null);
                            return api(
                              "/photos/" + view.record_id + "/placement",
                              "POST",
                              { folder_id: f },
                              view.revision,
                            );
                          });
                      }}
                    >
                      Move
                    </button>
                    <button onClick={() => trash(view)}>Trash</button>
                  </>
                ))}
            </div>
            <details>
              <summary>Sources and history</summary>
              <pre>{JSON.stringify(view, null, 2)}</pre>
            </details>
          </section>
        </div>
      )}
      {editing && (
        <MetadataEditor
          record={editing}
          cancel={() => K(null)}
          save={(body) =>
            act(async () => {
              let r = await api(
                "/photos/" + editing.record_id + "/metadata",
                "PATCH",
                body,
                editing.revision,
              );
              K(null);
              V(null);
              return r;
            })
          }
        />
      )}
    </>
  );
}
function MetadataEditor({ record, cancel, save }) {
  let [d, D] = S({ ...record.resolved }),
    [reset, R] = S([]);
  return (
    <div className="editor" role="dialog" aria-modal="true">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          let set = Object.fromEntries(
            [
              "title",
              "description",
              "capture_time",
              "people",
              "albums",
              "tags",
              "favorite",
              "display_rotation",
            ]
              .filter((k) => !reset.includes(k))
              .map((k) => [k, d[k] ?? null]),
          );
          save({ set, reset });
        }}
      >
        <h2>Edit photo metadata</h2>
        {[
          "title",
          "description",
          "capture_time",
          "people",
          "albums",
          "tags",
        ].map((k) => (
          <label key={k}>
            {k.replaceAll("_", " ")}
            <input
              value={Array.isArray(d[k]) ? d[k].join(", ") : d[k] || ""}
              onChange={(e) =>
                D({
                  ...d,
                  [k]: ["people", "albums", "tags"].includes(k)
                    ? e.target.value
                        .split(",")
                        .map((v) => v.trim())
                        .filter(Boolean)
                    : e.target.value || null,
                })
              }
            />
            <small>
              <input
                type="checkbox"
                checked={reset.includes(k)}
                onChange={(e) =>
                  R(
                    e.target.checked
                      ? [...reset, k]
                      : reset.filter((x) => x !== k),
                  )
                }
              />{" "}
              Reset to imported value
            </small>
          </label>
        ))}
        <label>
          Display rotation
          <select
            value={d.display_rotation || 0}
            onChange={(e) =>
              D({ ...d, display_rotation: Number(e.target.value) })
            }
          >
            {[0, 90, 180, 270].map((n) => (
              <option key={n} value={n}>
                {n}°
              </option>
            ))}
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={!!d.favorite}
            onChange={(e) => D({ ...d, favorite: e.target.checked })}
          />{" "}
          Favorite
        </label>
        <footer>
          <button type="button" onClick={cancel}>
            Cancel
          </button>
          <button>Save changes</button>
        </footer>
      </form>
    </div>
  );
}
const previewBlobs = new Map();
function rememberPreview(key, blob) {
  previewBlobs.delete(key);
  previewBlobs.set(key, blob);
  while (previewBlobs.size > 128)
    previewBlobs.delete(previewBlobs.keys().next().value);
}
function Thumb({ id, level = 512 }) {
  const [src, setSrc] = S(null),
    [failed, setFailed] = S(false);
  const [visible, setVisible] = S(false),
    ref = React.useRef(null);
  E(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "300px" },
    );
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, [id]);
  E(() => {
    if (!visible) return;
    let done = false,
      timer;
    setFailed(false);
    const cached =
      previewBlobs.get(`${id}:${level}`) ||
      (level > 512 && previewBlobs.get(`${id}:512`));
    setSrc(cached ? URL.createObjectURL(cached) : null);
    async function get(requestedLevel, fallback = false) {
      try {
        const response = await fetch(
          `/api/v1/photos/${id}/variants/${requestedLevel}`,
        );
        if (done) return;
        if (response.status === 202) {
          timer = setTimeout(() => get(requestedLevel, fallback), 1500);
          return;
        }
        if (!response.ok) {
          setFailed(true);
          if (requestedLevel > 512 && !fallback && !cached) get(512, true);
          return;
        }
        const blob = await response.blob();
        if (done) return;
        rememberPreview(`${id}:${requestedLevel}`, blob);
        setSrc(URL.createObjectURL(blob));
      } catch {
        if (!done) setFailed(true);
      }
    }
    get(level);
    return () => {
      done = true;
      clearTimeout(timer);
    };
  }, [id, level, visible]);
  E(
    () => () => {
      if (src) URL.revokeObjectURL(src);
    },
    [src],
  );
  return src ? (
    <img
      ref={ref}
      src={src}
      alt="Library photograph"
      title={failed ? "Showing smaller preview" : undefined}
      loading="lazy"
    />
  ) : (
    <div ref={ref} className="placeholder">
      {failed ? "Preview unavailable" : "◌"}
    </div>
  );
}
createRoot(document.getElementById("root")).render(<App />);
