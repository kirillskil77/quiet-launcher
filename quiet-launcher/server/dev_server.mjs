// Локальный сервер для проверки клиента: node dev_server.mjs [порт]
import http from "node:http";
import { makeEnv, loadWorker } from "./d1shim.mjs";

const env = makeEnv();
const worker = await loadWorker();
const server = http.createServer(async (req, res) => {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const body = chunks.length ? Buffer.concat(chunks) : undefined;
  const headers = { ...req.headers, "cf-connecting-ip": req.headers["x-test-ip"] || "127.0.0.1" };
  const r = await worker.fetch(new Request("http://localhost" + req.url, { method: req.method, headers, body: ["GET", "HEAD"].includes(req.method) ? undefined : body }), env);
  res.writeHead(r.status, Object.fromEntries(r.headers));
  res.end(Buffer.from(await r.arrayBuffer()));
});
server.listen(Number(process.argv[2] || 0), "127.0.0.1", () => console.log("listening " + server.address().port));
