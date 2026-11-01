import { GoogleReconciliation } from "./google-reconciliation.jsx";
import React, { useEffect, useRef, useState } from "react";
import { GoogleSync } from "./google-sync.jsx";
import { GoogleJobConsole } from "./google-job-console.jsx";
import { pairWithExtension } from "./google-pairing.js";
const labels = {
  unpaired: "Connect Google Photos",
  offline: "Google browser offline",
  needs_login: "Google needs attention",
  connected: "Google connected",
  checking: "Checking Google Photos",
};
export function GoogleConnection({ api }) {
  const call = useRef(api);
  call.current = api;
  const [status, setStatus] = useState(null),
    [open, setOpen] = useState(false),
    [account, setAccount] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function refresh() {
    const value = await call.current("/google/status");
    setStatus(value);
    return value;
  }
  useEffect(() => {
    let active = true,
      timer;
    async function poll() {
      try {
        const value = await call.current("/google/status");
        if (active) setStatus(value);
      } catch (e) {
        if (active) setError(e.message);
      } finally {
        if (active) timer = setTimeout(poll, 5000);
      }
    }
    poll();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, []);
  async function connect() {
    setBusy(true);
    setError("");
    try {
      const pairing = await call.current("/google/pairing", "POST", {
        account: account.trim(),
      });
      await pairWithExtension({ account: account.trim(), code: pairing.code });
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  const label = labels[status?.state] || "Checking Google connection";
  return (
    <div className="google-connection">
      <button onClick={() => setOpen(!open)} aria-expanded={open}>
        {status?.state === "connected" ? "✓" : "!"} {label}
      </button>
      {open && (
        <section className="google-panel" aria-label="Google Photos connection">
          <div className="google-panel-heading">
            <h3>Google Photos</h3>
            <button
              aria-label="Close Google Photos"
              onClick={() => setOpen(false)}
            >
              Close
            </button>
          </div>
          <p className="google-connection-status" role="status">
            {label}
            {status?.account ? `: ${status.account}` : ""}
          </p>
          {!status?.account ? (
            <section
              className="google-connect-setup"
              aria-label="Connect Google Photos"
            >
              <p>
                Open your signed-in{" "}
                <a
                  href="https://photos.google.com/"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Google Photos tab
                </a>{" "}
                in this browser, then connect your account.
              </p>
              <label>
                Google account
                <input
                  type="email"
                  value={account}
                  onChange={(e) => setAccount(e.target.value)}
                  autoComplete="email"
                  placeholder="you@example.com"
                />
              </label>
              <button
                className="google-primary"
                disabled={busy || !account.trim()}
                onClick={connect}
              >
                {busy ? "Connecting…" : "Connect Google Photos"}
              </button>
              <p className="google-install-note">
                First time here?{" "}
                <a href="/tools/google-photos-worker-0.4.1.zip">
                  Install the PhotoFlow extension
                </a>{" "}
                in Chrome or Edge.
              </p>
            </section>
          ) : (
            <GoogleSync
              account={status.account}
              connectionState={status.state}
              call={(...args) => call.current(...args)}
            />
          )}
          {error && <p role="alert">{error}</p>}
          <hr className="google-tools-divider" />
          <GoogleTools
            api={(...args) => call.current(...args)}
            status={status}
            refresh={refresh}
          />
        </section>
      )}
    </div>
  );
}

export function GoogleTools({ api, status, refresh }) {
  const call = useRef(api);
  call.current = api;
  const [account, setAccount] = useState(status?.account || ""),
    [pair, setPair] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [result, setResult] = useState(null);
  async function act(fn) {
    setBusy(true);
    setError("");
    try {
      await fn();
      await refresh();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="google-tools">
      <summary>Advanced &amp; troubleshooting</summary>
      <p className="google-tools-intro">
        Manual connection, step-by-step sync, and diagnostic tools.
      </p>
      <details className="google-connection-settings">
        <summary>Connection settings</summary>
        <p>
          Install the{" "}
          <a href="/tools/google-photos-worker-0.4.1.zip">
            PhotoFlow extension
          </a>{" "}
          in Chrome or Edge. Open Google Photos and use its Check connection
          button to obtain the account value below.
        </p>
        <label>
          Manual Google account{" "}
          <input
            value={account}
            onChange={(e) => setAccount(e.target.value)}
            autoComplete="off"
          />
        </label>
        <button
          disabled={busy || !account.trim()}
          onClick={() =>
            act(async () => {
              const value = await call.current("/google/pairing", "POST", {
                account: account.trim(),
              });
              await pairWithExtension({
                account: account.trim(),
                code: value.code,
              });
              setPair(null);
            })
          }
        >
          Connect through installed extension
        </button>
        <p>
          Open PhotoFlow and your signed-in Google Photos tab in the same Chrome
          profile. Connect here without copying a code; the current PhotoFlow
          address is used automatically.
        </p>
        <button
          disabled={busy || !account.trim()}
          onClick={() =>
            act(async () => {
              setPair(
                await call.current("/google/pairing", "POST", {
                  account: account.trim(),
                }),
              );
              window.open(
                "https://photos.google.com/",
                "_blank",
                "noopener,noreferrer",
              );
            })
          }
        >
          Create pairing code and open Google Photos
        </button>
        {pair && (
          <div>
            <p>
              Copy this single-use code into the extension's pairing field while
              the Google Photos tab is selected. It expires in five minutes.
            </p>
            <input
              aria-label="Pairing code"
              readOnly
              value={pair.code}
              onFocus={(e) => e.target.select()}
            />
          </div>
        )}
        <p>
          The desktop browser executes typed jobs. Its Google session stays on
          your desktop. Counts alone cannot authorize cloud changes.
        </p>
        <button
          disabled={busy || !status?.account}
          onClick={() => act(() => call.current("/google/jobs", "POST", {}))}
        >
          Read inventory counts
        </button>
        <button
          disabled={busy}
          onClick={() =>
            act(async () => {
              await call.current("/google/connection", "DELETE");
              setPair(null);
            })
          }
        >
          Disconnect Google worker
        </button>
      </details>
      <GoogleReconciliation
        call={(...args) => call.current(...args)}
        account={status?.account}
        targetPolicy={status?.pilotTargetPolicy}
      />
      <GoogleJobConsole
        operations={status?.operations || []}
        targetPolicy={status?.pilotTargetPolicy || "fixtures"}
        paired={!!status?.account}
        account={status?.account}
        busy={busy}
        act={act}
        call={(...args) => call.current(...args)}
      />
      <details className="google-job-history">
        <summary>Worker job history</summary>
        <ol>
          {status?.jobs?.map((job) => (
            <li key={job.id}>
              {job.operation}: {job.state}
              {job.result?.photos !== undefined &&
                ` — ${job.result.photos} items, ${job.result.favorites} favorites, ${job.result.albums} albums`}
              {job.result?.itemCount !== undefined &&
                ` — ${job.result.itemCount} returned items`}
              {job.result?.outcome && ` — ${job.result.outcome}`}
              {job.state === "succeeded" && (
                <button
                  onClick={() =>
                    act(async () => {
                      const value = await call.current(
                        `/google/jobs/${job.id}/result`,
                      );
                      setResult(value);
                    })
                  }
                >
                  View private result
                </button>
              )}
              {job.retry_preflight_allowed && (
                <button
                  onClick={() =>
                    act(async () => {
                      await call.current(
                        `/google/jobs/${job.id}/retry-preflight`,
                        "POST",
                        {},
                      );
                    })
                  }
                >
                  Retry failed preflight
                </button>
              )}
              {job.error && ` (${job.error})`}
              {job.events?.length > 0 && ` — ${job.events.at(-1).phase}`}
              <button
                onClick={() =>
                  act(async () => {
                    const value = await call.current(
                      `/google/jobs/${job.id}/diagnostics`,
                    );
                    const url = URL.createObjectURL(
                      new Blob([JSON.stringify(value, null, 2)], {
                        type: "application/json",
                      }),
                    );
                    const link = document.createElement("a");
                    link.href = url;
                    link.download = `photoflow-job-${job.id}.json`;
                    link.click();
                    setTimeout(() => URL.revokeObjectURL(url), 10000);
                  })
                }
              >
                Download job diagnostics
              </button>
            </li>
          ))}
        </ol>
      </details>
      {result && (
        <div>
          <p>Private job result — contains Google identifiers and metadata.</p>
          <button onClick={() => setResult(null)}>Close result</button>
          <pre>{JSON.stringify(result, null, 2)}</pre>
        </div>
      )}
      {error && <p role="alert">{error}</p>}
    </details>
  );
}
