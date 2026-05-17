import base64
import hashlib
import json
import logging
import re
import time
from typing import Any

import paho.mqtt.client as mqtt

from db import Database
from settings import Settings

LOGGER = logging.getLogger(__name__)
BROADCAST_NUMS = {0, 0xFFFFFFFF, 4294967295}


def _node_id(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return f"!{value:08x}"
    text = str(value)
    if text.startswith("!"):
        return text
    if text.isdigit():
        return f"!{int(text):08x}"
    return text


def _node_num(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    text = str(value)
    if text.startswith("!"):
        try:
            return int(text[1:], 16)
        except ValueError:
            return None
    try:
        return int(text)
    except ValueError:
        return None


def _first(data: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        value = data.get(name)
        if value is not None:
            return value
    return None


def _nested_text(data: dict[str, Any]) -> str | None:
    decoded = data.get("decoded") if isinstance(data.get("decoded"), dict) else {}
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else {}
    raw_payload = data.get("payload") if isinstance(data.get("payload"), str) else None
    candidates = [
        data.get("text"),
        data.get("message"),
        raw_payload,
        payload.get("text"),
        payload.get("message"),
        decoded.get("text"),
        decoded.get("payload"),
        decoded.get("payloadString"),
    ]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value
    return None


def _packet_id(data: dict[str, Any]) -> str | None:
    decoded = data.get("decoded") if isinstance(data.get("decoded"), dict) else {}
    packet = data.get("packet") if isinstance(data.get("packet"), dict) else {}
    value = _first(data, ["id", "packet_id", "packetId"]) or packet.get("id") or decoded.get("requestId")
    return str(value) if value is not None and value != "" else None


def _channel_from(topic: str, data: dict[str, Any]) -> str | None:
    parts = topic.split("/")
    if len(parts) >= 6 and parts[2] == "2" and parts[3] in ("json", "e", "c"):
        name = parts[-2]
        if name and not name.startswith("!"):
            return name
    channel = _first(data, ["channel", "channel_id", "channelId"])
    if channel is not None and channel != "":
        return str(channel)
    return None


def _sender_names(data: dict[str, Any]) -> tuple[str | None, str | None]:
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    from_user = data.get("fromUser") if isinstance(data.get("fromUser"), dict) else {}
    long_name = _first(data, ["longName", "long_name", "senderLongName"]) or user.get("longName") or from_user.get("longName")
    short_name = _first(data, ["shortName", "short_name", "senderShortName"]) or user.get("shortName") or from_user.get("shortName")
    return (str(long_name) if long_name else None, str(short_name) if short_name else None)


def _conversation_key(channel: str | None, sender_num: int | None, recipient_num: int | None) -> str:
    if sender_num is not None and recipient_num is not None and recipient_num not in BROADCAST_NUMS:
        low, high = sorted([sender_num, recipient_num])
        return f"dm:{low}:{high}"
    if channel:
        safe_channel = re.sub(r"\s+", "_", channel.strip())
        return f"channel:{safe_channel}"
    return "system:mesh"


def normalize_json_message(topic: str, payload_hash: str, data: dict[str, Any]) -> dict[str, Any] | None:
    text = _nested_text(data)
    if not text:
        return None

    sender = _first(data, ["from", "fromId", "from_id", "sender", "senderId", "sender_id"])
    recipient = _first(data, ["to", "toId", "to_id", "recipient", "recipientId", "recipient_id"])
    sender_num = _node_num(sender)
    recipient_num = _node_num(recipient)
    sender_node_id = _node_id(sender)
    recipient_node_id = _node_id(recipient)
    channel = _channel_from(topic, data)
    timestamp = _first(data, ["rxTime", "timestamp", "time", "received_at"]) or int(time.time())
    long_name, short_name = _sender_names(data)
    key = _conversation_key(channel, sender_num, recipient_num)
    title = channel or "Mesh"
    if key.startswith("dm:"):
        title = f"DM {sender_node_id or sender_num} / {recipient_node_id or recipient_num}"

    normalized = {
        "packet_id": _packet_id(data),
        "payload_hash": payload_hash,
        "conversation_key": key,
        "conversation_title": title,
        "sender_node_id": sender_node_id,
        "sender_node_num": sender_num,
        "sender_long_name": long_name,
        "sender_short_name": short_name,
        "recipient_node_id": recipient_node_id,
        "recipient_node_num": recipient_num,
        "timestamp": int(timestamp),
        "channel": channel,
        "topic": topic,
        "text": text,
    }
    normalized["normalized_json"] = json.dumps(normalized, separators=(",", ":"), sort_keys=True)
    return normalized


class MqttWorker:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.connected = False
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=settings.mqtt_client_id)
        if settings.mqtt_username:
            self.client.username_pw_set(settings.mqtt_username, settings.mqtt_password)
        if settings.mqtt_tls:
            self.client.tls_set()
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.on_subscribe = self._on_subscribe

    def start(self) -> None:
        LOGGER.info("Connecting to MQTT broker %s:%s", self.settings.mqtt_host, self.settings.mqtt_port)
        self.client.connect_async(self.settings.mqtt_host, self.settings.mqtt_port, keepalive=60)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()

    def publish_text(self, text: str, topic: str | None = None, channel: str | None = None, destination: str | None = None) -> str:
        publish_topic = topic or self.settings.send_topic
        if not publish_topic:
            raise ValueError("SEND_TOPIC is not configured")
        payload = {"text": text}
        if channel:
            payload["channel"] = channel
        if destination:
            payload["destination"] = destination
        result = self.client.publish(publish_topic, json.dumps(payload), qos=0, retain=False)
        result.wait_for_publish(timeout=5)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish failed with rc={result.rc}")
        return publish_topic

    def _on_connect(self, client: mqtt.Client, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any = None) -> None:
        self.connected = True
        LOGGER.info("MQTT connected: %s", reason_code)
        for topic in self.settings.subscribe_topics:
            LOGGER.info("Subscribing to %s", topic)
            client.subscribe(topic)

    def _on_disconnect(self, _client: mqtt.Client, _userdata: Any, _flags: Any, reason_code: Any, _properties: Any = None) -> None:
        self.connected = False
        LOGGER.warning("MQTT disconnected: %s", reason_code)

    def _on_subscribe(self, _client: mqtt.Client, _userdata: Any, mid: int, reason_codes: Any, _properties: Any = None) -> None:
        codes_iter = reason_codes if isinstance(reason_codes, (list, tuple)) else [reason_codes]
        values = [getattr(rc, "value", rc) for rc in codes_iter]
        rejected = [v for v in values if isinstance(v, int) and v >= 128]
        if rejected:
            LOGGER.error("Broker REJECTED subscribe mid=%s codes=%s (likely ACL denial)", mid, values)
        else:
            LOGGER.info("Broker confirmed subscribe mid=%s codes=%s", mid, values)

    def _on_message(self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage) -> None:
        received_at = int(time.time())
        payload = bytes(msg.payload)
        payload_hash = hashlib.sha256(payload).hexdigest()
        payload_base64 = base64.b64encode(payload).decode("ascii")
        topic = msg.topic
        LOGGER.info("Received MQTT message on %s (%d bytes, retain=%s)", topic, len(payload), msg.retain)

        payload_json = None
        data: dict[str, Any] | None = None
        try:
            parsed = json.loads(payload.decode("utf-8"))
            if isinstance(parsed, dict):
                data = parsed
                payload_json = json.dumps(parsed, separators=(",", ":"), sort_keys=True)
        except (UnicodeDecodeError, json.JSONDecodeError):
            LOGGER.info("Payload on %s is not JSON (likely encrypted/protobuf) — stored as raw frame only", topic)

        packet_id = _packet_id(data) if data else None
        self.db.insert_raw_frame(topic, payload_hash, packet_id, payload_base64, payload_json, received_at)

        if not data:
            return

        normalized = normalize_json_message(topic, payload_hash, data)
        if not normalized:
            LOGGER.info("JSON on %s had no text field — stored raw, skipped chat archive (keys=%s)", topic, list(data.keys()))
            return
        LOGGER.info("Archived message: conv=%s from=%s text=%r", normalized["conversation_key"], normalized.get("sender_node_id"), normalized["text"][:60])

        self.db.upsert_node(
            normalized.get("sender_node_id"),
            normalized.get("sender_node_num"),
            normalized.get("sender_long_name"),
            normalized.get("sender_short_name"),
            payload_json,
            normalized["timestamp"],
        )
        self.db.ensure_conversation(
            normalized["conversation_key"],
            normalized["conversation_title"],
            normalized.get("channel"),
            normalized["timestamp"],
        )
        self.db.insert_message(normalized)
