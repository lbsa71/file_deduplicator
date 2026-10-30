import { ProtocolError, identifier, requireThat } from "./errors.js";
export function createOAuthTransport({
  account,
  credentials,
  fetch = globalThis.fetch,
  timeoutMs = 300000,
}) {
  identifier(account);
  return async (request) => {
    requireThat(request.account === account, "Wrong OAuth account", "ACCOUNT");
    const url = new URL(request.url);
    const allowed =
      (request.method === "POST" &&
        ["/v1/uploads", "/v1/mediaItems:batchCreate"].includes(url.pathname)) ||
      (request.method === "GET" &&
        /^\/v1\/mediaItems\/[A-Za-z0-9_-]+$/.test(url.pathname));
    requireThat(
      url.origin === "https://photoslibrary.googleapis.com" &&
        !url.username &&
        !url.password &&
        !url.search &&
        !url.hash &&
        allowed,
      "Unsupported OAuth endpoint",
      "INPUT",
    );
    const credential = await credentials();
    requireThat(
      credential?.account === account,
      "OAuth credential account changed",
      "ACCOUNT",
    );
    identifier(credential.accessToken, "access token");
    const controller = new AbortController(),
      timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url.toString(), {
        method: request.method,
        headers: {
          ...request.headers,
          Authorization: `Bearer ${credential.accessToken}`,
        },
        body: request.body,
        redirect: "error",
        signal: controller.signal,
        ...(request.body?.[Symbol.asyncIterator] ? { duplex: "half" } : {}),
      });
      const reader = response.body?.getReader();
      requireThat(reader, "Missing HTTP body");
      const chunks = [];
      let size = 0;
      while (true) {
        const part = await reader.read();
        if (part.done) break;
        size += part.value.length;
        if (size > 1024 * 1024) {
          await reader.cancel();
          throw new ProtocolError("HTTP response exceeds limit");
        }
        chunks.push(part.value);
      }
      const bytes = new Uint8Array(size);
      let offset = 0;
      for (const c of chunks) {
        bytes.set(c, offset);
        offset += c.length;
      }
      return {
        account,
        status: response.status,
        body: new TextDecoder().decode(bytes),
      };
    } catch {
      throw new ProtocolError("OAuth request failed", "TRANSPORT");
    } finally {
      clearTimeout(timer);
    }
  };
}
