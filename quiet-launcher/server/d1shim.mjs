import { DatabaseSync } from "node:sqlite";
import { readFileSync } from "node:fs";

// Имитация D1 на встроенном node:sqlite — только для локальных проверок.
export function makeEnv() {
  const db = new DatabaseSync(":memory:");
  db.exec(readFileSync(new URL("./schema.sql", import.meta.url), "utf8"));
  class Stmt {
    constructor(sql) { this.sql = sql; this.args = []; }
    bind(...a) { const s = new Stmt(this.sql); s.args = a; return s; }
    async first() { return db.prepare(this.sql).get(...this.args) ?? null; }
    async all() { return { results: db.prepare(this.sql).all(...this.args) }; }
    async run() { db.prepare(this.sql).run(...this.args); return { success: true }; }
  }
  const DB = { prepare: (s) => new Stmt(s), batch: async (list) => { for (const s of list) await s.run(); return []; } };
  return { DB };
}
export async function loadWorker() {
  const src = readFileSync(new URL("./worker.js", import.meta.url), "utf8");
  return (await import("data:text/javascript;base64," + Buffer.from(src).toString("base64"))).default;
}
