import threading
import time
from typing import Any

import pymysql
from pymysql.cursors import DictCursor

from settings import Settings


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.RLock()
        self._connect_with_retry()
        self._migrate()

    def _connect(self, database: str | None = None):
        return pymysql.connect(
            host=self.settings.db_host,
            port=self.settings.db_port,
            user=self.settings.db_user,
            password=self.settings.db_password,
            database=database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
        )

    def _ensure_database(self) -> None:
        conn = self._connect()
        escaped_name = self.settings.db_name.replace("`", "``")
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{escaped_name}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
            conn.commit()
        except pymysql.MySQLError:
            conn.close()
            existing = self._connect(database=self.settings.db_name)
            existing.close()
        finally:
            if conn.open:
                conn.close()

    def _connect_with_retry(self) -> None:
        last_error: Exception | None = None
        for attempt in range(1, 31):
            try:
                self._ensure_database()
                self.conn = self._connect(database=self.settings.db_name)
                return
            except pymysql.MySQLError as exc:
                last_error = exc
                time.sleep(min(attempt, 10))
        raise RuntimeError("Could not connect to MariaDB after 30 attempts") from last_error

    def _execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        self.conn.ping(reconnect=True)
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.lastrowid

    def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        self.conn.ping(reconnect=True)
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            return list(cur.fetchall())

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def _migrate(self) -> None:
        with self._lock:
            statements = [
                """
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id VARCHAR(32) PRIMARY KEY,
                    node_num BIGINT UNSIGNED NULL,
                    long_name VARCHAR(255) NULL,
                    short_name VARCHAR(64) NULL,
                    last_seen BIGINT NOT NULL,
                    metadata_json LONGTEXT NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """,
                """
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_key VARCHAR(255) PRIMARY KEY,
                    title VARCHAR(255) NOT NULL,
                    channel VARCHAR(255) NULL,
                    created_at BIGINT NOT NULL,
                    updated_at BIGINT NOT NULL,
                    last_message_at BIGINT NULL,
                    last_message_id BIGINT UNSIGNED NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """,
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    packet_id VARCHAR(128) NULL,
                    payload_hash CHAR(64) NOT NULL,
                    conversation_key VARCHAR(255) NOT NULL,
                    sender_node_id VARCHAR(32) NULL,
                    sender_node_num BIGINT UNSIGNED NULL,
                    sender_long_name VARCHAR(255) NULL,
                    sender_short_name VARCHAR(64) NULL,
                    recipient_node_id VARCHAR(32) NULL,
                    recipient_node_num BIGINT UNSIGNED NULL,
                    timestamp BIGINT NOT NULL,
                    channel VARCHAR(255) NULL,
                    topic VARCHAR(512) NOT NULL,
                    text TEXT NOT NULL,
                    normalized_json LONGTEXT NOT NULL,
                    created_at BIGINT NOT NULL,
                    UNIQUE KEY uq_messages_packet_id (packet_id),
                    UNIQUE KEY uq_messages_payload_hash (payload_hash),
                    KEY idx_messages_conversation_ts (conversation_key, timestamp DESC),
                    FULLTEXT KEY idx_messages_text (text),
                    CONSTRAINT fk_messages_conversation
                        FOREIGN KEY (conversation_key) REFERENCES conversations(conversation_key)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """,
                """
                CREATE TABLE IF NOT EXISTS raw_frames (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    topic VARCHAR(512) NOT NULL,
                    payload_hash CHAR(64) NOT NULL,
                    packet_id VARCHAR(128) NULL,
                    payload_base64 LONGTEXT NOT NULL,
                    payload_json LONGTEXT NULL,
                    received_at BIGINT NOT NULL,
                    UNIQUE KEY uq_raw_frames_payload_hash (payload_hash),
                    KEY idx_raw_frames_packet (packet_id)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
                """,
            ]
            for statement in statements:
                self._execute(statement)
            self.conn.commit()

    def upsert_node(
        self,
        node_id: str | None,
        node_num: int | None,
        long_name: str | None,
        short_name: str | None,
        metadata_json: str | None,
        seen_at: int,
    ) -> None:
        if not node_id and node_num is None:
            return
        key = node_id or f"!{node_num:08x}"
        with self._lock:
            self._execute(
                """
                INSERT INTO nodes(node_id, node_num, long_name, short_name, last_seen, metadata_json)
                VALUES(%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    node_num=COALESCE(VALUES(node_num), node_num),
                    long_name=COALESCE(VALUES(long_name), long_name),
                    short_name=COALESCE(VALUES(short_name), short_name),
                    last_seen=GREATEST(VALUES(last_seen), last_seen),
                    metadata_json=COALESCE(VALUES(metadata_json), metadata_json)
                """,
                (key, node_num, long_name, short_name, seen_at, metadata_json),
            )
            self.conn.commit()

    def ensure_conversation(self, conversation_key: str, title: str, channel: str | None, at: int) -> None:
        with self._lock:
            self._execute(
                """
                INSERT INTO conversations(conversation_key, title, channel, created_at, updated_at)
                VALUES(%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    title=VALUES(title),
                    channel=COALESCE(VALUES(channel), channel),
                    updated_at=VALUES(updated_at)
                """,
                (conversation_key, title, channel, at, at),
            )
            self.conn.commit()

    def insert_raw_frame(
        self,
        topic: str,
        payload_hash: str,
        packet_id: str | None,
        payload_base64: str,
        payload_json: str | None,
        received_at: int,
    ) -> bool:
        with self._lock:
            try:
                self._execute(
                    """
                    INSERT INTO raw_frames(topic, payload_hash, packet_id, payload_base64, payload_json, received_at)
                    VALUES(%s, %s, %s, %s, %s, %s)
                    """,
                    (topic, payload_hash, packet_id, payload_base64, payload_json, received_at),
                )
                self.conn.commit()
                return True
            except pymysql.err.IntegrityError:
                self.conn.rollback()
                return False

    def insert_message(self, message: dict[str, Any]) -> bool:
        now = int(time.time())
        with self._lock:
            try:
                message_id = self._execute(
                    """
                    INSERT INTO messages(
                        packet_id, payload_hash, conversation_key,
                        sender_node_id, sender_node_num, sender_long_name, sender_short_name,
                        recipient_node_id, recipient_node_num, timestamp, channel, topic,
                        text, normalized_json, created_at
                    )
                    VALUES(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        message.get("packet_id"),
                        message["payload_hash"],
                        message["conversation_key"],
                        message.get("sender_node_id"),
                        message.get("sender_node_num"),
                        message.get("sender_long_name"),
                        message.get("sender_short_name"),
                        message.get("recipient_node_id"),
                        message.get("recipient_node_num"),
                        message["timestamp"],
                        message.get("channel"),
                        message["topic"],
                        message["text"],
                        message["normalized_json"],
                        now,
                    ),
                )
            except pymysql.err.IntegrityError:
                self.conn.rollback()
                return False

            self._execute(
                """
                UPDATE conversations
                SET last_message_at=%s, last_message_id=%s, updated_at=%s
                WHERE conversation_key=%s
                """,
                (message["timestamp"], message_id, now, message["conversation_key"]),
            )
            self.conn.commit()
            return True

    def get_conversations(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._fetchall(
                """
                SELECT
                    c.conversation_key,
                    c.title,
                    c.channel,
                    c.last_message_at,
                    m.text AS last_message_text,
                    COUNT(all_m.id) AS message_count
                FROM conversations c
                LEFT JOIN messages m ON m.id = c.last_message_id
                LEFT JOIN messages all_m ON all_m.conversation_key = c.conversation_key
                GROUP BY c.conversation_key, c.title, c.channel, c.last_message_at, m.text, c.updated_at
                ORDER BY c.last_message_at IS NULL, c.last_message_at DESC, c.updated_at DESC
                """
            )

    def get_messages(self, conversation_key: str, limit: int, before: int | None) -> list[dict[str, Any]]:
        limit = min(max(limit, 1), 500)
        params: list[Any] = [conversation_key]
        where = "conversation_key = %s"
        if before is not None:
            where += " AND timestamp < %s"
            params.append(before)
        params.append(limit)
        with self._lock:
            rows = self._fetchall(
                f"""
                SELECT * FROM messages
                WHERE {where}
                ORDER BY timestamp DESC, id DESC
                LIMIT %s
                """,
                tuple(params),
            )
            return list(reversed(rows))

    def delete_message(self, message_id: int) -> bool:
        with self._lock:
            rows = self._fetchall(
                "SELECT payload_hash, conversation_key FROM messages WHERE id = %s",
                (message_id,),
            )
            if not rows:
                return False
            payload_hash = rows[0]["payload_hash"]
            conversation_key = rows[0]["conversation_key"]

            self._execute("DELETE FROM messages WHERE id = %s", (message_id,))
            self._execute("DELETE FROM raw_frames WHERE payload_hash = %s", (payload_hash,))

            remaining = self._fetchall(
                """
                SELECT id, timestamp FROM messages
                WHERE conversation_key = %s
                ORDER BY timestamp DESC, id DESC
                LIMIT 1
                """,
                (conversation_key,),
            )
            now = int(time.time())
            if remaining:
                self._execute(
                    """
                    UPDATE conversations
                    SET last_message_id = %s, last_message_at = %s, updated_at = %s
                    WHERE conversation_key = %s
                    """,
                    (remaining[0]["id"], remaining[0]["timestamp"], now, conversation_key),
                )
            else:
                self._execute(
                    """
                    UPDATE conversations
                    SET last_message_id = NULL, last_message_at = NULL, updated_at = %s
                    WHERE conversation_key = %s
                    """,
                    (now, conversation_key),
                )
            self.conn.commit()
            return True

    def search_messages(self, query: str) -> list[dict[str, Any]]:
        like = f"%{query}%"
        with self._lock:
            return self._fetchall(
                """
                SELECT * FROM messages
                WHERE text LIKE %s OR sender_long_name LIKE %s OR sender_short_name LIKE %s OR sender_node_id LIKE %s
                ORDER BY timestamp DESC, id DESC
                LIMIT 200
                """,
                (like, like, like, like),
            )
