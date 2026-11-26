# PyInstaller spec: one-folder build of dmx-suite.exe with the browser UI and starter shows.
# Build from the repo root:  pyinstaller installer/dmx-suite.spec --noconfirm
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent

datas = [
    (str(ROOT / "dmx_suite" / "web" / "static"), "dmx_suite/web/static"),
    (str(ROOT / "shows"), "shows"),
]
binaries = []
hiddenimports = collect_submodules("dmx_suite") + collect_submodules("mido.backends")

# optional extras: real MIDI ports (python-rtmidi) and Claude Desktop tools (mcp)
for pkg in ("rtmidi", "mcp"):
    try:
        d, b, h = collect_all(pkg)
    except Exception:
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [str(ROOT / "installer" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "numpy", "PIL"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="dmx-suite",
    console=True,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="dmx-suite", upx=False)
