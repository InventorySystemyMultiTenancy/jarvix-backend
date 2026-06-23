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
}

SERVICE_MAP = {
    "turn_on": {
        "light": "turn_on",
        "switch": "turn_on",
        "fan": "turn_on",
        "media_player": "turn_on",
        "vacuum": "start",
    },
    "turn_off": {
        "light": "turn_off",
        "switch": "turn_off",
        "fan": "turn_off",
        "media_player": "turn_off",
        "vacuum": "return_to_base",
    },
    "toggle": {
        "light": "toggle",
        "switch": "toggle",
        "fan": "toggle",
    },
    "open": {"cover": "open_cover", "lock": "unlock"},
    "close": {"cover": "close_cover", "lock": "lock"},
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
        raise HomeAssistantError(f"NÃ£o foi possÃ­vel conectar ao Home Assistant: {exc.reason}") from exc

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


def list_entities(base_url: str, token: str) -> list[dict[str, Any]]:
    states = request_json(base_url, token, "/api/states")
    if not isinstance(states, list):
        raise HomeAssistantError("Resposta invÃ¡lida ao listar entidades.")
    entities: list[dict[str, Any]] = []
    for item in states:
        entity_id = str(item.get("entity_id", ""))
        domain = entity_id.split(".", 1)[0]
        if domain not in SUPPORTED_DOMAINS:
            continue
        attrs = item.get("attributes") or {}
        entities.append(
            {
                "entity_id": entity_id,
                "domain": domain,
                "name": attrs.get("friendly_name") or entity_id,
                "state": item.get("state", "unknown"),
            }
        )
    return sorted(entities, key=lambda entity: entity["name"].lower())


def call_device_service(base_url: str, token: str, entity_id: str, command: str) -> dict[str, Any]:
    domain = entity_id.split(".", 1)[0]
    service = SERVICE_MAP.get(command, {}).get(domain)
    if not service:
        raise HomeAssistantError(f"O comando {command} nÃ£o Ã© suportado para {domain}.")
    request_json(
        base_url,
        token,
        f"/api/services/{domain}/{service}",
        method="POST",
        payload={"entity_id": entity_id},
    )
    return {"entity_id": entity_id, "domain": domain, "service": service}
