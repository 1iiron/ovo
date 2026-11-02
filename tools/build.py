"""Builds the shareable app: dist/Ovo.exe (one file, no console window) and dist/Ovo-<version>-windows.zip.
Needs PyInstaller: python tools/build.py"""
import hashlib
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD, DIST = ROOT / 'build', ROOT / 'dist'
version = re.search(r"^VERSION = '([^']+)'", (ROOT / 'ovo.pyw').read_text(), re.M).group(1)
numbers = (list(map(int, version.split('.'))) + [0, 0, 0])[:4]  # the exe's version resource wants four numbers

# What Windows shows under the exe's Properties > Details.
BUILD.mkdir(exist_ok=True)
(BUILD / 'version_info.txt').write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple(numbers)}, prodvers={tuple(numbers)}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[StringFileInfo([StringTable('040904B0', [
      StringStruct('FileDescription', 'Ovo: Claude and Codex usage, at a glance'),
      StringStruct('FileVersion', '{version}'), StringStruct('InternalName', 'Ovo'),
      StringStruct('OriginalFilename', 'Ovo.exe'), StringStruct('ProductName', 'Ovo'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])])
""")

subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
                '--name', 'Ovo', '--icon', str(ROOT / 'assets' / 'ovo.ico'),
                '--version-file', str(BUILD / 'version_info.txt'),
                '--add-data', f"{ROOT / 'assets'};assets",
                '--distpath', str(DIST), '--workpath', str(BUILD), '--specpath', str(BUILD),
                str(ROOT / 'ovo.pyw')], check=True)

archive = DIST / f'Ovo-{version}-windows.zip'
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
    z.write(DIST / 'Ovo.exe', 'Ovo.exe')
    z.write(ROOT / 'README.md', 'README.md')
# The update check in Ovo downloads this next to the zip and refuses the zip if the two don't match.
checksum = archive.with_name(archive.name + '.sha256')
checksum.write_text(f'{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n')
print('built', DIST / 'Ovo.exe', archive, 'and', checksum)
