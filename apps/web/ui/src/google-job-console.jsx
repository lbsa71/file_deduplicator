import React, { useState } from "react";
import { readSuite, pilotSuite } from "./google-jobs.js";
export function GoogleJobConsole({
  operations,
  paired,
  busy,
  act,
  call,
  targetPolicy = "fixtures",
}) {
  const [photoUrl, setPhoto] = useState(""),
    [albumId, setAlbum] = useState(""),
    [hashes, setHashes] = useState(""),
    [operation, setOperation] = useState("photo-details"),
    [input, setInput] = useState("{}"),
    [metadata, setMetadata] = useState("{}"),
    [confirmed, setConfirmed] = useState(false),
    [plan, setPlan] = useState(null),
    [output, setOutput] = useState(null);
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
        Each job reports its own result. Writes require an explicitly authorized
        account and a finite plan with exact targets.{" "}
        {targetPolicy === "selected"
          ? "Selected-photo policy is enabled: personal images and private albums are allowed."
          : "Fixture policy requires small photoflow-test-… images and private PhotoFlow test … albums."}
      </p>
      <label>
        Selected library photo URL
        <input
          value={photoUrl}
          onChange={(e) => setPhoto(e.target.value)}
          placeholder="https://photos.google.com/photo/…"
        />
      </label>
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
        I authorize this finite pilot on the selected photos in the configured
        account.
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
            checks block later writes in this suite. This suite changes
            metadata: it ends with favorite/archive off, description cleared,
            and the photo removed from the selected album and restored from
            Trash. Optional timestamp changes persist and optional manual
            location is cleared. The new test album remains. It does not restore
            all previous values.
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
