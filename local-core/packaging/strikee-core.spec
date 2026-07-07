# PyInstaller spec for the Strikee Vision Local Core (dashboard + config app).
# Build on the target OS:  pyinstaller packaging/strikee-core.spec
#
# NOTE: this bundles the app, the schema, and the web dashboard. It does NOT
# bundle the heavy perception stack (torch/OpenCV) — packaging torch is large
# and brittle. To run the live YOLO pipeline, run from a Python venv with the
# perception extra instead (see packaging/BUILD.md).

block_cipher = None

a = Analysis(
    ['run_desktop.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('app/schema.sql', 'app'),
        ('web', 'web'),
    ],
    hiddenimports=[
        'uvicorn.logging',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.lifespan.on',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['torch', 'cv2', 'ultralytics'],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='StrikeeCore',
    debug=False,
    strip=False,
    upx=True,
    console=False,        # windowed app
)
