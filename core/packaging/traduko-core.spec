# PyInstaller spec for the Tauri sidecar build of the core.
# uvicorn and websockets import their implementations dynamically, so both
# are collected wholesale. The optional `asr` extra (faster-whisper) is
# intentionally not bundled; preflight reports ASR unavailable in the
# packaged app.
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("websockets")
    + collect_submodules("traduko")
)

a = Analysis(
    ["sidecar_entry.py"],
    pathex=["../src"],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    excludes=["faster_whisper", "pytest"],
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
