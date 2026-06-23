from __future__ import annotations

import json
from typing import Any
from urllib import error, request


SUPPORTED_DOMAINS = {
    "light",
    "switch",
    "fan",
    "cover",
    "climate",
    "media_player",
    "vacuum",
    "lock",
    "button",
    "input_button",
    "scene",
    "script",
    "automation",
}

SERVICE_MAP = {
    "turn_on": {
        "light": "turn_on",
        "switch": "turn_on",
        "fan": "turn_on",
        "climate": "turn_on",
        "media_player": "turn_on",
        "vacuum": "start",
        "scene": "turn_on",
        "script": "turn_on",
        "automation": "turn_on",
    },
    "turn_off": {
        "light": "turn_off",
        "switch": "turn_off",
        "fan": "turn_off",
        "climate": "turn_off",
        "media_player": "turn_off",
        "vacuum": "return_to_base",
        "script": "turn_off",
        "automation": "turn_off",
    },
    "toggle": {
        "light": "toggle",
        "switch": "toggle",
        "fan": "toggle",
        "automation": "toggle",
    },
    "open": {"cover": "open_cover", "lock": "unlock"},
    "close": {"cover": "close_cover", "lock": "lock"},
    "press": {"button": "press", "input_button": "press"},
    "trigger": {"automation": "trigger"},
}

COMMAND_LABELS = {
    "turn_on": "Ligar",
    "turn_off": "Desligar",
    "toggle": "Alternar",
    "open": "Abrir/destravar",
    "close": "Fechar/travar",
    "press": "Pressionar",
    "trigger": "Disparar",
}


class HomeAssistantError(RuntimeError):
    pass


def normalize_base_url(value: str) -> str:
    base_url = value.strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise HomeAssistantError("Informe a URL com http:// ou https://.")
    return base_url


def request_json(
    base_url: str,
    token: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: int = 15,
) -> Any:
    body = None
    headers = {
        "Authorization": f"Bearer {token.strip()}",
        "Content-Type": "application/json",
    }
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    req = request.Request(
        f"{normalize_base_url(base_url)}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            content = response.read().decode("utf-8")
    except error.HTTPError as exc:
        message = exc.read().decode("utf-8", errors="ignore") or exc.reason
        raise HomeAssistantError(f"Home Assistant respondeu {exc.code}: {message}") from exc
    except error.URLError as exc:
        raise HomeAssistantError(f"Não foi possível conectar ao Home Assistant: {exc.reason}") from exc

    if not content:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content


def test_connection(base_url: str, token: str) -> dict[str, Any]:
    result = request_json(base_url, token, "/api/")
    if isinstance(result, dict):
        return result
    return {"message": str(result)}


def get_config(base_url: str, token: str) -> dict[str, Any]:
    config = request_json(base_url, token, "/api/config")
    if not isinstance(config, dict):
        raise HomeAssistantError("Resposta inválida ao ler configuração.")
    return {
        "location_name": config.get("location_name"),
        "version": config.get("version"),
        "time_zone": config.get("time_zone"),
        "components": config.get("components", []),
    }


def list_services(base_url: str, token: str) -> dict[str, set[str]]:
    payload = request_json(base_url, token, "/api/services")
    if not isinstance(payload, list):
        raise HomeAssistantError("Resposta inválida ao listar serviços.")
    services: dict[str, set[str]] = {}
    for item in payload:
        domain = str(item.get("domain", ""))
        values = item.get("services") or []
        services[domain] = set(values if isinstance(values, list) else values.keys())
    return services


def get_state(base_url: str, token: str, entity_id: str) -> dict[str, Any]:
    state = request_json(base_url, token, f"/api/states/{entity_id}")
    if not isinstance(state, dict):
        raise HomeAssistantError("Resposta inválida ao consultar estado.")
    attrs = state.get("attributes") or {}
    domain = entity_id.split(".", 1)[0]
    return {
        "entity_id": entity_id,
        "domain": domain,
        "name": attrs.get("friendly_name") or entity_id,
        "state": state.get("state", "unknown"),
        "last_changed": state.get("last_changed"),
        "last_updated": state.get("last_updated"),
        "attributes": attrs,
    }


def list_entities(base_url: str, token: str) -> list[dict[str, Any]]:
    states = request_json(base_url, token, "/api/states")
    if not isinstance(states, list):
        raise HomeAssistantError("Resposta inválida ao listar entidades.")
    services = list_services(base_url, token)
    entities: list[dict[str, Any]] = []
    for item in states:
        entity_id = str(item.get("entity_id", ""))
        domain = entity_id.split(".", 1)[0]
        if domain not in SUPPORTED_DOMAINS:
            continue
        attrs = item.get("attributes") or {}
        commands = available_commands(domain, services)
        if not commands:
            continue
        entities.append(
            {
                "entity_id": entity_id,
                "domain": domain,
                "name": attrs.get("friendly_name") or entity_id,
                "state": item.get("state", "unknown"),
                "last_changed": item.get("last_changed"),
                "last_updated": item.get("last_updated"),
                "device_class": attrs.get("device_class"),
                "commands": commands,
            }
        )
    return sorted(entities, key=lambda entity: entity["name"].lower())


def available_commands(domain: str, services: dict[str, set[str]]) -> list[dict[str, str]]:
    domain_services = services.get(domain, set())
    commands: list[dict[str, str]] = []
    for command, domains in SERVICE_MAP.items():
        service = domains.get(domain)
        if service and service in domain_services:
            commands.append({"command": command, "label": COMMAND_LABELS[command], "service": service})
    return commands


def call_device_service(base_url: str, token: str, entity_id: str, command: str) -> dict[str, Any]:
    domain = entity_id.split(".", 1)[0]
    service = SERVICE_MAP.get(command, {}).get(domain)
    if not service:
        raise HomeAssistantError(f"O comando {command} não é suportado para {domain}.")
    services = list_services(base_url, token)
    if service not in services.get(domain, set()):
        raise HomeAssistantError(f"O serviço {domain}.{service} não está disponível neste Home Assistant.")

    result = request_json(
        base_url,
        token,
        f"/api/services/{domain}/{service}",
        method="POST",
        payload={"entity_id": entity_id},
    )
    state = None
    try:
        state = get_state(base_url, token, entity_id)
    except HomeAssistantError:
        pass
    return {
        "entity_id": entity_id,
        "domain": domain,
        "service": service,
        "changed_states": result if isinstance(result, list) else [],
        "state": state,
    }
