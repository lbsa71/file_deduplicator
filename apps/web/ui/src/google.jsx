import React, { useEffect, useRef, useState } from "react";
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
    [pair, setPair] = useState(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    let timer;
    async function refresh() {
      try {
        const value = await call.current("/google/status");
        if (active) setStatus(value);
      } catch (e) {
        if (active) setError(e.message);
      } finally {
        if (active) timer = setTimeout(refresh, 5000);
      }
    }
    refresh();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, []);
  async function act(fn) {
    setBusy(true);
    setError("");
    try {
      await fn();
      setStatus(await call.current("/google/status"));
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
          <h3>Google Photos</h3>
          <p role="status">
            {label}
            {status?.account ? `: ${status.account}` : ""}
          </p>
          <p>
            Install the{" "}
            <a href="/tools/google-photos-worker-0.2.0.zip">
              PhotoFlow extension
            </a>{" "}
            in Chrome or Edge. Open Google Photos and use its Check connection
            button to obtain the account value below.
          </p>
          <label>
            Google account{" "}
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
                Copy this single-use code into the extension's pairing field
                while the Google Photos tab is selected. It expires in five
                minutes.
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
            The desktop browser runs read-only inventory jobs. Its Google
            session stays on your desktop. Counts alone cannot authorize cloud
            changes.
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
          <ol>
            {status?.jobs?.map((job) => (
              <li key={job.id}>
                Inventory: {job.state}
                {job.result &&
                  ` — ${job.result.photos} items, ${job.result.favorites} favorites, ${job.result.albums} albums`}
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
          {error && <p role="alert">{error}</p>}
        </section>
      )}
    </div>
  );
}
