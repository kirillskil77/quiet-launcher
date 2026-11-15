// Quiet Launcher — сервер «Друзья» (Cloudflare Worker + D1, привязка DB).
// Хранится минимум: ник, код, хэш ключа, связи, список проектов Modrinth (если пользователь разрешил).
const NICK_RE = /^[A-Za-z0-9_\-А-Яа-яЁё]{2,20}$/u;
const CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
const MAX_FRIENDS = 100, MAX_INCOMING = 30, MAX_OUTGOING = 30, MAX_PROJECTS = 300;
const ONLINE_SECONDS = 150, MAX_BODY = 64 * 1024;

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
const fail = (status, error) => json({ error }, status);
const now = () => Math.floor(Date.now() / 1000);
const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
const sha256 = async (s) => hex(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));
const randHex = (n) => hex(crypto.getRandomValues(new Uint8Array(n)));
function randCode() {
  const b = crypto.getRandomValues(new Uint8Array(6));
  return "QL-" + [...b].map((x) => CODE_ALPHABET[x % CODE_ALPHABET.length]).join("");
}
function timingSafeEqual(a, b) {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}

async function limited(env, request, name, limit, windowSec) {
  const ip = request.headers.get("CF-Connecting-IP") || "local";
  const k = name + ":" + (await sha256("ql-salt:" + ip)).slice(0, 24);
  const win = Math.floor(now() / windowSec);
  const row = await env.DB.prepare("SELECT n, win FROM rate WHERE k = ?").bind(k).first();
  if (!row || row.win !== win) {
    await env.DB.prepare("INSERT OR REPLACE INTO rate (k, n, win) VALUES (?, 1, ?)").bind(k, win).run();
    return false;
  }
  if (row.n >= limit) return true;
  await env.DB.prepare("UPDATE rate SET n = n + 1 WHERE k = ?").bind(k).run();
  return false;
}

async function auth(env, request) {
  const h = request.headers.get("Authorization") || "";
  const m = /^Bearer ([0-9a-f]{16})\.([0-9a-f]{64})$/.exec(h);
  if (!m) return null;
  const u = await env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(m[1]).first();
  if (!u) return null;
  return timingSafeEqual(await sha256(m[2]), u.key_hash) ? u : null;
}

async function readBody(request) {
  const text = await request.text();
  if (text.length > MAX_BODY) throw new HttpError(413, "Слишком большой запрос");
  if (!text) return {};
  try { const v = JSON.parse(text); return v && typeof v === "object" ? v : {}; }
  catch { throw new HttpError(400, "Некорректный JSON"); }
}
class HttpError extends Error { constructor(status, msg) { super(msg); this.status = status; } }

const cleanNick = (n) => (typeof n === "string" && NICK_RE.test(n.trim()) ? n.trim() : null);
const isFriend = async (env, a, b) => !!(await env.DB.prepare("SELECT 1 FROM friendships WHERE a = ? AND b = ?").bind(a, b).first());
const isBlocked = async (env, owner, other) => !!(await env.DB.prepare("SELECT 1 FROM blocks WHERE owner = ? AND blocked = ?").bind(owner, other).first());

function cleanProjects(list) {
  if (!Array.isArray(list)) return [];
  const out = [], seen = new Set();
  for (const p of list) {
    if (!p || typeof p !== "object") continue;
    const id = typeof p.id === "string" && /^[A-Za-z0-9]{6,12}$/.test(p.id) ? p.id : null;
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const kind = ["mod", "resourcepack", "shader", "modpack"].includes(p.kind) ? p.kind : "mod";
    out.push({ id, title: String(p.title || "").slice(0, 80), kind });
    if (out.length >= MAX_PROJECTS) break;
  }
  return out;
}

const publicOf = (u, isFriendView = true) => ({
  id: u.id, nick: u.nick,
  online: !!u.presence && now() - u.last_seen < ONLINE_SECONDS,
  status: u.presence && now() - u.last_seen < ONLINE_SECONDS ? u.status : "",
  shares: !!u.share_mods,
});

const routes = {
  async "POST /register"(env, request) {
    if (await limited(env, request, "reg", 5, 3600)) throw new HttpError(429, "Слишком много попыток, попробуйте позже");
    const body = await readBody(request);
    const nick = cleanNick(body.nick);
    if (!nick) throw new HttpError(400, "Ник: 2–20 символов, буквы, цифры, _ и -");
    const id = randHex(8), key = randHex(32), keyHash = await sha256(key);
    for (let i = 0; i < 6; i++) {
      const code = randCode();
      try {
        await env.DB.prepare("INSERT INTO users (id, nick, code, key_hash, created) VALUES (?, ?, ?, ?, ?)").bind(id, nick, code, keyHash, now()).run();
        return json({ id, key, code, nick });
      } catch (e) { if (!String(e).includes("UNIQUE")) throw e; }
    }
    throw new HttpError(500, "Не удалось создать код, повторите");
  },

  async "POST /profile"(env, request, me) {
    const b = await readBody(request);
    const sets = [], vals = [];
    if ("nick" in b) { const n = cleanNick(b.nick); if (!n) throw new HttpError(400, "Некорректный ник"); sets.push("nick = ?"); vals.push(n); }
    if ("share_mods" in b) { sets.push("share_mods = ?"); vals.push(b.share_mods ? 1 : 0); }
    if ("presence" in b) { sets.push("presence = ?"); vals.push(b.presence ? 1 : 0); }
    if ("projects" in b) { sets.push("projects = ?"); vals.push(JSON.stringify(cleanProjects(b.projects))); }
    if ("status" in b) { sets.push("status = ?"); vals.push(String(b.status || "").slice(0, 40)); }
    if (sets.length) await env.DB.prepare(`UPDATE users SET ${sets.join(", ")} WHERE id = ?`).bind(...vals, me.id).run();
    const u = await env.DB.prepare("SELECT * FROM users WHERE id = ?").bind(me.id).first();
    return json({ id: u.id, nick: u.nick, code: u.code, share_mods: !!u.share_mods, presence: !!u.presence });
  },

  async "POST /heartbeat"(env, request, me) {
    const b = await readBody(request);
    await env.DB.prepare("UPDATE users SET last_seen = ?, status = ? WHERE id = ?").bind(now(), String(b.status || "").slice(0, 40), me.id).run();
    return json({ ok: true });
  },

  async "GET /friends"(env, request, me) {
    const fr = await env.DB.prepare(
      "SELECT u.* FROM friendships f JOIN users u ON u.id = f.b WHERE f.a = ? ORDER BY u.nick COLLATE NOCASE").bind(me.id).all();
    const inc = await env.DB.prepare(
      "SELECT u.id, u.nick FROM requests r JOIN users u ON u.id = r.from_id WHERE r.to_id = ? ORDER BY r.created DESC").bind(me.id).all();
    const out = await env.DB.prepare(
      "SELECT u.id, u.nick FROM requests r JOIN users u ON u.id = r.to_id WHERE r.from_id = ? ORDER BY r.created DESC").bind(me.id).all();
    return json({
      me: { id: me.id, nick: me.nick, code: me.code, share_mods: !!me.share_mods, presence: !!me.presence },
      friends: fr.results.map((u) => publicOf(u)), incoming: inc.results, outgoing: out.results,
    });
  },

  async "POST /friends/request"(env, request, me) {
    if (await limited(env, request, "req", 30, 3600)) throw new HttpError(429, "Слишком много заявок за час");
    const b = await readBody(request);
    const code = String(b.code || "").trim().toUpperCase();
    if (!/^QL-[A-Z0-9]{6}$/.test(code)) throw new HttpError(400, "Неверный формат кода (QL-XXXXXX)");
    const other = await env.DB.prepare("SELECT id, nick FROM users WHERE code = ?").bind(code).first();
    if (!other) throw new HttpError(404, "Пользователь с таким кодом не найден");
    if (other.id === me.id) throw new HttpError(400, "Это ваш собственный код");
    if (await isFriend(env, me.id, other.id)) throw new HttpError(409, "Вы уже друзья");
    if (await isBlocked(env, other.id, me.id)) return json({ ok: true, nick: other.nick });   // молча: не раскрываем блокировку
    if (await isBlocked(env, me.id, other.id)) await env.DB.prepare("DELETE FROM blocks WHERE owner = ? AND blocked = ?").bind(me.id, other.id).run();
    const cnt = async (q, id) => (await env.DB.prepare(q).bind(id).first()).n;
    if ((await cnt("SELECT COUNT(*) n FROM requests WHERE from_id = ?", me.id)) >= MAX_OUTGOING) throw new HttpError(429, "Слишком много неотвеченных заявок");
    if ((await cnt("SELECT COUNT(*) n FROM requests WHERE to_id = ?", other.id)) >= MAX_INCOMING) return json({ ok: true, nick: other.nick });
    const reverse = await env.DB.prepare("SELECT 1 FROM requests WHERE from_id = ? AND to_id = ?").bind(other.id, me.id).first();
    if (reverse) return await makeFriends(env, me.id, other.id, other.nick);        // встречная заявка = согласие обеих сторон
    await env.DB.prepare("INSERT OR IGNORE INTO requests (from_id, to_id, created) VALUES (?, ?, ?)").bind(me.id, other.id, now()).run();
    return json({ ok: true, nick: other.nick });
  },

  async "POST /friends/respond"(env, request, me) {
    const b = await readBody(request);
    const id = String(b.id || "");
    const req = await env.DB.prepare("SELECT 1 FROM requests WHERE from_id = ? AND to_id = ?").bind(id, me.id).first();
    if (!req) throw new HttpError(404, "Заявка не найдена");
    if (b.accept) {
      const u = await env.DB.prepare("SELECT nick FROM users WHERE id = ?").bind(id).first();
      return await makeFriends(env, me.id, id, u ? u.nick : "");
    }
    await env.DB.prepare("DELETE FROM requests WHERE from_id = ? AND to_id = ?").bind(id, me.id).run();
    if (b.block) await env.DB.prepare("INSERT OR IGNORE INTO blocks (owner, blocked) VALUES (?, ?)").bind(me.id, id).run();
    return json({ ok: true });
  },

  async "POST /friends/cancel"(env, request, me) {
    const b = await readBody(request);
    await env.DB.prepare("DELETE FROM requests WHERE from_id = ? AND to_id = ?").bind(me.id, String(b.id || "")).run();
    return json({ ok: true });
  },

  async "POST /friends/remove"(env, request, me) {
    const b = await readBody(request);
    const id = String(b.id || "");
    await env.DB.batch([
      env.DB.prepare("DELETE FROM friendships WHERE (a = ? AND b = ?) OR (a = ? AND b = ?)").bind(me.id, id, id, me.id),
      ...(b.block ? [env.DB.prepare("INSERT OR IGNORE INTO blocks (owner, blocked) VALUES (?, ?)").bind(me.id, id)] : []),
    ]);
    return json({ ok: true });
  },

  async "GET /friend/projects"(env, request, me) {
    const id = new URL(request.url).searchParams.get("id") || "";
    if (!(await isFriend(env, me.id, id))) throw new HttpError(403, "Вы не друзья");
    const u = await env.DB.prepare("SELECT nick, share_mods, projects FROM users WHERE id = ?").bind(id).first();
    if (!u) throw new HttpError(404, "Не найден");
    if (!u.share_mods) return json({ nick: u.nick, shared: false, projects: [] });
    return json({ nick: u.nick, shared: true, projects: JSON.parse(u.projects || "[]") });
  },

  async "POST /account/delete"(env, request, me) {
    await env.DB.batch([
      env.DB.prepare("DELETE FROM friendships WHERE a = ? OR b = ?").bind(me.id, me.id),
      env.DB.prepare("DELETE FROM requests WHERE from_id = ? OR to_id = ?").bind(me.id, me.id),
      env.DB.prepare("DELETE FROM blocks WHERE owner = ? OR blocked = ?").bind(me.id, me.id),
      env.DB.prepare("DELETE FROM users WHERE id = ?").bind(me.id),
    ]);
    return json({ ok: true });
  },
};

async function makeFriends(env, a, b, nick) {
  await env.DB.batch([
    env.DB.prepare("DELETE FROM requests WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?)").bind(a, b, b, a),
    env.DB.prepare("INSERT OR IGNORE INTO friendships (a, b, created) VALUES (?, ?, ?)").bind(a, b, now()),
    env.DB.prepare("INSERT OR IGNORE INTO friendships (a, b, created) VALUES (?, ?, ?)").bind(b, a, now()),
  ]);
  const n = (await env.DB.prepare("SELECT COUNT(*) n FROM friendships WHERE a = ?").bind(a).first()).n;
  if (n > MAX_FRIENDS) {
    await env.DB.prepare("DELETE FROM friendships WHERE (a = ? AND b = ?) OR (a = ? AND b = ?)").bind(a, b, b, a).run();
    throw new HttpError(409, "Достигнут предел числа друзей");
  }
  return json({ ok: true, friends: true, nick });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const key = `${request.method} ${url.pathname.replace(/\/+$/, "") || "/"}`;
    try {
      if (key === "GET /") return json({ service: "quiet-friends", ok: true });
      const handler = routes[key];
      if (!handler) return fail(404, "Не найдено");
      if (await limited(env, request, "all", 120, 60)) return fail(429, "Слишком много запросов");
      let me = null;
      if (key !== "POST /register") {
        me = await auth(env, request);
        if (!me) return fail(401, "Требуется вход");
      }
      return await handler(env, request, me);
    } catch (e) {
      if (e instanceof HttpError) return fail(e.status, e.message);
      return fail(500, "Ошибка сервера");
    }
  },
};
