(function () {
  "use strict";

  const API_BASE = "/api";

  let currentThreadId = null;
  let isStreaming = false;
  let pendingFiles = [];
  let threadCache = [];

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const elMessages = $("#chatMessages");
  const elInput = $("#messageInput");
  const elSend = $("#btnSend");
  const elModelSelect = $("#modelSelect");
  const elThreadList = $("#threadList");
  const elFileInput = $("#fileInput");
  const elUploadFiles = $("#uploadFiles");
  const elWelcome = $("#welcomeScreen");
  const elToggleThinking = $("#toggleThinking");
  const elToggleSubagent = $("#toggleSubagent");
  const elSearchThreads = $("#searchThreads");

  function generateId() {
    return crypto.randomUUID ? crypto.randomUUID() : "id-" + Date.now() + "-" + Math.random().toString(36).slice(2, 9);
  }

  function scrollToBottom() {
    requestAnimationFrame(() => {
      elMessages.scrollTop = elMessages.scrollHeight;
    });
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  function renderMarkdown(text) {
    let html = escapeHtml(text);
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
      return `<pre><code class="lang-${lang}">${code}</code></pre>`;
    });
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    html = html.replace(/\n/g, "<br>");
    return html;
  }

  function addMessage(role, content, extra) {
    if (elWelcome) elWelcome.style.display = "none";

    const div = document.createElement("div");
    div.className = `message ${role}`;

    const avatar = document.createElement("div");
    avatar.className = "message-avatar";
    avatar.textContent = role === "user" ? "U" : "AI";

    const body = document.createElement("div");
    body.className = "message-content";

    if (extra && extra.toolCalls) {
      extra.toolCalls.forEach((tc) => {
        const tcEl = document.createElement("div");
        tcEl.className = "tool-call";
        tcEl.innerHTML = `<span class="tool-name">${escapeHtml(tc.name || "tool")}</span> ${escapeHtml(tc.args ? JSON.stringify(tc.args).slice(0, 200) : "")}`;
        body.appendChild(tcEl);
      });
    }

    if (content) {
      const textEl = document.createElement("div");
      textEl.className = "message-text";
      textEl.innerHTML = renderMarkdown(content);
      body.appendChild(textEl);
    }

    if (role === "ai" && !content && !(extra && extra.toolCalls)) {
      const indicator = document.createElement("span");
      indicator.className = "typing-indicator";
      body.appendChild(indicator);
    }

    div.appendChild(avatar);
    div.appendChild(body);
    elMessages.appendChild(div);
    scrollToBottom();

    return body;
  }

  function appendToMessage(body, delta) {
    let textEl = body.querySelector(".message-text");
    if (!textEl) {
      const indicator = body.querySelector(".typing-indicator");
      if (indicator) indicator.remove();
      textEl = document.createElement("div");
      textEl.className = "message-text";
      body.appendChild(textEl);
    }
    const raw = (textEl._raw || "") + delta;
    textEl._raw = raw;
    textEl.innerHTML = renderMarkdown(raw);
    scrollToBottom();
  }

  function setLoading(loading) {
    isStreaming = loading;
    elSend.disabled = loading;
    elInput.disabled = loading;
    if (loading) {
      elSend.querySelector("svg").style.opacity = "0.5";
    } else {
      elSend.querySelector("svg").style.opacity = "1";
    }
  }

  async function loadModels() {
    try {
      const res = await fetch(`${API_BASE}/models`);
      const data = await res.json();
      elModelSelect.innerHTML = "";
      (data.models || []).forEach((m) => {
        const opt = document.createElement("option");
        opt.value = m.name;
        opt.textContent = m.display_name || m.name;
        elModelSelect.appendChild(opt);
      });
    } catch (e) {
      console.error("Failed to load models", e);
    }
  }

  async function loadThreads() {
    try {
      const res = await fetch(`${API_BASE}/threads?limit=50`);
      const data = await res.json();
      threadCache = data.thread_list || [];
      renderThreads(threadCache);
    } catch (e) {
      console.error("Failed to load threads", e);
    }
  }

  function renderThreads(threads) {
    const keyword = elSearchThreads.value.trim().toLowerCase();
    const filtered = keyword
      ? threads.filter((t) => (t.title || t.thread_id || "").toLowerCase().includes(keyword))
      : threads;

    elThreadList.innerHTML = "";
    filtered.forEach((t) => {
      const item = document.createElement("div");
      item.className = "thread-item" + (t.thread_id === currentThreadId ? " active" : "");
      item.dataset.threadId = t.thread_id;

      const title = document.createElement("span");
      title.className = "thread-title";
      title.textContent = t.title || t.thread_id || "新对话";

      const del = document.createElement("button");
      del.className = "thread-delete";
      del.textContent = "×";
      del.onclick = (e) => {
        e.stopPropagation();
        item.remove();
      };

      item.appendChild(title);
      item.appendChild(del);
      item.onclick = () => switchThread(t.thread_id);
      elThreadList.appendChild(item);
    });
  }

  function switchThread(threadId) {
    currentThreadId = threadId;
    elMessages.querySelectorAll(".message").forEach((m) => m.remove());
    if (elWelcome) elWelcome.style.display = "flex";

    $$(".thread-item").forEach((item) => {
      item.classList.toggle("active", item.dataset.threadId === threadId);
    });

    loadThreadMessages(threadId);
  }

  async function loadThreadMessages(threadId) {
    try {
      const res = await fetch(`${API_BASE}/threads/${threadId}`);
      const data = await res.json();
      const checkpoints = data.checkpoints || [];
      if (checkpoints.length === 0) return;

      const latest = checkpoints[checkpoints.length - 1];
      const messages = (latest && latest.messages) || [];

      if (elWelcome) elWelcome.style.display = "none";
      elMessages.querySelectorAll(".message").forEach((m) => m.remove());

      messages.forEach((msg) => {
        if (msg.type === "human") {
          addMessage("user", msg.content);
        } else if (msg.type === "ai") {
          addMessage("ai", msg.content);
        } else if (msg.type === "tool") {
          addMessage("ai", `[Tool: ${msg.name}] ${msg.content}`, { toolCalls: [{ name: msg.name }] });
        }
      });
      scrollToBottom();
    } catch (e) {
      console.error("Failed to load thread messages", e);
    }
  }

  function newChat() {
    currentThreadId = null;
    elMessages.querySelectorAll(".message").forEach((m) => m.remove());
    if (elWelcome) elWelcome.style.display = "flex";
    $$(".thread-item").forEach((item) => item.classList.remove("active"));
  }

  async function sendMessage() {
    const text = elInput.value.trim();
    if (!text && pendingFiles.length === 0) return;
    if (isStreaming) return;

    const messageText = text;
    elInput.value = "";
    elInput.style.height = "auto";
    updateSendButton();

    if (!currentThreadId) {
      currentThreadId = generateId();
      const item = document.createElement("div");
      item.className = "thread-item active";
      item.dataset.threadId = currentThreadId;
      const title = document.createElement("span");
      title.className = "thread-title";
      title.textContent = messageText.slice(0, 30) || "新对话";
      const del = document.createElement("button");
      del.className = "thread-delete";
      del.textContent = "×";
      del.onclick = (e) => {
        e.stopPropagation();
        item.remove();
      };
      item.appendChild(title);
      item.appendChild(del);
      item.onclick = () => switchThread(currentThreadId);
      elThreadList.insertBefore(item, elThreadList.firstChild);
    }

    if (pendingFiles.length > 0) {
      await uploadPendingFiles();
    }

    addMessage("user", messageText);

    const aiBody = addMessage("ai", "");
    setLoading(true);

    const payload = {
      message: messageText,
      thread_id: currentThreadId,
    };

    const selectedModel = elModelSelect.value;
    if (selectedModel) payload.model_name = selectedModel;
    if (elToggleThinking.checked) payload.thinking_enabled = true;
    else payload.thinking_enabled = false;
    if (elToggleSubagent.checked) payload.subagent_enabled = true;
    else payload.subagent_enabled = false;

    try {
      const res = await fetch(`${API_BASE}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6).trim();
          if (data === "[DONE]") continue;

          try {
            const event = JSON.parse(data);
            handleStreamEvent(event, aiBody);
          } catch (e) {
            // skip malformed
          }
        }
      }
    } catch (e) {
      console.error("Stream error", e);
      appendToMessage(aiBody, "\n\n[连接错误，请重试]");
    } finally {
      setLoading(false);
      loadThreads();
    }
  }

  function handleStreamEvent(event, aiBody) {
    const { type, data } = event;

    if (type === "messages-tuple") {
      if (data.type === "ai") {
        if (data.content) {
          appendToMessage(aiBody, data.content);
        }
        if (data.tool_calls) {
          data.tool_calls.forEach((tc) => {
            const tcEl = document.createElement("div");
            tcEl.className = "tool-call";
            tcEl.innerHTML = `<span class="tool-name">${escapeHtml(tc.name || "tool")}</span>`;
            aiBody.appendChild(tcEl);
            scrollToBottom();
          });
        }
      } else if (data.type === "tool") {
        const tcEl = document.createElement("div");
        tcEl.className = "tool-call";
        tcEl.innerHTML = `<span class="tool-name">${escapeHtml(data.name || "tool")}</span> ${escapeHtml((data.content || "").slice(0, 200))}`;
        aiBody.appendChild(tcEl);
        scrollToBottom();
      }
    } else if (type === "values") {
      // state snapshot - already handled by messages-tuple
    } else if (type === "custom") {
      // custom events
    } else if (type === "end") {
      // stream end
    }
  }

  async function uploadPendingFiles() {
    if (pendingFiles.length === 0) return;
    const fd = new FormData();
    pendingFiles.forEach((f) => fd.append("files", f));
    pendingFiles = [];
    renderUploadFiles();

    try {
      const res = await fetch(`${API_BASE}/upload/${currentThreadId}`, {
        method: "POST",
        body: fd,
      });
      const data = await res.json();
      if (!data.success) {
        console.error("Upload failed", data);
      }
    } catch (e) {
      console.error("Upload error", e);
    }
  }

  function renderUploadFiles() {
    elUploadFiles.innerHTML = "";
    pendingFiles.forEach((f, idx) => {
      const item = document.createElement("div");
      item.className = "upload-file-item";
      const name = document.createElement("span");
      name.textContent = f.name;
      const remove = document.createElement("span");
      remove.className = "file-remove";
      remove.textContent = "×";
      remove.onclick = () => {
        pendingFiles.splice(idx, 1);
        renderUploadFiles();
        updateSendButton();
      };
      item.appendChild(name);
      item.appendChild(remove);
      elUploadFiles.appendChild(item);
    });
  }

  function updateSendButton() {
    const hasText = elInput.value.trim().length > 0;
    const hasFiles = pendingFiles.length > 0;
    elSend.disabled = !hasText && !hasFiles;
  }

  function autoResize() {
    elInput.style.height = "auto";
    elInput.style.height = Math.min(elInput.scrollHeight, 150) + "px";
  }

  // Event listeners
  elInput.addEventListener("input", () => {
    autoResize();
    updateSendButton();
  });

  elInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  elSend.addEventListener("click", sendMessage);

  $("#btnNewChat").addEventListener("click", newChat);

  $("#btnSidebarToggle").addEventListener("click", () => {
    $("#sidebar").classList.toggle("collapsed");
  });

  $("#btnUpload").addEventListener("click", () => {
    elFileInput.click();
  });

  elFileInput.addEventListener("change", () => {
    for (const file of elFileInput.files) {
      pendingFiles.push(file);
    }
    elFileInput.value = "";
    renderUploadFiles();
    updateSendButton();
  });

  elSearchThreads.addEventListener("input", () => {
    renderThreads(threadCache);
  });

  // Init
  loadModels();
  loadThreads();
})();
