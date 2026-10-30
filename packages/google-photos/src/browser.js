import { ProtocolError } from "./errors.js";

// Self-contained so Chrome scripting or Playwright can serialize it into the
// authenticated page. Session values stay there. This shipped transport is
// read-only; mutation transports require separate live qualification.
export async function pageRequest(request) {
  const fail = (error) => ({ error });
  if (globalThis.location?.origin !== "https://photos.google.com")
    return fail("ORIGIN");
  const session = globalThis.WIZ_global_data;
  if (!session || typeof session.oPEP7c !== "string" || !session.oPEP7c)
    return fail("SESSION");
  if (request?.operation === "identity") return { account: session.oPEP7c };
  if (request?.account !== session.oPEP7c) return fail("ACCOUNT");
  const allowed = new Set([
    "lcxiM",
    "EzkLib",
    "Z5xsfc",
    "snAcKc",
    "zy0IHe",
    "VrseUb",
    "fDcn4b",
    "swbisb",
  ]);
  if (request.mode !== "read" || !allowed.has(request.rpc))
    return fail("UNQUALIFIED");
  if (!Array.isArray(request.data)) return fail("INPUT");
  if (
    typeof session.eptZe !== "string" ||
    !/^\/(?:u\/\d+\/)?_\/PhotosUi\/$/.test(session.eptZe)
  )
    return fail("SESSION");
  for (const key of ["FdrFJe", "cfb2h", "SNlM0e"])
    if (typeof session[key] !== "string" || !session[key])
      return fail("SESSION");
  const url = new URL(
    `https://photos.google.com${session.eptZe}data/batchexecute`,
  );
  url.search = new URLSearchParams({
    rpcids: request.rpc,
    "source-path": globalThis.location.pathname,
    "f.sid": session.FdrFJe,
    bl: session.cfb2h,
    pageId: "none",
    rt: "c",
  }).toString();
  const body = new URLSearchParams({
    "f.req": JSON.stringify([
      [[request.rpc, JSON.stringify(request.data), null, "generic"]],
    ]),
    at: session.SNlM0e,
  }).toString();
  const controller = new AbortController(),
    timer = setTimeout(() => controller.abort(), 30000);
  try {
    const response = await globalThis.fetch(url.toString(), {
      method: "POST",
      headers: {
        "content-type": "application/x-www-form-urlencoded;charset=UTF-8",
      },
      credentials: "include",
      redirect: "error",
      body,
      signal: controller.signal,
    });
    const chunks = [];
    let length = 0;
    const reader = response.body?.getReader();
    if (!reader) return fail("BODY");
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      length += part.value.length;
      if (length > 16 * 1024 * 1024) {
        await reader.cancel();
        return fail("SIZE");
      }
      chunks.push(part.value);
    }
    if (globalThis.WIZ_global_data?.oPEP7c !== request.account)
      return fail("ACCOUNT");
    const bytes = new Uint8Array(length);
    let pos = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, pos);
      pos += chunk.length;
    }
    return {
      account: request.account,
      status: response.status,
      body: new TextDecoder().decode(bytes),
    };
  } catch {
    return fail("TRANSPORT");
  } finally {
    clearTimeout(timer);
  }
}

export function createPageTransport({ evaluate }) {
  return async (request) => {
    let result;
    try {
      result = await evaluate(pageRequest, request);
    } catch {
      throw new ProtocolError("Browser evaluation failed", "TRANSPORT");
    }
    if (result?.error)
      throw new ProtocolError(
        "Browser request could not be verified",
        result.error,
      );
    return result;
  };
}
