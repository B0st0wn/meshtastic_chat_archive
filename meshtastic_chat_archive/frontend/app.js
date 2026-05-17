const DEFAULT_POLL_SECONDS = 7;

class MeshtasticChatPanel extends HTMLElement {
  constructor() {
    super();
    this.apiBase = "";
    this.basePath = new URL(".", window.location.href).pathname;
    this.pollSeconds = DEFAULT_POLL_SECONDS;
    this.conversations = [];
    this.messages = [];
    this.activeKey = "";
    this.searchMode = false;
    this.timer = null;
  }

  set hass(value) {
    this._hass = value;
  }

  set panel(value) {
    this._panel = value;
    if (value?.config?.apiBase) this.apiBase = value.config.apiBase.replace(/\/$/, "");
    if (value?.config?.pollSeconds) this.pollSeconds = Number(value.config.pollSeconds);
  }

  connectedCallback() {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
      this.render();
      this.bindEvents();
    }
    this.load();
    this.timer = window.setInterval(() => this.refresh(), this.pollSeconds * 1000);
  }

  disconnectedCallback() {
    if (this.timer) window.clearInterval(this.timer);
  }

  async api(path, options = {}) {
    const cleanPath = path.replace(/^\//, "");
    const url = this.apiBase ? `${this.apiBase}/${cleanPath}` : `${this.basePath}${cleanPath}`;
    const response = await fetch(url, {
      headers: { "content-type": "application/json" },
      ...options,
    });
    if (!response.ok) throw new Error(await response.text());
    return response.json();
  }

  async load() {
    await this.loadConversations();
    if (!this.activeKey && this.conversations.length) this.activeKey = this.conversations[0].conversation_key;
    await this.loadMessages();
  }

  async refresh() {
    if (this.searchMode) return;
    await this.loadConversations(true);
    if (this.activeKey) await this.loadMessages(true);
  }

  async loadConversations(shouldRender = true) {
    this.conversations = await this.api("/api/conversations");
    if (shouldRender) this.renderConversations();
  }

  async loadMessages(shouldRender = true) {
    if (!this.activeKey) {
      this.messages = [];
    } else {
      this.messages = await this.api(`/api/messages?conversation_key=${encodeURIComponent(this.activeKey)}&limit=100`);
    }
    if (shouldRender) {
      this.renderConversations();
      this.renderMessages();
    }
  }

  async search(query) {
    const q = query.trim();
    this.searchMode = q.length > 0;
    if (!this.searchMode) {
      await this.load();
      return;
    }
    this.messages = await this.api(`/api/search?q=${encodeURIComponent(q)}`);
    this.renderMessages("Search results");
  }

  async sendMessage(text) {
    await this.api("/api/send", {
      method: "POST",
      body: JSON.stringify({ text, channel: this.currentConversation()?.channel }),
    });
    await this.refresh();
  }

  currentConversation() {
    return this.conversations.find((item) => item.conversation_key === this.activeKey);
  }

  bindEvents() {
    const root = this.shadowRoot;
    root.querySelector(".conversation-list").addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-key]");
      if (!button) return;
      this.activeKey = button.dataset.key;
      this.searchMode = false;
      root.querySelector(".search").value = "";
      await this.loadMessages();
    });

    root.querySelector(".search").addEventListener("input", (event) => {
      window.clearTimeout(this.searchDebounce);
      this.searchDebounce = window.setTimeout(() => this.search(event.target.value), 250);
    });

    root.querySelector(".message-list").addEventListener("click", async (event) => {
      const button = event.target.closest(".message-delete");
      if (!button) return;
      event.preventDefault();
      await this.deleteMessage(button.dataset.id);
    });

    root.querySelector(".composer").addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = root.querySelector(".composer-input");
      const text = input.value.trim();
      if (!text) return;
      input.disabled = true;
      try {
        await this.sendMessage(text);
        input.value = "";
      } catch (error) {
        root.querySelector(".status").textContent = "Send failed. Check SEND_TOPIC and MQTT access.";
      } finally {
        input.disabled = false;
        input.focus();
      }
    });
  }

  render() {
    this.shadowRoot.innerHTML = `
      <link rel="stylesheet" href="${this.assetUrl("static/style.css")}">
      <main class="shell">
        <aside class="sidebar">
          <div class="brand">
            <div>
              <h1>Mesh Chat</h1>
              <p>Meshtastic archive</p>
            </div>
          </div>
          <input class="search" type="search" placeholder="Search messages" />
          <nav class="conversation-list" aria-label="Conversations"></nav>
        </aside>
        <section class="chat">
          <header class="chat-header">
            <div>
              <h2 class="chat-title">No conversation</h2>
              <p class="chat-subtitle"></p>
            </div>
            <span class="status">Auto-refresh on</span>
          </header>
          <div class="message-list"></div>
          <form class="composer">
            <input class="composer-input" type="text" maxlength="4096" placeholder="Send a message" />
            <button type="submit">Send</button>
          </form>
        </section>
      </main>
    `;
  }

  renderConversations() {
    const list = this.shadowRoot.querySelector(".conversation-list");
    list.innerHTML = this.conversations.map((conversation) => {
      const active = conversation.conversation_key === this.activeKey ? "active" : "";
      const time = conversation.last_message_at ? this.formatTime(conversation.last_message_at) : "";
      return `
        <button class="conversation ${active}" data-key="${this.escape(conversation.conversation_key)}">
          <span class="conversation-title">${this.escape(conversation.title)}</span>
          <span class="conversation-time">${time}</span>
          <span class="conversation-preview">${this.escape(conversation.last_message_text || "No messages yet")}</span>
        </button>
      `;
    }).join("");
  }

  renderMessages(titleOverride = "") {
    const conversation = this.currentConversation();
    this.shadowRoot.querySelector(".chat-title").textContent = titleOverride || conversation?.title || "Mesh Chat";
    this.shadowRoot.querySelector(".chat-subtitle").textContent = conversation?.conversation_key || "";

    const list = this.shadowRoot.querySelector(".message-list");
    if (!this.messages.length) {
      list.innerHTML = `<div class="empty">No archived messages yet.</div>`;
      return;
    }

    list.innerHTML = this.messages.map((message) => {
      const sender = message.sender_long_name || message.sender_short_name || message.sender_node_id || "Unknown";
      const short = message.sender_short_name ? ` (${this.escape(message.sender_short_name)})` : "";
      const channel = message.channel ? `#${this.escape(message.channel)}` : "mesh";
      return `
        <article class="message" data-id="${message.id}">
          <div class="message-meta">
            <strong>${this.escape(sender)}${short}</strong>
            <span>${this.escape(message.sender_node_id || "")}</span>
            <span>${this.formatDateTime(message.timestamp)}</span>
            <span>${channel}</span>
            <button class="message-delete" data-id="${message.id}" title="Delete this message" aria-label="Delete this message">×</button>
          </div>
          <p>${this.escape(message.text)}</p>
        </article>
      `;
    }).join("");
    list.scrollTop = list.scrollHeight;
  }

  async deleteMessage(id) {
    if (!window.confirm("Delete this message permanently?")) return;
    try {
      await this.api(`/api/messages/${id}`, { method: "DELETE" });
      await this.refresh();
    } catch (error) {
      this.shadowRoot.querySelector(".status").textContent = "Delete failed.";
    }
  }

  formatTime(unix) {
    return new Date(unix * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  formatDateTime(unix) {
    return new Date(unix * 1000).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  escape(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;",
    })[char]);
  }

  assetUrl(path) {
    const cleanPath = path.replace(/^\//, "");
    return this.apiBase ? `${this.apiBase}/${cleanPath}` : `${this.basePath}${cleanPath}`;
  }
}

if (!customElements.get("meshtastic-chat-panel")) {
  customElements.define("meshtastic-chat-panel", MeshtasticChatPanel);
}

if (!customElements.get("ha-panel-meshtastic-chat")) {
  customElements.define("ha-panel-meshtastic-chat", MeshtasticChatPanel);
}
