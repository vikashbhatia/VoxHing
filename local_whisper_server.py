import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

import ctranslate2
import numpy as np
import sounddevice as sd
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from faster_whisper import WhisperModel


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.getenv("VOXHING_CONFIG", str(BASE_DIR / "voxhing_config.json")))

DEFAULT_CONFIG = {
    "host": "127.0.0.1",
    "port": 8765,
    "token": "vikash-local-whisper-v1",
    "model": "base",
    "device": "auto",
    "cpu_compute_type": "int8",
    "cuda_compute_type": "float16",
    "cpu_threads": 0,
    "sample_rate": 16000,
    "channels": 1,
    "blocksize": 1024,
    "silence_seconds": 0.50,
    "silence_rms": 0.012,
    "no_speech_timeout": 7.0,
    "max_record_seconds": 30.0,
    "pre_roll_seconds": 0.18,
    "post_roll_seconds": 0.18,
    "beam_size": 1,
    "best_of": 1,
    "temperature": 0.0,
    "vad_filter": False,
    "vad_min_silence_ms": 250,
    "condition_on_previous_text": False,
    "word_timestamps": False,
    "without_timestamps": True,
    "hinglish_prompt": (
        "Mai Hindi aur English naturally mix karke Roman letters mein bolta hu. "
        "Aur kaise ho tum? Doctor Nivedita Sai Chandra hai. Consult date 13 08 2026. "
        "Bengaluru, Mahadevapura, Haryana, Jammu Kashmir, Chandigarh, Ludhiana, Jalandhar."
    ),
    "english_prompt": (
        "Indian English dictation. Doctor, consult date, Bengaluru, Mahadevapura, "
        "Haryana, Jammu Kashmir, Chandigarh, Ludhiana, Jalandhar."
    ),
    "hindi_prompt": (
        "मैं हिंदी में साफ़ तरीके से बोल रहा हूँ। डॉक्टर, तारीख, दिल्ली, चंडीगढ़, हरियाणा।"
    ),
}


def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)

    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("r", encoding="utf-8") as file:
                user_config = json.load(file)
            if not isinstance(user_config, dict):
                raise ValueError("Top-level JSON value must be an object")
            config.update(user_config)
            print(f"[VoxHing] Loaded config: {CONFIG_PATH}")
        except Exception as exc:
            print(f"[VoxHing] Could not read config: {exc}")
            print("[VoxHing] Using built-in defaults.")
    else:
        print(f"[VoxHing] Config not found: {CONFIG_PATH}")
        print("[VoxHing] Using built-in defaults.")

    # Environment variables are still supported and override JSON.
    env_map = {
        "VOXHING_PORT": ("port", int),
        "VOXHING_TOKEN": ("token", str),
        "WHISPER_MODEL": ("model", str),
        "VOXHING_SILENCE_SECONDS": ("silence_seconds", float),
        "VOXHING_SILENCE_RMS": ("silence_rms", float),
        "VOXHING_NO_SPEECH_TIMEOUT": ("no_speech_timeout", float),
        "VOXHING_MAX_RECORD_SECONDS": ("max_record_seconds", float),
    }

    for env_name, (key, converter) in env_map.items():
        value = os.getenv(env_name)
        if value is not None:
            config[key] = converter(value)

    return config


CONFIG = load_config()

HOST = str(CONFIG["host"])
PORT = int(CONFIG["port"])
TOKEN = str(CONFIG["token"])
MODEL_NAME = str(CONFIG["model"])
DEVICE = str(CONFIG["device"]).lower()

SAMPLE_RATE = int(CONFIG["sample_rate"])
CHANNELS = int(CONFIG["channels"])
BLOCKSIZE = int(CONFIG["blocksize"])

SILENCE_SECONDS = float(CONFIG["silence_seconds"])
SILENCE_RMS = float(CONFIG["silence_rms"])
NO_SPEECH_TIMEOUT = float(CONFIG["no_speech_timeout"])
MAX_RECORD_SECONDS = float(CONFIG["max_record_seconds"])
PRE_ROLL_SECONDS = float(CONFIG["pre_roll_seconds"])
POST_ROLL_SECONDS = float(CONFIG["post_roll_seconds"])

BEAM_SIZE = max(1, int(CONFIG["beam_size"]))
BEST_OF = max(1, int(CONFIG["best_of"]))
TEMPERATURE = float(CONFIG["temperature"])
USE_VAD = bool(CONFIG["vad_filter"])
VAD_MIN_SILENCE_MS = int(CONFIG["vad_min_silence_ms"])
CONDITION_ON_PREVIOUS_TEXT = bool(CONFIG["condition_on_previous_text"])
WORD_TIMESTAMPS = bool(CONFIG["word_timestamps"])
WITHOUT_TIMESTAMPS = bool(CONFIG["without_timestamps"])

HINGLISH_PROMPT = str(CONFIG["hinglish_prompt"])
ENGLISH_PROMPT = str(CONFIG["english_prompt"])
HINDI_PROMPT = str(CONFIG["hindi_prompt"])


DIGITS = {
    "zero": "0", "oh": "0", "o": "0", "one": "1", "two": "2", "three": "3",
    "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ek": "1", "do": "2", "teen": "3", "char": "4", "chaar": "4", "panch": "5",
    "paanch": "5", "che": "6", "chhe": "6", "saat": "7", "aath": "8", "nau": "9",
    "एक": "1", "दो": "2", "तीन": "3", "चार": "4", "पांच": "5", "पाँच": "5",
    "छह": "6", "छः": "6", "सात": "7", "आठ": "8", "नौ": "9", "वन": "1", "टू": "2",
    "थ्री": "3", "फोर": "4", "फाइव": "5", "सिक्स": "6", "सेवन": "7", "एट": "8",
    "एइट": "8", "नाइन": "9", "जीरो": "0", "ज़ीरो": "0", "ज़ीरो": "0",
}

REPEAT_WORDS = {"double": 2, "triple": 3, "डबल": 2, "ट्रिपल": 3}


def normalize_token(token: str) -> str:
    return re.sub(
        r"^[^\w\u0900-\u097F]+|[^\w\u0900-\u097F]+$",
        "",
        token.lower(),
        flags=re.UNICODE,
    )


def spoken_digits_to_numbers(text: str) -> str:
    words = text.split()
    output = []
    i = 0

    while i < len(words):
        pieces = []
        j = i

        while j < len(words):
            current = normalize_token(words[j])

            if current in REPEAT_WORDS and j + 1 < len(words):
                next_word = normalize_token(words[j + 1])
                if next_word in DIGITS:
                    pieces.append(DIGITS[next_word] * REPEAT_WORDS[current])
                    j += 2
                    continue

            if current in DIGITS:
                pieces.append(DIGITS[current])
                j += 1
                continue

            break

        joined = "".join(pieces)

        if len(joined) >= 2:
            output.append(joined)
            i = j
        else:
            output.append(words[i])
            i += 1

    return re.sub(r"\s+", " ", " ".join(output)).strip()


def collapse_phrase_loop(text: str) -> str:
    words = text.split()
    count = len(words)

    if count < 6:
        return text

    normalized = [re.sub(r"\W+", "", word.lower()) for word in words]

    for size in range(2, count // 3 + 1):
        if count % size:
            continue
        if count // size < 3:
            continue

        phrase = normalized[:size]
        if all(normalized[index] == phrase[index % size] for index in range(count)):
            return " ".join(words[:size])

    return text


def cleanup_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    text = collapse_phrase_loop(text)
    text = spoken_digits_to_numbers(text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"([.!?])\1+", r"\1", text)
    return text.strip()


def configured_cpu_threads() -> int:
    requested = int(CONFIG["cpu_threads"])
    if requested > 0:
        return requested
    return max(2, os.cpu_count() or 4)


def load_model() -> WhisperModel:
    cpu_threads = configured_cpu_threads()
    cpu_compute = str(CONFIG["cpu_compute_type"])
    cuda_compute = str(CONFIG["cuda_compute_type"])

    if DEVICE not in {"auto", "cpu", "cuda"}:
        raise ValueError("config 'device' must be auto, cpu, or cuda")

    if DEVICE in {"auto", "cuda"}:
        try:
            cuda_count = ctranslate2.get_cuda_device_count()
        except Exception:
            cuda_count = 0

        if cuda_count > 0:
            print(f"[VoxHing] Loading {MODEL_NAME} on CUDA ({cuda_compute})...")
            try:
                return WhisperModel(
                    MODEL_NAME,
                    device="cuda",
                    compute_type=cuda_compute,
                    cpu_threads=cpu_threads,
                )
            except Exception as exc:
                if DEVICE == "cuda":
                    raise
                print(f"[VoxHing] CUDA load failed: {exc}")
                print("[VoxHing] Falling back to CPU.")
        elif DEVICE == "cuda":
            raise RuntimeError("CUDA was forced in config, but no CUDA device was found")

    print(f"[VoxHing] Loading {MODEL_NAME} on CPU ({cpu_compute}), threads={cpu_threads}...")
    return WhisperModel(
        MODEL_NAME,
        device="cpu",
        compute_type=cpu_compute,
        cpu_threads=cpu_threads,
    )


print()
print("==========================================")
print("             VoxHing Server")
print("==========================================")
print()
print(f"[VoxHing] Model: {MODEL_NAME}")
print(f"[VoxHing] Device preference: {DEVICE}")
print(f"[VoxHing] Beam size: {BEAM_SIZE}")
print(f"[VoxHing] Silence stop: {SILENCE_SECONDS}s")
print("[VoxHing] Starting model load. First launch may download the model.")

MODEL = load_model()

print("[VoxHing] Model ready.")
print()


class StartRequest(BaseModel):
    mode: str = "HING"
    context: Optional[str] = None


class RecorderState:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.job_id = 0
        self.state = "idle"
        self.text = ""
        self.error = ""
        self.detected_language = ""
        self.mode = "HING"
        self.record_seconds = 0.0
        self.audio_seconds = 0.0
        self.transcribe_seconds = 0.0

    def snapshot(self):
        with self.lock:
            return {
                "ok": True,
                "job_id": self.job_id,
                "state": self.state,
                "text": self.text,
                "error": self.error,
                "detected_language": self.detected_language,
                "mode": self.mode,
                "record_seconds": round(self.record_seconds, 3),
                "audio_seconds": round(self.audio_seconds, 3),
                "transcribe_seconds": round(self.transcribe_seconds, 3),
            }


STATE = RecorderState()
app = FastAPI(title="VoxHing Local Whisper Server")


def check_token(value: Optional[str]):
    if value != TOKEN:
        raise HTTPException(status_code=401, detail="Bad local VoxHing token")


def choose_prompt(mode: str, context: str = ""):
    mode = mode.upper().strip()
    context = re.sub(r"\s+", " ", context).strip()[:100]

    if mode == "HI":
        return "hi", HINDI_PROMPT

    if mode == "EN":
        return "en", ENGLISH_PROMPT + (f" {context}" if context else "")

    return None, HINGLISH_PROMPT + (f" {context}" if context else "")


def trim_recording(chunks, voice_flags):
    if not chunks or not voice_flags:
        return np.array([], dtype=np.float32)

    voice_indices = [
        index
        for index, is_voice in enumerate(voice_flags)
        if is_voice
    ]

    if not voice_indices:
        return np.array([], dtype=np.float32)

    block_seconds = BLOCKSIZE / SAMPLE_RATE
    pre_blocks = max(1, int(PRE_ROLL_SECONDS / block_seconds))
    post_blocks = max(1, int(POST_ROLL_SECONDS / block_seconds))

    start_index = max(0, voice_indices[0] - pre_blocks)
    end_index = min(len(chunks), voice_indices[-1] + post_blocks + 1)
    selected = chunks[start_index:end_index]

    if not selected:
        return np.array([], dtype=np.float32)

    return np.concatenate(selected).astype(np.float32, copy=False)


def transcribe_audio(audio, language, prompt):
    kwargs = {
        "language": language,
        "task": "transcribe",
        "beam_size": BEAM_SIZE,
        "best_of": BEST_OF,
        "temperature": TEMPERATURE,
        "initial_prompt": prompt,
        "condition_on_previous_text": CONDITION_ON_PREVIOUS_TEXT,
        "vad_filter": USE_VAD,
        "word_timestamps": WORD_TIMESTAMPS,
        "without_timestamps": WITHOUT_TIMESTAMPS,
    }

    if USE_VAD:
        kwargs["vad_parameters"] = {
            "min_silence_duration_ms": VAD_MIN_SILENCE_MS
        }

    return MODEL.transcribe(audio, **kwargs)


def recorder_worker(job_id: int, mode: str, context: str):
    chunks = []
    voice_flags = []
    started = time.monotonic()
    last_voice = started
    heard_speech = False

    def callback(indata, frames, time_info, status):
        nonlocal last_voice, heard_speech

        if status:
            print("[VoxHing] Audio status:", status)

        mono = np.asarray(indata[:, 0], dtype=np.float32).copy()
        rms = float(np.sqrt(np.mean(np.square(mono)) + 1e-12))
        is_voice = rms >= SILENCE_RMS

        chunks.append(mono)
        voice_flags.append(is_voice)

        if is_voice:
            heard_speech = True
            last_voice = time.monotonic()

    try:
        with STATE.lock:
            if STATE.job_id != job_id:
                return

            STATE.state = "recording"
            STATE.error = ""
            STATE.text = ""
            STATE.detected_language = ""
            STATE.record_seconds = 0.0
            STATE.audio_seconds = 0.0
            STATE.transcribe_seconds = 0.0

        print()
        print(f"[VoxHing] Recording job {job_id} | mode={mode}")

        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            callback=callback,
            blocksize=BLOCKSIZE,
        ):
            while not STATE.stop_event.is_set():
                now = time.monotonic()
                elapsed = now - started

                if elapsed >= MAX_RECORD_SECONDS:
                    print("[VoxHing] Maximum recording time reached.")
                    break

                if heard_speech and now - last_voice >= SILENCE_SECONDS:
                    print("[VoxHing] Silence detected. Stopping.")
                    break

                if not heard_speech and elapsed >= NO_SPEECH_TIMEOUT:
                    print("[VoxHing] No speech detected.")
                    break

                time.sleep(0.02)

        recording_seconds = time.monotonic() - started

        with STATE.lock:
            STATE.record_seconds = recording_seconds

        if not chunks or not heard_speech:
            with STATE.lock:
                if STATE.job_id == job_id:
                    STATE.state = "done"
                    STATE.text = ""
            return

        audio = trim_recording(chunks, voice_flags)

        if audio.size == 0:
            with STATE.lock:
                if STATE.job_id == job_id:
                    STATE.state = "done"
                    STATE.text = ""
            return

        audio_seconds = len(audio) / SAMPLE_RATE

        with STATE.lock:
            if STATE.job_id != job_id:
                return
            STATE.audio_seconds = audio_seconds
            STATE.state = "transcribing"

        language, prompt = choose_prompt(mode, context)

        print(f"[VoxHing] Audio sent to Whisper: {audio_seconds:.2f} sec")
        print(f"[VoxHing] Transcribing job {job_id}")
        print(f"[VoxHing] Language: {language or 'AUTO'}")
        print(f"[VoxHing] Model: {MODEL_NAME}")
        print(f"[VoxHing] Beam size: {BEAM_SIZE}")

        transcribe_started = time.monotonic()
        segments, info = transcribe_audio(audio, language, prompt)

        result_parts = [
            segment.text.strip()
            for segment in segments
            if segment.text.strip()
        ]

        text = cleanup_text(" ".join(result_parts))
        transcribe_seconds = time.monotonic() - transcribe_started
        detected_language = getattr(info, "language", "") or ""

        with STATE.lock:
            if STATE.job_id == job_id:
                STATE.state = "done"
                STATE.text = text
                STATE.detected_language = detected_language
                STATE.transcribe_seconds = transcribe_seconds

        print()
        print(f"[VoxHing] Result: {text}")
        print(f"[VoxHing] Recording: {recording_seconds:.2f} sec")
        print(f"[VoxHing] Whisper audio: {audio_seconds:.2f} sec")
        print(f"[VoxHing] Transcribing: {transcribe_seconds:.2f} sec")
        print(f"[VoxHing] Detected language: {detected_language or 'unknown'}")
        print()

    except Exception as exc:
        print()
        print("[VoxHing] ERROR:")
        print(repr(exc))
        print()

        with STATE.lock:
            if STATE.job_id == job_id:
                STATE.state = "error"
                STATE.error = str(exc)


@app.get("/health")
def health(x_voice_token: Optional[str] = Header(default=None)):
    check_token(x_voice_token)
    snapshot = STATE.snapshot()

    return {
        "ok": True,
        "model": MODEL_NAME,
        "device": DEVICE,
        "beam_size": BEAM_SIZE,
        "sample_rate": SAMPLE_RATE,
        "state": snapshot["state"],
        "config_path": str(CONFIG_PATH),
    }


@app.post("/start")
def start_recording(
    body: StartRequest,
    x_voice_token: Optional[str] = Header(default=None),
):
    check_token(x_voice_token)
    mode = body.mode.upper().strip()

    if mode not in {"HING", "HI", "EN"}:
        mode = "HING"

    with STATE.lock:
        if STATE.state in {"starting", "recording", "transcribing"}:
            raise HTTPException(status_code=409, detail="VoxHing is already busy")

        STATE.job_id += 1
        job_id = STATE.job_id
        STATE.mode = mode
        STATE.state = "starting"
        STATE.text = ""
        STATE.error = ""
        STATE.detected_language = ""
        STATE.record_seconds = 0.0
        STATE.audio_seconds = 0.0
        STATE.transcribe_seconds = 0.0
        STATE.stop_event = threading.Event()

    thread = threading.Thread(
        target=recorder_worker,
        args=(job_id, mode, body.context or ""),
        daemon=True,
    )

    STATE.thread = thread
    thread.start()

    return {"ok": True, "job_id": job_id, "state": "starting"}


@app.post("/stop")
def stop_recording(x_voice_token: Optional[str] = Header(default=None)):
    check_token(x_voice_token)
    STATE.stop_event.set()
    return {"ok": True, "state": STATE.snapshot()["state"]}


@app.get("/status")
def status(x_voice_token: Optional[str] = Header(default=None)):
    check_token(x_voice_token)
    return STATE.snapshot()


if __name__ == "__main__":
    import uvicorn

    print(f"[VoxHing] Local server: http://{HOST}:{PORT}")
    print(f"[VoxHing] Config file: {CONFIG_PATH}")
    print()

    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
