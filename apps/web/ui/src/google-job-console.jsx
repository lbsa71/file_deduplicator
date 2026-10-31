import React, { useState } from "react";
import { readSuite, pilotSuite } from "./google-jobs.js";
const matchLabels = {
  "verified-local": "Local original verified",
  unmapped: "No account-bound local mapping. A local copy may still exist.",
  "local-trash": "The mapped local original is in Trash.",
  "local-content-changed": "Local bytes no longer match the imported original.",
  "stale-local-metadata":
    "Local metadata changed. Rescan the library and check again.",
  "local-unavailable": "The mapped local original is unavailable.",
  "remote-details-changed": "Google details differ from the saved association.",
  "verification-deferred":
    "Verification reached its size budget. The original remains unverified.",
  ambiguous: "Conflicting local mappings need investigation.",
  "needs-investigation":
    "Local copies have different verification results. Review the details.",
};
export function GoogleJobConsole({
  operations,
  paired,
  account,
  busy,
  act,
  call,
}) {
  const [photoUrl, setPhoto] = useState(""),
    [albumId, setAlbum] = useState(""),
    [hashes, setHashes] = useState(""),
    [operation, setOperation] = useState("photo-details"),
    [input, setInput] = useState("{}"),
    [metadata, setMetadata] = useState(
      '{"timestampSec": 1700000000, "timezoneSec": 0}',
    ),
    [confirmed, setConfirmed] = useState(false),
    [plan, setPlan] = useState(null),
    [output, setOutput] = useState(null),
    [localMatch, setLocalMatch] = useState(null);
  const visibleMatch =
    localMatch?.account === account && localMatch?.photoUrl === photoUrl.trim()
      ? localMatch
      : null;
  const selected = operations.find((x) => x.operation === operation);
  const writesEnabled = operations.some(
    (x) => x.effect === "write" && x.enabled,
  );
  const target = () => ({
    photoUrl: photoUrl.trim(),
    albumId: albumId.trim(),
    hashes: hashes.trim() ? hashes.trim().split(/[\s,]+/) : [],
  });
  function example(name = operation) {
    const spec = operations.find((x) => x.operation === name);
    const values = {
      photoUrl: photoUrl.trim(),
      albumId: albumId.trim(),
      cursor: null,
      hashes: target().hashes,
      value: true,
      title: "PhotoFlow test " + Date.now(),
      description: "PhotoFlow pilot",
      timestampSec: 1700000000,
      timezoneSec: 0,
      centerE7: [10000000, 20000000],
      visible1E7: [9000000, 19000000],
      visible2E7: [11000000, 21000000],
      scale: 14,
      placeId: "",
      originalJobId: "",
    };
    return Object.fromEntries(
      Object.keys(spec?.fields || {}).map((k) => [k, values[k] ?? null]),
    );
  }
  return (
    <details className="google-job-console">
      <summary>Operation workbench and qualification suite</summary>
      <p>
        Each job reports its own result. Personal accounts support reads only.
        Write pilots require an independently configured isolated test account,
        a small image named photoflow-test-… and a private album named PhotoFlow
        test ….
      </p>
      <label>
        Selected library photo URL
        <input
          value={photoUrl}
          onChange={(e) => setPhoto(e.target.value)}
          placeholder="https://photos.google.com/photo/…"
        />
      </label>
      <button
        disabled={busy || !paired || !photoUrl.trim()}
        onClick={() =>
          act(async () => {
            setLocalMatch(null);
            const url = photoUrl.trim();
            const result = await call("/google/local-matches", "POST", {
              account,
              photoUrls: [url],
            });
            setLocalMatch({ account, photoUrl: url, result });
          })
        }
      >
        Check local original
      </button>
      {visibleMatch && (
        <section aria-label="Local original verification">
          <p role="status">
            {matchLabels[visibleMatch.result.items[0].state] ||
              "Local original remains unverified."}
          </p>
          <p>
            Checks the saved association for {account} and current local bytes.
            Current Google byte equality and cloud removal safety remain
            unverified.
          </p>
          {visibleMatch.result.items[0].recordIds.map((id) => (
            <p key={id}>
              <a href={`/photos/${encodeURIComponent(id)}`}>
                Open local original
              </a>
            </p>
          ))}
          <details>
            <summary>Verification details</summary>
            <pre>{JSON.stringify(visibleMatch.result, null, 2)}</pre>
          </details>
        </section>
      )}
      <label>
        Selected album ID
        <input value={albumId} onChange={(e) => setAlbum(e.target.value)} />
      </label>
      <label>
        Optional opaque Google hashes
        <input value={hashes} onChange={(e) => setHashes(e.target.value)} />
      </label>
      <label>
        Pilot metadata (timestamp seconds/timezone seconds; optional location in
        E7 units)
        <textarea
          aria-label="Pilot metadata"
          value={metadata}
          onChange={(e) => setMetadata(e.target.value)}
          rows={3}
        />
      </label>
      <label>
        <input
          type="checkbox"
          checked={confirmed}
          disabled={!writesEnabled}
          onChange={(e) => setConfirmed(e.target.checked)}
        />
        I am testing synthetic media in the configured isolated account.
      </label>
      <button
        disabled={busy}
        onClick={() => act(async () => setPlan(readSuite(target())))}
      >
        Prepare read suite
      </button>
      <button
        disabled={busy || !writesEnabled || !confirmed}
        onClick={() =>
          act(async () =>
            setPlan([
              ...readSuite(target()),
              ...pilotSuite(target(), JSON.parse(metadata)),
            ]),
          )
        }
      >
        Prepare read and write pilot suite
      </button>
      {plan && (
        <div>
          <pre>{JSON.stringify(plan, null, 2)}</pre>
          <p>
            Independent reads continue after a failed check. Failed or uncertain
            checks block later writes in this suite. Timestamp changes persist
            on the synthetic image; the new test album remains for inspection.
          </p>
          <button
            disabled={busy || !paired}
            onClick={() =>
              act(async () => {
                const result = await call("/google/suites", "POST", {
                  jobs: plan,
                  confirmTestWrite: confirmed,
                });
                setOutput(result);
                setPlan(null);
              })
            }
          >
            Queue prepared suite
          </button>
        </div>
      )}
      <label>
        Individual operation
        <select
          aria-label="Individual operation"
          value={operation}
          onChange={(e) => {
            setOperation(e.target.value);
            setInput(JSON.stringify(example(e.target.value), null, 2));
          }}
        >
          {operations.map((x) => (
            <option key={x.operation} value={x.operation}>
              {x.label} — {x.effect}
              {!x.enabled ? " (gated)" : ""}
            </option>
          ))}
        </select>
      </label>
      <p>
        Input fields:{" "}
        {Object.entries(selected?.fields || {})
          .map(([name, type]) => name + ": " + type)
          .join(", ") || "none"}
      </p>
      <button onClick={() => setInput(JSON.stringify(example(), null, 2))}>
        Use selected targets
      </button>
      <label>
        Job input JSON
        <textarea
          aria-label="Job input JSON"
          rows={6}
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />
      </label>
      <button
        disabled={
          busy ||
          !paired ||
          !selected?.enabled ||
          (selected?.effect === "write" && !confirmed)
        }
        onClick={() =>
          act(async () =>
            setOutput(
              await call("/google/jobs", "POST", {
                operation,
                input: JSON.parse(input),
                confirmTestWrite: confirmed,
              }),
            ),
          )
        }
      >
        Queue selected operation
      </button>
      {output && <p role="status">Queued. Inspect individual jobs below.</p>}
    </details>
  );
}
