from __future__ import annotations

from contextlib import asynccontextmanager
import os
from typing import Annotated, Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .assistant import answer
from .auth import create_access_token, decode_access_token, hash_password, verify_password
from .database import (
    create_user,
    delete_row,
    find_user_by_email,
    find_user_by_id,
    get_integration,
    get_row,
    initialize,
    insert_row,
    list_rows,
    update_row,
)
from .home_assistant import (
    HomeAssistantError,
    call_device_service,
    get_config,
    get_state,
    list_entities,
    normalize_base_url,
    test_connection,
)


load_dotenv()


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    yield


app = FastAPI(title="Jarvix API", version="0.2.0", lifespan=lifespan)
allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "JARVIX_ALLOWED_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=1, max_length=128)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


class DeviceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    kind: str = Field(min_length=2, max_length=40)
    room: str = Field(default="", max_length=60)
    status: str = "offline"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReminderCreate(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    scheduled_at: str
    notes: str = Field(default="", max_length=500)
    completed: bool = False


class RoutineCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    trigger_text: str = Field(min_length=2, max_length=120)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    enabled: bool = True


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class MediaCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    artist: str = Field(default="", max_length=120)
    album: str = Field(default="", max_length=160)
    provider: str = Field(default="youtube_music", max_length=40)
    media_type: str = Field(default="music", pattern="^(music|album|playlist)$")


class HomeAssistantConfig(BaseModel):
    base_url: str = Field(min_length=8, max_length=300)
    token: str = Field(min_length=20, max_length=4096)


class HomeAssistantImport(BaseModel):
    entity_id: str = Field(min_length=3, max_length=160)
    name: str = Field(default="", max_length=100)
    room: str = Field(default="", max_length=60)


class DeviceCommand(BaseModel):
    command: str = Field(pattern="^(turn_on|turn_off|toggle|open|close)$")


def current_user(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Faça login para acessar o Jarvix.")
    payload = decode_access_token(authorization.split(" ", 1)[1].strip())
    if not payload:
        raise HTTPException(401, "Sessão expirada ou inválida.")
    user = find_user_by_id(int(payload["sub"]))
    if not user:
        raise HTTPException(401, "Usuário não encontrado.")
    return user


User = Annotated[dict[str, Any], Depends(current_user)]


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "product": "Jarvix", "version": "0.2.0"}


@app.post("/api/auth/register", response_model=AuthResponse, status_code=201)
def register(payload: RegisterRequest) -> dict[str, Any]:
    if find_user_by_email(payload.email):
        raise HTTPException(409, "Este e-mail já está cadastrado.")
    user = create_user(payload.name, payload.email, hash_password(payload.password))
    return {"access_token": create_access_token(user), "user": user}


@app.post("/api/auth/login", response_model=AuthResponse)
def login(payload: LoginRequest) -> dict[str, Any]:
    user = find_user_by_email(payload.email)
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(401, "E-mail ou senha inválidos.")
    public_user = {key: user[key] for key in ("id", "name", "email", "created_at")}
    return {"access_token": create_access_token(public_user), "user": public_user}


@app.get("/api/auth/me")
def me(user: User) -> dict[str, Any]:
    return {"user": user}


@app.get("/api/dashboard")
def dashboard(user: User) -> dict[str, Any]:
    user_id = int(user["id"])
    devices = list_rows("devices", user_id)
    reminders = list_rows("reminders", user_id)
    routines = list_rows("routines", user_id)
    integrations = [_public_integration(item) for item in list_rows("integrations", user_id)]
    return {
        "user": user,
        "devices": devices,
        "reminders": reminders,
        "routines": routines,
        "integrations": integrations,
        "media": list_rows("media_library", user_id),
        "summary": {
            "devices_online": sum(item["status"] == "online" for item in devices),
            "pending_reminders": sum(not item["completed"] for item in reminders),
            "active_routines": sum(item["enabled"] for item in routines),
        },
    }


@app.post("/api/devices", status_code=201)
def create_device(payload: DeviceCreate, user: User) -> dict[str, Any]:
    return insert_row("devices", payload.model_dump(), int(user["id"]))


@app.post("/api/reminders", status_code=201)
def create_reminder(payload: ReminderCreate, user: User) -> dict[str, Any]:
    return insert_row("reminders", payload.model_dump(), int(user["id"]))


@app.patch("/api/reminders/{row_id}")
def patch_reminder(row_id: int, payload: dict[str, Any], user: User) -> dict[str, Any]:
    row = update_row("reminders", row_id, payload, int(user["id"]))
    if not row:
        raise HTTPException(404, "Lembrete não encontrado")
    return row


@app.post("/api/routines", status_code=201)
def create_routine(payload: RoutineCreate, user: User) -> dict[str, Any]:
    return insert_row("routines", payload.model_dump(), int(user["id"]))


@app.post("/api/media", status_code=201)
def create_media(payload: MediaCreate, user: User) -> dict[str, Any]:
    return insert_row("media_library", payload.model_dump(), int(user["id"]))


@app.post("/api/integrations/home-assistant")
def configure_home_assistant(payload: HomeAssistantConfig, user: User) -> dict[str, Any]:
    user_id = int(user["id"])
    try:
        base_url = normalize_base_url(payload.base_url)
        test_connection(base_url, payload.token)
        ha_config = get_config(base_url, payload.token)
    except HomeAssistantError as exc:
        raise HTTPException(400, str(exc)) from exc

    integration = get_integration("home_assistant", user_id)
    if not integration:
        raise HTTPException(500, "IntegraÃ§Ã£o Home Assistant nÃ£o foi inicializada.")
    updated = update_row(
        "integrations",
        int(integration["id"]),
        {
            "status": "connected",
            "display_name": "Home Assistant",
            "config": {
                "base_url": base_url,
                "token": payload.token.strip(),
                "location_name": ha_config.get("location_name"),
                "version": ha_config.get("version"),
                "time_zone": ha_config.get("time_zone"),
            },
        },
        user_id,
    )
    return {"integration": _public_integration(updated or integration)}


@app.get("/api/integrations/home-assistant/entities")
def home_assistant_entities(user: User) -> dict[str, Any]:
    config = _home_assistant_config(int(user["id"]))
    try:
        return {"entities": list_entities(config["base_url"], config["token"])}
    except HomeAssistantError as exc:
        raise HTTPException(502, str(exc)) from exc


@app.post("/api/integrations/home-assistant/import", status_code=201)
def import_home_assistant_device(payload: HomeAssistantImport, user: User) -> dict[str, Any]:
    user_id = int(user["id"])
    config = _home_assistant_config(user_id)
    try:
        entities = list_entities(config["base_url"], config["token"])
    except HomeAssistantError as exc:
        raise HTTPException(502, str(exc)) from exc
    entity = next((item for item in entities if item["entity_id"] == payload.entity_id), None)
    if not entity:
        raise HTTPException(404, "Entidade nÃ£o encontrada no Home Assistant.")

    status = "online" if entity["state"] not in {"unavailable", "unknown"} else "offline"
    return insert_row(
        "devices",
        {
            "name": payload.name.strip() or entity["name"],
            "kind": entity["domain"],
            "room": payload.room.strip(),
            "status": status,
            "metadata": {
                "integration": "home_assistant",
                "entity_id": entity["entity_id"],
                "domain": entity["domain"],
                "state": entity["state"],
                "last_updated": entity.get("last_updated"),
                "device_class": entity.get("device_class"),
                "commands": entity.get("commands", []),
            },
        },
        user_id,
    )


@app.post("/api/integrations/home-assistant/sync")
def sync_home_assistant_devices(user: User) -> dict[str, Any]:
    user_id = int(user["id"])
    config = _home_assistant_config(user_id)
    synced: list[dict[str, Any]] = []
    for device in list_rows("devices", user_id):
        metadata = device.get("metadata") or {}
        entity_id = metadata.get("entity_id")
        if metadata.get("integration") != "home_assistant" or not entity_id:
            continue
        try:
            state = get_state(config["base_url"], config["token"], entity_id)
        except HomeAssistantError:
            continue
        updated = _update_device_home_assistant_state(device, state, user_id)
        if updated:
            synced.append(updated)
    return {"synced": len(synced), "devices": synced}


@app.post("/api/devices/{row_id}/command")
def command_device(row_id: int, payload: DeviceCommand, user: User) -> dict[str, Any]:
    user_id = int(user["id"])
    device = get_row("devices", row_id, user_id)
    if not device:
        raise HTTPException(404, "Dispositivo nÃ£o encontrado.")
    metadata = device.get("metadata") or {}
    if metadata.get("integration") != "home_assistant" or not metadata.get("entity_id"):
        raise HTTPException(400, "Este dispositivo ainda nÃ£o tem integraÃ§Ã£o acionÃ¡vel.")

    config = _home_assistant_config(user_id)
    try:
        result = call_device_service(
            config["base_url"],
            config["token"],
            metadata["entity_id"],
            payload.command,
        )
    except HomeAssistantError as exc:
        raise HTTPException(502, str(exc)) from exc
    updated_device = None
    if result.get("state"):
        updated_device = _update_device_home_assistant_state(device, result["state"], user_id)
    return {"ok": True, "device": updated_device or device, **result}


@app.get("/api/sync/snapshot")
def sync_snapshot(user: User) -> dict[str, Any]:
    user_id = int(user["id"])
    return {
        "version": 2,
        "user": user,
        "devices": list_rows("devices", user_id),
        "reminders": list_rows("reminders", user_id),
        "routines": list_rows("routines", user_id),
        "integrations": [_public_integration(item) for item in list_rows("integrations", user_id)],
        "media": list_rows("media_library", user_id),
    }


@app.delete("/api/{resource}/{row_id}", status_code=204)
def delete_resource(resource: str, row_id: int, user: User) -> None:
    table = {
        "devices": "devices",
        "reminders": "reminders",
        "routines": "routines",
        "media": "media_library",
    }.get(resource)
    if not table or not delete_row(table, row_id, int(user["id"])):
        raise HTTPException(404, "Item não encontrado")


@app.post("/api/assistant/chat")
def chat(payload: ChatRequest, user: User) -> dict[str, str]:
    try:
        return answer(payload.message, _memory_context(int(user["id"])))
    except Exception:
        raise HTTPException(502, "Não foi possível consultar a IA agora.") from None


def _memory_context(user_id: int) -> str:
    devices = list_rows("devices", user_id)[:20]
    reminders = [item for item in list_rows("reminders", user_id) if not item["completed"]][:20]
    routines = [item for item in list_rows("routines", user_id) if item["enabled"]][:20]
    media = list_rows("media_library", user_id)[:20]
    return "\n".join(
        [
            f"Dispositivos: {', '.join(item['name'] for item in devices) or 'nenhum'}",
            f"Alertas pendentes: {', '.join(item['title'] for item in reminders) or 'nenhum'}",
            f"Rotinas ativas: {', '.join(item['name'] for item in routines) or 'nenhuma'}",
            f"Músicas/álbuns: {', '.join(item['title'] for item in media) or 'nenhum'}",
        ]
    )


def _home_assistant_config(user_id: int) -> dict[str, str]:
    integration = get_integration("home_assistant", user_id)
    config = (integration or {}).get("config") or {}
    if not config.get("base_url") or not config.get("token"):
        raise HTTPException(400, "Configure o Home Assistant antes de importar ou controlar dispositivos.")
    return {"base_url": config["base_url"], "token": config["token"]}


def _public_integration(integration: dict[str, Any]) -> dict[str, Any]:
    item = dict(integration)
    config = dict(item.get("config") or {})
    if "token" in config:
        config["token_configured"] = True
        config.pop("token", None)
    item["config"] = config
    return item


def _update_device_home_assistant_state(
    device: dict[str, Any], state: dict[str, Any], user_id: int
) -> dict[str, Any] | None:
    metadata = {**(device.get("metadata") or {})}
    metadata.update(
        {
            "state": state.get("state", "unknown"),
            "last_updated": state.get("last_updated"),
            "last_changed": state.get("last_changed"),
            "attributes": state.get("attributes", {}),
        }
    )
    status = "offline" if state.get("state") in {"unavailable", "unknown"} else "online"
    return update_row(
        "devices",
        int(device["id"]),
        {
            "status": status,
            "metadata": metadata,
        },
        user_id,
    )
