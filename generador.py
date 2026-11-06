#!/usr/bin/env python3
"""Generador del repositorio Kodi.

Uso:  python3 generador.py

Lee los addons de la carpeta  src/  y genera en  docs/ :
  - zips de cada addon (con su version en el nombre)
  - addons.xml y addons.xml.md5
  - index.html en cada carpeta (Kodi lo necesita para "Añadir fuente")
"""
import hashlib
import html
import os
import shutil
import xml.etree.ElementTree as ET
import zipfile

# ================== CONFIGURA ESTO ==================
GITHUB_USER = "mimse1"   # tu usuario de GitHub
REPO_NAME = "nolokodi"             # nombre del repositorio en GitHub
REPO_ID = "repository.nolokodi"     # id del addon-repositorio
REPO_VERSION = "1.0.0"              # solo sube esto si cambias la URL
# ====================================================

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "src")
OUT = os.path.join(BASE, "docs")
URL = f"https://{GITHUB_USER}.github.io/{REPO_NAME}/"
EXCLUDE = {".git", ".github", "__pycache__", ".DS_Store", ".gitignore"}

REPO_XML = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<addon id="{REPO_ID}" name="Repositorio Nolokodi" version="{REPO_VERSION}" provider-name="{GITHUB_USER}">
  <extension point="xbmc.addon.repository" name="Repositorio Nolokodi">
    <dir>
      <info compressed="false">{URL}addons.xml</info>
      <checksum>{URL}addons.xml.md5</checksum>
      <datadir zip="true">{URL}</datadir>
    </dir>
  </extension>
  <extension point="xbmc.addon.metadata">
    <summary>Repositorio de addons de {GITHUB_USER}</summary>
    <description>Repositorio para instalar y actualizar Nolokodi.</description>
    <platform>all</platform>
    <assets><icon>icon.png</icon></assets>
  </extension>
</addon>
"""


def write_index(folder):
    """index.html con enlaces: Kodi lo usa como listado de directorio."""
    items = sorted(os.listdir(folder))
    rows = []
    if os.path.abspath(folder) != os.path.abspath(OUT):
        rows.append('<a href="../">../</a>')
    for n in items:
        if n == "index.html":
            continue
        suf = "/" if os.path.isdir(os.path.join(folder, n)) else ""
        rows.append(f'<a href="{html.escape(n)}{suf}">{html.escape(n)}{suf}</a>')
    with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as f:
        f.write("<!DOCTYPE html><html><head><meta charset='utf-8'><title>Index</title></head>"
                "<body><pre>\n" + "\n".join(rows) + "\n</pre></body></html>\n")


def make_zip(addon_id, version, src_dir, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    for old in os.listdir(dest_dir):  # borra zips de versiones antiguas
        if old.endswith(".zip"):
            os.remove(os.path.join(dest_dir, old))
    zpath = os.path.join(dest_dir, f"{addon_id}-{version}.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = [d for d in dirs if d not in EXCLUDE]
            for fn in files:
                if fn in EXCLUDE:
                    continue
                full = os.path.join(root, fn)
                arc = os.path.join(addon_id, os.path.relpath(full, src_dir))
                z.write(full, arc)
    for asset in ("icon.png", "fanart.jpg", "fanart.png"):
        if os.path.exists(os.path.join(src_dir, asset)):
            shutil.copy(os.path.join(src_dir, asset), dest_dir)


def main():
    # El addon-repositorio se genera a partir de la configuracion de arriba
    repo_src = os.path.join(SRC, REPO_ID)
    os.makedirs(repo_src, exist_ok=True)
    with open(os.path.join(repo_src, "addon.xml"), "w", encoding="utf-8") as f:
        f.write(REPO_XML)
    icon = os.path.join(SRC, "plugin.video.nolokodi", "icon.png")
    if os.path.exists(icon):
        shutil.copy(icon, os.path.join(repo_src, "icon.png"))

    os.makedirs(OUT, exist_ok=True)
    entries = []
    for name in sorted(os.listdir(SRC)):
        d = os.path.join(SRC, name)
        xml_path = os.path.join(d, "addon.xml")
        if not os.path.isfile(xml_path):
            continue
        root = ET.parse(xml_path).getroot()
        addon_id, version = root.get("id"), root.get("version")
        make_zip(addon_id, version, d, os.path.join(OUT, addon_id))
        write_index(os.path.join(OUT, addon_id))
        with open(xml_path, encoding="utf-8") as f:
            txt = f.read().strip()
        entries.append("\n".join(l for l in txt.splitlines() if not l.startswith("<?xml")))
        print(f"OK  {addon_id} {version}")

    addons = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<addons>\n' \
        + "\n".join(entries) + "\n</addons>\n"
    with open(os.path.join(OUT, "addons.xml"), "w", encoding="utf-8") as f:
        f.write(addons)
    with open(os.path.join(OUT, "addons.xml.md5"), "w") as f:
        f.write(hashlib.md5(addons.encode("utf-8")).hexdigest())
    # Pages: evita que Jekyll procese los archivos
    open(os.path.join(OUT, ".nojekyll"), "w").close()
    write_index(OUT)
    print("Listo. Sube los cambios a GitHub (git add . / commit / push).")


if __name__ == "__main__":
    main()
