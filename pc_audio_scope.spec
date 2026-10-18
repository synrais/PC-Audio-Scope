# PyInstaller recipe for both platforms:   pyinstaller packaging/pc_audio_scope.spec --noconfirm
#   Windows: dist/PC Audio Scope.exe  (one file, no console)
#   macOS:   dist/PC Audio Scope.app  (must be built on a Mac)
import os
import sys

root = os.path.dirname(SPECPATH)
mac = sys.platform == 'darwin'
icon = os.path.join(SPECPATH, 'icon.icns' if mac else 'icon.ico')

# nothing the program does needs these; leaving them out keeps the exe small
excludes = ['scipy', 'ssl', '_ssl', 'unittest', 'pydoc', 'doctest', 'test', 'tkinter.test', 'distutils', 'setuptools', 'pkg_resources', 'lib2to3',
            'numpy.testing', 'numpy.f2py', 'PIL._avif', 'PIL._webp', 'PIL._imagingcms', 'PIL._imagingft', 'PIL._imagingmorph']
a = Analysis([os.path.join(root, 'pc_audio_scope.py')], pathex=[root], excludes=excludes)
pyz = PYZ(a.pure)

if mac:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='PC Audio Scope', console=False, icon=icon)
    coll = COLLECT(exe, a.binaries, a.datas, name='PC Audio Scope')
    app = BUNDLE(coll, name='PC Audio Scope.app', icon=icon, bundle_identifier='io.github.pc-audio-scope',
                 info_plist={'NSMicrophoneUsageDescription': 'PC Audio Scope shows and records the sound of the input you choose.',
                             'NSHighResolutionCapable': True})
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='PC Audio Scope', console=False, icon=icon, upx=False)
