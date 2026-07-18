# PyInstaller spec for the Tauri sidecar build of the core.
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
datas = [("../src/traduko/dubbing/runner.py", "traduko/dubbing")]
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
    a.binaries,
    a.datas,
    [],
    name="traduko-core",
    console=True,
    upx=False,
)
