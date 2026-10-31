export const DEFAULT_WORKER_ORIGIN = "https://photos.lbsa71.net";

export async function readWorkerOrigin(storage, fallback) {
  const saved = (await storage.get("workerOriginPreference"))
    .workerOriginPreference;
  return workerOrigin(saved ?? fallback);
}

export async function saveWorkerOrigin(storage, value) {
  const origin = workerOrigin(value);
  await storage.set({ workerOriginPreference: origin });
  return origin;
}

export function workerOrigin(value = DEFAULT_WORKER_ORIGIN) {
  if (typeof value !== "string" || !value)
    throw new Error("Invalid PhotoFlow endpoint");
  const url = new URL(value);
  if (
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    url.pathname !== "/" ||
    url.search ||
    url.hash
  )
    throw new Error(
      "PhotoFlow endpoint must be an HTTPS origin without a path, credentials, query or fragment",
    );
  return url.origin;
}
