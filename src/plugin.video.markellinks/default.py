# -*- coding: utf-8 -*-
"""
plugin.video.markellinks
Recopila los enlaces AceStream de markellinks.app y los reproduce con Horus.

Fuentes (en orden de preferencia):
  1. /assets/links.json + /assets/provider-order.json  (fuente oficial de la web)
  2. https://listam3u.markellinks.app/lista.m3u        (lista M3U oficial)
  3. HTML de la portada                                (ultimo respaldo)

Reproduccion: por defecto la URL de Horus se pone como ruta del item, en un
unico salto, para evitar la doble resolucion que reinicia el motor.
"""

import gzip
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import zlib

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

try:
    import requests
    HAVE_REQUESTS = True
except ImportError:
    HAVE_REQUESTS = False

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
ADDON_NAME = ADDON.getAddonInfo('name')

BASE = 'https://www.markellinks.app/'
LINKS_URL = BASE + 'assets/links.json'
ORDER_URL = BASE + 'assets/provider-order.json'
M3U_URL = 'https://listam3u.markellinks.app/lista.m3u'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')

HANDLE = int(sys.argv[1]) if len(sys.argv) > 1 else -1
ARGS = sys.argv[2][1:] if len(sys.argv) > 2 else ''
PARAMS = dict(urllib.parse.parse_qsl(ARGS))

HASH_RE = re.compile(r'[0-9a-fA-F]{40}\Z')
OPT_SUFFIX_RE = re.compile(r'\s*\(\s*OPCI[OÓ]N\s*\d+\s*\)\s*$', re.I)


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #
def build_url(**kwargs):
    return sys.argv[0] + '?' + urllib.parse.urlencode(kwargs)


def log(msg, level=xbmc.LOGINFO):
    xbmc.log('[%s] %s' % (ADDON_ID, msg), level)


def s_int(key, default=0):
    try:
        return int(ADDON.getSetting(key) or default)
    except (TypeError, ValueError):
        return default


def s_bool(key, default=False):
    value = ADDON.getSetting(key)
    if value == '':
        return default
    return value.lower() == 'true'


def notify(msg, icon=xbmcgui.NOTIFICATION_INFO):
    xbmcgui.Dialog().notification(ADDON_NAME, msg, icon, 4000)


def clean_hash(link):
    h = link.split('://', 1)[-1].strip()
    return h.split('&')[0].split('/')[0].split('?')[0]


def strip_tags(text):
    text = re.sub(r'<[^>]+>', '', text)
    text = text.replace('&amp;', '&').replace('&#39;', "'").replace('&quot;', '"')
    return re.sub(r'\s+', ' ', text).strip()


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def http_get(url, timeout=25):
    """Devuelve (texto, status, bytes). Lanza en error de red."""
    headers = {
        'User-Agent': UA,
        'Accept': 'application/json,text/plain,text/html,*/*;q=0.8',
        'Accept-Language': 'es-ES,es;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'Referer': BASE,
        'Cache-Control': 'no-cache',
    }
    if HAVE_REQUESTS:
        resp = requests.get(url, headers=headers, timeout=timeout)
        raw = resp.content
        status = resp.status_code
        encoding = (resp.headers.get('Content-Encoding') or '').lower()
    else:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            status = resp.getcode()
            encoding = (resp.headers.get('Content-Encoding') or '').lower()
    if 'gzip' in encoding:
        raw = gzip.decompress(raw)
    elif 'deflate' in encoding:
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
    return raw.decode('utf-8', 'replace'), status, len(raw)


def get_json(url):
    text, status, size = http_get(url + '?_t=%d' % int(time.time()))
    log('GET %s -> %s (%d bytes)' % (url, status, size))
    if status >= 400:
        raise ValueError('HTTP %s en %s' % (status, url))
    data = json.loads(text)
    if isinstance(data, dict):
        data = data.get('links') or data.get('items') or data.get('data') or []
    if not isinstance(data, list):
        raise ValueError('JSON con formato inesperado')
    return data, size


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #
def cache_file():
    folder = xbmcvfs.translatePath('special://profile/addon_data/%s/' % ADDON_ID)
    if not xbmcvfs.exists(folder):
        xbmcvfs.mkdirs(folder)
    return folder + 'lista.json'


def load_cache():
    path = cache_file()
    if not xbmcvfs.exists(path):
        return None
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if time.time() - data.get('ts', 0) > s_int('cache_minutes', 10) * 60:
        return None
    return data


def save_cache(payload):
    try:
        with open(cache_file(), 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, ensure_ascii=False)
    except OSError as exc:
        log('No se pudo guardar cache: %s' % exc)


# --------------------------------------------------------------------------- #
# Construccion de la lista
# --------------------------------------------------------------------------- #
def match_provider(tags, order):
    for prov in order:
        pattern = prov.get('pattern') or ''
        if pattern == '__never_match__':
            continue
        try:
            if re.search(pattern, tags, re.I):
                return prov['name']
        except re.error:
            continue
    for prov in order:
        if prov.get('pattern') == '__never_match__':
            return prov['name']
    return 'Otros'


def build_from_entries(entries, order):
    """Agrupa por tags -> canal, y asigna cada canal a su proveedor."""
    channels = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        url = (entry.get('url') or '').strip()
        if not url.startswith('acestream://'):
            continue
        tags = (entry.get('tags') or '').strip().lower()
        title = strip_tags(entry.get('title') or '')
        if not title:
            continue
        key = tags or title.lower()
        name = OPT_SUFFIX_RE.sub('', title).strip() or title
        channel = channels.get(key)
        if channel is None:
            channel = channels[key] = {
                'name': name,
                'logo': entry.get('img') or '',
                'provider': match_provider(tags or name.lower(), order),
                'links': [],
            }
        if url not in channel['links']:
            channel['links'].append(url)

    providers = {}
    for channel in channels.values():
        providers.setdefault(channel.pop('provider'), []).append(channel)

    ordered = []
    for prov in order:
        name = prov.get('name')
        if name and providers.get(name):
            ordered.append({'name': name, 'channels': providers.pop(name)})
    for name, chans in sorted(providers.items()):
        ordered.append({'name': name, 'channels': chans})
    return ordered


def parse_m3u(text):
    entries = []
    pending = ''
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('#EXTINF'):
            pending = line.split(',', 1)[-1].strip()
        elif line.startswith('acestream://'):
            name = OPT_SUFFIX_RE.sub('', pending).strip() or 'Canal'
            entries.append({'title': pending or name, 'url': line,
                            'tags': name.lower(), 'img': ''})
            pending = ''
    return entries


def parse_html(html):
    entries = []
    marks = [m.start() for m in re.finditer(r'class="provider-section[^"]*"', html)]
    for pos, start in enumerate(marks):
        end = marks[pos + 1] if pos + 1 < len(marks) else len(html)
        block = html[start:end]
        ch_marks = [m.start() for m in re.finditer(r'class="channel-card"', block)]
        for c_pos, c_start in enumerate(ch_marks):
            c_end = ch_marks[c_pos + 1] if c_pos + 1 < len(ch_marks) else len(block)
            card = block[c_start:c_end]
            name_match = re.search(r'<h5[^>]*channel-name[^>]*>(.*?)</h5>', card, re.S | re.I)
            if not name_match:
                continue
            name = strip_tags(name_match.group(1))
            logo_match = re.search(r'<img[^>]*channel-logo[^>]*>', card, re.I)
            logo = ''
            if logo_match:
                src = re.search(r'src="([^"]+)"', logo_match.group(0), re.I)
                logo = src.group(1) if src else ''
            for url in re.findall(r'href="(acestream://[^"]+)"', card, re.I):
                entries.append({'title': name, 'url': url.replace('&amp;', '&'),
                                'tags': name.lower(), 'img': logo})
    return entries


def fetch_all():
    """Devuelve (providers, fuente, detalle) usando la primera fuente que sirva."""
    detail = []
    order = []

    try:
        order_data, size = get_json(ORDER_URL)
        order = [p for p in order_data if isinstance(p, dict) and p.get('name')]
        detail.append('provider-order.json: %d categorias, %d bytes' % (len(order), size))
    except Exception as exc:  # noqa: BLE001
        detail.append('provider-order.json FALLO: %s' % exc)
        log('order fallo: %s' % exc, xbmc.LOGWARNING)

    try:
        entries, size = get_json(LINKS_URL)
        detail.append('links.json: %d entradas, %d bytes' % (len(entries), size))
        providers = build_from_entries(entries, order)
        if providers:
            return providers, 'links.json', detail
        detail.append('links.json sin canales utilizables')
    except Exception as exc:  # noqa: BLE001
        detail.append('links.json FALLO: %s' % exc)
        log('links fallo: %s' % exc, xbmc.LOGWARNING)

    try:
        text, status, size = http_get(M3U_URL)
        detail.append('lista.m3u: HTTP %s, %d bytes' % (status, size))
        entries = parse_m3u(text)
        detail.append('lista.m3u: %d entradas' % len(entries))
        providers = build_from_entries(entries, order)
        if providers:
            return providers, 'lista.m3u', detail
    except Exception as exc:  # noqa: BLE001
        detail.append('lista.m3u FALLO: %s' % exc)

    try:
        html, status, size = http_get(BASE)
        detail.append('HTML: HTTP %s, %d bytes' % (status, size))
        entries = parse_html(html)
        detail.append('HTML: %d enlaces' % len(entries))
        providers = build_from_entries(entries, order)
        if providers:
            return providers, 'html', detail
    except Exception as exc:  # noqa: BLE001
        detail.append('HTML FALLO: %s' % exc)

    return [], 'ninguna', detail


def get_data(force=False):
    if not force:
        cached = load_cache()
        if cached and cached.get('providers'):
            return cached
    providers, source, detail = fetch_all()
    if providers:
        payload = {'ts': time.time(), 'source': source,
                   'detail': detail, 'providers': providers}
        save_cache(payload)
        log('Fuente usada: %s' % source)
        return payload
    cached = load_cache()
    if cached and cached.get('providers'):
        notify('No se pudo actualizar. Usando lista guardada.',
               xbmcgui.NOTIFICATION_WARNING)
        return cached
    notify('No se pudo obtener la lista', xbmcgui.NOTIFICATION_ERROR)
    return {'ts': time.time(), 'source': 'ninguna', 'detail': detail, 'providers': []}


# --------------------------------------------------------------------------- #
# Reproduccion
# --------------------------------------------------------------------------- #
def horus_module():
    return (ADDON.getSetting('horus_module') or 'script.module.horus').strip()


def horus_installed():
    return xbmc.getCondVisibility('System.HasAddon(%s)' % horus_module())


def horus_url(link):
    """Misma URL que usa plugin.video.nolokodi para abrir Horus."""
    return 'plugin://%s?action=play&id=%s' % (horus_module(), clean_hash(link))


# --------------------------------------------------------------------------- #
# Vistas
# --------------------------------------------------------------------------- #
def set_info(li, title=None, plot=None):
    tag = li.getVideoInfoTag()
    if title:
        tag.setTitle(title)
    if plot:
        tag.setPlot(plot)


def add_folder(label, url, icon='', info=None):
    li = xbmcgui.ListItem(label=label, offscreen=True)
    if icon:
        li.setArt({'icon': icon, 'thumb': icon})
    if info:
        set_info(li, plot=info.get('plot'))
    xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=True)


def index():
    data = get_data()
    providers = data['providers']
    total_ch = sum(len(p['channels']) for p in providers)
    total_ln = sum(len(c['links']) for p in providers for c in p['channels'])

    stamp = time.strftime('%d/%m %H:%M', time.localtime(data.get('ts', time.time())))
    header = ('[COLOR grey]%d canales / %d enlaces - %s - %s[/COLOR]'
              % (total_ch, total_ln, data.get('source', '?'), stamp))
    add_folder(header, build_url(mode='diag'), 'DefaultAddonProgram.png')

    add_folder('[B][COLOR orange]Buscar canal[/COLOR][/B]',
               build_url(mode='search'), 'DefaultAddonSearch.png')
    add_folder('[B][COLOR lime]Rescanear web[/COLOR][/B]',
               build_url(mode='refresh'), 'DefaultAddonService.png')

    if not providers:
        add_folder('[COLOR red]Sin datos. Abre Diagnostico.[/COLOR]',
                   build_url(mode='diag'), 'DefaultAddonWarning.png')

    for i, prov in enumerate(providers):
        add_folder('%s [COLOR grey](%d)[/COLOR]' % (prov['name'], len(prov['channels'])),
                   build_url(mode='provider', i=i),
                   info={'plot': '%d canales' % len(prov['channels'])})

    xbmcplugin.setContent(HANDLE, 'files')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


def show_provider(index_i):
    providers = get_data()['providers']
    if index_i < 0 or index_i >= len(providers):
        notify('Proveedor no encontrado', xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    prov = providers[index_i]
    for c, channel in enumerate(prov['channels']):
        add_folder('%s [COLOR grey](%d opciones)[/COLOR]'
                   % (channel['name'], len(channel['links'])),
                   build_url(mode='channel', i=index_i, c=c),
                   channel['logo'],
                   info={'plot': '%s - %d enlaces' % (channel['name'], len(channel['links']))})

    xbmcplugin.setContent(HANDLE, 'files')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


def show_channel(index_i, channel_i):
    providers = get_data()['providers']
    try:
        channel = providers[index_i]['channels'][channel_i]
    except (IndexError, KeyError):
        notify('Canal no encontrado', xbmcgui.NOTIFICATION_ERROR)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    limit = s_int('max_options', 0)
    links = channel['links'][:limit] if limit > 0 else channel['links']
    show_hash = s_bool('show_hash', False)

    for n, link in enumerate(links, 1):
        label = 'Opcion %d' % n
        if show_hash:
            label += ' [COLOR grey]%s[/COLOR]' % clean_hash(link)[:8]

        url = build_url(mode='play', link=link, title=channel['name'])
        li = xbmcgui.ListItem(label=label, offscreen=True)
        li.setArt({'icon': channel['logo'], 'thumb': channel['logo']})
        set_info(li, title='%s - %s' % (channel['name'], label), plot=link)
        if s_bool('nolo_style', False):
            # Igual que nolokodi: reproducible + setResolvedUrl(False) + PlayMedia
            li.setProperty('IsPlayable', 'true')
            xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=False)
        else:
            # Elemento-accion: Kodi no espera resolver nada, asi que no hay
            # reintentos ni salto al siguiente elemento de la lista.
            xbmcplugin.addDirectoryItem(HANDLE, url, li, isFolder=True)

    xbmcplugin.setContent(HANDLE, 'files')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)

def search():
    kb = xbmc.Keyboard('', 'Buscar canal')
    kb.doModal()
    if not kb.isConfirmed() or not kb.getText().strip():
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    term = kb.getText().strip().lower()

    hits = 0
    for i, prov in enumerate(get_data()['providers']):
        for c, channel in enumerate(prov['channels']):
            if term in channel['name'].lower():
                hits += 1
                add_folder('%s [COLOR grey](%s)[/COLOR]' % (channel['name'], prov['name']),
                           build_url(mode='channel', i=i, c=c), channel['logo'])
    if not hits:
        notify('Sin resultados para "%s"' % term, xbmcgui.NOTIFICATION_WARNING)
    xbmcplugin.setContent(HANDLE, 'files')
    xbmcplugin.endOfDirectory(HANDLE, cacheToDisc=False)


def diag():
    data = get_data()
    lines = [
        'Fuente usada: %s' % data.get('source', '?'),
        'Canales: %d' % sum(len(p['channels']) for p in data['providers']),
        'Enlaces: %d' % sum(len(c['links']) for p in data['providers'] for c in p['channels']),
        'Horus instalado: %s' % xbmc.getCondVisibility('System.HasAddon(script.module.horus)'),
        'URL Horus de ejemplo: plugin://%s?action=play&id=<hash>' % horus_module(),
        'requests disponible: %s' % HAVE_REQUESTS,
        '',
        'Trazas:',
    ]
    lines += data.get('detail', []) or ['(sin trazas)']
    lines += ['', 'Ruta de cache:', cache_file()]
    xbmcgui.Dialog().textviewer('Diagnostico Markel Links', '\n'.join(lines))
    xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def finish_without_resolving():
    """Cierra la llamada sin resolver nada, segun como la haya abierto Kodi."""
    if HANDLE < 0:
        return
    if s_bool('nolo_style', False):
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
    else:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False, cacheToDisc=False)


def play(link, title):
    title = title or 'Markel Links'
    ace_id = clean_hash(link)

    # Seguro anti-bucle: si Kodi reintenta, no se vuelve a abrir Horus.
    win = xbmcgui.Window(10000)
    try:
        last = float(win.getProperty('markellinks.last_play') or 0)
    except ValueError:
        last = 0
    if time.time() - last < 6:
        log('Llamada repetida ignorada (%s)' % ace_id, xbmc.LOGINFO)
        finish_without_resolving()
        return
    win.setProperty('markellinks.last_play', str(time.time()))

    if horus_installed():
        target = horus_url(link)
        log('play(): handle=%s -> PlayMedia %s' % (HANDLE, target), xbmc.LOGINFO)
        finish_without_resolving()
        xbmc.executebuiltin('PlayMedia("%s")' % target)
        return

    log('Horus no instalado (%s)' % horus_module(), xbmc.LOGWARNING)
    if s_bool('direct_fallback', True) and HANDLE >= 0 and s_bool('nolo_style', False):
        xbmcplugin.setResolvedUrl(HANDLE, True,
                                  xbmcgui.ListItem(label=title, path='acestream://' + ace_id))
        return
    notify('Instala Horus para reproducir', xbmcgui.NOTIFICATION_ERROR)
    finish_without_resolving()


def refresh():
    data = get_data(force=True)
    notify('Rescaneado: %d canales (%s)'
           % (sum(len(p['channels']) for p in data['providers']), data.get('source', '?')))
    xbmc.executebuiltin('Container.Refresh')


# --------------------------------------------------------------------------- #
# Router
# --------------------------------------------------------------------------- #
def run():
    mode = PARAMS.get('mode', '')
    if mode == 'provider':
        show_provider(int(PARAMS.get('i', -1)))
    elif mode == 'channel':
        show_channel(int(PARAMS.get('i', -1)), int(PARAMS.get('c', -1)))
    elif mode == 'search':
        search()
    elif mode == 'refresh':
        refresh()
    elif mode == 'diag':
        diag()
    elif mode == 'play':
        play(PARAMS.get('link', ''), PARAMS.get('title', ''))
    else:
        index()


if __name__ == '__main__':
    run()