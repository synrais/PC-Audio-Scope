# PC Audio Scope

A scope for the sound your PC is playing (or any microphone), with a recorder, a timeline player and a tool that compares
two recordings, or a recording against the sound that is playing right now.

It is built so that a person and an AI can look at the same sound. Everything the scope shows is also available as text, JSON
and pictures: every channel is measured on its own, faults are found automatically and reported with a time and a channel, and
a whole recording can be summed up in one picture. It started as a way to check that two builds of the same game sound the same.

![PC Audio Scope playing music: oscilloscope, vectorscope, levels, spectrum and level history](docs/live.gif)

## Download

| platform | download |
|---|---|
| Windows 10 / 11 | [PC-Audio-Scope.exe](releases/PC-Audio-Scope.exe?raw=true): one file, nothing to install |
| macOS (Apple Silicon, experimental) | built by the [build workflow](https://github.com/synrais/PC-Audio-Scope/actions/workflows/build.yml), see [macOS](#macos-experimental) |
| any system with Python | the [source code](https://github.com/synrais/PC-Audio-Scope), see [Run from the source](#run-from-the-source) |

Put the Windows exe in its own folder, because it keeps your recordings next to itself. It is unsigned, so Windows SmartScreen
may say "unknown publisher" (More info, Run anyway), and it needs a few seconds to unpack when it starts.

## The live view

- **Oscilloscope** (triggers on the left channel, its gain follows the sound) and **vectorscope**. Both are drawn like the beam
  of a CRT: bright where it moves slowly, dim where it sweeps, with a glow and a fading afterglow. XY pictures such as
  oscilloscope music show clearly (play a lossless file for the cleanest picture).
- **Levels**: peak meters with hold, a balance bar, and figures per channel: DC offset (red above 3 %), hold, peak, session
  peak and clipped 10 ms blocks. The balance figure says which side is louder: `L 2.0 dB` is left louder, `R 2.0 dB` right.
- **Spectrum** (with the ranges an equaliser uses named along its bottom) or a scrolling spectrogram (`G`), and a 30 second
  **level history**. The spectrum and the history share one dB scale (0 down to -80).
- **Double-click** a window to make it fill the program (nothing else on screen, the keys still work); double-click again to
  go back. An enlarged window is drawn at its own size and gets more light, so its lines stay as bright as in the normal view.
- **Right-click** a window for its menu: grid and info on or off (the full screen view has its own two), its own colours,
  and three rows with an arrow either side (click the arrows, hold one to run, scroll over the row, or use Left / Right):
  - **Phosphor** (0 to 3.0): the glow close to the line. 0 is clean lines with no phosphor effects at all.
  - **Glow** (0 to 3.0): a broad, faint haze round bright things, like light scattered in the glass of a monitor.
  - **Line strength** (1 to 10): raises the weak end of the beam so faint and fast strokes look solid.

  Your choices are remembered. A first run starts on the **Orange + blue** theme.
- **Input**: the Windows default output (it follows the default when you change it), any other output, or any microphone.

### Scope rate

The program works at 48 kHz, so anything a sound draws above 24 kHz is lost. Oscilloscope music is made for a scope with no
such limit (the circles of Jerobeam Fenderson's 192 kHz files shrink to a hot spot at 48 kHz). **Scope rate** (right-click the
oscilloscope or vectorscope: Auto, 48, 96 or 192 kHz) makes the capture read at the higher rate and both scopes draw from it;
the vectorscope also interpolates between the samples, so a circle of only six samples a turn comes out round. The meters,
spectrum, history and recordings still get a 48 kHz copy.

Windows has to deliver that rate: set the output's format to 24 bit, 192000 Hz (Sound settings, the output device, Advanced)
and play the file in a player that does not lower it. **Auto** (the default) follows the rate Windows mixes the output at,
checked every second. The status line shows `Sample rate 192k`, and `(Scope rate 96k)` after it if you chose another rate.
Higher rates cost more processor time.

### Frame rate

Automatic, from 30 to 60 frames a second. Once a second the program looks at how busy the window is and aims to keep it about
70 % busy, so a computer with room runs at 60 and a slower one settles lower, never jumping. The graphs are drawn on threads
of their own, and a graph that falls behind skips frames instead of lagging.

## Record and review

- `REC` (`F5`) records what you hear, up to 10 minutes, to `recordings/clip_<date>.wav` and opens it on the timeline.
- Every panel follows the playhead, so scopes, meters, loudness and the spectrogram all work on a recording.
- The timeline is collapsed until you record, open a clip or compare. Click or drag to seek, wheel to zoom, right-drag to pan,
  double-click for the whole clip.
- Markers (`M`), an A-B selection (`I`, `O` or shift-drag) with its own loudness figures, loop (`P`), export of the selection (`E`).
  Markers, selection and the Windows volume a clip was recorded at are kept in a small `.json` next to the `.wav`.

![review](docs/review.png)

## Compare two clips

- Both clips sit on a shared timeline, each with its own start. Drag a lane, type a start, nudge it (`Alt`+arrows), drop a
  marker on the same event in both and press *Align markers*, or press *Auto-align* (it fires once when the comparison opens,
  on the loudest part of A; press it again with a selection to align on that part).
- Listen to A, B or the difference (`1`, `2`, `3`).
- Two strips show where the clips match and where they differ. The report gives loudness and peak of both, how many windows
  differ, the level difference and a null test.

![compare](docs/compare.png)

**Compare a clip with the live sound** (*Compare to live...*): play the same sound now and the live input is recorded and
compared with the clip as it goes. The white line is where in the clip the live sound is. Auto-align fires after about 6 s of
sound; click the timeline, drag the live lane or nudge to move it. *Stop live* saves the session as a WAV and opens it as clip B.

![spectrogram](docs/spectrogram.png)

## Finding problems

`F` (or the *Find problems* button) looks through the open clip, **each channel on its own**, and marks what it finds on the
timeline (the markers start with `!`). For a saved clip it also writes a report, a JSON file and a picture next to the WAV
(`clip.analysis.txt`, `.json`, `.png`). It looks for:

- a channel that **blasts** far above its own level while the other one does not
- **DC offset**: steps, and long stretches where a channel sits off centre
- **dropouts**: digital silence in the middle of sound, or one channel silent while the other plays
- a **stuck output**, **clicks and pops**, **clipping**, and passages that are **out of phase**

![analysis](docs/analysis.png)

The same from the command line, with no window:

```
python pc_audio_scope.py --analyze clip.wav
python pc_audio_scope.py --analyze reference.wav clip.wav
```

With two files it also writes a segment-by-segment comparison: where each stretch of the first recording sits in the second,
how alike they are, the level and DC difference of each channel, and a verdict. The functions (`find_problems`, `compare_clips`,
`findings_image`) are in `pc_audio_scope.py` if you want to call them from your own code.

## Themes

`T` (or the *Theme* button) rolls through the colour schemes: classic yellow and red, four single-colour phosphor screens
(green, amber, blue, red; the left channel is the paler shade) and three two-colour ones (blue + orange, green + magenta,
cyan + red). Everything is tinted to match. The choice is remembered.

![themes](docs/themes.png)

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
| `F` | find problems in the open clip |
| `E` | export the selection (or the whole clip) as a WAV |
| `G` | spectrum / spectrogram |
| `T` | next theme |
| `U` | switch the undoing of a system equaliser on or off (see below) |
| `R` | reset the peaks (session peak, held peaks, clipped-block counts) |
| `1` `2` `3` | listen to A / B / the difference while comparing |
| `Alt+Left` `Alt+Right` | nudge the chosen clip 10 ms (`Alt+Shift` 1 ms, `Alt+Ctrl` 100 ms) |
| `Q` `Esc` | quit |

## Levels and the Windows volume

On the outputs this was developed with, Windows loopback capture sees the sound after the master volume, so a quiet Windows
volume makes everything read low. The scope shows the levels as measured (it reads the volume only to show it and never
changes it). Recordings remember the volume they were taken at, and playback undoes the current volume, so a clip plays about
as loud as it was heard, never above full scale. The loudness figures use BS.1770 K-weighting: a stereo 997 Hz sine at
-20 dBFS reads -20.0 LUFS.

**System equalisers.** Windows loopback records the sound *after* the audio engine's effects, so an equaliser such as
[Equalizer APO](https://sourceforge.net/projects/equalizerapo/) (a headphone correction curve, say) is in what the scope hears,
and its phase shifts bend oscilloscope music. The scope reads the Equalizer APO configuration of the output it captures and,
when it is all peaking or shelf filters and a preamp, undoes it with the exact inverse; the status line then says *Equalizer
APO undone*. If the configuration holds anything else (a low-pass, a plugin, a convolution) nothing is undone and the status
line says so. `U` switches it off, to hear the sound as the headphones get it.

## Run from the source

Python 3 (tested on 3.11).

```
pip install -r requirements.txt
python pc_audio_scope.py
```

or double-click `Start PC Audio Scope.bat`. If a package is missing the program says which. The window can be resized and
everything scales with it. Size, position and settings are remembered (`%APPDATA%\PC Audio Scope\settings.json` on Windows).

## macOS (experimental)

The macOS build is made by GitHub Actions and has not been run on a Mac by its author, so expect rough edges. A Mac has no
"what you hear" capture of its own: install a virtual audio device such as BlackHole, route the sound to it (a Multi-Output
Device in Audio MIDI Setup lets you listen at the same time) and pick it as the input. Microphones work directly. macOS asks
for microphone permission the first time. The build is for Apple Silicon and is unsigned (open it the first time with
right-click, Open). Recordings go to `~/Documents/PC Audio Scope/recordings`.

## Building the program yourself

```
pip install -r requirements.txt pyinstaller
pyinstaller packaging/pc_audio_scope.spec --noconfirm
```

This gives `dist/PC Audio Scope.exe` on Windows and `dist/PC Audio Scope.app` on a Mac. `PC Audio Scope.exe --check report.txt`
starts it hidden for a few seconds on the real sound card and writes a one-line report. The workflow in
`.github/workflows/build.yml` does both builds on GitHub's machines (Actions tab, Run workflow); put the downloads in
`releases/`. The icon is drawn by `packaging/make_icon.py`.

## Layout

| | |
|---|---|
| `pc_audio_scope.py` | the whole program: analysis, capture, recorder, player and window |
| `tests/` | `python tests/run.py` runs everything in about a minute, in a hidden window with a synthetic input; nothing is played |
| `packaging/` | the PyInstaller recipe and the icon |
| `releases/` | the ready-made programs |
| `docs/` | the pictures above (`live.gif` is a real capture; the others come from `python tests/screenshots.py` with synthetic data) |
| `recordings/` | your clips (created on first use, not part of the repository) |

## Limits

- The Windows version is the one in daily use: capture uses WASAPI loopback through SoundCard and the volume is read through COM.
- Developed and tested on one Windows 11 PC, with current and slightly older NumPy releases.

Built on [SoundCard](https://github.com/bastibe/SoundCard), [sounddevice](https://python-sounddevice.readthedocs.io), NumPy, Pillow and comtypes.
