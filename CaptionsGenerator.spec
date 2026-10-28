from PyInstaller.utils.hooks import collect_all

binaries = []
datas = []
hiddenimports = []
for package in ('faster_whisper', 'ctranslate2', 'onnxruntime'):
	package_datas, package_binaries, package_imports = collect_all(package)
	datas += package_datas
	binaries += package_binaries
	hiddenimports += package_imports

a = Analysis(
	['main.py'],
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
pyz = PYZ(a.pure)
exe = EXE(
	pyz,
	a.scripts,
	[],
	exclude_binaries=True,
	name='CaptionsGenerator',
	debug=False,
	strip=False,
	upx=False,
	console=True,
)
coll = COLLECT(
	exe,
	a.binaries,
	a.datas,
	strip=False,
	upx=False,
	name='CaptionsGenerator',
)
