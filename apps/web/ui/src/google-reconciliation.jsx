import React, { useEffect, useRef, useState } from "react";

const blockers = {
  "current-remote-bytes-unverified":
    "Current Google bytes have not been compared with the local original.",
  "takeout-roundtrip-unverified":
    "Matching account-bound Takeout metadata has not been verified.",
  "independent-backup-unverified":
    "An independent backup has not been verified.",
  "companion-preservation-unverified":
    "Preservation of all required companion media is unverified.",
  "album-intent-unclassified":
    "Google albums have not been classified as curated or generated.",
  "remote-ownership-unverified":
    "Google ownership and sharing state are unverified.",
  "collection-inventory-incomplete":
    "This selected-photo review is not a complete account inventory.",
  "local-original-unverified": "The local original remains unverified.",
  "remote-observation-failed":
    "The Google read failed or its result is unavailable.",
  "remote-observation-pending": "The Google read is still pending.",
  "remote-favorite-unknown": "Google favorite state is unknown.",
  "remote-albums-unknown": "Google album membership is unknown.",
  "remote-observation-stale":
    "The Google observation is older than ten minutes. Create a new review for fresh reads.",
};

export function GoogleReconciliation({ account, photoUrl, busy, act, call }) {
  const selection = useRef(0);
  const [review, setReview] = useState(null),
    [saved, setSaved] = useState([]),
    [error, setError] = useState(""),
    [refreshing, setRefreshing] = useState(false);
  const base = "/google/reconciliation/reviews";
  useEffect(() => {
    let active = true;
    const initialSelection = selection.current;
    if (!account) return;
    async function restore() {
      try {
        const result = await call(
          `${base}?account=${encodeURIComponent(account)}`,
        );
        if (!active || selection.current !== initialSelection) return;
        setSaved(result.items);
        if (result.items.length) {
          const value = await call(
            `${base}/${result.items[0].id}?account=${encodeURIComponent(account)}`,
          );
          if (active && selection.current === initialSelection)
            setReview(value);
        }
      } catch (e) {
        if (active) setError(e.message);
      }
    }
    restore();
    return () => {
      active = false;
    };
  }, [account]);

  useEffect(() => {
    if (review?.state !== "collecting") return;
    let active = true,
      timer;
    async function collect() {
      try {
        const value = await call(`${base}/${review.id}/refresh`, "POST", {
          account,
        });
        if (!active) return;
        setReview(value);
        if (value.state === "collecting") timer = setTimeout(collect, 3000);
      } catch (e) {
        if (active) setError(e.message);
      }
    }
    timer = setTimeout(collect, 1000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [review?.id, review?.state, account]);

  return (
    <section aria-label="Reconciliation review">
      <h4>Reconciliation review</h4>
      <p>
        Capture current Google details for the selected photo and verify its
        mapped local original. Reviews preserve dated evidence and show the
        checks still needed for reconciliation.
      </p>
      <button
        disabled={busy || !account || !photoUrl.trim()}
        onClick={() =>
          act(async () => {
            selection.current += 1;
            setError("");
            const value = await call(base, "POST", {
              account,
              photoUrls: [photoUrl.trim()],
            });
            setReview(value);
            setSaved((items) => [value, ...items].slice(0, 20));
          })
        }
      >
        Prepare read-only reconciliation review
      </button>
      {saved.length > 0 && (
        <label>
          Saved reconciliation review
          <select
            aria-label="Saved reconciliation review"
            value={review?.id || ""}
            disabled={busy || refreshing}
            onChange={(e) => {
              selection.current += 1;
              const id = e.target.value;
              act(async () => {
                setError("");
                setReview(
                  await call(
                    `${base}/${id}?account=${encodeURIComponent(account)}`,
                  ),
                );
              });
            }}
          >
            {saved.map((item) => (
              <option key={item.id} value={item.id}>
                {new Date(item.createdAt * 1000).toLocaleString()} —{" "}
                {item.id.slice(0, 8)}
              </option>
            ))}
          </select>
        </label>
      )}
      {review && (
        <div>
          <p role="status">
            {review.state === "review-ready"
              ? "Review captured"
              : review.state === "collecting"
                ? "Collecting selected Google observations"
                : review.state === "stale"
                  ? "Review contains stale Google observations"
                  : "Review incomplete"}
          </p>
          <p>
            {review.summary.observed} of {review.summary.selected} Google
            observations captured; {review.summary.localVerified} local
            originals verified. Read-only review; cloud execution remains
            disabled.
          </p>
          <button
            disabled={busy || refreshing}
            onClick={async () => {
              setRefreshing(true);
              setError("");
              try {
                setReview(
                  await call(`${base}/${review.id}/refresh`, "POST", {
                    account,
                  }),
                );
              } catch (e) {
                setError(e.message);
              } finally {
                setRefreshing(false);
              }
            }}
          >
            Refresh local verification
          </button>
          {review.targets.map((target) => {
            const item = review.items.find(
              (item) => item.mediaKey === target.mediaKey,
            );
            return (
              <div key={target.mediaKey}>
                <p>
                  Frozen target:{" "}
                  <a
                    href={target.photoUrl}
                    style={{ overflowWrap: "anywhere" }}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {target.photoUrl}
                  </a>
                </p>
                {item && (
                  <>
                    <p>
                      {item.local?.state === "verified-local"
                        ? "Local original verified"
                        : "Local original remains unverified"}
                    </p>
                    {item.remote.state === "observed" && (
                      <p>
                        Google read started:{" "}
                        {new Date(
                          item.remote.observedAt * 1000,
                        ).toLocaleString()}
                        . Local check:{" "}
                        {new Date(item.localCheckedAt * 1000).toLocaleString()}.
                      </p>
                    )}
                    {item.localRecords.map((record) => (
                      <p key={record.recordId}>
                        <a
                          href={`/photos/${encodeURIComponent(record.recordId)}`}
                        >
                          Open reviewed local original
                        </a>
                      </p>
                    ))}
                    {item.protections.length > 0 && (
                      <p>
                        Preserve:{" "}
                        {item.protections
                          .map((value) => value.replaceAll("-", " "))
                          .join(", ")}
                      </p>
                    )}
                    <details>
                      <summary>
                        Evidence still needed ({item.blockedBy.length})
                      </summary>
                      <ul>
                        {item.blockedBy.map((reason) => (
                          <li key={reason}>{blockers[reason] || reason}</li>
                        ))}
                      </ul>
                    </details>
                  </>
                )}
              </div>
            );
          })}
          <details>
            <summary>Private review evidence</summary>
            <pre>{JSON.stringify(review, null, 2)}</pre>
          </details>
        </div>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
