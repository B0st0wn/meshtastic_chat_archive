import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from db import Database
from models import Conversation, HealthResponse, Message, SendRequest, SendResponse
from mqtt_worker import MqttWorker
from settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

settings = get_settings()
db = Database(settings)
mqtt_worker = MqttWorker(settings, db)


def row_to_message(row) -> Message:
    return Message(
        id=row["id"],
        packet_id=row["packet_id"],
        conversation_key=row["conversation_key"],
        sender_node_id=row["sender_node_id"],
        sender_long_name=row["sender_long_name"],
        sender_short_name=row["sender_short_name"],
        recipient_node_id=row["recipient_node_id"],
        timestamp=row["timestamp"],
        channel=row["channel"],
        topic=row["topic"],
        text=row["text"],
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    mqtt_worker.start()
    yield
    mqtt_worker.stop()
    db.close()


app = FastAPI(title="Meshtastic Chat Archive", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(ok=True, mqtt_connected=mqtt_worker.connected, database=settings.database_label)


@app.get("/api/conversations", response_model=list[Conversation])
def conversations() -> list[Conversation]:
    return [Conversation(**dict(row)) for row in db.get_conversations()]


@app.get("/api/messages", response_model=list[Message])
def messages(
    conversation_key: str,
    limit: int = Query(default=100, ge=1, le=500),
    before: int | None = None,
) -> list[Message]:
    return [row_to_message(row) for row in db.get_messages(conversation_key, limit, before)]


@app.get("/api/search", response_model=list[Message])
def search(q: str = Query(min_length=1)) -> list[Message]:
    return [row_to_message(row) for row in db.search_messages(q)]


@app.post("/api/send", response_model=SendResponse)
def send(request: SendRequest) -> SendResponse:
    try:
        topic = mqtt_worker.publish_text(request.text, request.topic, request.channel, request.destination)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return SendResponse(ok=True, topic=topic)


if settings.frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=settings.frontend_dir), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    index_path = settings.frontend_dir / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    html = index_path.read_text(encoding="utf-8")
    js_path = settings.frontend_dir / "app.js"
    css_path = settings.frontend_dir / "style.css"
    js_bust = str(int(js_path.stat().st_mtime)) if js_path.exists() else "0"
    css_bust = str(int(css_path.stat().st_mtime)) if css_path.exists() else "0"
    html = html.replace("static/app.js", f"static/app.js?v={js_bust}")
    html = html.replace("static/style.css", f"static/style.css?v={css_bust}")
    response = HTMLResponse(content=html)
    response.headers["Cache-Control"] = "no-store"
    return response
