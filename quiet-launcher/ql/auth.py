"""Аккаунты: офлайн, Ely.by (Yggdrasil + authlib-injector) и Microsoft (device code flow)."""
import hashlib
import json
import os
import re
import time
import uuid

from . import endpoints
from .util import (HttpError, Cancelled, get_json, post_json, post_form, download, read_json)


class AuthError(Exception):
    pass


class TwoFactorRequired(AuthError):
    pass


NAME_RE = re.compile(r"^[A-Za-z0-9_]{3,16}$")


def _new_id():
    return uuid.uuid4().hex


# ------------------------------------------------------------------ офлайн

def offline_uuid(name):
    """Тот же UUID, что считает сама игра для офлайн-ника (UUID v3 от "OfflinePlayer:<ник>")."""
    h = bytearray(hashlib.md5(("OfflinePlayer:" + name).encode("utf-8")).digest())
    h[6] = (h[6] & 0x0F) | 0x30
    h[8] = (h[8] & 0x3F) | 0x80
    return bytes(h).hex()


def new_offline(name):
    name = name.strip()
    if not NAME_RE.match(name):
        raise AuthError("Ник: 3–16 символов, только латиница, цифры и _")
    return {"id": _new_id(), "type": "offline", "name": name, "uuid": offline_uuid(name),
            "access_token": "0", "client_token": "", "refresh_token": "", "expires": 0}


# ------------------------------------------------------------------ Ely.by

def _ely_error(e):
    msg = ""
    try:
        msg = json.loads(e.body or "{}").get("errorMessage", "")
    except ValueError:
        pass
    return msg or str(e)


def ely_login(username, password, totp=""):
    pw = password + ":" + totp.strip() if totp.strip() else password
    client_token = _new_id()
    try:
        r = post_json(endpoints.ELY_AUTH + "/authenticate", {
            "username": username.strip(), "password": pw,
            "clientToken": client_token, "requestUser": True})
    except HttpError as e:
        msg = _ely_error(e)
        if "two factor" in msg.lower():
            raise TwoFactorRequired("Включена двухфакторная защита: введите код из приложения")
        if e.status in (400, 401, 403):
            raise AuthError("Ely.by отклонил вход: %s" % msg)
        raise AuthError(str(e))
    prof = r.get("selectedProfile") or {}
    if not prof.get("id"):
        raise AuthError("На аккаунте Ely.by нет профиля игрока")
    return {"id": _new_id(), "type": "elyby", "name": prof["name"], "uuid": prof["id"],
            "access_token": r["accessToken"], "client_token": r.get("clientToken", client_token),
            "refresh_token": "", "expires": 0, "login": username.strip()}


def ely_ensure(acc):
    """Проверяет токен, при необходимости обновляет. True, если аккаунт изменился."""
    try:
        post_json(endpoints.ELY_AUTH + "/validate", {"accessToken": acc["access_token"]})
        return False
    except HttpError as e:
        if e.status not in (400, 401, 403):
            raise AuthError(str(e))
    try:
        r = post_json(endpoints.ELY_AUTH + "/refresh", {
            "accessToken": acc["access_token"], "clientToken": acc["client_token"]})
    except HttpError as e:
        raise AuthError("Токен Ely.by устарел, войдите заново (%s)" % _ely_error(e))
    acc["access_token"] = r["accessToken"]
    return True


def authlib_injector(store, log=None):
    """Путь к authlib-injector.jar (скачивается один раз)."""
    folder = os.path.join(store.cache, "authlib")
    existing = [f for f in (os.listdir(folder) if os.path.isdir(folder) else []) if f.endswith(".jar")]
    if existing:
        return os.path.join(folder, sorted(existing)[-1])
    if log:
        log("Скачиваю authlib-injector для Ely.by…")
    try:
        meta = get_json(endpoints.AUTHLIB_LATEST)
        url = meta["download_url"]
    except Exception:
        rel = get_json(endpoints.AUTHLIB_GITHUB)
        url = [a["browser_download_url"] for a in rel["assets"] if a["name"].endswith(".jar")][0]
    dest = os.path.join(folder, url.rsplit("/", 1)[-1])
    download(url, dest)
    return dest


# ------------------------------------------------------------------ Microsoft

MS_SCOPE = "XboxLive.signin offline_access"

_XSTS_ERRORS = {
    2148916233: "У этой учётной записи Microsoft нет профиля Xbox. Создайте его на xbox.com.",
    2148916235: "Xbox Live недоступен в вашей стране.",
    2148916236: "Для аккаунта нужна проверка возраста (Xbox).",
    2148916237: "Для аккаунта нужна проверка возраста (Xbox).",
    2148916238: "Это детский аккаунт: добавьте его в семейную группу Microsoft.",
}


def ms_device_start(client_id):
    if not client_id.strip():
        raise AuthError("Не указан client id приложения Microsoft (Настройки)")
    try:
        return post_form(endpoints.MS_DEVICE, {"client_id": client_id.strip(), "scope": MS_SCOPE})
    except HttpError as e:
        raise AuthError("Microsoft не принял client id: %s" % (e.body or e))


def ms_device_wait(client_id, dev, cancel=None):
    """Ждёт, пока пользователь введёт код на сайте. Возвращает ответ с токенами."""
    interval = int(dev.get("interval", 5))
    deadline = time.time() + int(dev.get("expires_in", 900))
    while time.time() < deadline:
        for _ in range(interval * 5):
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            time.sleep(0.2)
        try:
            return post_form(endpoints.MS_TOKEN, {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": client_id.strip(), "device_code": dev["device_code"]})
        except HttpError as e:
            try:
                err = json.loads(e.body or "{}").get("error", "")
            except ValueError:
                err = ""
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                interval += 5
                continue
            if err in ("expired_token", "authorization_declined", "bad_verification_code"):
                raise AuthError("Вход отменён или код устарел")
            raise AuthError("Ошибка входа Microsoft: %s" % (e.body or e))
    raise AuthError("Время ожидания входа истекло")


def _minecraft_from_ms(ms_access):
    try:
        xbl = post_json(endpoints.XBL_AUTH, {
            "Properties": {"AuthMethod": "RPS", "SiteName": "user.auth.xboxlive.com",
                           "RpsTicket": "d=" + ms_access},
            "RelyingParty": "http://auth.xboxlive.com", "TokenType": "JWT"})
        uhs = xbl["DisplayClaims"]["xui"][0]["uhs"]
        try:
            xsts = post_json(endpoints.XSTS_AUTH, {
                "Properties": {"SandboxId": "RETAIL", "UserTokens": [xbl["Token"]]},
                "RelyingParty": "rp://api.minecraftservices.com/", "TokenType": "JWT"})
        except HttpError as e:
            try:
                code = int(json.loads(e.body or "{}").get("XErr", 0))
            except ValueError:
                code = 0
            raise AuthError(_XSTS_ERRORS.get(code, "Xbox отклонил вход (%s)" % (e.body or e)))
        try:
            mc = post_json(endpoints.MC_LOGIN, {
                "identityToken": "XBL3.0 x=%s;%s" % (uhs, xsts["Token"])})
        except HttpError as e:
            if e.status == 403:
                raise AuthError("Mojang не принял приложение (Invalid app registration). "
                                "Client id нужно одобрить — см. README, раздел «Вход через Microsoft».")
            raise
        try:
            prof = get_json(endpoints.MC_PROFILE, headers={"Authorization": "Bearer " + mc["access_token"]})
        except HttpError as e:
            if e.status == 404:
                raise AuthError("На этой учётной записи нет Minecraft: Java Edition")
            raise
    except HttpError as e:
        raise AuthError("Сбой входа через Microsoft: %s" % e)
    return mc, prof


def ms_account_from_token(tok, existing=None):
    mc, prof = _minecraft_from_ms(tok["access_token"])
    acc = existing or {"id": _new_id(), "type": "microsoft", "client_token": ""}
    acc.update({"name": prof["name"], "uuid": prof["id"], "access_token": mc["access_token"],
                "refresh_token": tok.get("refresh_token", acc.get("refresh_token", "")),
                "expires": int(time.time()) + int(mc.get("expires_in", 86400))})
    return acc


def ms_ensure(client_id, acc):
    if acc.get("expires", 0) - 300 > time.time():
        return False
    if not acc.get("refresh_token"):
        raise AuthError("Нужно войти в Microsoft заново")
    try:
        tok = post_form(endpoints.MS_TOKEN, {
            "grant_type": "refresh_token", "client_id": client_id.strip(),
            "refresh_token": acc["refresh_token"], "scope": MS_SCOPE})
    except HttpError:
        raise AuthError("Сессия Microsoft истекла, войдите заново")
    ms_account_from_token(tok, acc)
    return True


# ------------------------------------------------------------------ общее

def ensure_fresh(store, acc):
    """Обновляет токены перед запуском. True, если аккаунт изменился (нужно сохранить)."""
    t = acc["type"]
    if t == "elyby":
        return ely_ensure(acc)
    if t == "microsoft":
        return ms_ensure(store.settings.get("ms_client_id", ""), acc)
    return False


def identity(acc):
    """Что подставляется в аргументы запуска игры."""
    user_type = {"microsoft": "msa", "elyby": "mojang"}.get(acc["type"], "legacy")
    return {"username": acc["name"], "uuid": acc["uuid"], "access_token": acc["access_token"],
            "user_type": user_type, "type": acc["type"]}


def type_title(t):
    return {"offline": "Офлайн", "elyby": "Ely.by", "microsoft": "Microsoft"}.get(t, t)
