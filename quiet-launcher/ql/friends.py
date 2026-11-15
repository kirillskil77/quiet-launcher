"""Клиент сервера «Друзья». Профиль без пароля: id + секретный ключ лежат только в friends.json на этом компьютере.
На сервер уходит минимум: ник, код, связи и — только если вы разрешили — список проектов Modrinth."""
import json
import os
import urllib.parse

from . import endpoints
from .util import HttpError, request, read_json, write_json


class FriendsError(Exception):
    pass


def _message(e):
    """Человекочитаемая ошибка из ответа сервера."""
    if isinstance(e, HttpError):
        if e.status is None:
            return "Нет связи с сервером «Друзья»"
        try:
            text = json.loads(e.body or "{}").get("error")
        except ValueError:
            text = None
        return text or "Ошибка сервера (%s)" % e.status
    return str(e)


def collect_projects(instances, limit=300):
    """Уникальные проекты Modrinth из всех сборок: id, название, тип. Сами файлы никуда не отправляются."""
    out, seen = [], set()
    for inst in instances:
        for m in inst.mods:
            pid = m.get("project_id")
            if not pid or pid in seen:
                continue
            seen.add(pid)
            out.append({"id": pid, "title": m.get("title", "")[:80], "kind": m.get("kind") or "mod"})
            if len(out) >= limit:
                return out
    return out


class Friends(object):
    def __init__(self, store, base=None):
        self.base = (base or endpoints.FRIENDS_API).rstrip("/")
        self.path = os.path.join(store.home, "friends.json")
        self.profile = read_json(self.path, None)
        if not (isinstance(self.profile, dict) and self.profile.get("id") and self.profile.get("key")):
            self.profile = None

    @property
    def registered(self):
        return self.profile is not None

    def _save(self):
        write_json(self.path, self.profile)

    def _call(self, method, path, payload=None, auth=True):
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        if auth:
            if not self.profile:
                raise FriendsError("Сначала создайте профиль")
            headers["Authorization"] = "Bearer %s.%s" % (self.profile["id"], self.profile["key"])
        try:
            _, body = request(self.base + path, data=data, headers=headers, method=method, timeout=15, retries=2)
        except HttpError as e:
            if e.status == 401 and auth:
                raise FriendsError("Профиль не найден на сервере. Создайте его заново (старые друзья не сохранятся)")
            raise FriendsError(_message(e))
        return json.loads(body.decode("utf-8") or "{}")

    # --- профиль
    def register(self, nick):
        r = self._call("POST", "/register", {"nick": nick}, auth=False)
        self.profile = {"id": r["id"], "key": r["key"], "code": r["code"], "nick": r["nick"]}
        self._save()
        return self.profile

    def forget(self):
        """Забыть профиль на этом компьютере (на сервере он остаётся, пока его не удалят)."""
        self.profile = None
        try:
            os.remove(self.path)
        except OSError:
            pass

    def delete_account(self):
        self._call("POST", "/account/delete", {})
        self.forget()

    def update(self, **fields):
        r = self._call("POST", "/profile", fields)
        if self.profile:
            self.profile["nick"], self.profile["code"] = r["nick"], r["code"]
            self._save()
        return r

    def heartbeat(self, status=""):
        self._call("POST", "/heartbeat", {"status": status})

    # --- друзья
    def overview(self):
        return self._call("GET", "/friends")

    def request_friend(self, code):
        return self._call("POST", "/friends/request", {"code": code})

    def respond(self, user_id, accept, block=False):
        return self._call("POST", "/friends/respond", {"id": user_id, "accept": bool(accept), "block": bool(block)})

    def cancel(self, user_id):
        return self._call("POST", "/friends/cancel", {"id": user_id})

    def remove(self, user_id, block=False):
        return self._call("POST", "/friends/remove", {"id": user_id, "block": bool(block)})

    def projects_of(self, user_id):
        return self._call("GET", "/friend/projects?id=" + urllib.parse.quote(user_id))
