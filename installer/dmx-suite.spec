# PyInstaller spec: one folder with two programs sharing the same files
#   0.05 DMX Suite.exe  desktop app (window + tray icon), what the shortcuts open
#   dmx-suite.exe       console: Claude Desktop tools (MCP), simulator console, MIDI monitor, checks
# Build from the repo root:  pyinstaller installer/dmx-suite.spec --noconfirm
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
ICON = str(ROOT / "installer" / "icon.ico")

datas = [
    (str(ROOT / "dmx_suite" / "web" / "static"), "dmx_suite/web/static"),
    (str(ROOT / "shows"), "shows"),
]
binaries = []
hiddenimports = collect_submodules("dmx_suite") + collect_submodules("mido.backends")

# optional extras: real MIDI ports, Claude Desktop tools, desktop window and tray
for pkg in ("rtmidi", "mcp", "webview", "pystray"):
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [str(ROOT / "installer" / "launcher_app.py"), str(ROOT / "installer" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "numpy"],
    noarchive=False,
)
pyz = PYZ(a.pure)
app_exe = EXE(
    pyz,
    [s for s in a.scripts if s[0] != "launcher"],
    [],
    exclude_binaries=True,
    name="0.05 DMX Suite",
    console=False,
    icon=ICON,
    upx=False,
)
cli_exe = EXE(
    pyz,
    [s for s in a.scripts if s[0] != "launcher_app"],
    [],
    exclude_binaries=True,
    name="dmx-suite",
    console=True,
    icon=ICON,
    upx=False,
)
coll = COLLECT(app_exe, cli_exe, a.binaries, a.datas, name="dmx-suite", upx=False)
