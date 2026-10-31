import React, { useEffect, useRef, useState } from "react";

export function GoogleReconciliation({ call, account, targetPolicy }) {
  const api = useRef(call);
  api.current = call;
  const [scope, setScope] = useState(""),
    [nonVital, setNonVital] = useState(false),
    [reserve, setReserve] = useState(256),
    [jobs, setJobs] = useState([]),
    [manifest, setManifest] = useState(null),
    [reviewed, setReviewed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const base = "/google/reconciliation";
  useEffect(() => {
    let active = true,
      timer;
    const refresh = async () => {
      try {
        const value = await api.current(base);
        if (active) setJobs(value.items);
      } catch (e) {
        if (active) setError(e.message);
      } finally {
        if (active) timer = setTimeout(refresh, 3000);
      }
    };
    refresh();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [account]);
  useEffect(() => {
    setManifest(null);
    setReviewed(false);
    setNonVital(false);
  }, [account]);
  async function act(work) {
    setBusy(true);
    setError("");
    try {
      await work();
      setJobs((await api.current(base)).items);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  function download() {
    // Download the server's immutable bytes. Re-stringifying parsed JSON here
    // would round nanosecond filesystem fingerprints beyond JS safe integers.
    const link = document.createElement("a");
    link.href =
      "/api/v1/google/reconciliation/manifests/" + manifest.id + "/download";
    link.download = "photoflow-reconciliation-" + manifest.id + ".json";
    link.click();
  }
  return (
    <details className="google-reconciliation">
      <summary>Prepare and commit reconciliation</summary>
      <p>
        Preparation reads the inventory and writes a reviewable manifest. It
        changes no Google photos or local originals. Commit executes that exact
        manifest in order. Unproved or unsupported actions stay held.
      </p>
      <label>
        Selected photo URLs (one per line; empty means full inventory)
        <textarea
          aria-label="Reconciliation photo URLs"
          value={scope}
          onChange={(e) => setScope(e.target.value)}
          rows={3}
        />
      </label>
      <label>
        Leave free (MiB)
        <input
          aria-label="Reconciliation reserve MiB"
          type="number"
          min="0"
          value={reserve}
          onChange={(e) => setReserve(Number(e.target.value))}
        />
      </label>
      <label>
        <input
          type="checkbox"
          checked={nonVital}
          disabled={targetPolicy !== "selected" || !scope.trim()}
          onChange={(e) => setNonVital(e.target.checked)}
        />
        I confirm the selected photos are non-vital and authorize a Trash pilot.
      </label>
      <p>
        Cleanup precedes the quota check and publication. Existing free space
        can be used immediately. Full accounts defer uploads to a later run. No
        automatic permanent deletion is available. Image publication still
        requires a qualified adapter; missing evidence is shown in the manifest.
      </p>
      <button
        disabled={busy || !account}
        onClick={() =>
          act(async () => {
            await api.current(base + "/prepare", "POST", {
              photoUrls: scope.trim() ? scope.trim().split(/\s+/) : [],
              nonVital,
              reserveBytes: reserve * 1024 * 1024,
            });
          })
        }
      >
        Prepare dry-run manifest
      </button>
      <ul>
        {jobs.slice(0, 15).map((job) => (
          <li key={job.id}>
            {job.action}: {job.state}
            {job.waiting_reason ? " — " + job.waiting_reason : ""}
            {job.progress?.stage ? " — " + job.progress.stage : ""}
            {job.error && <p role="alert">{job.error}</p>}
            {job.action === "google.commit" &&
              ["failed", "partial"].includes(job.state) &&
              !job.result?.deferred?.length && (
                <button
                  disabled={busy}
                  onClick={() =>
                    act(async () => {
                      await api.current(
                        base + "/jobs/" + job.id + "/resume",
                        "POST",
                        {},
                      );
                    })
                  }
                >
                  Resume interrupted commit
                </button>
              )}
            {job.result?.manifestId && job.action === "google.prepare" && (
              <button
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    setManifest(
                      await api.current(
                        base + "/manifests/" + job.result.manifestId,
                      ),
                    );
                    setReviewed(false);
                  })
                }
              >
                Inspect prepared manifest
              </button>
            )}
            {job.action === "google.commit" && job.result && (
              <p>
                Completed: {job.result.completed?.length || 0}; deferred:{" "}
                {job.result.deferred?.length || 0}; held: {job.result.held || 0}
                . {job.result.deferred?.map((x) => x.reason).join(", ")}
              </p>
            )}
          </li>
        ))}
      </ul>
      {manifest && manifest.account === account && (
        <section aria-label="Prepared reconciliation manifest">
          <p>
            Manifest {manifest.id}; SHA-256 <code>{manifest.sha256}</code>
          </p>
          <p>
            Scope:{" "}
            {manifest.inventoryScope === "selected"
              ? "selected Google photos"
              : "whole Google library"}
            . Remote items: {manifest.counts.remote}; local records:{" "}
            {manifest.counts.local}; sequential operations:{" "}
            {manifest.operations.length}.
          </p>
          <pre>{JSON.stringify(manifest.counts.actions, null, 2)}</pre>
          <p>{manifest.limitations.join(" ")}</p>
          <button onClick={download}>Download full private manifest</button>
          {manifest.retentionPolicy && (
            <p>
              Retain starred photos, all album members and anything without a
              verified local original. The owner accepts the Takeout backup
              without verification. Only reviewed reversible Trash is permitted.
            </p>
          )}
          <table>
            <thead>
              <tr>
                <th>Order</th>
                <th>Phase</th>
                <th>Operation</th>
                <th>Target</th>
              </tr>
            </thead>
            <tbody>
              {manifest.operations.slice(0, 100).map((op) => (
                <tr key={op.seq}>
                  <td>{op.seq}</td>
                  <td>{op.phase}</td>
                  <td>{op.operation}</td>
                  <td>
                    {op.input.photoUrl || op.input.recordId || "Account quota"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p>
            Showing up to 100 operations. The download includes every operation,
            held item and revision. It contains private photo identifiers.
          </p>
          <label>
            <input
              type="checkbox"
              checked={reviewed}
              onChange={(e) => setReviewed(e.target.checked)}
            />
            I reviewed this manifest and authorize its listed executable
            operations.
          </label>
          <button
            disabled={busy || !reviewed}
            onClick={() =>
              act(async () => {
                await api.current(
                  base + "/manifests/" + manifest.id + "/commit",
                  "POST",
                  { sha256: manifest.sha256 },
                );
                setReviewed(false);
              })
            }
          >
            Commit reviewed manifest
          </button>
        </section>
      )}
      {error && <p role="alert">{error}</p>}
    </details>
  );
}
