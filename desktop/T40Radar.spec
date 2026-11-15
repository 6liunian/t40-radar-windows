from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_dynamic_libs, copy_metadata

desktop = Path(SPECPATH)
project = desktop.parent
assets = desktop / 'assets'
datas = [(str(assets), 'assets'),
         (str(desktop / 'device_setup.ps1'), 'assets'),
         (str(project / 'native_windows' / 'firmware'), 'assets/firmware')]
datas += copy_metadata('python-can')
binaries = collect_dynamic_libs('usb1')
binaries += [(str(project / 'windows/pcan-basic-x64/x64/PCANBasic.dll'), '.')]
# venvs based on Conda do not expose Library/bin to PyInstaller's DLL resolver.
for name in ('ffi.dll', 'sqlite3.dll', 'tcl86t.dll', 'tk86t.dll'):
    dll = Path(sys.base_prefix) / 'Library/bin' / name
    if dll.exists():
        binaries.append((str(dll), '.'))
a = Analysis([str(desktop / 'app.py')],
             pathex=[str(project / 'native_windows'), str(project / 'radar_client')],
             binaries=binaries, datas=datas,
             hiddenimports=['can.interfaces.pcan.pcan', 'can.interfaces.pcan.basic'],
             excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'IPython', 'pytest', 'scipy', 'pandas'],
             hooksconfig={'matplotlib': {'backends': ['TkAgg']}}, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='T40Radar',
          icon=str(assets / 'T40Radar.ico'),
          debug=False, strip=False, upx=False, console=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='T40Radar')
