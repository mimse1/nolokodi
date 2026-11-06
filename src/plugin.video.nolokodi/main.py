import json
import os
import re
import sys
import urllib.request
from urllib.parse import urlencode, parse_qsl, urljoin, quote

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

ADDON = xbmcaddon.Addon()
HANDLE = int(sys.argv[1])
BASE_URL = sys.argv[0]
PATH = xbmcvfs.translatePath(ADDON.getAddonInfo("path"))
LOCAL_JSON = PATH + "resources/channels.json"
ICON = ADDON.getAddonInfo("icon")
FANART = ADDON.getAddonInfo("fanart")
CACHE_JSON = xbmcvfs.translatePath("special://profile/addon_data/%s/channels_cache.json" % ADDON.getAddonInfo("id"))


def log(msg, level=xbmc.LOGINFO):
    xbmc.log("[%s] %s" % (ADDON.getAddonInfo("id"), msg), level)


def build_url(**params):
    return "%s?%s" % (BASE_URL, urlencode(params))


def normalize_url(url):
    """Convierte enlaces de Google Drive (compartir) en enlaces de descarga directa."""
    m = re.search(r"drive\.google\.com/file/d/([\w-]+)", url) or \
        re.search(r"drive\.google\.com/(?:open|uc)\?(?:.*&)?id=([\w-]+)", url)
    if m:
        return "https://drive.google.com/uc?export=download&id=%s" % m.group(1)
    return url


def save_cache(raw):
    try:
        xbmcvfs.mkdirs(os.path.dirname(CACHE_JSON))
        with open(CACHE_JSON, "wb") as fh:
            fh.write(raw)
    except Exception as exc:
        log("No se pudo guardar la caché: %s" % exc, xbmc.LOGWARNING)


def load_data():
    """Carga channels.json: remoto (Google Drive, etc.), caché o local como respaldo."""
    if ADDON.getSettingBool("use_remote"):
        url = normalize_url(ADDON.getSetting("remote_url").strip())
        if url:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Kodi"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    raw = resp.read()
                data = json.loads(raw.decode("utf-8-sig"))
                save_cache(raw)
                return data
            except Exception as exc:
                log("No se pudo cargar la lista remota: %s" % exc, xbmc.LOGWARNING)
                xbmcgui.Dialog().notification(
                    ADDON.getAddonInfo("name"), ADDON.getLocalizedString(30010),
                    xbmcgui.NOTIFICATION_WARNING, 4000)
                try:
                    with open(CACHE_JSON, "r", encoding="utf-8-sig") as fh:
                        return json.load(fh)
                except Exception:
                    pass
    try:
        with open(LOCAL_JSON, "r", encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception as exc:
        log("Error leyendo channels.json: %s" % exc, xbmc.LOGERROR)
        xbmcgui.Dialog().ok(ADDON.getAddonInfo("name"), ADDON.getLocalizedString(30011))
        return {"categories": []}


def make_item(label, thumb="", plot=""):
    item = xbmcgui.ListItem(label=label)
    art = {"icon": thumb or ICON, "thumb": thumb or ICON}
    if FANART:
        art["fanart"] = FANART
    item.setArt(art)
    if plot:
        item.getVideoInfoTag().setPlot(plot)
    return item


def set_url():
    """Pide la URL de la lista (p. ej. enlace de Google Drive) y la guarda en los ajustes."""
    current = ADDON.getSetting("remote_url")
    url = xbmcgui.Dialog().input("URL de channels.json (Google Drive o directa)",
                                 defaultt=current, type=xbmcgui.INPUT_ALPHANUM)
    if url is not None and url.strip():
        ADDON.setSetting("remote_url", url.strip())
        ADDON.setSettingBool("use_remote", True)
        xbmcgui.Dialog().notification(ADDON.getAddonInfo("name"), "URL guardada",
                                      xbmcgui.NOTIFICATION_INFO, 3000)
        xbmc.executebuiltin("Container.Refresh")


def list_categories():
    data = load_data()
    cfg = make_item("[COLOR yellow]Configurar URL de la lista (Google Drive)[/COLOR]")
    xbmcplugin.addDirectoryItem(HANDLE, build_url(action="set_url"), cfg, isFolder=False)
    for idx, cat in enumerate(data.get("categories", [])):
        item = make_item(cat.get("name", "?"), cat.get("thumb", ""), cat.get("plot", ""))
        url = build_url(action="category", index=idx)
        xbmcplugin.addDirectoryItem(HANDLE, url, item, isFolder=True)
    xbmcplugin.setContent(HANDLE, "videos")
    xbmcplugin.endOfDirectory(HANDLE)


def list_links(index):
    data = load_data()
    try:
        cat = data["categories"][int(index)]
    except (KeyError, IndexError, ValueError):
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    for link in cat.get("links", []):
        # Enlace web: "web": "https://..." (pagina con vídeo) o "stream": "https://...m3u8" (directo)
        web = (link.get("web") or link.get("stream") or "").strip()
        if web:
            name = link.get("name", web)
            item = make_item(name, link.get("thumb", ""), link.get("plot", ""))
            item.setProperty("IsPlayable", "true")
            url = build_url(action="play_web", url=web, name=name,
                            direct="1" if link.get("stream") else "0")
            xbmcplugin.addDirectoryItem(HANDLE, url, item, isFolder=False)
            continue
        ace_id = extract_id(link)
        if not ace_id:
            continue
        name = link.get("name", ace_id)
        item = make_item(name, link.get("thumb", ""), link.get("plot", ""))
        item.setProperty("IsPlayable", "true")
        url = build_url(action="play", id=ace_id, name=name)
        xbmcplugin.addDirectoryItem(HANDLE, url, item, isFolder=False)
    xbmcplugin.setContent(HANDLE, "videos")
    xbmcplugin.endOfDirectory(HANDLE)


def extract_id(link):
    """Acepta 'id': 'hash' o 'url': 'acestream://hash'."""
    raw = (link.get("id") or link.get("url") or "").strip()
    return raw.replace("acestream://", "").strip()


def play(ace_id, name):
    method = ADDON.getSettingInt("player_method")
    # 0 = Motor Acestream HTTP, 1 = Horus, 2 = Plexus, 3 = Android (app Ace Stream)
    if method == 0:
        host = ADDON.getSetting("engine_host").strip() or "127.0.0.1"
        port = ADDON.getSetting("engine_port").strip() or "6878"
        stream = "http://%s:%s/ace/getstream?id=%s" % (host, port, ace_id)
        item = xbmcgui.ListItem(label=name, path=stream)
        xbmcplugin.setResolvedUrl(HANDLE, True, item)
        return

    xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
    if method == 1:
        target = "plugin://script.module.horus?action=play&id=%s" % ace_id
        xbmc.executebuiltin('PlayMedia("%s")' % target)
    elif method == 2:
        target = "plugin://program.plexus/?" + urlencode(
            {"mode": "1", "url": "acestream://" + ace_id, "name": name})
        xbmc.executebuiltin('RunPlugin("%s")' % target)
    elif method == 3:
        pkg = ADDON.getSetting("android_package").strip() or "org.acestream.media"
        xbmc.executebuiltin(
            'StartAndroidActivity("%s","android.intent.action.VIEW","","acestream://%s")'
            % (pkg, ace_id))


# ----------------------------------------------------------------------------
# Reproducción de vídeos de páginas web (p. ej. 7tvandalucia.es)
# ----------------------------------------------------------------------------
WEB_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
MEDIA_RE = re.compile(r"https?://[^\s\"'<>\\()]+?\.(m3u8|mpd|mp4)(?:\?[^\s\"'<>\\()]*)?", re.I)
IFRAME_RE = re.compile(r"<iframe[^>]+?(?:data-)?src=[\"']([^\"']+)[\"']", re.I)
YOUTUBE_RE = re.compile(r"(?:youtube(?:-nocookie)?\.com/(?:embed/|watch\?v=)|youtu\.be/)([\w-]{11})")
SKIP_FRAME = ("facebook.com", "twitter.com", "doubleclick", "googletagmanager", "adservice")


def fetch_text(url, referer=None):
    headers = {"User-Agent": WEB_UA, "Accept-Language": "es-ES,es;q=0.9"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read()
    text = raw.decode("utf-8", errors="replace")
    # Des-escapa JSON/JS embebido: https:\/\/host\/a.m3u8  y  \u0026
    return (text.replace("\\/", "/").replace("\\u0026", "&").replace("\\u002F", "/")
            .replace("&amp;", "&"))


def find_media(url, depth=0, seen=None):
    """Busca m3u8/mpd/mp4 en la página y, si hace falta, dentro de sus iframes."""
    seen = seen if seen is not None else set()
    if url in seen or depth > 2:
        return []
    seen.add(url)
    try:
        text = fetch_text(url, referer=url if depth else None)
    except Exception as exc:
        log("No se pudo leer %s: %s" % (url, exc), xbmc.LOGWARNING)
        return []
    found = []
    for m in MEDIA_RE.finditer(text):
        if m.group(0) not in [f[0] for f in found]:
            found.append((m.group(0), url))
    yt = YOUTUBE_RE.search(text)
    if yt and not found:
        found.append(("plugin://plugin.video.youtube/play/?video_id=" + yt.group(1), url))
    if not found:
        for src in IFRAME_RE.findall(text):
            frame = urljoin(url, src)
            if frame.startswith("http") and not any(b in frame for b in SKIP_FRAME):
                found += find_media(frame, depth + 1, seen)
                if found:
                    break
    return found


def play_web(page_url, name, direct=False):
    if direct:
        media, referer = page_url, ""
    else:
        found = find_media(page_url)
        if not found:
            log("Sin vídeo en %s" % page_url, xbmc.LOGERROR)
            xbmcgui.Dialog().notification(ADDON.getAddonInfo("name"),
                                          "No se encontró el vídeo en la página",
                                          xbmcgui.NOTIFICATION_ERROR, 5000)
            xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
            return
        # Preferencia: m3u8 > mpd > mp4 > resto
        order = {"m3u8": 0, "mpd": 1, "mp4": 2}
        found.sort(key=lambda f: order.get(f[0].split("?")[0].rsplit(".", 1)[-1].lower(), 3))
        media, referer = found[0]
    log("Reproduciendo %s (origen %s)" % (media, referer or page_url))
    if media.startswith("plugin://"):
        path = media
    else:
        ref = referer or page_url
        origin = "/".join(ref.split("/")[:3]) + "/"
        path = "%s|User-Agent=%s&Referer=%s&Origin=%s" % (
            media, quote(WEB_UA), quote(ref, safe=""), quote(origin, safe=""))
    item = xbmcgui.ListItem(label=name, path=path)
    if ".m3u8" in media.lower():
        item.setMimeType("application/vnd.apple.mpegurl")
        item.setContentLookup(False)
    xbmcplugin.setResolvedUrl(HANDLE, True, item)


def router(paramstring):
    params = dict(parse_qsl(paramstring.lstrip("?")))
    action = params.get("action")
    if action == "category":
        list_links(params.get("index", 0))
    elif action == "set_url":
        set_url()
    elif action == "play_web":
        play_web(params.get("url", ""), params.get("name", ""), params.get("direct") == "1")
    elif action == "play":
        play(params.get("id", ""), params.get("name", ""))
    else:
        list_categories()


if __name__ == "__main__":
    router(sys.argv[2])
