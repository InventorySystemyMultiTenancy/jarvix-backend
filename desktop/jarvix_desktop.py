from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import edge_tts
import pygame
import requests
import speech_recognition as sr
import webview


SYNC_INTERVAL = int(os.getenv("JARVIX_SYNC_INTERVAL", "15"))
LOCAL_PORT = int(os.getenv("JARVIX_LOCAL_PORT", "0"))
DATA_DIR = Path(os.getenv("LOCALAPPDATA", Path.home())) / "Jarvix"
MEMORY_FILE = DATA_DIR / "memory.json"
STATE_FILE = DATA_DIR / "state.json"
CONFIG_FILE = DATA_DIR / "config.json"


class JarvixMemory:
    def __init__(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.data = self._load(MEMORY_FILE, self.empty())
        self.state = self._load(STATE_FILE, {"notified_reminders": []})

    @staticmethod
    def empty() -> dict:
        return {"version": 1, "devices": [], "reminders": [], "routines": [], "integrations": [], "media": []}

    @staticmethod
    def _load(path: Path, default: dict) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    @staticmethod
    def _save(path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def sync(self, api_url: str) -> None:
        response = requests.get(f"{api_url}/api/sync/snapshot", timeout=10)
        response.raise_for_status()
        with self.lock:
            self.data = response.json()
            self._save(MEMORY_FILE, self.data)

    def due_reminders(self) -> list[dict]:
        now = datetime.now()
        notified = set(self.state.get("notified_reminders", []))
        due = []
        with self.lock:
            reminders = list(self.data.get("reminders", []))
        for reminder in reminders:
            if reminder.get("completed") or reminder.get("id") in notified:
                continue
            try:
                if datetime.fromisoformat(reminder["scheduled_at"]) <= now:
                    due.append(reminder)
            except (KeyError, ValueError):
                pass
        return due

    def mark_notified(self, reminder_id: int) -> None:
        notified = self.state.setdefault("notified_reminders", [])
        if reminder_id not in notified:
            notified.append(reminder_id)
            self._save(STATE_FILE, self.state)

    def context(self) -> str:
        with self.lock:
            names = lambda key, field: ", ".join(item[field] for item in self.data.get(key, [])) or "nenhum"
            pending = ", ".join(
                item["title"] for item in self.data.get("reminders", []) if not item.get("completed")
            ) or "nenhum"
            return (
                f"Dispositivos: {names('devices', 'name')}. Rotinas: {names('routines', 'name')}. "
                f"Músicas e álbuns: {names('media', 'title')}. Alertas pendentes: {pending}."
            )


class Jarvix:
    def __init__(self) -> None:
        self.memory = JarvixMemory()
        self.recognizer = sr.Recognizer()
        self.api_url = self.load_api_url()
        self.status = "Iniciando..."
        self.messages: list[str] = []
        pygame.mixer.init()

    @staticmethod
    def load_api_url() -> str:
        try:
            value = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("api_url")
        except (OSError, json.JSONDecodeError):
            value = None
        return (value or os.getenv("JARVIX_API_URL", "http://127.0.0.1:8765")).rstrip("/")

    def configure(self, api_url: str) -> str:
        self.api_url = api_url.strip().rstrip("/")
        CONFIG_FILE.write_text(json.dumps({"api_url": self.api_url}, indent=2), encoding="utf-8")
        return f"Servidor configurado: {self.api_url}"

    def send(self, message: str) -> str:
        normalized = message.lower()
        if "tocar" in normalized and self.memory.data.get("media"):
            selected = next(
                (item for item in self.memory.data["media"] if item["title"].lower() in normalized),
                self.memory.data["media"][0],
            )
            webbrowser.open("https://music.youtube.com/search?q=" + quote_plus(selected["title"]))
            answer = f"Abrindo {selected['title']} no YouTube Music."
        elif "o que você lembra" in normalized or "minha memória" in normalized:
            answer = self.memory.context()
        else:
            try:
                response = requests.post(
                    f"{self.api_url}/api/assistant/chat",
                    json={"message": f"{message}\n\nMemória sincronizada: {self.memory.context()}"},
                    timeout=60,
                )
                response.raise_for_status()
                answer = response.json()["text"]
            except requests.RequestException:
                answer = "Estou offline. Ainda lembro localmente: " + self.memory.context()
        threading.Thread(target=self.speak, args=(answer,), daemon=True).start()
        return answer

    def listen(self) -> dict[str, str]:
        try:
            with sr.Microphone() as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.4)
                audio = self.recognizer.listen(source, timeout=8, phrase_time_limit=10)
            return {"text": self.recognizer.recognize_google(audio, language="pt-BR")}
        except Exception:
            return {"text": "", "error": "Não consegui entender o microfone."}

    @staticmethod
    def speak(text: str) -> None:
        async def generate(path: str) -> None:
            await edge_tts.Communicate(text=text, voice="pt-BR-AntonioNeural").save(path)
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        path = handle.name
        handle.close()
        try:
            asyncio.run(generate(path))
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def background_loop(self) -> None:
        while True:
            try:
                self.memory.sync(self.api_url)
                self.status = "Memória sincronizada com o site"
            except requests.RequestException:
                self.status = "Modo offline — usando memória local"
            for reminder in self.memory.due_reminders():
                text = f"Lembrete: {reminder['title']}. {reminder.get('notes', '')}".strip()
                self.messages.append(text)
                threading.Thread(target=self.speak, args=(text,), daemon=True).start()
                self.memory.mark_notified(reminder["id"])
            time.sleep(SYNC_INTERVAL)


HTML = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jarvix</title><style>:root{color-scheme:dark;--m:#78f8c6;--b:#06100e;--p:#0b1815;--l:#18342c}*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 50% -10%,#184535,transparent 35%),var(--b);color:#edfdf7;font:15px Segoe UI,Arial}main{width:min(980px,calc(100% - 40px));margin:auto;padding:30px 0}.top{display:flex;justify-content:space-between;align-items:center}.brand{letter-spacing:.25em}.status{color:#8ca89e}.orb{width:150px;height:150px;margin:28px auto;border-radius:50%;background:radial-gradient(circle,#baffdf 0 3%,#58eeba 5%,#173d32 30%,#07110f 68%);box-shadow:0 0 60px #36dca555}#messages{height:300px;overflow:auto;padding:20px;border:1px solid var(--l);border-radius:18px;background:var(--p)}.msg{margin:0 0 16px}.msg b{color:var(--m)}form{display:flex;gap:10px;margin-top:14px}input{flex:1;padding:14px;border:1px solid var(--l);border-radius:10px;background:#081410;color:white}button{padding:12px 18px;border:1px solid #397862;border-radius:10px;background:#10231e;color:white;cursor:pointer}.primary{background:var(--m);color:#052018;font-weight:700}</style></head><body><main>
<div class="top"><strong class="brand">JARVIX</strong><span><button id="settings">Servidor</button> <span id="status" class="status">Iniciando...</span></span></div><div class="orb"></div>
<div id="messages"><p class="msg"><b>Jarvix</b><br>Estou pronto. Minha memória será sincronizada com o site.</p></div>
<form id="form"><input id="input" placeholder="Digite um pedido..." autocomplete="off"><button class="primary">Enviar</button><button id="voice" type="button">🎙 Falar</button></form>
</main><script>const m=document.querySelector("#messages"),i=document.querySelector("#input"),s=document.querySelector("#status");function add(w,t){const p=document.createElement("p");p.className="msg";p.innerHTML=`<b>${w}</b><br>`;p.append(document.createTextNode(t));m.append(p);m.scrollTop=m.scrollHeight}async function call(path,body){const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body||{})});return r.json()}document.querySelector("#form").onsubmit=async e=>{e.preventDefault();const t=i.value.trim();if(!t)return;add("Você",t);i.value="";const r=await call("/api/send",{message:t});add("Jarvix",r.text)};document.querySelector("#voice").onclick=async()=>{s.textContent="Ouvindo...";const r=await call("/api/listen");if(r.text){i.value=r.text;document.querySelector("#form").requestSubmit()}else add("Jarvix",r.error);};document.querySelector("#settings").onclick=async()=>{const u=prompt("URL do backend Jarvix","http://127.0.0.1:8765");if(u){const r=await call("/api/configure",{api_url:u});add("Jarvix",r.text)}};setInterval(async()=>{const r=await fetch("/api/status").then(x=>x.json());s.textContent=r.status;(r.messages||[]).forEach(x=>add("Jarvix",x))},3000);</script></body></html>"""


jarvix = Jarvix()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args) -> None:
        pass

    def reply(self, data: dict, status: int = 200) -> None:
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        if urlparse(self.path).path == "/":
            payload = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        elif self.path == "/api/status":
            messages, jarvix.messages = jarvix.messages, []
            self.reply({"status": jarvix.status, "messages": messages})
        else:
            self.reply({"error": "not found"}, 404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self.reply({"error": "invalid json"}, 400)
        if self.path == "/api/send":
            self.reply({"text": jarvix.send(body.get("message", ""))})
        elif self.path == "/api/listen":
            self.reply(jarvix.listen())
        elif self.path == "/api/configure":
            self.reply({"text": jarvix.configure(body.get("api_url", ""))})
        else:
            self.reply({"error": "not found"}, 404)


if __name__ == "__main__":
    threading.Thread(target=jarvix.background_loop, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", LOCAL_PORT), Handler)
    url = f"http://127.0.0.1:{server.server_port}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    webview.create_window("Jarvix", url, width=1280, height=860)
    webview.start()
