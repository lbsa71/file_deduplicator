export const ACCOUNT = "fixture-account";
export const envelope = (rpc, value) =>
  ")]}'\n\n" +
  JSON.stringify([
    ["wrb.fr", rpc, JSON.stringify(value), null, null, null, "generic"],
  ]) +
  "\n";
export function item(id = "media-a", favorite = undefined) {
  const row = Array(16).fill(null);
  row[0] = id;
  row[1] = ["https://example.invalid/thumbnail", 100, 80];
  row[2] = 1700000000000;
  row[3] = `dedup-${id}`;
  row[5] = 1700000001000;
  row[15] = favorite === undefined ? {} : { 163238866: [favorite] };
  return row;
}
export function album(id = "album-a") {
  return [
    id,
    null,
    null,
    null,
    null,
    null,
    ["owner-a"],
    { 72930366: [null, "Fixture album", null, 1, false] },
  ];
}
export function harness(responses = []) {
  const calls = [];
  const transport = async (request) => {
    calls.push(structuredClone(request));
    const next = responses.shift();
    if (next instanceof Error) throw next;
    return (
      next ?? {
        account: ACCOUNT,
        status: 200,
        body: envelope(request.rpc, [[]]),
      }
    );
  };
  const reply = (rpc, data, extras = {}) => ({
    account: ACCOUNT,
    status: 200,
    body: envelope(rpc, data),
    ...extras,
  });
  return { calls, transport, reply };
}
