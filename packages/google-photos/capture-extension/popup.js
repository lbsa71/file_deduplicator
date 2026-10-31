import { createCommandClient } from "./commands.js";

const status = document.querySelector("#status");
const command = createCommandClient({ chrome });
const buttons = [...document.querySelectorAll("button")];
let busy = false;
function setBusy(value) {
  busy = value;
  for (const button of buttons) button.disabled = value;
}
for (const id of [
  "start",
  "stop",
  "export",
  "identity",
  "inventory",
  "inspect",
])
  document.getElementById(id).addEventListener("click", async () => {
    if (busy) return;
    setBusy(true);
    status.textContent =
      id === "inventory" ? "Reading Google Photos…" : "Working…";
    try {
      const selection =
        id === "inspect"
          ? {
              account: document.querySelector("#account").value.trim(),
              albumUrl: document.querySelector("#album-url").value.trim(),
              photoUrl: document.querySelector("#photo-url").value.trim(),
            }
          : undefined;
      const result = await command(id, selection);
      if (id === "export") {
        if (!result.capture) throw new Error("No capture available");
        const url = URL.createObjectURL(
          new Blob([JSON.stringify(result.capture, null, 2)], {
            type: "application/json",
          }),
        );
        const a = document.createElement("a");
        a.href = url;
        a.download = "google-photos.capture.json";
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
        status.textContent = `Downloaded ${result.capture.entries.length} sanitized interactions. Complete: ${result.capture.complete}`;
      } else status.textContent = JSON.stringify(result, null, 2);
    } catch (e) {
      status.textContent = e.message;
    } finally {
      setBusy(false);
    }
  });
setBusy(true);
try {
  const result = await command("status");
  status.textContent = result.recording
    ? `Recording (${result.count} requests). Return here to stop and download.`
    : "Ready. Open a Google Photos tab before starting.";
} catch (e) {
  status.textContent = e.message;
} finally {
  setBusy(false);
}
