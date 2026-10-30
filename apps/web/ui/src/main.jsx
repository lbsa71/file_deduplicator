import React, { useState as S, useEffect as E } from "react";
import { createRoot } from "react-dom/client";
import "./style.css";
function App() {
  const [user, U] = S(null),
    [error, X] = S(""),
    [items, I] = S([]),
    [total, T] = S(0),
    [tab, B] = S("Photos"),
    [query, Q] = S(""),
    [folder, F] = S("."),
    [folders, G] = S([]),
    [registered, R] = S([]),
    [view, V] = S(null),
    [busy, W] = S(""),
    [jobs, J] = S([]),
    [offset, O] = S(0),
    [selected, C] = S(new Set()),
    [editing, K] = S(null),
    [trashFolders, H] = S([]);
  async function api(path, method = "GET", body, revision) {
    let r = await fetch("/api/v1" + path, {
      method,
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(user ? { "X-CSRF-Token": user.csrf } : {}),
        ...(revision ? { "If-Match": `"${revision}"` } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!r.ok) {
      let e = await r.json().catch(() => ({ detail: r.statusText }));
      throw Error(
        typeof e.detail === "string" ? e.detail : JSON.stringify(e.detail),
      );
    }
    return r.status === 204 ? null : r.json();
  }
  async function load() {
    try {
      let p = new URLSearchParams({
        q: query,
        offset: String(offset),
        limit: "100",
        trash: String(tab === "Trash"),
        favorite: String(tab === "Favorites"),
        duplicates: String(tab === "Duplicates" || tab === "Folders"),
      });
      if (tab === "Folders" && folder !== ".") p.set("folder", folder);
      let d = await api("/photos?" + p);
      I(d.items);
      T(d.total);
      if (tab === "Trash") H((await api("/trash/folders")).items);
      if (tab === "Folders")
        G((await api("/folders?path=" + encodeURIComponent(folder))).items);
      if (tab === "Activity") J((await api("/jobs")).items);
      R((await api("/library")).folders);
    } catch (e) {
      X(e.message);
    }
  }
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
      .then(U)
      .catch(() => {});
  }, []);
  E(() => {
    if (user) load();
  }, [user, tab, query, folder, offset]);
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
      await load();
    } catch (e) {
      X(e.message);
    } finally {
      W("");
    }
  }
  async function open(id) {
    try {
      V(await api("/photos/" + id));
    } catch (e) {
      X(e.message);
    }
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
        let r = await api("/exports", "POST", { ids: [...selected] });
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
    } else
      for (let id of selected) {
        let d = await api("/photos/" + id);
        await act(() => api("/photos/" + id, "DELETE", undefined, d.revision));
      }
    C(new Set());
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
          <button
            className={tab === t ? "active" : ""}
            onClick={() => {
              B(t);
              O(0);
              C(new Set());
            }}
            key={t}
          >
            {t}
          </button>
        ))}
        <footer>
          {user.username}
          <button
            onClick={() =>
              act(async () => {
                await api("/auth/logout", "POST", {});
                U(null);
                I([]);
                V(null);
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
            <button
              onClick={() =>
                act(() => api("/scans", "POST", { mode: "reconcile" }))
              }
            >
              Rescan
            </button>
          )}
        </header>
        <section className="heading">
          <div>
            <h2>{tab}</h2>
            <small>{total.toLocaleString()} photographs and videos</small>
          </div>
          <span>{busy}</span>
        </section>
        {error && (
          <div className="error" role="alert" onClick={() => X("")}>
            {error} ×
          </div>
        )}
        {selected.size > 0 && (
          <div className="selection">
            {selected.size} selected{" "}
            <button onClick={() => bulk("download")}>Download</button>
            {user.role >= 2 && (
              <button
                onClick={() =>
                  confirm("Trash selected occurrences?") && bulk("trash")
                }
              >
                Trash
              </button>
            )}
            <button onClick={() => C(new Set())}>Clear</button>
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
                <button
                  key={f.path}
                  onClick={() => {
                    F(f.path);
                    O(0);
                  }}
                >
                  📁 {f.name}
                </button>
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
                <small>{new Date(j.created * 1000).toLocaleString()}</small>
              </article>
            ))}
            <button onClick={load}>Refresh</button>
          </section>
        ) : (
          <>
            <section className="grid">
              {items.map((d) => (
                <article className="tile" key={d.id} data-record-id={d.id}>
                  <input
                    aria-label="Select photo"
                    type="checkbox"
                    checked={selected.has(d.id)}
                    onChange={(e) =>
                      C((s) => {
                        let n = new Set(s);
                        e.target.checked ? n.add(d.id) : n.delete(d.id);
                        return n;
                      })
                    }
                  />
                  <button onClick={() => open(d.id)}>
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
                  </button>
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
          </>
        )}
      </main>
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
