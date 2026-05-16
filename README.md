# Meshtastic Chat Archive Add-on

Home Assistant add-on that runs a Meshtastic MQTT chat archive web app. It subscribes to user-configured MQTT topics, stores messages in an external MariaDB database, and serves a chat-style UI through Home Assistant ingress or direct port `8124`.

This is an app/add-on, not a Home Assistant integration. It does not use Home Assistant Recorder as its primary message database.

## What It Does

- Subscribes to one or more MQTT topics entered in the add-on options.
- Works with local brokers or public MQTT servers.
- Stores normalized JSON text messages in external MariaDB.
- Stores raw MQTT payloads as base64 frames for future protobuf parsing.
- Deduplicates by packet ID when available, with SHA256 payload hash fallback.
- Maintains `nodes`, `conversations`, `messages`, and `raw_frames` tables.
- Provides a web chat UI with conversations, messages, search, and auto-refresh.
- Supports optional outbound MQTT publishing via `send_topic`.

## Recommended Topics

Broad Meshtastic defaults:

```text
msh/+/2/json/+/+
msh/+/2/e/+/+
msh/+/2/c/+/+
```

Specific public/local channel example:

```text
msh/US/2/json/HOME/+
```

Specific node example:

```text
msh/US/2/json/HOME/!f66f8014
```

## MariaDB Requirement

This add-on expects an external MariaDB server. You can use:

- The Home Assistant MariaDB add-on, commonly reachable as `core-mariadb`.
- A MariaDB container on Unraid.
- A MariaDB server elsewhere on your LAN.

Create a database/user ahead of time if your database user cannot create databases:

```sql
CREATE DATABASE meshtastic_chat CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'meshtastic'@'%' IDENTIFIED BY 'change-this-db-password';
GRANT ALL PRIVILEGES ON meshtastic_chat.* TO 'meshtastic'@'%';
FLUSH PRIVILEGES;
```

## Add-on Options

```yaml
mqtt_host: core-mosquitto
mqtt_port: 1883
mqtt_username: ""
mqtt_password: ""
mqtt_tls: false
mqtt_client_id: meshtastic-chat-archive
mqtt_topics:
  - msh/+/2/json/+/+
  - msh/+/2/e/+/+
  - msh/+/2/c/+/+
db_host: core-mariadb
db_port: 3306
db_name: meshtastic_chat
db_user: meshtastic
db_password: change-this-db-password
send_topic: ""
poll_interval_seconds: 7
```

For a public MQTT server, set `mqtt_host`, `mqtt_port`, credentials, and `mqtt_tls` as required by that server.

## API

- `GET /api/health`
- `GET /api/conversations`
- `GET /api/messages?conversation_key=<key>&limit=100&before=<unix_ts>`
- `GET /api/search?q=<text>`
- `POST /api/send`

Conversation keys use:

- `channel:<channel_name>`
- `dm:<lower_node_num>:<higher_node_num>`
- `system:mesh`

## Direct Docker Use

The same app can run outside Home Assistant:

```bash
cp .env.example .env
docker compose up -d --build
```

For Docker use, set `DB_HOST` to your external MariaDB host. The compose file intentionally does not start MariaDB for you.

## Security

Do not expose this app or MariaDB directly to the internet. Treat the database as sensitive message history. Use Home Assistant ingress, VPN, or an authenticated reverse proxy.
