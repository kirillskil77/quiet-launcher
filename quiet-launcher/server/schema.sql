-- Quiet Launcher: «Друзья». Выполнить один раз в D1 -> Console (или wrangler d1 execute).
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  nick TEXT NOT NULL,
  code TEXT NOT NULL UNIQUE,
  key_hash TEXT NOT NULL,
  share_mods INTEGER NOT NULL DEFAULT 0,
  presence INTEGER NOT NULL DEFAULT 0,
  projects TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT '',
  last_seen INTEGER NOT NULL DEFAULT 0,
  created INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS friendships (
  a TEXT NOT NULL,
  b TEXT NOT NULL,
  created INTEGER NOT NULL,
  PRIMARY KEY (a, b)
);
CREATE TABLE IF NOT EXISTS requests (
  from_id TEXT NOT NULL,
  to_id TEXT NOT NULL,
  created INTEGER NOT NULL,
  PRIMARY KEY (from_id, to_id)
);
CREATE TABLE IF NOT EXISTS blocks (
  owner TEXT NOT NULL,
  blocked TEXT NOT NULL,
  PRIMARY KEY (owner, blocked)
);
CREATE TABLE IF NOT EXISTS rate (
  k TEXT PRIMARY KEY,
  n INTEGER NOT NULL,
  win INTEGER NOT NULL
);
