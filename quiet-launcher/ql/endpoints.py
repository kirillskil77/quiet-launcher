"""Все внешние адреса в одном месте (их же подменяют тесты)."""

# Mojang
VERSION_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
VERSION_MANIFEST_FALLBACK = "https://launchermeta.mojang.com/mc/game/version_manifest.json"
ASSETS_BASE = "https://resources.download.minecraft.net/"
LIBRARIES_BASE = "https://libraries.minecraft.net/"
JAVA_RUNTIME_INDEX = (
    "https://launchermeta.mojang.com/v1/products/java-runtime/"
    "2ec0cc96c44e5a76b9c8b7c39df7210883d12871/all.json"
)

# Java Zulu (Azul): API со ссылкой на свежую сборку и запасные прямые ссылки
AZUL_API = "https://api.azul.com/metadata/v1/zulu/packages/"
ZULU_FALLBACK = {
    "x64": "https://cdn.azul.com/zulu/bin/zulu21.38.21-ca-jre21.0.5-win_x64.zip",
    "x86": "https://cdn.azul.com/zulu/bin/zulu21.38.21-ca-jre21.0.5-win_i686.zip",
}

# Загрузчики
FABRIC_META = "https://meta.fabricmc.net/v2"
QUILT_META = "https://meta.quiltmc.org/v3"
FORGE_MAVEN = "https://maven.minecraftforge.net/net/minecraftforge/forge/"
NEOFORGE_MAVEN = "https://maven.neoforged.net/releases/net/neoforged/neoforge/"

# Моды
MODRINTH_API = "https://api.modrinth.com/v2"

# Обновления лаунчера: GitHub Releases (владелец/репозиторий)
GITHUB_REPO = "kirillskil77/quiet-launcher"
UPDATE_API = "https://api.github.com/repos/%s/releases/latest" % GITHUB_REPO
RELEASES_PAGE = "https://github.com/%s/releases" % GITHUB_REPO

# Ely.by / authlib-injector
ELY_AUTH = "https://authserver.ely.by/auth"
ELY_AGENT_SERVER = "ely.by"
AUTHLIB_LATEST = "https://authlib-injector.yushi.moe/artifact/latest.json"
AUTHLIB_GITHUB = "https://api.github.com/repos/yushijinhun/authlib-injector/releases/latest"

# Microsoft / Xbox / Minecraft Services
MS_DEVICE = "https://login.microsoftonline.com/consumers/oauth2/v2.0/devicecode"
MS_TOKEN = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
XBL_AUTH = "https://user.auth.xboxlive.com/user/authenticate"
XSTS_AUTH = "https://xsts.auth.xboxlive.com/xsts/authorize"
MC_LOGIN = "https://api.minecraftservices.com/authentication/login_with_xbox"
MC_PROFILE = "https://api.minecraftservices.com/minecraft/profile"

ELY_SKIN = "https://skinsystem.ely.by/skins/{name}.png"

FRIENDS_API = "https://quiet-friends.kirillbilous8.workers.dev"
