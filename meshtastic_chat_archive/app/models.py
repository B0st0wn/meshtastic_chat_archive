from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    ok: bool
    mqtt_connected: bool
    database: str


class Conversation(BaseModel):
    conversation_key: str
    title: str
    channel: str | None = None
    last_message_at: int | None = None
    last_message_text: str | None = None
    message_count: int = 0


class Message(BaseModel):
    id: int
    packet_id: str | None = None
    conversation_key: str
    sender_node_id: str | None = None
    sender_long_name: str | None = None
    sender_short_name: str | None = None
    recipient_node_id: str | None = None
    timestamp: int
    channel: str | None = None
    topic: str
    text: str


class SendRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    topic: str | None = None
    channel: str | None = None
    destination: str | None = None


class SendResponse(BaseModel):
    ok: bool
    topic: str
