import React, { useEffect, useRef, useState } from "react";

export function GoogleInventory({ account, busy, act, call }) {
  const [inventory, setInventory] = useState(null),
    [error, setError] = useState("");
  const selection = useRef(0);
  const base = "/google/inventories";
  useEffect(() => {
    if (!account) return;
    let active = true;
    const generation = selection.current;
    call(`${base}?account=${encodeURIComponent(account)}`)
      .then(async (value) => {
        if (!active || selection.current !== generation || !value.items.length)
          return;
        const current = await call(
          `${base}/${value.items[0].id}?account=${encodeURIComponent(account)}`,
        );
        if (active && selection.current === generation) setInventory(current);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [account]);
  useEffect(() => {
    if (inventory?.state !== "running") return;
    let active = true,
      timer;
    async function refresh() {
      try {
        const value = await call(
          `${base}/${inventory.id}?account=${encodeURIComponent(account)}`,
        );
        if (!active) return;
        setInventory(value);
        if (value.state === "running") timer = setTimeout(refresh, 2000);
      } catch (e) {
        if (active) setError(e.message);
      }
    }
    timer = setTimeout(refresh, 1000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [inventory?.id, inventory?.state, account]);
  async function control(action) {
    setError("");
    setInventory(
      await call(`${base}/${inventory.id}/${action}`, "POST", { account }),
    );
  }
  return (
    <section aria-label="Full Google inventory">
      <h4>Full Google inventory</h4>
      <p>
        Capture every page of library, favorites, albums, Trash and album
        membership. The server continues in the background while the paired
        Google browser is available. No Google changes are made by this capture.
      </p>
      <button
        disabled={busy || !account || inventory?.state === "running"}
        onClick={() =>
          act(async () => {
            selection.current += 1;
            setError("");
            setInventory(await call(base, "POST", { account }));
          })
        }
      >
        Start full Google inventory
      </button>
      {inventory && (
        <div>
          <p role="status">
            {inventory.complete
              ? "Inventory complete"
              : inventory.state === "running"
                ? "Inventory running"
                : inventory.state === "cancelled"
                  ? "Inventory cancelled"
                  : "Inventory incomplete"}
          </p>
          <p>
            {inventory.pages} pages captured; {inventory.counts.library} library
            items, {inventory.counts.favorites} favorites,{" "}
            {inventory.counts.albums} albums, {inventory.counts.trash} Trash
            items, {inventory.counts.albumMembers} album members.
          </p>
          {inventory.background?.waiting_reason && (
            <p>
              Waiting:{" "}
              {inventory.background.waiting_reason.replaceAll("_", " ")}
            </p>
          )}
          {inventory.background?.error && (
            <p role="alert">{inventory.background.error}</p>
          )}
          {inventory.error && (
            <p role="alert">
              {inventory.error}. This inventory cannot authorize reconciliation
              changes.
            </p>
          )}
          {inventory.state === "running" && (
            <button
              disabled={busy}
              onClick={() => act(() => control("cancel"))}
            >
              Cancel inventory after current page
            </button>
          )}
          {inventory.state === "running" &&
            ["failed", "partial", "cancelled"].includes(
              inventory.background?.state,
            ) && (
              <button
                disabled={busy}
                onClick={() => act(() => control("resume"))}
              >
                Resume inventory
              </button>
            )}
          <details>
            <summary>Inventory coverage and diagnostics</summary>
            <pre>{JSON.stringify(inventory, null, 2)}</pre>
          </details>
        </div>
      )}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
