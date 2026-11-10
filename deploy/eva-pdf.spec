from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH).parent
datas = []
binaries = []
hiddenimports = [
    "worker", "server", "performance", "advanced_tools", "extended_tools",
    "acrobat_tools", "scan_editor", "export_names", "office_export",
] + collect_submodules("engines")
for package in (
    "flask", "waitress", "pymupdf", "PIL", "docx", "openpyxl", "pptx",
    "pikepdf", "cv2", "pillow_heif", "pyhanko", "pyhanko_certvalidator",
    "cryptography", "lxml", "requests",
    "ctranslate2", "sentencepiece", "subword_nmt", "sacremoses",
):
    package_datas, package_binaries, package_imports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_imports
for folder in ("templates", "static"):
    datas += [(str(root / folder / "*"), folder)]
if (root / "static" / "modules").is_dir():
    datas += [(str(root / "static" / "modules" / "*"), "static/modules")]
if (root / "addons").is_dir():
    datas += [(str(root / "addons"), "addons")]
for language in ("spa", "eng"):
    datas.append((str(root / "models" / f"{language}.traineddata"), "models"))
for path in (
    "config/site_config.example.json", "desktop/EVA-Desktop.ps1",
    "README.md", "CHANGELOG.md", "requirements.txt", "docs",
):
    source = root / path
    datas.append((str(source), str(Path(path).parent) if source.is_file() else path))

a = Analysis(
    [str(root / "deploy" / "frozen_entry.py")],
    pathex=[str(root)], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
    excludes=["pytest", "unittest", "tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="EVA-PDF",
    debug=False, strip=False, upx=False, console=True, contents_directory=".",
    icon=str(root / "static" / "eva.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="EVA-PDF")
