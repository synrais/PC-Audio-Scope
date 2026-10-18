# PyInstaller recipe for both platforms:   pyinstaller packaging/pc_audio_scope.spec --noconfirm
#   Windows: dist/PC Audio Scope.exe  (one file, no console)
#   macOS:   dist/PC Audio Scope.app  (must be built on a Mac)
import os
import sys

root = os.path.dirname(SPECPATH)
mac = sys.platform == 'darwin'
icon = os.path.join(SPECPATH, 'icon.icns' if mac else 'icon.ico')

a = Analysis([os.path.join(root, 'pc_audio_scope.py')], pathex=[root])
pyz = PYZ(a.pure)

if mac:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='PC Audio Scope', console=False, icon=icon)
    coll = COLLECT(exe, a.binaries, a.datas, name='PC Audio Scope')
    app = BUNDLE(coll, name='PC Audio Scope.app', icon=icon, bundle_identifier='io.github.pc-audio-scope',
                 info_plist={'NSMicrophoneUsageDescription': 'PC Audio Scope shows and records the sound of the input you choose.',
                             'NSHighResolutionCapable': True})
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='PC Audio Scope', console=False, icon=icon, upx=False)
