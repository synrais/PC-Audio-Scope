# PC Audio Scope

A scope for the sound your PC is playing, or for any microphone, with a recorder, a timeline player and a tool for
comparing two recordings, or a recording against the sound that is playing right now. It started as a way to check that
two builds of the same game sound the same.

![review](docs/review.png)

## Download

The ready-made programs are in the [releases](releases) folder:

| platform | download | |
|---|---|---|
| Windows 10 / 11 | [PC-Audio-Scope.exe](releases/PC-Audio-Scope.exe?raw=true) | one file, nothing to install |
| macOS (Apple Silicon, experimental) | built by the [build workflow](https://github.com/synrais/PC-Audio-Scope/actions/workflows/build.yml) | see [macOS](#macos-experimental) below |
| any system with Python | [source code](https://github.com/synrais/PC-Audio-Scope) | see [Run from the source](#run-from-the-source) |

Put the Windows exe in its own folder, because it keeps your recordings next to itself. It is unsigned: Windows
SmartScreen may say "unknown publisher" (More info, Run anyway). The exe unpacks itself on start, so allow a few seconds before
the window appears.

## What it does

**Live view**
- oscilloscope (triggered on the left channel) and a vectorscope
- peak meters with hold, balance, stereo correlation (+1 mono, 0 wide, -1 out of phase)
- loudness in LUFS (ITU-R BS.1770 / EBU R128): short-term (3 s) and integrated (gated)
- a count of flat-topped (clipped) 10 ms blocks per channel
- spectrum, or a scrolling spectrogram (`G`), and a 30 second level history
- input: the Windows default output (follows it when you change device), any other output, or any microphone

**Record and review**
- `REC` (`F5`) records what you hear, up to 10 minutes, to `recordings/clip_<date>.wav` and opens it on the timeline
- every panel follows the playhead, so scopes, meters, loudness and the spectrogram all work on a recording
- timeline: click or drag to seek, wheel to zoom, right-drag to pan, double-click for the whole clip
- markers (`M`), an A-B selection (`I`, `O` or shift-drag) with its own loudness figures, loop (`P`), export of the selection (`E`)
- markers, selection and the Windows volume a clip was recorded at are kept in a small `.json` next to the `.wav`

**Compare two clips**
- both clips sit on a shared timeline, each with its own start position: drag a lane, type a start, nudge it (Alt+arrows),
  drop a marker on the same event in both and press *Align markers*, or press *Auto-align* (it fires once when the
  comparison opens, on the loudest part of A; press it again with a selection to align on that part)
- listen to A, B or the difference between them (`1`, `2`, `3`)
- two strips under the clips show where they match and where they differ; the report gives loudness and peak of both, how
  many windows differ, the level difference and a null test

![compare](docs/compare.png)

**Compare a clip with the live sound** (*Compare to live...*)
- play the same sound now and the live input is recorded and compared with the clip as it goes
- the white line is the running point: where in the clip the live sound is. Auto-align fires once after about 6 s of sound;
  click the timeline, drag the live lane or nudge to move it, or press *Auto-align* again
- *Stop live* saves the session as a WAV and opens it as clip B of an ordinary comparison, with the same alignment

![spectrogram](docs/spectrogram.png)

## Themes

`T` (or the *Theme* button) rolls through the colour schemes: the classic red and yellow, four single-colour phosphor
screens (green, amber, blue, red; the right channel is the paler shade) and three two-colour ones that keep the channels
easy to tell apart (orange + blue, green + magenta, red + cyan). Everything is tinted to match, including the
spectrogram, and the traces glow. The choice is remembered.

![themes](docs/themes.png)

## Run from the source

Python 3 (tested on 3.11).

```
pip install -r requirements.txt
python pc_audio_scope.py
```

or double-click `Start PC Audio Scope.bat`. If a package is missing the program says which and how to install it. The window
can be resized; everything scales with it, and the size, position and settings are remembered
(`%APPDATA%\PC Audio Scope\settings.json` on Windows).

## Keys

| key | |
|---|---|
| `F5` | record / stop |
| `Space` | play / pause (freezes the scopes when live) |
| `L` | back to live |
| `Ctrl+O` | open a clip |
| `Left` `Right` | seek 1 s (`Shift` 5 s); `Home` `End` jump to the start / end |
| `M` | add a marker; `PageUp` `PageDown` jump between markers; `Delete` removes the nearest |
| `I` `O` `X` | selection start / end / clear |
| `P` | loop the selection (or the whole clip) |
| `E` | export the selection (or the whole clip) as a WAV |
| `G` | spectrum / spectrogram |
| `T` | next theme |
| `+` `-` | scope gain; `A` auto gain |
| `C` | add back the Windows volume (see below) |
| `R` | reset peaks and loudness |
| `1` `2` `3` | listen to A / B / the difference while comparing |
| `Alt+Left` `Alt+Right` | nudge the chosen clip 10 ms (`Alt+Shift` 1 ms, `Alt+Ctrl` 100 ms) |
| `Q` `Esc` | quit |

## How the levels are measured

On the outputs this was developed with, Windows loopback capture sees the sound after the master volume, so a quiet Windows
volume makes everything read low. The scope reads the volume of the output (read only, it never changes it) and, with
*Add back Windows volume* on (the default), adds it back, so the numbers are about the level the program produced.
Recordings remember the volume they were taken at, and playback undoes the current volume the same way, so a clip plays
about as loud as it was heard, never above full scale. If your driver captures before the volume, switch the compensation
off with `C`. A muted output is shown in the status line.

The loudness figures use the BS.1770 K-weighting; a stereo 997 Hz sine at -20 dBFS reads -20.0 LUFS (see `tests/dsp.py`).

## macOS (experimental)

The macOS build is made by GitHub Actions (see below) and has not been run on a Mac by its author, so expect rough edges.
A Mac has no "what you hear" capture of its own: install a virtual audio device such as BlackHole, route the sound to it
(a Multi-Output Device in Audio MIDI Setup lets you listen at the same time) and pick it as the input; microphones work
directly. macOS asks for microphone permission the first time. There is no volume to add back, so `C` does nothing. The
build is for Apple Silicon. Recordings go to `~/Documents/PC Audio Scope/recordings`.

## Building the program yourself

```
pip install -r requirements.txt pyinstaller
pyinstaller packaging/pc_audio_scope.spec --noconfirm
```

gives `dist/PC Audio Scope.exe` on Windows and `dist/PC Audio Scope.app` on a Mac (PyInstaller builds for the system it runs
on). `PC Audio Scope.exe --check report.txt` starts it hidden for a few seconds on the real sound card and writes a one-line
report. The workflow in `.github/workflows/build.yml` does both builds on GitHub's machines: run it from the Actions tab
(build, Run workflow) and download `PC-Audio-Scope.exe` and `PC-Audio-Scope-macOS.zip` from the finished run; put them in `releases/`.
On a Mac you open the app the first time with right-click, Open (it is unsigned). The icon is drawn by `packaging/make_icon.py`.

## Layout

| | |
|---|---|
| `pc_audio_scope.py` | the whole program: the analysis (loudness, correlation, spectrogram, alignment, comparison), capture, recorder, player and window |
| `tests/` | `python tests/run.py` runs everything in about a minute, in a hidden window with a synthetic input; nothing is played |
| `packaging/` | the PyInstaller recipe and the icon |
| `releases/` | the ready-made programs |
| `docs/` | the pictures above, made by `python tests/screenshots.py` from synthetic data |
| `recordings/` | your clips (created on first use, not part of the repository) |

## Limits

- The Windows version is the one in daily use: capture uses WASAPI loopback through SoundCard and the volume is read through COM.
- Developed and tested on one Windows 11 PC, with current and slightly older NumPy / SciPy releases.

Built on [SoundCard](https://github.com/bastibe/SoundCard), [sounddevice](https://python-sounddevice.readthedocs.io), NumPy, SciPy, Pillow and comtypes.
