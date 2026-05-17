"""Home Assistant add-on entrypoint."""

from __future__ import annotations

import json
import os
from pathlib import Path

import uvicorn


OPTIONS_PATH = Path("/data/options.json")


def _set_env(name: str, value: object | None) -> None:
    if value is None:
        return
    if isinstance(value, bool):
        os.environ[name] = "true" if value else "false"
        return
    os.environ[name] = str(value)


def _load_options() -> dict:
    if not OPTIONS_PATH.exists():
        return {}
    with OPTIONS_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def main() -> None:
    options = _load_options()
    topics = options.get("mqtt_topics") or []
    if isinstance(topics, str):
        topics = [item.strip() for item in topics.replace(",", "\n").splitlines() if item.strip()]

    env_map = {
        "APP_HOST": "0.0.0.0",
        "APP_PORT": 8124,
        "FRONTEND_DIR": "/frontend",
        "DB_HOST": options.get("db_host"),
        "DB_PORT": options.get("db_port"),
        "DB_NAME": options.get("db_name"),
        "DB_USER": options.get("db_user"),
        "DB_PASSWORD": options.get("db_password"),
        "MQTT_HOST": options.get("mqtt_host"),
        "MQTT_PORT": options.get("mqtt_port"),
        "MQTT_USERNAME": options.get("mqtt_username"),
        "MQTT_PASSWORD": options.get("mqtt_password"),
        "MQTT_TLS": options.get("mqtt_tls"),
        "MQTT_CLIENT_ID": options.get("mqtt_client_id"),
        "MQTT_SUBSCRIBE_TOPICS": ",".join(topics),
        "SEND_TOPIC": options.get("send_topic"),
        "CORS_ORIGINS": "*",
    }

    for name, value in env_map.items():
        if value != "":
            _set_env(name, value)

    uvicorn.run("main:app", host="0.0.0.0", port=8124, log_level="info", app_dir="/app")


if __name__ == "__main__":
    main()
