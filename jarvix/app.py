from __future__ import annotations

from contextlib import asynccontextmanager
import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .assistant import answer
from .database import delete_row, initialize, insert_row, list_rows, update_row


load_dotenv()


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    yield


app = FastAPI(title="Jarvix API", version="0.1.0", lifespan=lifespan)
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


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "product": "Jarvix", "version": "0.1.0"}


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    devices = list_rows("devices")
    reminders = list_rows("reminders")
    routines = list_rows("routines")
    return {
        "devices": devices,
        "reminders": reminders,
        "routines": routines,
        "integrations": list_rows("integrations"),
        "summary": {
            "devices_online": sum(item["status"] == "online" for item in devices),
            "pending_reminders": sum(not item["completed"] for item in reminders),
            "active_routines": sum(item["enabled"] for item in routines),
        },
    }


@app.post("/api/devices", status_code=201)
def create_device(payload: DeviceCreate) -> dict[str, Any]:
    return insert_row("devices", payload.model_dump())


@app.post("/api/reminders", status_code=201)
def create_reminder(payload: ReminderCreate) -> dict[str, Any]:
    return insert_row("reminders", payload.model_dump())


@app.patch("/api/reminders/{row_id}")
def patch_reminder(row_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    row = update_row("reminders", row_id, payload)
    if not row:
        raise HTTPException(404, "Lembrete não encontrado")
    return row


@app.post("/api/routines", status_code=201)
def create_routine(payload: RoutineCreate) -> dict[str, Any]:
    return insert_row("routines", payload.model_dump())


@app.delete("/api/{resource}/{row_id}", status_code=204)
def delete_resource(resource: str, row_id: int) -> None:
    table = {"devices": "devices", "reminders": "reminders", "routines": "routines"}.get(
        resource
    )
    if not table or not delete_row(table, row_id):
        raise HTTPException(404, "Item não encontrado")


@app.post("/api/assistant/chat")
def chat(payload: ChatRequest) -> dict[str, str]:
    try:
        return answer(payload.message)
    except Exception:
        raise HTTPException(502, "Não foi possível consultar a IA agora.") from None
