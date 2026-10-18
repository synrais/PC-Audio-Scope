"""writes icon.ico and icon.icns next to this script, from the same drawing the program shows in its window and on the taskbar (draw_icon in pc_audio_scope.py):  python packaging/make_icon.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import pc_audio_scope  # noqa: E402

tile = pc_audio_scope.draw_icon(1024)
tile.save(os.path.join(HERE, 'icon.ico'), sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
tile.save(os.path.join(HERE, 'icon.icns'))
