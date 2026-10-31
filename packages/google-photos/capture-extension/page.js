// A narrow bridge for pairing only. It never exposes saved credentials or jobs.
window.addEventListener("message", async (event) => {
  const value = event.data;
  if (
    event.source !== window ||
    event.origin !== location.origin ||
    value?.channel !== "photoflow-pair-request" ||
    typeof value.id !== "string" ||
    value.id.length > 64 ||
    typeof value.code !== "string" ||
    value.code.length !== 43 ||
    typeof value.account !== "string" ||
    value.account.length > 4096
  )
    return;
  let response;
  try {
    response = await chrome.runtime.sendMessage({
      action: "page-pair",
      account: value.account,
      code: value.code,
    });
  } catch {
    response = {
      ok: false,
      message: "Reload the PhotoFlow extension and this page, then try again.",
    };
  }
  window.postMessage(
    { channel: "photoflow-pair-response", id: value.id, response },
    location.origin,
  );
});
