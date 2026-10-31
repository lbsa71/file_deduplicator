export function pairWithExtension({ account, code }, target = window) {
  return new Promise((resolve, reject) => {
    const id = crypto.randomUUID();
    const finish = (error, result) => {
      clearTimeout(timer);
      target.removeEventListener("message", receive);
      error ? reject(error) : resolve(result);
    };
    const receive = (event) => {
      if (
        event.source !== target ||
        event.origin !== target.location.origin ||
        event.data?.channel !== "photoflow-pair-response" ||
        event.data.id !== id
      )
        return;
      const response = event.data.response;
      if (response?.ok === true && typeof response.result?.state === "string")
        finish(null, response.result);
      else
        finish(
          new Error(
            typeof response?.message === "string"
              ? response.message
              : "The extension could not verify pairing.",
          ),
        );
    };
    const timer = setTimeout(
      () =>
        finish(
          new Error(
            "No extension reply. Open this PhotoFlow page in Chrome with the updated extension enabled and allowed on this site. Pairing may still be running; check connection status before trying again.",
          ),
        ),
      30000,
    );
    target.addEventListener("message", receive);
    target.postMessage(
      { channel: "photoflow-pair-request", id, account, code },
      target.location.origin,
    );
  });
}
