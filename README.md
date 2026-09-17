# VoxHing

**Local Whisper-powered Hinglish, Hindi and English voice typing for the web.**

VoxHing adds a small floating microphone beside editable web fields. Audio is recorded by a local Windows Python service and transcribed with `faster-whisper` / Whisper Large V3 Turbo. In **HING** mode, Whisper uses automatic language detection plus Roman-Hinglish decoder context instead of converting Hindi Devanagari into Roman text afterward.

## Why this approach

A normal Hindi browser speech recognizer usually produces Devanagari first. Transliteration afterward can turn place names into forms such as `Bengaluroo`, `Mahaadevapuraa`, or `hariyaanaa`.

VoxHing instead uses this pipeline:

```text
Microphone
   ↓
Local Whisper Large V3 Turbo
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
- Runs Whisper locally after the model has been downloaded
- Uses NVIDIA CUDA automatically when available, otherwise CPU `int8`
- Auto-stops after silence
- Converts spoken digit sequences such as `one two three four` → `1234`
- Floating microphone for inputs, textareas and contenteditable fields
- React/Vue-friendly input insertion
- Keyboard-first navigation

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

Clone it:

```powershell
git clone https://github.com/vikashbhatia/VoxHing.git
cd VoxHing
```

Or download the repository as a ZIP from GitHub and extract it.

### 3. Start the local server

Double-click:

```text
start_voice_server.bat
```

The BAT file checks the dependencies and installs missing packages automatically. The first launch may also download the Whisper `turbo` model.

Manual install is also possible:

```powershell
python -m pip install -r requirements.txt
python local_whisper_server.py
```

When ready you should see messages similar to:

```text
[VoxHing] Starting model load...
[VoxHing] Model ready.
[VoxHing] Local server: http://127.0.0.1:8765
```

## Tampermonkey setup

1. Install Tampermonkey in Chrome/Edge.
2. Open `voxhing.user.js` from this repository.
3. Copy it into a new Tampermonkey userscript and save.
4. Reload the target website.
5. Click/focus a text field. The floating `🎤 HING` control should appear.

The userscript talks only to the local service at:

```text
http://127.0.0.1:8765
```

## Modes

Click the mode label to cycle:

```text
HING → HI → EN → HING
```

### HING

Whisper language is left unset so mixed speech can be auto-detected. A Roman-Hinglish `initial_prompt` nudges decoding toward spellings such as `Bengaluru`, `Mahadevapura`, `Haryana`, and normal Roman Hinglish.

### HI

Forces Whisper to Hindi (`hi`) and uses a Hindi prompt.

### EN

Forces Whisper to English (`en`) and uses Indian-English place-name context.

## Configuration

The server supports environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `WHISPER_MODEL` | `turbo` | faster-whisper model |
| `VOXHING_PORT` | `8765` | local HTTP port |
| `VOXHING_TOKEN` | `vikash-local-whisper-v1` | local API token |
| `VOXHING_SILENCE_SECONDS` | `1.0` | auto-stop after speech silence |
| `VOXHING_SILENCE_RMS` | `0.012` | microphone speech threshold |
| `VOXHING_NO_SPEECH_TIMEOUT` | `10` | stop if no speech is detected |
| `VOXHING_MAX_RECORD_SECONDS` | `30` | maximum recording duration |

If you change `VOXHING_TOKEN` or the port, update `TOKEN` / `API` near the top of `voxhing.user.js` as well.

## Troubleshooting

### `ModuleNotFoundError: No module named 'sounddevice'`

Run:

```powershell
python -m pip install -r requirements.txt
```

Or just use the latest `start_voice_server.bat`, which installs missing dependencies automatically.

### Mic does not appear

- Make sure the Tampermonkey script is enabled.
- Reload the page after installing/updating it.
- Click inside a normal input, textarea or contenteditable field.
- Disable older voice-typing userscripts so they do not conflict.

### `VoxHing server is not running`

Start `start_voice_server.bat` before using the mic.

### CPU is slow

Large V3 Turbo is much faster with an NVIDIA GPU. CPU `int8` is used automatically when CUDA is unavailable. You can also try a smaller faster-whisper model by setting `WHISPER_MODEL` before launch.

## Files

```text
VoxHing/
├── local_whisper_server.py   # microphone + Whisper + local API
├── voxhing.user.js           # Tampermonkey browser UI
├── start_voice_server.bat    # Windows dependency check + launcher
├── requirements.txt
├── .gitignore
└── README.md
```

## Privacy

The service binds to `127.0.0.1`, not to your LAN. Whisper transcription itself runs locally. The first model download requires internet access unless the model is already cached.

## Status

Early development. The main focus is accurate, natural Roman Hinglish and reliable keyboard-driven dictation on Windows.
