import React, { useEffect, useRef, useState } from "react";
import { canStartSync, syncPresentation } from "./google-sync.js";

export function GoogleSync({ call, account, connectionState }) {
  const api = useRef(call);
  api.current = call;
  const [sync, setSync] = useState(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(() => {
    let active = true,
      timer;
    setSync(null);
    setError("");
    async function refresh() {
      try {
        const value = await api.current("/google/sync");
        if (active) setSync(value);
      } catch (e) {
        if (active) setError(e.message);
      } finally {
        if (active) timer = setTimeout(refresh, 3000);
      }
    }
    refresh();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [account]);
  const view = syncPresentation(sync);
  async function act() {
    setBusy(true);
    setError("");
    try {
      if (view.action === "commit") {
        if (!canStartSync(sync))
          throw new Error(
            "This review is out of date. Prepare an updated sync.",
          );
        await api.current(
          `/google/reconciliation/manifests/${sync.review.manifestId}/commit`,
          "POST",
          { sha256: sync.review.sha256 },
        );
      } else if (view.action)
        await api.current("/google/sync/" + view.action, "POST", {});
      setSync(await api.current("/google/sync"));
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const processed = sync?.progress?.processed ?? sync?.progress?.completed;
  const total = sync?.progress?.total;
  const determinate =
    Number.isInteger(processed) && Number.isInteger(total) && total > 0;
  const working = ["preparing", "running", "pausing"].includes(sync?.state);
  return (
    <section className="google-sync" aria-label="Google Photos sync">
      <h4>{view.title}</h4>
      <p className="google-sync-description">{view.description}</p>
      <div className="google-retention-rule">
        <p>Keep in Google Photos</p>
        <ul>
          <li>Starred photos</li>
          <li>Photos in any album</li>
          <li>Photos without a verified local copy</li>
        </ul>
        <small>
          Uncertain matches and unverified motion-photo companions stay in
          Google too.
        </small>
      </div>
      {working && (
        <div className="google-sync-progress" role="status">
          <progress
            aria-label="Sync progress"
            {...(determinate ? { value: processed, max: total } : {})}
          />
          {determinate && (
            <p>
              {processed.toLocaleString()} of {total.toLocaleString()} photos
              checked{sync?.state === "running" ? " for this sync" : ""}
            </p>
          )}
        </div>
      )}
      {sync?.review && (
        <dl className="google-sync-totals" aria-label="Sync review totals">
          <div>
            <dt>Keep in Google Photos</dt>
            <dd>{sync.review.keep.toLocaleString()}</dd>
          </div>
          <div>
            <dt>Move to Google Trash</dt>
            <dd>{sync.review.trash.toLocaleString()}</dd>
          </div>
        </dl>
      )}
      {sync?.totals && (
        <dl className="google-sync-totals" aria-label="Sync results">
          <div>
            <dt>Verified in Google Trash</dt>
            <dd>{sync.totals.trashed.toLocaleString()}</dd>
          </div>
          <div>
            <dt>Kept in Google Photos</dt>
            <dd>{sync.totals.retained.toLocaleString()}</dd>
          </div>
        </dl>
      )}
      {["offline", "needs_login"].includes(connectionState) && (
        <p className="google-browser-note">
          Open your signed-in{" "}
          <a
            href="https://photos.google.com/"
            target="_blank"
            rel="noopener noreferrer"
          >
            Google Photos tab
          </a>{" "}
          to keep the browser connected.
        </p>
      )}
      {sync && !sync.enabled && (
        <p>
          Sync is not enabled for this account. Connection settings are below.
        </p>
      )}
      {view.action && (
        <button
          className="google-primary"
          disabled={busy || !sync?.enabled}
          onClick={act}
        >
          {busy ? "Please wait…" : view.label}
        </button>
      )}
      {sync?.state === "review" && sync.review?.trash > 0 && (
        <small className="google-trash-note">
          Moving to Trash preserves the local originals. This action does not
          permanently delete photos.
        </small>
      )}
      {sync?.state === "running" && (
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError("");
            try {
              await api.current("/google/sync/pause", "POST", {});
              setSync(await api.current("/google/sync"));
            } catch (e) {
              setError(e.message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Pause sync
        </button>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
