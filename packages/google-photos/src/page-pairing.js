import { workerOrigin } from "./worker-origin.js";

const fail = (code) =>
  Object.assign(new Error("Page pairing stopped"), { diagnostic: { code } });

export async function pairFromPage(message, sender, { tabs, identity, pair }) {
  const url = new URL(sender.url);
  if (
    sender.frameId !== 0 ||
    !Number.isInteger(sender.tab?.id) ||
    url.protocol !== "https:" ||
    url.username ||
    url.password ||
    !(
      url.hostname === "localhost" || url.origin === "https://photos.lbsa71.net"
    )
  )
    throw fail("PAIR_ENDPOINT");
  if (
    typeof message.code !== "string" ||
    !/^[A-Za-z0-9_-]{43}$/.test(message.code) ||
    typeof message.account !== "string" ||
    !message.account ||
    message.account.length > 4096
  )
    throw fail("PAIR_CODE");
  for (const tab of await tabs()) {
    const current = await identity(tab.id);
    if (current?.account === message.account)
      return pair({
        origin: workerOrigin(url.origin),
        code: message.code,
        tabId: tab.id,
      });
  }
  throw fail("PAIR_SESSION");
}
