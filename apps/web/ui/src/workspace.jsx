import React, { useState, useEffect, useRef } from "react";
import { routeURL, followLink } from "./routes.js";
import { batchOperation, routeFromScope } from "./batch.js";

export function Modal({ title, onClose, children }) {
  const ref = useRef(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog.showModal();
    return () => dialog.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className="workspace-modal"
      aria-labelledby="workspace-dialog-title"
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") e.stopPropagation();
      }}
    >
      <div className="modal-heading">
        <h2 id="workspace-dialog-title">{title}</h2>
        <button aria-label="Close dialog" onClick={onClose}>
          ×
        </button>
      </div>
      {children}
    </dialog>
  );
}

export function SavedViews({ api, scope, navigate, username }) {
  const [views, setViews] = useState([]),
    [draft, setDraft] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function reload() {
    setViews((await api("/views")).items);
  }
  useEffect(() => {
    let alive = true;
    api("/views")
      .then((r) => {
        if (alive) setViews(r.items);
      })
      .catch((e) => {
        if (alive) setError(e.message);
      });
    return () => {
      alive = false;
    };
  }, [username]);
  async function save(remove = false) {
    try {
      setBusy(true);
      setError("");
      if (remove)
        await api("/views/" + draft.id, "DELETE", undefined, draft.revision);
      else
        await api(
          "/views" + (draft.id ? "/" + draft.id : ""),
          draft.id ? "PATCH" : "POST",
          {
            name: draft.name,
            query: draft.replaceQuery ? scope : draft.query,
          },
          draft.revision,
        );
      await reload();
      setDraft(null);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="saved-views" aria-label="Saved views">
      <div className="saved-heading">
        <h3>Saved views</h3>
        <button
          onClick={() => {
            setError("");
            setDraft({ name: "", query: scope, replaceQuery: true });
          }}
        >
          Save view
        </button>
      </div>
      <p className="facet-help">
        Personal shortcuts. New matching photos appear automatically.
      </p>
      {views.map((v) => (
        <div className="saved-view" key={v.id}>
          <a
            href={routeURL(routeFromScope(v.query))}
            onClick={(e) => followLink(e, navigate)}
          >
            {v.name}
          </a>
          <button
            aria-label={"Manage " + v.name}
            onClick={() => {
              setError("");
              setDraft({ ...v, replaceQuery: false });
            }}
          >
            ⋯
          </button>
        </div>
      ))}
      {error && !draft && <p role="alert">{error}</p>}
      {draft && (
        <Modal
          title={draft.id ? "Manage saved view" : "Save current view"}
          onClose={() => !busy && setDraft(null)}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              save();
            }}
          >
            <label className="form-field">
              Name
              <input
                required
                maxLength={120}
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
              />
            </label>
            {draft.id && (
              <label className="inline-check">
                <input
                  type="checkbox"
                  checked={draft.replaceQuery}
                  onChange={(e) =>
                    setDraft({ ...draft, replaceQuery: e.target.checked })
                  }
                />
                Replace filters with the current view
              </label>
            )}
            <p>
              Saved for {username}. Photo metadata and album membership stay
              independent of this shortcut.
            </p>
            <details>
              <summary>Query</summary>
              <pre>
                {JSON.stringify(
                  draft.replaceQuery ? scope : draft.query,
                  null,
                  2,
                )}
              </pre>
            </details>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <div className="modal-actions">
              {draft.id && (
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => save(true)}
                >
                  Delete saved view
                </button>
              )}
              <button
                type="button"
                onClick={() => setDraft(null)}
                disabled={busy}
              >
                Cancel
              </button>
              <button disabled={busy}>Save</button>
            </div>
          </form>
        </Modal>
      )}
    </section>
  );
}

export function BatchDialog({
  api,
  selection,
  count,
  folders,
  trashed,
  onClose,
  onDone,
}) {
  const [draft, setDraft] = useState({
      action: trashed ? "restore" : "labels",
      field: "tags",
      mode: "add",
      value: "",
    }),
    [plan, setPlan] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [result, setResult] = useState(null);
  function change(patch) {
    setDraft({ ...draft, ...patch });
    setPlan(null);
    setError("");
  }
  async function preview(e) {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      setPlan(
        await api("/batch-plans", "POST", {
          ...selection,
          operation: batchOperation(draft),
        }),
      );
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function execute() {
    setBusy(true);
    setError("");
    try {
      const r = await api(
        "/batch-plans/" + plan.id + "/execute",
        "POST",
        {},
        plan.revision,
      );
      for (let i = 0; i < 3600; i++) {
        const j = await api("/jobs/" + r.job_id);
        if (j.state === "failed") throw Error(j.error);
        if (j.state === "succeeded") {
          setResult(j.result);
          onDone();
          return;
        }
        await new Promise((r) => setTimeout(r, 500));
      }
      throw Error("The batch is still running. Check Activity for its result.");
    } catch (e) {
      setError(e.message);
      setPlan(null);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Modal
      title={
        result
          ? "Batch result"
          : `Edit ${count.toLocaleString()} selected photos`
      }
      onClose={() => !busy && onClose()}
    >
      {result ? (
        <>
          <p role="status">
            {result.succeeded} updated · {result.conflicts} conflicts ·{" "}
            {result.failed} failed
          </p>
          <details>
            <summary>Per-photo results</summary>
            <ul>
              {result.items.map((x) => (
                <li key={x.id}>
                  {x.id}: {x.state}
                  {x.error ? " — " + x.error : ""}
                </li>
              ))}
            </ul>
          </details>
          <div className="modal-actions">
            <button onClick={onClose}>Done</button>
          </div>
        </>
      ) : plan ? (
        <>
          <p>
            <strong>{plan.count.toLocaleString()} photos</strong> captured for
            this operation. Photos changed since selection are skipped and
            reported.
          </p>
          <h3>Preview</h3>
          {plan.preview.map((item) => (
            <article className="batch-preview" key={item.id}>
              <small>{item.path}</small>
              <div>
                <section>
                  <b>Before</b>
                  <pre>{JSON.stringify(item.before, null, 2)}</pre>
                </section>
                <section>
                  <b>After</b>
                  <pre>{JSON.stringify(item.after, null, 2)}</pre>
                </section>
              </div>
            </article>
          ))}
          <small>
            Showing up to five examples. This operation applies to all{" "}
            {plan.count.toLocaleString()} selected photos.
          </small>
          <div className="modal-actions">
            <button disabled={busy} onClick={() => setPlan(null)}>
              Back
            </button>
            <button disabled={busy} onClick={execute}>
              {busy
                ? "Applying…"
                : `Apply to ${plan.count.toLocaleString()} photos`}
            </button>
          </div>
        </>
      ) : (
        <form onSubmit={preview}>
          <label className="form-field">
            Action
            <select
              value={draft.action}
              onChange={(e) =>
                change({
                  action: e.target.value,
                  value: e.target.value === "favorite" ? "yes" : "",
                  mode:
                    e.target.value === "labels" && draft.field === "place"
                      ? "replace"
                      : "add",
                })
              }
            >
              {trashed ? (
                <option value="restore">Restore from trash</option>
              ) : (
                <>
                  <option value="labels">Edit labels</option>
                  <option value="favorite">Set favourite</option>
                  <option value="date">Correct capture date</option>
                  <option value="move">Move to folder</option>
                  <option value="trash">Move to trash</option>
                </>
              )}
            </select>
          </label>
          {draft.action === "labels" && (
            <>
              <label className="form-field">
                Field
                <select
                  value={draft.field}
                  onChange={(e) =>
                    change({
                      field: e.target.value,
                      mode: e.target.value === "place" ? "replace" : "add",
                    })
                  }
                >
                  <option value="tags">Tags</option>
                  <option value="people">People</option>
                  <option value="albums">Albums</option>
                  <option value="place">Place hierarchy</option>
                </select>
              </label>
              <label className="form-field">
                Change
                <select
                  value={draft.mode}
                  onChange={(e) => change({ mode: e.target.value })}
                >
                  {draft.field !== "place" && (
                    <>
                      <option value="add">Add labels</option>
                      <option value="remove">Remove labels</option>
                    </>
                  )}
                  <option value="replace">Replace all labels</option>
                  <option value="reset">
                    {draft.field === "place"
                      ? "Reset to automatic hierarchy"
                      : "Reset to imported values"}
                  </option>
                </select>
              </label>
              {draft.mode !== "reset" && (
                <label className="form-field">
                  Labels — one per line
                  <textarea
                    rows={5}
                    value={draft.value}
                    onChange={(e) => change({ value: e.target.value })}
                  />
                </label>
              )}
              <p>
                {draft.mode === "replace"
                  ? "Replaces the entire selected field. An empty list clears it."
                  : draft.mode === "reset"
                    ? "Removes your override and resolves the preserved source metadata again."
                    : "Other labels remain. Original imported metadata is preserved."}
              </p>
            </>
          )}
          {draft.action === "favorite" && (
            <label className="form-field">
              Favourite
              <select
                value={draft.value}
                onChange={(e) => change({ value: e.target.value })}
              >
                <option value="yes">Yes</option>
                <option value="no">No</option>
                <option value="reset">Reset to imported value</option>
              </select>
            </label>
          )}
          {draft.action === "date" && (
            <>
              <label className="form-field">
                Date correction
                <select
                  value={draft.mode}
                  onChange={(e) => change({ mode: e.target.value })}
                >
                  <option value="add">
                    Set the same date on every selected photo
                  </option>
                  <option value="reset">Reset to imported dates</option>
                </select>
              </label>
              {draft.mode !== "reset" && (
                <label className="form-field">
                  Capture date
                  <input
                    type="date"
                    value={draft.value}
                    onChange={(e) => change({ value: e.target.value })}
                  />
                </label>
              )}
              <p>
                An empty date clears the field. Preview the change before
                applying.
              </p>
            </>
          )}
          {draft.action === "move" && (
            <label className="form-field">
              Destination
              <select
                value={draft.value}
                required
                onChange={(e) => change({ value: e.target.value })}
              >
                <option value="">Choose a user folder</option>
                {folders.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.path}
                  </option>
                ))}
              </select>
            </label>
          )}
          {draft.action === "trash" && (
            <p>
              Moves these occurrences to recoverable trash. Other retained
              copies remain.
            </p>
          )}
          {draft.action === "restore" && (
            <p>
              Restores these occurrences. Occupied destinations are reported as
              conflicts.
            </p>
          )}
          <div className="modal-actions">
            <button type="button" onClick={onClose}>
              Cancel
            </button>
            <button disabled={busy}>
              {busy ? "Preparing…" : "Preview changes"}
            </button>
          </div>
        </form>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </Modal>
  );
}
