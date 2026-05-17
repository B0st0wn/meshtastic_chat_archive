from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8124, alias="APP_PORT")
    frontend_dir: Path = Field(default=Path("/frontend"), alias="FRONTEND_DIR")

    db_host: str = Field(default="mariadb", alias="DB_HOST")
    db_port: int = Field(default=3306, alias="DB_PORT")
    db_name: str = Field(default="meshtastic_chat", alias="DB_NAME")
    db_user: str = Field(default="meshtastic", alias="DB_USER")
    db_password: str = Field(default="meshtastic", alias="DB_PASSWORD")

    mqtt_host: str = Field(default="localhost", alias="MQTT_HOST")
    mqtt_port: int = Field(default=1883, alias="MQTT_PORT")
    mqtt_username: str | None = Field(default=None, alias="MQTT_USERNAME")
    mqtt_password: str | None = Field(default=None, alias="MQTT_PASSWORD")
    mqtt_client_id: str = Field(default="meshtastic-chat-archive", alias="MQTT_CLIENT_ID")
    mqtt_tls: bool = Field(default=False, alias="MQTT_TLS")
    mqtt_subscribe_topics: str = Field(
        default="msh/+/2/json/+/+,msh/+/2/e/+/+,msh/+/2/c/+/+",
        alias="MQTT_SUBSCRIBE_TOPICS",
    )
    send_topic: str | None = Field(default=None, alias="SEND_TOPIC")

    cors_origins: str = Field(default="*", alias="CORS_ORIGINS")

    @property
    def subscribe_topics(self) -> list[str]:
        raw_topics = self.mqtt_subscribe_topics.replace("\r", "\n").replace(",", "\n")
        return [topic.strip() for topic in raw_topics.splitlines() if topic.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def database_label(self) -> str:
        return f"mariadb://{self.db_user}@{self.db_host}:{self.db_port}/{self.db_name}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
