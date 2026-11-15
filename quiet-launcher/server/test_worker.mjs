// Локальная проверка worker.js без Cloudflare. Запуск: node test_worker.mjs (Node 22+)
import assert from "node:assert/strict";
import { makeEnv, loadWorker } from "./d1shim.mjs";

const { DB } = makeEnv();
const worker = await loadWorker();

let ip = 1;
async function call(method, path, body, creds, fixedIp) {
  const headers = { "CF-Connecting-IP": fixedIp || "10.0.0." + (ip++) };
  if (creds) headers.Authorization = `Bearer ${creds.id}.${creds.key}`;
  const r = await worker.fetch(new Request("https://x.test" + path, { method, headers, body: body ? JSON.stringify(body) : undefined }), { DB });
  return { status: r.status, data: await r.json() };
}
const reg = async (nick) => (await call("POST", "/register", { nick })).data;

// регистрация и проверки ввода
assert.equal((await call("POST", "/register", { nick: "a" })).status, 400);
assert.equal((await call("POST", "/register", { nick: "bad nick!" })).status, 400);
const A = await reg("Kirill"), B = await reg("Друг_1"), C = await reg("Third");
assert.match(A.code, /^QL-[A-Z2-9]{6}$/);
assert.equal((await call("GET", "/friends")).status, 401);
assert.equal((await call("GET", "/friends", null, { id: A.id, key: "0".repeat(64) })).status, 401);

// заявка -> принятие
assert.equal((await call("POST", "/friends/request", { code: "bad" }, A)).status, 400);
assert.equal((await call("POST", "/friends/request", { code: A.code }, A)).status, 400);
assert.equal((await call("POST", "/friends/request", { code: "QL-ZZZZZZ" }, A)).status, 404);
assert.equal((await call("POST", "/friends/request", { code: B.code }, A)).status, 200);
let fb = (await call("GET", "/friends", null, B)).data;
assert.equal(fb.incoming.length, 1); assert.equal(fb.incoming[0].nick, "Kirill");
assert.equal((await call("GET", "/friends", null, A)).data.outgoing.length, 1);
assert.equal((await call("POST", "/friends/respond", { id: A.id, accept: true }, B)).data.friends, true);
assert.equal((await call("GET", "/friends", null, A)).data.friends[0].nick, "Друг_1");
assert.equal((await call("GET", "/friends", null, B)).data.incoming.length, 0);

// приватность: список модов виден только друзьям и только если разрешено
const proj = [{ id: "AANobbMI", title: "Sodium", kind: "mod" }, { id: "bad id", title: "x" }, { id: "AANobbMI", title: "dup" }];
await call("POST", "/profile", { projects: proj }, A);
let p = (await call("GET", "/friend/projects?id=" + A.id, null, B)).data;
assert.equal(p.shared, false); assert.deepEqual(p.projects, []);
await call("POST", "/profile", { share_mods: true }, A);
p = (await call("GET", "/friend/projects?id=" + A.id, null, B)).data;
assert.equal(p.shared, true); assert.equal(p.projects.length, 1); assert.equal(p.projects[0].title, "Sodium");
assert.equal((await call("GET", "/friend/projects?id=" + A.id, null, C)).status, 403);

// присутствие: по умолчанию скрыто
await call("POST", "/heartbeat", { status: "играет" }, A);
assert.equal((await call("GET", "/friends", null, B)).data.friends[0].online, false);
await call("POST", "/profile", { presence: true }, A);
let st = (await call("GET", "/friends", null, B)).data.friends[0];
assert.equal(st.online, true); assert.equal(st.status, "играет");

// встречные заявки = дружба, блокировка, удаление
assert.equal((await call("POST", "/friends/request", { code: C.code }, A)).status, 200);
assert.equal((await call("POST", "/friends/request", { code: A.code }, C)).data.friends, true);
await call("POST", "/friends/remove", { id: C.id, block: true }, A);
assert.equal((await call("GET", "/friends", null, C)).data.friends.length, 0);
assert.equal((await call("POST", "/friends/request", { code: A.code }, C)).status, 200);       // молча
assert.equal((await call("GET", "/friends", null, A)).data.incoming.length, 0);               // и не доходит

// лимит регистраций с одного адреса
let last;
for (let i = 0; i < 6; i++) last = await call("POST", "/register", { nick: "Spam" + i }, null, "9.9.9.9");
assert.equal(last.status, 429);

// удаление аккаунта
assert.equal((await call("POST", "/account/delete", {}, B)).status, 200);
assert.equal((await call("GET", "/friends", null, B)).status, 401);
assert.equal((await call("GET", "/friends", null, A)).data.friends.length, 0);
assert.equal((await call("GET", "/nope")).status, 404);
console.log("worker: все проверки пройдены");
