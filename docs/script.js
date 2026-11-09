const REPO = "kirillskil77/quiet-launcher";
const RELEASES_API = `https://api.github.com/repos/${REPO}/releases/latest`;
const FALLBACK_RELEASE = `https://github.com/${REPO}/releases/latest`;

document.getElementById("year").textContent = new Date().getFullYear();

async function setupDownload() {
  const links = [document.getElementById("hero-download"), document.getElementById("main-download")];
  const versionLabels = [document.getElementById("hero-version"), document.getElementById("download-version")];
  try {
    const response = await fetch(RELEASES_API, {headers: {"Accept": "application/vnd.github+json"}});
    if (!response.ok) throw new Error("GitHub release unavailable");
    const release = await response.json();
    const exe = (release.assets || []).find(asset => /\.exe$/i.test(asset.name));
    const label = release.tag_name || "Последняя версия";
    versionLabels.forEach(el => { if (el) el.textContent = `${label} · Windows`; });
    if (exe && exe.browser_download_url) {
      links.forEach(link => { link.href = exe.browser_download_url; link.setAttribute("download", ""); });
      document.getElementById("download-note").textContent = `${label} · ${exe.name} · Windows 7 SP1 и новее`;
    } else {
      links.forEach(link => link.href = release.html_url || FALLBACK_RELEASE);
      document.getElementById("download-note").textContent = "Откроется страница релиза — выбери установщик в Assets.";
    }
  } catch (error) {
    links.forEach(link => link.href = FALLBACK_RELEASE);
    versionLabels.forEach(el => { if (el) el.textContent = "Последний релиз на GitHub"; });
    document.getElementById("download-note").textContent = "Если скачивание не началось, открой страницу релизов GitHub.";
  }
}
setupDownload();

const menuButton = document.querySelector(".menu-toggle");
const nav = document.querySelector(".nav");
menuButton.addEventListener("click", () => {
  const open = nav.classList.toggle("open");
  menuButton.setAttribute("aria-expanded", String(open));
});
nav.querySelectorAll("a").forEach(a => a.addEventListener("click", () => {
  nav.classList.remove("open");
  menuButton.setAttribute("aria-expanded", "false");
}));
