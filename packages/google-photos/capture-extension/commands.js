const deadlines = {
  status: 5000,
  identity: 10000,
  start: 15000,
  stop: 15000,
  export: 10000,
  inventory: 300000,
};
const failure = () =>
  new Error(
    "Extension response could not be verified. Check the Google Photos tab and sign-in.",
  );

export function createCommandClient({
  chrome,
  setTimeout = globalThis.setTimeout,
  clearTimeout = globalThis.clearTimeout,
}) {
  return function command(action) {
    if (!Object.hasOwn(deadlines, action)) return Promise.reject(failure());
    return new Promise((resolve, reject) => {
      let expired = false;
      const timer = setTimeout(() => {
        expired = true;
        clearTimeout(timer);
        reject(
          new Error(
            action === "identity"
              ? "Connection check timed out. Keep Google Photos open and reload the extension before checking again. No automatic retry was made."
              : "Capture command timed out. Its outcome is unknown; check capture status before trying again.",
          ),
        );
      }, deadlines[action]);
      (async () => {
        const [tab] = await chrome.tabs.query({
          active: true,
          currentWindow: true,
        });
        // A late tab lookup must never start an operation after the deadline.
        if (expired) return;
        if (!Number.isInteger(tab?.id) || tab.id < 0) throw failure();
        const response = await chrome.runtime.sendMessage({
          action,
          tabId: tab?.id,
        });
        if (expired) return;
        if (
          response?.ok !== true ||
          !response.result ||
          typeof response.result !== "object" ||
          Array.isArray(response.result)
        )
          throw failure();
        if (
          action === "identity" &&
          (typeof response.result.account !== "string" ||
            !response.result.account ||
            response.result.account.length > 4096 ||
            /[\s\x00-\x1f]/.test(response.result.account))
        )
          throw failure();
        clearTimeout(timer);
        resolve(response.result);
      })().catch(() => {
        clearTimeout(timer);
        if (!expired) reject(failure());
      });
    });
  };
}
