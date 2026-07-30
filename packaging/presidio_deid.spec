# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the NDIS Behaviour Support Plan De-identifier.

Run from the project root so relative paths resolve:

    pyinstaller packaging/presidio_deid.spec --noconfirm

Produces a one-folder ("onedir") build under dist/NDIS-Deidentifier/. Onedir
(rather than onefile) is deliberate: the spaCy en_core_web_lg model alone is
several hundred MB, and onefile would re-extract that on every launch. On
Windows, zip the dist/NDIS-Deidentifier folder for distribution. On macOS,
this same spec additionally produces dist/NDIS-Deidentifier.app (the BUNDLE
step below is a no-op on non-Darwin platforms), which can be zipped or
wrapped in a .dmg.

Needs `pip install -r requirements.txt` (which includes pyinstaller) and the
`en_core_web_lg` spaCy model downloaded first (`spacy download en_core_web_lg`).
"""
from PyInstaller.utils.hooks import collect_all

APP_NAME = "NDIS-Deidentifier"

datas = []
binaries = []
hiddenimports = []

# These packages ship non-Python resources (spaCy's model data, presidio's
# YAML recognizer configs, tkinterdnd2's bundled Tcl/Tk extension) that
# PyInstaller can't see just by following imports - collect_all pulls in
# their data files, binaries and hidden imports together.
for pkg in (
    "en_core_web_lg",
    "spacy",
    "spacy_legacy",
    "spacy_loggers",
    "presidio_analyzer",
    "presidio_anonymizer",
    "tkinterdnd2",
    "ttkbootstrap",
):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["../main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

# tldextract (a dependency of presidio's email recognizer) can leave a
# runtime-created ".suffix_cache" directory inside its own package folder,
# full of long hashed filenames (e.g. "<32-hex-chars>.tldextract.json.lock").
# If that exists on the build machine when PyInstaller runs, it gets swept
# into the bundle and blows past Windows' 260-character path limit once
# nested inside a real install path. It isn't needed - EmailRecognizer only
# calls tldextract.extract(), which works fine from the package's built-in
# offline snapshot (.tld_set_snapshot) with no cache present - so strip it.
a.datas = [d for d in a.datas if "suffix_cache" not in d[0].replace("\\", "/")]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    bundle_identifier="org.presidio-ndis.deidentifier",
    info_plist={
        "NSHighResolutionCapable": "True",
        "CFBundleShortVersionString": "1.0.0",
    },
)
