# VoxHing

**Local Whisper-powered Hinglish, Hindi and English voice typing for the web.**

VoxHing adds a small floating microphone beside editable web fields. Audio is recorded by a local Windows Python service and transcribed with `faster-whisper`. In **HING** mode, Whisper uses automatic language detection plus Roman-Hinglish decoder context instead of converting Hindi Devanagari into Roman text afterward.

## Why this approach

A normal Hindi browser speech recognizer often produces Devanagari first. Transliteration afterward can create awkward spellings such as `Bengaluroo`, `Mahaadevapuraa`, or `hariyaanaa`.

VoxHing instead uses this pipeline:

```text
Microphone
   ↓
Local Whisper model
   ↓
language = auto in HING mode
   ↓
Roman-Hinglish initial prompt
   ↓
Roman Hinglish transcript directly
   ↓
insert into the active web field
```

Example targets:

```text
Aur kaise ho tum
Bengaluru
Mahadevapura
Haryana
Jammu Kashmir
123456
```

## Features

- `HING` — mixed Hindi/English with Roman-script Hinglish output
- `HI` — Hindi/Devanagari
- `EN` — Indian English
- Runs Whisper locally after the selected model has been downloaded
- Supports CPU and NVIDIA CUDA
- User-editable model and performance settings in `voxhing_config.json`
- Auto-stops after silence
- Trims silence before sending audio to Whisper
- Converts spoken digit sequences such as `one two three four` → `1234`
- Floating microphone for inputs, textareas and contenteditable fields
- React/Vue-friendly input insertion
- Keyboard-first navigation
- Prints recording and transcription timing for every request

## Keyboard controls

```text
Text field 1
    Shift
Mic 1
    Space       start / stop recording
    Left Arrow  return to Text field 1
    Shift       move to Text field 2
Text field 2
    Shift
Mic 2
```

After normal recording stops or silence is detected, focus remains on the microphone so you can press **Space** again immediately.

## Windows setup

### 1. Install Python

Install Python 3.10+ and make sure `python` works in PowerShell:

```powershell
python --version
```

### 2. Download the repository

```powershell
git clone https://github.com/vikashbhatia/VoxHing.git
cd VoxHing
```

Or download the repository as a ZIP from GitHub and extract it.

### 3. Start VoxHing

Double-click:

```text
start_voice_server.bat
```

The launcher checks the required Python packages and installs missing ones automatically.

The first time you select a Whisper model it may need to download that model.

Manual start:

```powershell
python -m pip install -r requirements.txt
python local_whisper_server.py
```

When ready you should see output similar to:

```text
[VoxHing] Loaded config: ...\voxhing_config.json
[VoxHing] Model: base
[VoxHing] Device preference: auto
[VoxHing] Beam size: 1
[VoxHing] Model ready.
[VoxHing] Local server: http://127.0.0.1:8765
```

## Tampermonkey setup

1. Install Tampermonkey in Chrome or Edge.
2. Open `voxhing.user.js` from this repository.
3. Copy it into a new Tampermonkey userscript and save.
4. Reload the target website.
5. Click/focus a text field. The floating `🎤 HING` control should appear.

The userscript talks to the local service at:

```text
http://127.0.0.1:8765
```

## Modes

Click the mode label to cycle:

```text
HING → HI → EN → HING
```

### HING

Whisper language is left unset so mixed Hindi/English speech can be auto-detected. A Roman-Hinglish `initial_prompt` nudges decoding toward Roman output.

### HI

Forces Whisper to Hindi (`hi`) and uses a Hindi prompt.

### EN

Forces Whisper to English (`en`) and uses Indian-English context.

# Configuration

All normal user settings are now in:

```text
voxhing_config.json
```

**Edit this file, save it, then restart `start_voice_server.bat`.**

The default configuration is optimized for a CPU-first setup:

```json
{
  "model": "base",
  "device": "auto",
  "cpu_compute_type": "int8",
  "cuda_compute_type": "float16",
  "cpu_threads": 0,
  "silence_seconds": 0.5,
  "silence_rms": 0.012,
  "beam_size": 1,
  "best_of": 1,
  "vad_filter": false
}
```

The real `voxhing_config.json` contains additional options and editable prompts.

## Choosing a Whisper model

Change this line in `voxhing_config.json`:

```json
"model": "base"
```

Common choices:

| Model | Relative speed | Relative accuracy | Suggested use |
|---|---|---|---|
| `tiny` | Fastest | Lowest | Very slow CPUs / quick testing |
| `base` | Very fast | Good | Recommended starting point for CPU |
| `small` | Medium | Better | Stronger CPU or when accuracy matters more |
| `medium` | Slow on CPU | Higher | Better suited to faster hardware |
| `turbo` | Excellent on suitable GPU, heavy on CPU | High | Recommended mainly with a capable NVIDIA GPU |
| `large-v3` | Heaviest | Highest class | Accuracy-first GPU use |

A newly selected model may be downloaded on first launch.

## CPU / GPU selection

```json
"device": "auto"
```

Available values:

```text
auto  -> use CUDA when available, otherwise CPU
cpu   -> always use CPU
cuda  -> require NVIDIA CUDA
```

For CPU the default compute type is:

```json
"cpu_compute_type": "int8"
```

For CUDA:

```json
"cuda_compute_type": "float16"
```

### CPU threads

```json
"cpu_threads": 0
```

`0` means VoxHing automatically uses the available CPU threads.

You can force a value such as:

```json
"cpu_threads": 6
```

if you want VoxHing to leave more CPU capacity available for other applications.

## Speed vs accuracy settings

### Beam size

```json
"beam_size": 1
```

`1` is recommended for fast voice typing.

Higher values such as `3` or `5` can improve decoding in some situations but can make CPU transcription significantly slower.

### Best-of

```json
"best_of": 1
```

Keep this at `1` for speed.

### Temperature

```json
"temperature": 0.0
```

`0.0` keeps decoding deterministic and is recommended for dictation.

### Second Whisper VAD pass

```json
"vad_filter": false
```

VoxHing already detects speech/silence during microphone recording, so the second Whisper VAD pass is disabled by default to reduce latency.

If you enable it:

```json
"vad_filter": true,
"vad_min_silence_ms": 250
```

## Silence detection

### How quickly recording stops

```json
"silence_seconds": 0.5
```

Lower value = stops faster after you finish speaking.

Example:

```json
"silence_seconds": 0.35
```

If VoxHing cuts you off during natural pauses, raise it to `0.7` or `1.0`.

### Microphone threshold

```json
"silence_rms": 0.012
```

If background noise prevents auto-stop, try raising it:

```json
"silence_rms": 0.018
```

If quiet speech is not detected, lower it:

```json
"silence_rms": 0.008
```

### No-speech timeout

```json
"no_speech_timeout": 7.0
```

This controls how long VoxHing waits when the mic was started but no speech is detected.

### Maximum recording time

```json
"max_record_seconds": 30.0
```

## Audio trimming

VoxHing trims unused silence before transcription while keeping a small safety margin around speech:

```json
"pre_roll_seconds": 0.18,
"post_roll_seconds": 0.18
```

This reduces unnecessary audio sent to Whisper without intentionally cutting the beginning/end of speech.

## Custom Hinglish vocabulary and names

You can edit the prompt directly in `voxhing_config.json`:

```json
"hinglish_prompt": "Mai Hindi aur English naturally mix karke Roman letters mein bolta hu. Bengaluru, Mahadevapura, Haryana, Jammu Kashmir."
```

Add names, hospitals, medicines, localities or other terms you regularly dictate, preferably inside short natural examples rather than a huge word list.

The file also contains:

```json
"english_prompt": "...",
"hindi_prompt": "..."
```

## Server settings

Defaults:

```json
"host": "127.0.0.1",
"port": 8765,
"token": "vikash-local-whisper-v1"
```

Keeping `host` as `127.0.0.1` means the service is only exposed locally on your PC.

If you change `port` or `token`, update the corresponding `API` / `TOKEN` values near the top of `voxhing.user.js` too.

## Environment variables

For advanced users, these environment variables are still supported and override values from `voxhing_config.json`:

| Variable | Config equivalent |
|---|---|
| `WHISPER_MODEL` | `model` |
| `VOXHING_PORT` | `port` |
| `VOXHING_TOKEN` | `token` |
| `VOXHING_SILENCE_SECONDS` | `silence_seconds` |
| `VOXHING_SILENCE_RMS` | `silence_rms` |
| `VOXHING_NO_SPEECH_TIMEOUT` | `no_speech_timeout` |
| `VOXHING_MAX_RECORD_SECONDS` | `max_record_seconds` |
| `VOXHING_CONFIG` | path to an alternate config JSON file |

## Performance testing

After every dictation VoxHing prints useful timing information:

```text
[VoxHing] Result: Aur kaise ho tum
[VoxHing] Recording: 2.31 sec
[VoxHing] Whisper audio: 1.79 sec
[VoxHing] Transcribing: 1.24 sec
[VoxHing] Detected language: hi
```

The most useful number when comparing models is:

```text
Transcribing: X.XX sec
```

This lets you test `tiny`, `base`, `small`, `turbo`, etc. on your own hardware rather than guessing which one will be fastest.

## Troubleshooting

### `ModuleNotFoundError: No module named 'sounddevice'`

Run:

```powershell
python -m pip install -r requirements.txt
```

Or run `start_voice_server.bat`, which checks and installs missing dependencies.

### Mic does not appear

- Make sure the Tampermonkey script is enabled.
- Reload the webpage after installing/updating it.
- Click inside a normal input, textarea or contenteditable field.
- Disable older voice-typing userscripts if they conflict.

### `VoxHing server is not running`

Start:

```text
start_voice_server.bat
```

### Transcription is too slow

For a CPU-only PC, try this first:

```json
"model": "base",
"beam_size": 1,
"best_of": 1,
"vad_filter": false,
"cpu_compute_type": "int8"
```

If that is still too slow, try:

```json
"model": "tiny"
```

If you have a compatible NVIDIA GPU, `small` or `turbo` may give a better speed/accuracy balance.

## Files

```text
VoxHing/
├── local_whisper_server.py   # microphone + Whisper + local API
├── voxhing_config.json       # user-editable model/performance settings
├── voxhing.user.js           # Tampermonkey browser UI
├── start_voice_server.bat    # Windows dependency check + launcher
├── requirements.txt
├── .gitignore
└── README.md
```

## Privacy

The service binds to `127.0.0.1` by default, not to your LAN. Whisper transcription itself runs locally. Downloading a model requires internet access unless that model is already cached.

## Status

Early development. The main focus is fast, accurate, natural Roman Hinglish and reliable keyboard-driven dictation on Windows.
