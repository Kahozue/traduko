# PyInstaller spec for the Tauri sidecar build of the core.
# This is deliberately a one-folder build. A one-file build re-extracts the
# whole payload into a fresh temp directory on every launch, so macOS has to
# validate the signature of every bundled dylib again each time and the core
# takes seven seconds or more to answer /health when it is spawned by the
# desktop app. A one-folder build lives at a stable path, so that validation
# is cached after the first run and startup drops to well under a second.
# uvicorn and websockets import their implementations dynamically, so both
# are collected wholesale. faster-whisper and its native dependencies
# (ctranslate2, onnxruntime, av, tokenizers) are bundled so the packaged
# app can transcribe locally; model weights still download at runtime into
# the Hugging Face cache via the /asr endpoints.
from PyInstaller.utils.hooks import collect_all, collect_submodules

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("websockets")
    + collect_submodules("discord")
    + collect_submodules("traduko")
)

binaries = []
# The dubbing runner is executed by file path with the engine venv's
# python (never imported), so it must exist as a real file in the bundle.
# The heavy dubbing deps (voxcpm, pyannote, torch) intentionally stay out:
# they live in the managed engine venv under the data root.
datas = [
    ("../src/traduko/dubbing/runner.py", "traduko/dubbing"),
    ("../src/traduko/asr/macos_helper.swift", "traduko/asr"),
]
for package in (
    "faster_whisper",
    "ctranslate2",
    "onnxruntime",
    "av",
    "tokenizers",
    "ebooklib",
    "lxml",
    "mcp",
):
    pkg_datas, pkg_binaries, pkg_hidden = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    ["sidecar_entry.py"],
    pathex=["../src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="traduko-core",
    console=True,
    upx=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="traduko-core",
)
