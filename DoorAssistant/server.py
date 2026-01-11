import os
import time
import threading
from typing import Dict, Any, List, Optional

import serial
from serial.tools import list_ports

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from openai import OpenAI

# Try loading a local .env file if present (optional; safe if missing)
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
    print("[config] .env file loaded via python-dotenv")
except ImportError:
    print("[config] WARNING: python-dotenv not installed. Run: pip install python-dotenv")
except Exception as e:
    print(f"[config] WARNING: Failed to load .env: {e}")

SERIAL_PORT = os.getenv("SERIAL_PORT", "")
BAUD = 115200

USE_LLM = os.getenv("USE_LLM", "0") == "1"

# BLE integration (optional)
ENABLE_BLE = os.getenv("ENABLE_BLE", "0") == "1"
BLE_DEVICE_NAME = os.getenv("BLE_DEVICE_NAME", "")
BLE_DEVICE_ADDRESS = os.getenv("BLE_DEVICE_ADDRESS", "")  # Windows sometimes shows MAC like AA:BB:CC:DD:EE:FF
BLE_SERVICE_UUID = os.getenv("BLE_SERVICE_UUID", "")      # e.g. custom service
BLE_CHAR_UUID = os.getenv("BLE_CHAR_UUID", "")             # characteristic that notifies messages

STT_MODEL = "gpt-4o-mini-transcribe"
LLM_MODEL = "gpt-4o-mini"

# Read OpenAI API key from environment; avoid constructing the client if missing
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
if OPENAI_API_KEY:
    print("[config] OPENAI_API_KEY found. Initializing OpenAI client...")
    client: Optional[OpenAI] = OpenAI(api_key=OPENAI_API_KEY)
else:
    print("[config] WARNING: OPENAI_API_KEY not set. Audio transcription will fail.")
    print("[config]   - Check your .env file in the DoorAssistant/ directory")
    print("[config]   - Or set env var: $env:OPENAI_API_KEY='your-key'")
    client = None

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

subscribers: List[List[Dict[str, Any]]] = []

last_items: List[str] = []
last_transcript: str = ""

BASE_ESSENTIALS = ["keys", "wallet", "phone", "ID"]
DEST_ITEMS = {
    "gym": ["water bottle", "towel", "headphones", "gym shoes", "deodorant"],
    "class": ["laptop", "charger", "notebook", "pen"],
    "campus": ["laptop", "charger", "notebook", "pen"],
    "work": ["laptop", "charger", "badge", "lunch"],
    "grocery": ["reusable bags", "shopping list", "wallet"],
    "store": ["reusable bags", "shopping list"],
}

def broadcast(ev: Dict[str, Any]):
    for box in subscribers:
        box.append(ev)

def guess_port() -> str:
    ports = list(list_ports.comports())
    if not ports:
        return ""

    for p in ports:
        desc = (p.description or "").lower()
        if "arduino" in desc or "usb serial" in desc or "ch340" in desc or "cp210" in desc:
            return p.device
    return ports[0].device

def serial_worker():
    global SERIAL_PORT
    if not SERIAL_PORT:
        SERIAL_PORT = guess_port()
    if not SERIAL_PORT:
        print("[serial] No serial ports found.")
        return

    print("[serial] Using port:", SERIAL_PORT)
    ser = serial.Serial(SERIAL_PORT, BAUD, timeout=1)

    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if not line:
            continue
        # print("[serial]", line)
        if line == "EVENT:LEAVING":
            broadcast({"type": "LEAVING", "ts": time.time()})

def ble_worker():
    # Run BLE logic in its own async loop
    try:
        import asyncio
        from bleak import BleakClient, BleakScanner
    except Exception as e:
        print("[ble] bleak not available. Install with: pip install bleak")
        return

    async def find_device():
        if BLE_DEVICE_ADDRESS:
            return BLE_DEVICE_ADDRESS
        devices = await BleakScanner.discover()
        for d in devices:
            if BLE_DEVICE_NAME and (d.name or "") == BLE_DEVICE_NAME:
                return d.address
        return None

    async def run():
        while True:
            try:
                addr = await find_device()
                if not addr:
                    print("[ble] Device not found. Scanning again in 5s...")
                    await asyncio.sleep(5)
                    continue
                print(f"[ble] Connecting to {addr}...")
                async with BleakClient(addr) as cl:
                    if BLE_CHAR_UUID:
                        def on_notify(_, data: bytes):
                            try:
                                msg = data.decode("utf-8", errors="ignore").strip()
                            except Exception:
                                msg = ""
                            if msg:
                                # print("[ble]", msg)
                                if msg == "EVENT:LEAVING":
                                    broadcast({"type": "LEAVING", "ts": time.time()})

                        await cl.start_notify(BLE_CHAR_UUID, on_notify)
                        print("[ble] Subscribed to notifications.")
                        # Keep connection
                        while True:
                            await asyncio.sleep(1)
                    else:
                        print("[ble] BLE_CHAR_UUID not set; cannot subscribe.")
                        await asyncio.sleep(10)
            except Exception as e:
                print("[ble] Error:", e)
                await asyncio.sleep(3)

    try:
        import asyncio
        asyncio.run(run())
    except Exception as e:
        print("[ble] Loop error:", e)

@app.on_event("startup")
def startup():
    threading.Thread(target=serial_worker, daemon=True).start()
    if ENABLE_BLE:
        print("[ble] BLE enabled. Starting BLE worker...")
        threading.Thread(target=ble_worker, daemon=True).start()

@app.get("/", response_class=HTMLResponse)
def index():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

@app.get("/events/stream")
async def sse_stream():
    box: List[Dict[str, Any]] = []
    subscribers.append(box)

    async def gen():
        try:
            while True:
                if box:
                    ev = box.pop(0)
                    yield f"data: {__import__('json').dumps(ev)}\n\n"
                else:
                    yield ":\n\n"
                await __import__("asyncio").sleep(0.25)
        finally:
            if box in subscribers:
                subscribers.remove(box)

    return StreamingResponse(gen(), media_type="text/event-stream")

def normalize_destination(text: str) -> str:
    t = text.lower().strip()
    # very simple: if user says "i'm going to the gym"
    for key in DEST_ITEMS.keys():
        if key in t:
            return key
    # fallback: first word
    return t.split()[-1] if t else ""

def dedup(items: List[str]) -> List[str]:
    out, seen = [], set()
    for it in items:
        s = str(it).strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out

def items_from_builtin(dest_key: str) -> List[str]:
    extras = DEST_ITEMS.get(dest_key, [])
    return dedup(BASE_ESSENTIALS + extras)

def items_from_llm(transcript: str) -> List[str]:
    if client is None:
        return []
    # Responses API reference :contentReference[oaicite:6]{index=6}
    prompt = f"""
Return ONLY JSON in the format: {{"items":[string,...]}}.

User said: "{transcript}"

Goal: Suggest a short list (5-10) of items to bring.
Always include: keys, wallet, phone, ID (unless clearly irrelevant).
Avoid duplicates. Use concise nouns.
"""
    resp = client.responses.create(model=LLM_MODEL, input=prompt)
    text = resp.output_text.strip()

    import json
    try:
        data = json.loads(text)
        items = data.get("items", [])
        if not isinstance(items, list):
            return []
        return dedup([str(x) for x in items])
    except Exception:
        return []

@app.post("/audio_suggest")
async def audio_suggest(audio: UploadFile = File(...)):
    """
    Receives recorded audio from browser.
    Transcribes it, applies voice commands, returns items.
    """
    global last_items, last_transcript

    import io

    raw = await audio.read()
    f = io.BytesIO(raw)
    f.name = audio.filename or "clip.webm"

    # Speech-to-text requires OpenAI client and API key
    if client is None:
        return {"transcript": "", "items": [], "mode": "error", "message": "OPENAI_API_KEY is not set. Set it and restart the server."}

    # Speech-to-text guide :contentReference[oaicite:7]{index=7}
    stt = client.audio.transcriptions.create(model=STT_MODEL, file=f)
    transcript = getattr(stt, "text", None) or (stt.get("text") if isinstance(stt, dict) else "")
    transcript = (transcript or "").strip()
    if not transcript:
        return {"transcript": "", "items": [], "mode": "error", "message": "No transcript"}

    t = transcript.lower()

    # Voice commands
    if "cancel" in t or "stop" in t:
        last_transcript = transcript
        return {"transcript": transcript, "items": [], "mode": "command", "message": "Cancelled"}

    if "repeat" in t:
        return {"transcript": transcript, "items": last_items, "mode": "command", "message": "Repeat"}

    # Normal destination flow
    dest_key = normalize_destination(transcript)
    items = items_from_builtin(dest_key)

    # Optional LLM fallback if destination not recognized
    if USE_LLM and (dest_key not in DEST_ITEMS):
        llm_items = items_from_llm(transcript)
        if llm_items:
            items = dedup(llm_items)

    last_items = items
    last_transcript = transcript
    return {"transcript": transcript, "items": items, "mode": "result", "message": ""}
