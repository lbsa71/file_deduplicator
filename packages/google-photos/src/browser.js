import { ProtocolError } from "./errors.js";

// Self-contained so Chrome scripting or Playwright can serialize it into the
// authenticated page. Session values stay there. Writes require an explicit
// account-bound pilot scope; production mutations remain separately gated.
export function pageRequest(request) {
  const fail = (error) => ({ error });
  // Chrome argument conversion can omit null object properties. Serialize the
  // complete request so absent targets remain explicit, validated nulls.
  if (typeof request === "string") {
    try {
      request = JSON.parse(request);
    } catch {
      return fail("INPUT");
    }
  }
  if (!request || typeof request !== "object" || Array.isArray(request))
    return fail("INPUT");
  if (globalThis.location?.origin !== "https://photos.google.com")
    return fail("ORIGIN");
  const session = globalThis.WIZ_global_data;
  if (!session || typeof session.oPEP7c !== "string" || !session.oPEP7c)
    return fail("SESSION");
  // Identity inspection needs no asynchronous page work or network request.
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
    "EzwWhf",
    "pLFTfd",
  ]);
  const writes = {
    "favorite-set": "Ftfh0",
    "archive-set": "w7TP3c",
    trash: "XwAOJf",
    restore: "XwAOJf",
    "album-create": "OXvT9d",
    "album-add": "E1Cajb",
    "album-remove": "ycV3Nd",
    "description-set": "AQNOFd",
    "timestamp-set": "DaSgWe",
    "location-set": "EtUHOe",
    "location-clear": "EtUHOe",
  };
  if (request.mode === "write") {
    const scope = request.testScope;
    const checks = [
      [
        scope?.testOnly === true &&
          ["fixtures", "selected"].includes(scope?.targetPolicy ?? "fixtures"),
        "TEST_MODE",
      ],
      [scope?.account === request.account, "ACCOUNT"],
      [scope?.operation === request.operation, "OPERATION"],
      [writes[request.operation] === request.rpc, "RPC"],
      [
        typeof scope?.jobId === "string" &&
          scope.jobId.length > 0 &&
          scope.jobId.length <= 128,
        "JOB_ID",
      ],
      [
        Number.isSafeInteger(scope?.expiresAt) &&
          scope.expiresAt > Date.now() &&
          scope.expiresAt <= Date.now() + 3600000,
        "EXPIRY",
      ],
      [scope?.photoKey === (request.targetMediaKey ?? null), "PHOTO_TARGET"],
      [scope?.albumId === (request.targetAlbumId ?? null), "ALBUM_TARGET"],
    ];
    const rejected = checks.find(([passed]) => !passed);
    if (rejected) return { error: "UNQUALIFIED", scopeRule: rejected[1] };
  } else if (request.mode !== "read" || !allowed.has(request.rpc))
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
  return (async () => {
    let stage = "fetch";
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
      stage = "body";
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
      stage = "decode";
      return {
        account: request.account,
        status: response.status,
        body: new TextDecoder().decode(bytes),
      };
    } catch (error) {
      let reason = "UnknownError";
      try {
        if (
          [
            "AbortError",
            "TypeError",
            "RangeError",
            "ReferenceError",
            "SecurityError",
            "SyntaxError",
          ].includes(error?.name)
        )
          reason = error.name;
      } catch {
        /* Unknown page exceptions do not become diagnostic text. */
      }
      return { error: "TRANSPORT", diagnostic: { stage, reason } };
    } finally {
      clearTimeout(timer);
    }
  })();
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
