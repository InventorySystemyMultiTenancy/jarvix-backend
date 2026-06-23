from __future__ import annotations

import asyncio
import json
import os
import tempfile
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

import edge_tts
import pygame
import requests
import speech_recognition as sr
import webview


SYNC_INTERVAL = int(os.getenv("JARVIX_SYNC_INTERVAL", "15"))
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
        return {
            "version": 1,
            "devices": [],
            "reminders": [],
            "routines": [],
            "integrations": [],
            "media": [],
        }

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

    def mark_notified(self, reminder_id: int) -> None:
        notified = self.state.setdefault("notified_reminders", [])
        if reminder_id not in notified:
            notified.append(reminder_id)
            self._save(STATE_FILE, self.state)

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
                scheduled = datetime.fromisoformat(reminder["scheduled_at"])
            except (KeyError, ValueError):
                continue
            if scheduled <= now:
                due.append(reminder)
        return due

    def context(self) -> str:
        with self.lock:
            devices = ", ".join(item["name"] for item in self.data.get("devices", [])) or "nenhum"
            routines = ", ".join(item["name"] for item in self.data.get("routines", [])) or "nenhuma"
            media = ", ".join(item["title"] for item in self.data.get("media", [])) or "nenhuma"
            pending = [
                item["title"] for item in self.data.get("reminders", [])
                if not item.get("completed")
            ]
        return (
            f"Dispositivos: {devices}. Rotinas: {routines}. "
            f"Músicas e álbuns: {media}. Alertas pendentes: {', '.join(pending) or 'nenhum'}."
        )


class JarvixApi:
    def __init__(self) -> None:
        self.memory = JarvixMemory()
        self.api_url = self.load_api_url()
        self.recognizer = sr.Recognizer()
        self.window = None
        pygame.mixer.init()

    @staticmethod
    def load_api_url() -> str:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            configured = json.loads(CONFIG_FILE.read_text(encoding="utf-8")).get("api_url")
        except (OSError, json.JSONDecodeError):
            configured = None
        return (configured or os.getenv("JARVIX_API_URL", "http://127.0.0.1:8765")).rstrip("/")

    def configure(self, api_url: str) -> dict[str, str]:
        self.api_url = api_url.strip().rstrip("/")
        CONFIG_FILE.write_text(
            json.dumps({"api_url": self.api_url}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {"text": f"Servidor configurado: {self.api_url}"}

    def set_window(self, window) -> None:
        self.window = window

    def send(self, message: str) -> dict[str, str]:
        message = message.strip()
        normalized = message.lower()
        if not message:
            return {"text": ""}
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
                    json={"message": f"{message}\n\nMemória sincronizada do usuário: {self.memory.context()}"},
                    timeout=60,
                )
                response.raise_for_status()
                answer = response.json()["text"]
            except requests.RequestException:
                answer = "Estou offline. Ainda lembro localmente: " + self.memory.context()
        threading.Thread(target=self.speak, args=(answer,), daemon=True).start()
        return {"text": answer}

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

    def emit(self, kind: str, text: str) -> None:
        if not self.window:
            return
        script = f"window.jarvixEvent({json.dumps(kind)}, {json.dumps(text)})"
        try:
            self.window.evaluate_js(script)
        except Exception:
            pass

    def background_loop(self) -> None:
        while True:
            try:
                self.memory.sync(self.api_url)
                self.emit("status", "Memória sincronizada com o site")
            except requests.RequestException:
                self.emit("status", "Modo offline — usando memória local")
            for reminder in self.memory.due_reminders():
                text = f"Lembrete: {reminder['title']}. {reminder.get('notes', '')}".strip()
                self.emit("message", text)
                threading.Thread(target=self.speak, args=(text,), daemon=True).start()
                self.memory.mark_notified(reminder["id"])
            time.sleep(SYNC_INTERVAL)


HTML = """
<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{color-scheme:dark;--mint:#78f8c6;--bg:#06100e;--panel:#0b1815;--line:#18342c}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(circle at 50% -10%,#184535,transparent 35%),var(--bg);color:#edfdf7;font:15px Segoe UI,Arial}
main{width:min(980px,calc(100% - 40px));margin:auto;padding:30px 0}.top{display:flex;justify-content:space-between;align-items:center}.brand{letter-spacing:.25em}.status{color:#8ca89e}
.orb{width:150px;height:150px;margin:28px auto;border-radius:50%;background:radial-gradient(circle,#baffdf 0 3%,#58eeba 5%,#173d32 30%,#07110f 68%);box-shadow:0 0 60px #36dca555}
#messages{height:300px;overflow:auto;padding:20px;border:1px solid var(--line);border-radius:18px;background:var(--panel)}.msg{margin:0 0 16px}.msg b{color:var(--mint)}
form{display:flex;gap:10px;margin-top:14px}input{flex:1;padding:14px;border:1px solid var(--line);border-radius:10px;background:#081410;color:white}button{padding:12px 18px;border:1px solid #397862;border-radius:10px;background:#10231e;color:white;cursor:pointer}.primary{background:var(--mint);color:#052018;font-weight:700}
</style></head><body><main>
<div class="top"><strong class="brand">JARVIX</strong><span><button id="settings" type="button">Servidor</button> <span id="status" class="status">Iniciando...</span></span></div>
<div class="orb"></div><div id="messages"><p class="msg"><b>Jarvix</b><br>Estou pronto. Sua memória será sincronizada com o site.</p></div>
<form id="form"><input id="input" placeholder="Digite um pedido..." autocomplete="off"><button class="primary">Enviar</button><button id="voice" type="button">🎙 Falar</button></form>
</main><script>
const messages=document.querySelector("#messages"),input=document.querySelector("#input");
function add(who,text){const p=document.createElement("p");p.className="msg";p.innerHTML=`<b>${who}</b><br>`;p.append(document.createTextNode(text));messages.append(p);messages.scrollTop=messages.scrollHeight}
window.jarvixEvent=(kind,text)=>{if(kind==="status")document.querySelector("#status").textContent=text;else add("Jarvix",text)}
document.querySelector("#form").onsubmit=async(e)=>{e.preventDefault();const text=input.value.trim();if(!text)return;add("Você",text);input.value="";add("Jarvix","Pensando...");const waiting=messages.lastChild;const result=await pywebview.api.send(text);waiting.remove();add("Jarvix",result.text)}
document.querySelector("#voice").onclick=async()=>{document.querySelector("#status").textContent="Ouvindo...";const result=await pywebview.api.listen();if(result.text){input.value=result.text;document.querySelector("#form").requestSubmit()}else add("Jarvix",result.error);document.querySelector("#status").textContent="Jarvix online"}
document.querySelector("#settings").onclick=async()=>{const url=prompt("URL do backend Jarvix","http://127.0.0.1:8765");if(url){const result=await pywebview.api.configure(url);add("Jarvix",result.text)}}
</script></body></html>
"""


if __name__ == "__main__":
    api = JarvixApi()
    window = webview.create_window(
        "Jarvix",
        html=HTML,
        js_api=api,
        width=1080,
        height=760,
        min_size=(760, 560),
        background_color="#06100e",
    )
    api.set_window(window)
    threading.Thread(target=api.background_loop, daemon=True).start()
    webview.start()
