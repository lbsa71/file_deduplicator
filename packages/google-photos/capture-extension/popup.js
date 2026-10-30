const status = document.querySelector("#status");
async function command(action) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const response = await chrome.runtime.sendMessage({ action, tabId: tab?.id });
  if (!response.ok) throw new Error(response.error);
  return response.result;
}
for (const id of ["start", "stop", "export", "identity", "inventory"])
  document.getElementById(id).addEventListener("click", async () => {
    status.textContent =
      id === "inventory" ? "Reading Google Photos…" : "Working…";
    try {
      const result = await command(id);
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
    }
  });
const result = await command("status");
status.textContent = result.recording
  ? `Recording (${result.count} requests). Return here to stop and download.`
  : "Ready. Open a Google Photos tab before starting.";
