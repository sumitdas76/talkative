"""Write build/version_info.txt for PyInstaller's --version-file, so
Talkative.exe carries product name, version and publisher in its Windows
file properties (Explorer -> Properties -> Details). Code signing via
SignPath Foundation requires this metadata to be set.

The version comes from talkative/__init__.py, the same single source the
About tab reads.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

with open(os.path.join(ROOT, "talkative", "__init__.py"), encoding="utf-8") as f:
    version = re.search(r'__version__\s*=\s*"([^"]+)"', f.read()).group(1)
nums = [int(n) for n in re.findall(r"\d+", version)][:4]
nums += [0] * (4 - len(nums))

text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tuple(nums)}, prodvers={tuple(nums)},
                    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Sumit Das'),
      StringStruct('FileDescription', 'Talkative - hold-to-talk dictation'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'Talkative'),
      StringStruct('LegalCopyright', 'Copyright (c) 2026 Sumit Chatterjee. MIT License.'),
      StringStruct('OriginalFilename', 'Talkative.exe'),
      StringStruct('ProductName', 'Talkative'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
out = os.path.join(ROOT, "build", "version_info.txt")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(text)
print(f"version_info.txt: {version}")
sys.exit(0)
