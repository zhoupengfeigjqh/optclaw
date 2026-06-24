(function () {
  "use strict";

  const API_BASE = "/api";

  let currentThreadId = null;
  let hasThreadMessages = false;
  let isStreaming = false;
  let pendingFiles = [];
  let abortController = null;
  let threadCache = [];
  const modelMeta = {};

  const SUPPORTED_EXTS = new Set([".pdf", ".csv", ".txt", ".png", ".jpg", ".jpeg"]);

  function isSupportedFileType(file) {
    const ext = "." + file.name.split(".").pop().toLowerCase();
    return SUPPORTED_EXTS.has(ext);
  }

  function isImageOrVideo(file) {
    return file.type.startsWith("image/");
  }

  function currentModelSupportsVision() {
    const name = elModelSelect.value;
    return name && modelMeta[name] ? modelMeta[name].supports_vision : true;
  }

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
  const elTogglePlan = $("#togglePlan");
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

  function cleanContent(text) {
    if (!text) return text;
    if (Array.isArray(text)) {
      return text
        .filter(function (block) { return block && block.type === "text"; })
        .map(function (block) { return block.text || ""; })
        .join("\n")
        .trim();
    }
    if (typeof text !== "string") return String(text);
    text = text.replace(/<system-reminder>[\s\S]*?<\/system-reminder>/gi, "");
    text = text.replace(/\[ImageId:[^\]]*\]\s*This is an image\.\s*If the user needs to view or analyze this image.*?(?=\n|$)/gi, "");
    text = text.replace(/\[ImageId:[^\]]*\]/g, "");
    text = text.replace(/\n{3,}/g, "\n\n");
    return text.trim();
  }

  function renderMarkdown(text) {
    let html = escapeHtml(text);
    // Image markdown ![](path) → img tag, rewrite path to artifact URL
    html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, alt, url) => {
      const idx = url.indexOf('user-data/');
      if (idx !== -1) {
        url = `/api/threads/${currentThreadId}/artifacts/mnt/${url.slice(idx)}`;
      } else {
        // Knowledge base images: extract agent name and filename
        const km = url.match(/agents\/([^/]+)\/knowledge\/image\/(.+)/);
        if (km) {
          url = `/api/knowledge/image/${km[1]}/${km[2]}`;
        } else {
          const kd = url.match(/knowledge\/image\/(.+)/);
          if (kd) {
            url = `/api/knowledge/image/default/${kd[1]}`;
          }
        }
      }
      return `<img src="${url}" alt="${alt}" style="max-width:100%">`;
    });
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
      return `<pre><code class="lang-${lang}">${code}</code></pre>`;
    });
    // Markdown tables: match blocks of pipe-delimited rows
    html = html.replace(/((?:^\|.+\|$\n?)+)/gm, (block) => {
      const lines = block.trim().split(/\n/);
      if (lines.length < 2) return block;
      let result = '<table>';
      for (let i = 0; i < lines.length; i++) {
        const cells = lines[i].split('|').map(c => c.trim()).filter(c => c);
        if (cells.length === 0) continue;
        // Skip separator rows like |---|---|
        if (/^[-:]+$/.test(cells[0])) continue;
        const tag = i === 0 ? 'th' : 'td';
        result += '<tr>' + cells.map(c => `<${tag}>${c}</${tag}>`).join('') + '</tr>';
      }
      result += '</table>';
      return result;
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

    if (extra && extra.attachments && extra.attachments.length > 0) {
      const filesDiv = document.createElement("div");
      filesDiv.className = "message-files";
      extra.attachments.forEach((f) => {
        const item = document.createElement("span");
        item.className = "message-file-item";
        item.title = f.filename || f.name || "";
        item.textContent = "📄 " + (f.filename || f.name || "");
        item.style.cursor = "pointer";
        item.addEventListener("click", () => {
          const url = f.artifact_url || `/api/artifacts/${currentThreadId}/${f.filename}`;
          window.open(url, "_blank");
        });
        filesDiv.appendChild(item);
      });
      body.appendChild(filesDiv);
    }

    if (content) {
      const textEl = document.createElement("div");
      textEl.className = "message-text";
      textEl.innerHTML = renderMarkdown(cleanContent(content));
      body.appendChild(textEl);
    }

    if (role === "ai" && !content && !(extra && extra.toolCalls)) {
      const indicator = document.createElement("span");
      indicator.className = "syncing-indicator";
      indicator.textContent = "Syncing messages...";
      body.appendChild(indicator);
    }

    div.appendChild(avatar);
    div.appendChild(body);
    elMessages.appendChild(div);
    scrollToBottom();

    return body;
  }

  function appendToMessage(body, delta, deltaType) {
    const indicator = body.querySelector(".typing-indicator, .syncing-indicator");
    if (indicator) indicator.remove();

    if (deltaType === "reasoning_text") {
      let el = body.querySelector(".stream-reasoning");
      if (!el) {
        el = document.createElement("div");
        el.className = "stream-reasoning";
        body.appendChild(el);
      }
      el.textContent += delta;
      scrollToBottom();
      return;
    }

    if (deltaType === "tool_calls") {
      let el = body.querySelector(".stream-tool-calls");
      if (!el) {
        el = document.createElement("div");
        el.className = "stream-tool-calls";
        body.appendChild(el);
      }
      el.textContent += delta;
      scrollToBottom();
      return;
    }

    if (deltaType === "artifacts") {
      let filesDiv = body.querySelector(".message-files");
      if (!filesDiv) {
        filesDiv = document.createElement("div");
        filesDiv.className = "message-files";
        body.appendChild(filesDiv);
      }
      try {
        const files = JSON.parse(delta);
        files.forEach(function (f) {
          const item = document.createElement("span");
          item.className = "message-file-item";
          var filename = f.split("/").pop();
          item.title = filename;
          item.textContent = "\u{1F4C4} " + filename;
          item.style.cursor = "pointer";
          item.addEventListener("click", function () {
            var idx = f.indexOf("user-data/");
            if (idx !== -1) {
              window.open("/api/threads/" + currentThreadId + "/artifacts/mnt/" + f.slice(idx), "_blank");
            }
          });
          filesDiv.appendChild(item);
        });
      } catch (_) {}
      scrollToBottom();
      return;
    }

    let textEl = body.querySelector(".message-text");
    if (!textEl) {
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
    const btnNewChat = $("#btnNewChat");
    if (btnNewChat) {
      btnNewChat.disabled = loading;
      btnNewChat.style.opacity = loading ? "0.4" : "1";
      btnNewChat.style.pointerEvents = loading ? "none" : "auto";
    }
    $$(".thread-item").forEach((item) => {
      item.style.opacity = loading ? "0.4" : "1";
      item.style.pointerEvents = loading ? "none" : "auto";
    });
    const elStop = $("#btnStop");
    if (loading) {
      elSend.style.display = "none";
      if (elStop) elStop.style.display = "flex";
    } else {
      elSend.style.display = "flex";
      if (elStop) elStop.style.display = "none";
    }
  }

  async function loadModels() {
    try {
      const res = await fetch(`${API_BASE}/models`);
      const data = await res.json();
      elModelSelect.innerHTML = "";
      (data.models || []).forEach((m) => {
        modelMeta[m.name] = {
          supports_vision: m.supports_vision !== false,
          supports_thinking: m.supports_thinking,
        };
        const opt = document.createElement("option");
        opt.value = m.name;
        opt.textContent = (m.display_name || m.name) + (m.supports_vision ? "" : " (无视觉)");
        elModelSelect.appendChild(opt);
      });
      const saved = localStorage.getItem("optclaw_model");
      if (saved && elModelSelect.querySelector(`option[value="${saved}"]`)) {
        elModelSelect.value = saved;
      }
      updateUploadButtonForModel();
      updateThinkingToggleForModel();
    } catch (e) {
      console.error("Failed to load models", e);
    }
  }

  async function loadThreads() {
    try {
      let url = `${API_BASE}/threads?limit=10`;
      if (selectedAgentName) {
        url += `&agent_name=${encodeURIComponent(selectedAgentName)}`;
      }
      const res = await fetch(url);
      const data = await res.json();
      threadCache = data.thread_list || [];
      renderThreads(threadCache);
    } catch (e) {
      console.error("Failed to load threads", e);
    }
  }

  function createThreadItem(threadId, titleText, opts = {}) {
    const item = document.createElement("div");
    item.className = "thread-item" + (opts.active ? " active" : "");
    item.dataset.threadId = threadId;
    const title = document.createElement("span");
    title.className = "thread-title";
    title.textContent = titleText || "新对话";
    const del = document.createElement("button");
    del.className = "thread-delete";
    del.textContent = "×";
    del.onclick = opts.onDelete || (() => {});
    item.appendChild(title);
    item.appendChild(del);
    item.onclick = () => switchThread(threadId);
    return item;
  }

  function renderThreads(threads) {
    const keyword = elSearchThreads.value.trim().toLowerCase();
    const filtered = keyword
      ? threads.filter((t) => (t.title || t.thread_id || "").toLowerCase().includes(keyword))
      : threads;

    elThreadList.innerHTML = "";
    filtered.forEach((t) => {
      const item = createThreadItem(t.thread_id, t.title || t.thread_id, {
        active: t.thread_id === currentThreadId,
        onDelete: async (e) => {
          e.stopPropagation();
          if (!confirm("确定删除此对话？")) return;
          try {
            await fetch(`${API_BASE}/threads/${t.thread_id}`, { method: "DELETE" });
          } catch (err) {
            console.error("Delete thread failed", err);
          }
          if (currentThreadId === t.thread_id) newChat();
          item.remove();
        },
      });
      elThreadList.appendChild(item);
    });
  }

  function clearMessages(showWelcome = false) {
    elMessages.querySelectorAll(".message").forEach((m) => m.remove());
    if (elWelcome) elWelcome.style.display = showWelcome ? "flex" : "none";
  }

  function switchThread(threadId) {
    if (isStreaming) return;
    if (threadId === currentThreadId) return;
    currentThreadId = threadId;
    hasThreadMessages = true;
    clearMessages(true);


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
      const messages = (latest && latest.values && latest.values.messages) || [];

      clearMessages(false);

      messages.forEach((msg) => {
        if (msg.type === "human") {
          const c = cleanContent(msg.content);
          const attachments = (msg.additional_kwargs && msg.additional_kwargs.files) || null;
          if (c || attachments) addMessage("user", c || "", attachments ? { attachments } : undefined);
        } else if (msg.type === "ai") {
          const c = cleanContent(msg.content);
          if (c) addMessage("ai", c);
        }
      });
      scrollToBottom();
    } catch (e) {
      console.error("Failed to load thread messages", e);
    }
  }

  function newChat() {
    if (isStreaming) return;
    currentThreadId = null;
    hasThreadMessages = false;
    clearMessages(true);
    $$(".thread-item").forEach((item) => item.classList.remove("active"));

  }

  async function sendMessage() {
    const text = elInput.value.trim();
    if (!text && pendingFiles.length === 0) return;
    if (isStreaming) return;

    hasThreadMessages = true;

    // Filter out image/video files when model doesn't support vision
    if (!currentModelSupportsVision()) {
      const before = pendingFiles.length;
      pendingFiles = pendingFiles.filter((f) => !isImageOrVideo(f));
      if (pendingFiles.length < before) {
        renderUploadFiles();
        showUploadTip();
      }
    }

    elInput.value = "";
    elInput.style.height = "auto";
    updateSendButton();

    if (!currentThreadId) {
      currentThreadId = generateId();
      const item = createThreadItem(currentThreadId, text.slice(0, 30), {
        active: true,
        onDelete: (e) => { e.stopPropagation(); item.remove(); },
      });
      elThreadList.insertBefore(item, elThreadList.firstChild);
    }

    let uploadedFiles = [];
    if (pendingFiles.length > 0) {
      uploadedFiles = await uploadPendingFiles();
    }

    addMessage("user", text, { attachments: uploadedFiles });

    const aiBody = addMessage("ai", "");
    setLoading(true);

    const payload = {
      message: text,
      thread_id: currentThreadId,
      files: uploadedFiles.length > 0 ? uploadedFiles : undefined,
    };

    const selectedModel = elModelSelect.value;
    if (selectedModel) payload.model_name = selectedModel;
    payload.thinking_enabled = elToggleThinking.checked;
    payload.subagent_enabled = elToggleSubagent.checked;
    payload.plan_mode = elTogglePlan.checked;
    payload.agent_name = selectedAgentName || "";

    abortController = new AbortController();
    try {
      const res = await fetch(`${API_BASE}/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
        signal: abortController.signal,
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
      if (e.name === "AbortError") {
        appendToMessage(aiBody, "\n\n[对话已停止]");
      } else {
        console.error("Stream error", e);
        appendToMessage(aiBody, "\n\n[连接错误，请重试]");
      }
    } finally {
      abortController = null;
      const reasoningEl = aiBody.querySelector(".stream-reasoning");
      if (reasoningEl) reasoningEl.remove();
      const toolCallsEl = aiBody.querySelector(".stream-tool-calls");
      if (toolCallsEl) toolCallsEl.remove();
      setLoading(false);
      loadThreads();
    }
  }

  function stopStream() {
    if (abortController) {
      abortController.abort();
      abortController = null;
    }
    if (currentThreadId) {
      fetch(`${API_BASE}/chat/stop`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_id: currentThreadId }),
      }).catch(() => {});
    }
  }

  function handleStreamEvent(event, aiBody) {
    const { type, data } = event;

    if (type === "delta") {
      if (data.content) {
        const deltaType = data.delta_type || "text";
        appendToMessage(aiBody, data.content, deltaType);
      }
    } else if (type === "error") {
      appendToMessage(aiBody, "\n\n[服务错误: " + (data.message || "未知错误") + "]");
    } else if (type === "stopped") {
      appendToMessage(aiBody, "\n\n[对话已停止]");
    }
  }

  async function uploadPendingFiles() {
    if (pendingFiles.length === 0) return [];
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
        return [];
      }
      return data.files || [];
    } catch (e) {
      console.error("Upload error", e);
      return [];
    }
  }

  function renderUploadFiles() {
    elUploadFiles.innerHTML = "";
    pendingFiles.forEach((f) => {
      const item = document.createElement("div");
      item.className = "upload-file-item";
      const name = document.createElement("span");
      name.textContent = f.name;
      const remove = document.createElement("span");
      remove.className = "file-remove";
      remove.textContent = "×";
      remove.onclick = () => {
        pendingFiles = pendingFiles.filter((pf) => pf !== f);
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

  function updateUploadButtonForModel() {
    if (!currentModelSupportsVision()) {
      elFileInput.setAttribute("accept", "application/pdf,text/csv,text/plain");
    } else {
      elFileInput.setAttribute("accept", "application/pdf,text/csv,text/plain,image/png,image/jpeg");
    }
  }

  function updateThinkingToggleForModel() {
    const name = elModelSelect.value;
    const supports = name && modelMeta[name] ? modelMeta[name].supports_thinking : true;
    if (!supports) {
      elToggleThinking.checked = false;
      elToggleThinking.disabled = true;
    } else {
      elToggleThinking.disabled = false;
    }
    localStorage.setItem("optclaw_thinking", elToggleThinking.checked);
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

  const elStop = $("#btnStop");
  if (elStop) elStop.addEventListener("click", stopStream);

  $("#btnNewChat").addEventListener("click", newChat);

  $("#btnSidebarToggle").addEventListener("click", () => {
    $("#sidebar").classList.toggle("collapsed");
  });

  $("#btnUpload").addEventListener("click", () => {
    if (!currentModelSupportsVision() && pendingFiles.length === 0) {
      showUploadTip();
    }
    elFileInput.click();
  });

  function showUploadTip() {
    const tip = document.createElement("div");
    tip.className = "upload-tip";
    tip.textContent = "当前模型不支持图片/视频，已过滤";
    tip.style.cssText = "color:#f59e0b;font-size:12px;margin-top:4px;";
    elUploadFiles.appendChild(tip);
    setTimeout(() => tip.remove(), 3000);
  }

  elFileInput.addEventListener("change", () => {
    let added = 0;
    let rejected = 0;
    for (const file of elFileInput.files) {
      if (!isSupportedFileType(file)) {
        rejected++;
        continue;
      }
      if (!currentModelSupportsVision() && isImageOrVideo(file)) {
        rejected++;
        continue;
      }
      pendingFiles.push(file);
      added++;
    }
    elFileInput.value = "";
    renderUploadFiles();
    updateSendButton();
    if (rejected > 0) {
      alert("仅支持上传 pdf, csv, txt, png, jpg, jpeg 文件，已自动跳过不支持的类型。");
    }
  });

  elSearchThreads.addEventListener("input", () => {
    renderThreads(threadCache);
  });

  // Memory panel
  const elMemoryPanel = $("#memoryPanel");
  const elSkillsPanel = $("#skillsPanel");
  const elUploadsPanel = $("#uploadsPanel");
  const elAgentsPanel = $("#agentsPanel");
  const elPanelOverlay = $("#panelOverlay");
  const elMemoryList = $("#memoryList");
  const elSkillsList = $("#skillsList");
  const elUploadsList = $("#uploadsList");
  const elHealthBadge = $("#healthBadge");
  const elMemoryConfigGrid = $("#memoryConfigGrid");
  const elAgentBadgeLabel = $("#agentBadgeLabel");
  const elSkillsModal = $("#skillsModal");
  const elSkillsPopupList = $("#skillsPopupList");
  const elMcpBadge = $("#mcpBadge");
  const elMcpBadgeLabel = $("#mcpBadgeLabel");
  const elSkillsBadge = $("#skillsBadge");
  const elSkillsBadgeLabel = $("#skillsBadgeLabel");
  const elMcpPopupOverlay = $("#mcpPopupOverlay");
  const elMcpPopupList = $("#mcpPopupList");

  const elMcpPanel = $("#mcpPanel");
  const elMcpList = $("#mcpList");
  const elMcpModalOverlay = $("#mcpModalOverlay");

  const elToolsPanel = $("#toolsPanel");
  const elToolsList = $("#toolsList");

  let selectedAgentName = localStorage.getItem("optclaw_agent") || "";

  function openPanel(panel) {
    if (elPanelOverlay) elPanelOverlay.classList.add("visible");
    panel.classList.add("open");
  }

  function closeAllPanels() {
    if (elPanelOverlay) elPanelOverlay.classList.remove("visible");
    if (elMemoryPanel) elMemoryPanel.classList.remove("open");
    if (elSkillsPanel) elSkillsPanel.classList.remove("open");
    if (elUploadsPanel) elUploadsPanel.classList.remove("open");
    if (elAgentsPanel) elAgentsPanel.classList.remove("open");
    if (elMcpPanel) elMcpPanel.classList.remove("open");
    if (elToolsPanel) elToolsPanel.classList.remove("open");
  }

  function closeSkillsModal() {
    if (elSkillsModal) elSkillsModal.style.display = "none";
  }

  function updateAgentLabel() {
    if (elAgentBadgeLabel) {
      elAgentBadgeLabel.textContent = selectedAgentName ? "当前Agent为：" + selectedAgentName : "当前Agent为：默认";
    }
  }

  async function updateHeaderBadges() {
    try {
      const res = await fetch(`${API_BASE}/mcp`);
      const data = await res.json();
      const servers = data.mcpServers || {};
      const enabled = Object.entries(servers).filter(([, s]) => s.enabled);
      if (elMcpBadgeLabel) {
        elMcpBadgeLabel.textContent = "当前MCP个数：" + enabled.length + "个";
      }
    } catch (e) {
      if (elMcpBadgeLabel) elMcpBadgeLabel.textContent = "当前MCP个数：0个";
    }

    try {
      const res = await fetch(`${API_BASE}/skills`);
      const data = await res.json();
      const skills = data.skills || [];
      const enabled = skills.filter((s) => s.enabled);
      if (elSkillsBadgeLabel) {
        elSkillsBadgeLabel.textContent = "当前技能数：" + enabled.length + "个";
      }
    } catch (e) {
      if (elSkillsBadgeLabel) elSkillsBadgeLabel.textContent = "当前技能数：0个";
    }
  }


  async function refreshIntroHints() {
    const hintAgent = document.getElementById("introAgentHint");
    const hintSkills = document.getElementById("introSkillsHint");
    const hintMemory = document.getElementById("introMemoryHint");
    const hintMcp = document.getElementById("introMcpHint");
    if (!hintAgent && !hintSkills && !hintMemory && !hintMcp) return;

    if (hintAgent) {
      hintAgent.textContent = selectedAgentName || "默认";
    }

    if (hintSkills) {
      try {
        const res = await fetch(`${API_BASE}/skills`);
        const data = await res.json();
        const skills = data.skills || [];
        const enabled = skills.filter((s) => s.enabled).length;
        hintSkills.textContent = enabled + " 个已开启";
      } catch (e) {
        hintSkills.textContent = "--";
      }
    }

    if (hintMemory) {
      try {
        const res = await fetch(`${API_BASE}/memory${memAgentParam()}`);
        const data = await res.json();
        const facts = data.facts || data.memory_facts || [];
        hintMemory.textContent = facts.length + " 条事实";
      } catch (e) {
        hintMemory.textContent = "--";
      }
    }

    if (hintMcp) {
      try {
        const res = await fetch(`${API_BASE}/mcp`);
        const data = await res.json();
        const servers = data.mcpServers || {};
        const enabled = Object.values(servers).filter((s) => s.enabled).length;
        hintMcp.textContent = enabled + " 个已开启";
      } catch (e) {
        hintMcp.textContent = "--";
      }
    }

    const hintTools = document.getElementById("introToolsHint");
    if (hintTools) {
      try {
        const res = await fetch(`${API_BASE}/tools`);
        const data = await res.json();
        const tools = data.tools || [];
        const enabled = tools.filter((t) => t.enabled).length;
        hintTools.textContent = enabled + " 个已开启";
      } catch (e) {
        hintTools.textContent = "--";
      }
    }

    const hintKnowledge = document.getElementById("introKnowledgeHint");
    if (hintKnowledge) {
      try {
        const agent = selectedAgentName || "default";
        const res = await fetch(`${API_BASE}/knowledge/stats?agent_name=${encodeURIComponent(agent)}`);
        const data = await res.json();
        hintKnowledge.textContent = (data.total_documents || 0) + " 个文档";
      } catch (e) {
        hintKnowledge.textContent = "--";
      }
    }

    updateHeaderBadges();
  }

  updateAgentLabel();
  updateHeaderBadges();

  async function checkHealth() {
    if (!elHealthBadge) return;
    try {
      const res = await fetch(`${API_BASE}/health`);
      const data = await res.json();
      elHealthBadge.className = "health-badge " + (data.status === "ok" ? "ok" : "err");
      elHealthBadge.title = "服务状态: " + data.status;
    } catch (e) {
      elHealthBadge.className = "health-badge err";
      elHealthBadge.title = "服务状态: 不可达";
    }
  }

  // 退出按钮
  const elBtnLogout = $("#btnLogout");
  if (elBtnLogout) {
    elBtnLogout.addEventListener("click", () => {
      if (!confirm("确定要退出当前对话吗？")) return;
      // Notify backend to clean up background tasks, then reload
      fetch(`${API_BASE}/reset-agent`, { method: "POST" }).catch(() => {});
      sessionStorage.removeItem("optclaw_visited");
      window.location.reload();
    });
  }

  function memAgentParam() {
    return selectedAgentName ? `?agent_name=${encodeURIComponent(selectedAgentName)}` : "";
  }

  async function loadMemoryConfig() {
    if (!elMemoryConfigGrid) return;
    try {
      const [statusRes, modelsRes] = await Promise.all([
        fetch(`${API_BASE}/memory/config${memAgentParam()}`),
        fetch(`${API_BASE}/models`),
      ]);
      const data = await statusRes.json();
      const modelsData = await modelsRes.json();
      const availableModels = (modelsData.models || []).map((m) => m.name);
      const cfg = data.config || data;
      elMemoryConfigGrid.innerHTML = "";
      const labels = {
        enabled: "启用", storage_path: "存储路径", debounce_seconds: "防抖(秒)",
        max_facts: "最大事实数", fact_confidence_threshold: "置信度阈值",
        injection_enabled: "注入启用", max_injection_tokens: "最大注入Token", model_name: "模型"
      };
      for (const [k, v] of Object.entries(cfg)) {
        const item = document.createElement("div");
        item.className = "config-item";
        const isBool = typeof v === "boolean";
        const val = isBool ? (v ? "true" : "false") : String(v);
        item.innerHTML = `<div class="config-key">${labels[k] || k}</div>`;
        if (isBool) {
          item.innerHTML += `<select class="config-input" data-key="${k}"><option value="true" ${v?"selected":""}>是</option><option value="false" ${!v?"selected":""}>否</option></select>`;
        } else if (k === "model_name") {
          let opts = '<option value="">默认</option>';
          availableModels.forEach((m) => {
            opts += `<option value="${escapeHtml(m)}" ${v===m?"selected":""}>${escapeHtml(m)}</option>`;
          });
          item.innerHTML += `<select class="config-input" data-key="${k}">${opts}</select>`;
        } else if (k === "storage_path") {
          item.innerHTML += `<input class="config-input" data-key="${k}" value="${escapeHtml(val)}" readonly disabled style="opacity:0.5;cursor:not-allowed;" />`;
        } else {
          item.innerHTML += `<input class="config-input" data-key="${k}" value="${escapeHtml(val)}" />`;
        }
        elMemoryConfigGrid.appendChild(item);
      }
    } catch (e) {
      console.error("Failed to load memory config", e);
    }
  }

  async function saveMemoryConfig() {
    if (!elMemoryConfigGrid) return;
    if (!confirm("确定保存配置？将同时修改内存和config.yaml文件。")) return;
    const inputs = elMemoryConfigGrid.querySelectorAll(".config-input");
    const updates = {};
    inputs.forEach((el) => {
      const key = el.dataset.key;
      let val = el.value;
      if (val === "true") val = true;
      else if (val === "false") val = false;
      else if (!isNaN(val) && key !== "storage_path" && key !== "model_name") val = Number(val);
      updates[key] = val;
    });
    try {
      await fetch(`${API_BASE}/memory/update_config${memAgentParam()}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(updates),
      });
    } catch (e) {
      console.error("Save config failed", e);
    }
  }

  async function reloadMemory() {
    if (!confirm("确定刷新记忆？将重新加载配置。")) return;
    try {
      await fetch(`${API_BASE}/memory/reload${memAgentParam()}`, { method: "POST" });
      loadMemoryConfig();
      loadMemory();
    } catch (e) {
      console.error("Reload memory failed", e);
    }
  }

  async function loadMemory() {
    try {
      const res = await fetch(`${API_BASE}/memory${memAgentParam()}`);
      const data = await res.json();
      let facts = data.facts || data.memory_facts || [];
      const filterCategory = ($("#memoryFilterCategory") || {}).value || "";
      if (filterCategory) {
        facts = facts.filter((f) => (f.category || "") === filterCategory);
      }
      elMemoryList.innerHTML = "";
      if (facts.length === 0) {
        elMemoryList.innerHTML = '<div style="color:var(--text-muted);font-size:13px;text-align:center;padding:20px;">暂无记忆数据</div>';
        refreshIntroHints();
        return;
      }
      facts.forEach((f) => {
        const item = document.createElement("div");
        item.className = "fact-item";
        const fid = f.id || f.fact_id || "";
        const createdTime = f.createdAt ? new Date(f.createdAt).toLocaleString() : "";
        const metaParts = [escapeHtml(f.category || ""), `置信度 ${(f.confidence || 0).toFixed(2)}`];
        if (createdTime) metaParts.push(createdTime);
        item.innerHTML = `
          <div class="fact-body">
            <div class="fact-content">${escapeHtml(f.content || f.text || "")}</div>
            <div class="fact-meta">${metaParts.join(" · ")}</div>
          </div>
          <button class="btn-fact-edit" title="编辑">✎</button>
          <button class="btn-fact-delete" title="删除">×</button>
        `;
        item.querySelector(".btn-fact-delete").onclick = async () => {
          if (!fid) return;
          if (!confirm("确定删除此记忆事实？")) return;
          try {
            await fetch(`${API_BASE}/memory/facts/${fid}${memAgentParam()}`, { method: "DELETE" });
          } catch (err) { console.error("Delete fact failed", err); }
          loadMemory();
        };
        item.querySelector(".btn-fact-edit").onclick = () => {
          const body = item.querySelector(".fact-body");
          body.innerHTML = `
            <div class="fact-edit-form">
              <label class="edit-label">内容</label>
              <input type="text" class="edit-content" value="${escapeHtml(f.content || f.text || "")}" />
              <label class="edit-label">类别</label>
              <select class="edit-category">
                <option value="preference" ${f.category==="preference"?"selected":""}>偏好 (preference)</option>
                <option value="knowledge" ${f.category==="knowledge"?"selected":""}>知识 (knowledge)</option>
                <option value="context" ${(f.category||"")==="context"?"selected":""}>背景 (context)</option>
                <option value="behavior" ${f.category==="behavior"?"selected":""}>行为 (behavior)</option>
                <option value="goal" ${f.category==="goal"?"selected":""}>目标 (goal)</option>
                <option value="correction" ${f.category==="correction"?"selected":""}>纠正 (correction)</option>
              </select>
              <label class="edit-label">置信度</label>
              <input type="number" class="edit-confidence" value="${f.confidence||0.5}" step="0.1" min="0" max="1" />
              ${createdTime ? `<label class="edit-label">创建时间</label><div class="edit-readonly">${createdTime}</div>` : ""}
              <div class="fact-edit-actions">
                <button class="fact-edit-save">保存</button>
                <button class="fact-edit-cancel">取消</button>
              </div>
            </div>
          `;
          body.querySelector(".fact-edit-save").onclick = async () => {
            const nc = body.querySelector(".edit-content").value;
            const ncat = body.querySelector(".edit-category").value;
            const nconf = parseFloat(body.querySelector(".edit-confidence").value) || 0.5;
            try {
              await fetch(`${API_BASE}/memory/facts/${fid}${memAgentParam()}`, {
                method: "PATCH",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ content: nc, category: ncat, confidence: nconf }),
              });
            } catch (err) { console.error("Update fact failed", err); }
            loadMemory();
          };
          body.querySelector(".fact-edit-cancel").onclick = () => { loadMemory(); };
        };
        elMemoryList.appendChild(item);
      });
    } catch (e) {
      console.error("Failed to load memory", e);
    }
    refreshIntroHints();
  }

  function openFactModal() {
    const overlay = $("#factModalOverlay");
    if (overlay) overlay.style.display = "flex";
    const contentEl = $("#modalFactContent");
    if (contentEl) { contentEl.value = ""; contentEl.focus(); }
    const confEl = $("#modalFactConfidence");
    if (confEl) confEl.value = "0.7";
  }

  function closeFactModal() {
    const overlay = $("#factModalOverlay");
    if (overlay) overlay.style.display = "none";
  }

  async function addMemoryFact() {
    const content = ($("#modalFactContent") || {}).value || "";
    const category = ($("#modalFactCategory") || {}).value || "context";
    const confidence = parseFloat(($("#modalFactConfidence") || {}).value) || 0.7;
    if (!content.trim()) return;
    try {
      await fetch(`${API_BASE}/memory/facts${memAgentParam()}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, category, confidence }),
      });
      closeFactModal();
      loadMemory();
    } catch (e) {
      console.error("Add fact failed", e);
    }
  }

  let skillChanges = {};
  let skillsCache = null;

  async function fetchSkills() {
    if (skillsCache) return skillsCache;
    const res = await fetch(`${API_BASE}/skills`);
    skillsCache = await res.json();
    return skillsCache;
  }

  async function loadSkills() {
    try {
      const data = await fetchSkills();
      const skills = data.skills || [];
      elSkillsList.innerHTML = "";
      skillChanges = {};
      if (skills.length === 0) {
        elSkillsList.innerHTML = '<div style="color:var(--text-muted);font-size:13px;text-align:center;padding:20px;">暂无技能</div>';
        return;
      }
      skills.forEach((s) => {
        const item = document.createElement("div");
        item.className = "skill-item";
        const enabled = s.enabled;
        const toggleCls = enabled ? "skill-toggle on" : "skill-toggle off";
        const toggleTxt = enabled ? "ON" : "OFF";
        const nameStyle = enabled ? "color:var(--text-primary)" : "color:var(--text-muted)";
        item.innerHTML = `
          <div class="skill-name" style="${nameStyle}">${escapeHtml(s.name || "")}<span class="skill-category">${escapeHtml(s.category || "")}</span></div>
          <div class="skill-desc">${escapeHtml(s.description || "")}</div>
          <button class="${toggleCls}" data-skill="${escapeHtml(s.name || "")}" data-enabled="${enabled}">${toggleTxt}</button>
        `;
        item.querySelector(".skill-toggle").onclick = (e) => {
          const btn = e.target;
          const currentEnabled = btn.dataset.enabled === "true";
          const newEnabled = !currentEnabled;
          btn.dataset.enabled = String(newEnabled);
          btn.textContent = newEnabled ? "ON" : "OFF";
          btn.className = newEnabled ? "skill-toggle on" : "skill-toggle off";
          const nameEl = item.querySelector(".skill-name");
          if (nameEl) nameEl.style.color = newEnabled ? "var(--text-primary)" : "var(--text-muted)";
          skillChanges[btn.dataset.skill] = newEnabled;
        };
        elSkillsList.appendChild(item);
      });
    } catch (e) {
      console.error("Failed to load skills", e);
    }
  }

  async function loadSkillsPopup() {
    if (!elSkillsPopupList) return;
    try {
      const data = await fetchSkills();
      const skills = (data.skills || []).filter((s) => s.enabled);
      elSkillsPopupList.innerHTML = "";
      if (skills.length === 0) {
        elSkillsPopupList.innerHTML = '<div class="skills-popup-empty">暂无已启用的技能</div>';
        return;
      }
      skills.forEach((s) => {
        const item = document.createElement("div");
        item.className = "skills-popup-item";
        item.innerHTML = `
          <span class="skills-popup-name">${escapeHtml(s.name || "")}</span>
          <span class="skills-popup-category">${escapeHtml(s.category || "")}</span>
          <span class="skills-popup-status on">启用</span>
        `;
        elSkillsPopupList.appendChild(item);
      });
    } catch (e) {
      console.error("Failed to load skills for popup", e);
    }
  }

  async function saveSkillConfig() {
    if (Object.keys(skillChanges).length === 0) {
      alert("没有修改任何技能配置");
      return;
    }
    if (!confirm("确定保存技能配置？")) return;
    try {
      for (const [name, enabled] of Object.entries(skillChanges)) {
        await fetch(`${API_BASE}/skills/${encodeURIComponent(name)}?enabled=${enabled}`, { method: "PATCH" });
      }
      skillChanges = {};
      skillsCache = null;
      loadSkills();
      refreshIntroHints();
    } catch (e) {
      console.error("Save skill config failed", e);
    }
  }

  function showInstallResult(success, message) {
    const el = $("#installResult");
    if (!el) return;
    el.className = "install-result " + (success ? "success" : "error");
    el.textContent = message;
    el.style.display = "block";
    setTimeout(() => { el.style.display = "none"; }, 5000);
  }

  async function installSkill() {
    const fileInput = $("#skillFileInput");
    if (!fileInput) return;
    fileInput.value = "";
    fileInput.click();
  }

  async function handleSkillFileUpload() {
    const fileInput = $("#skillFileInput");
    if (!fileInput || !fileInput.files || fileInput.files.length === 0) return;
    const file = fileInput.files[0];
    if (!file.name.endsWith(".skill")) {
      showInstallResult(false, "仅支持 .skill 后缀的文件");
      return;
    }
    const btn = $("#btnInstallSkill");
    if (btn) { btn.disabled = true; btn.textContent = "安装中..."; }
    try {
      const fd = new FormData();
      fd.append("file", file);
      const res = await fetch(`${API_BASE}/skills/install`, { method: "POST", body: fd });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showInstallResult(false, err.detail || "安装失败");
        return;
      }
      const data = await res.json();
      showInstallResult(true, `技能「${data.skill_name || file.name}」安装成功`);
      skillsCache = null;
      loadSkills();
    } catch (e) {
      showInstallResult(false, "安装失败: " + (e.message || e));
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = "安装技能"; }
    }
  }

  // ── Tools management ────────────────────────────────────────────────

  let toolChanges = {};

  async function loadTools() {
    if (!elToolsList) return;
    try {
      const res = await fetch(`${API_BASE}/tools`);
      const data = await res.json();
      const tools = data.tools || [];
      elToolsList.innerHTML = "";
      toolChanges = {};
      if (tools.length === 0) {
        elToolsList.innerHTML = '<div style="color:var(--text-muted);font-size:13px;text-align:center;padding:20px;">暂无工具</div>';
        return;
      }
      tools.forEach((t) => {
        const item = document.createElement("div");
        item.className = "skill-item";
        const enabled = t.enabled;
        const toggleCls = enabled ? "skill-toggle on" : "skill-toggle off";
        const toggleTxt = enabled ? "ON" : "OFF";
        const nameStyle = enabled ? "color:var(--text-primary)" : "color:var(--text-muted)";
        item.innerHTML = `
          <div class="skill-name" style="${nameStyle}">${escapeHtml(t.name)}<span class="skill-category">${escapeHtml(t.group || "")}</span></div>
          <button class="${toggleCls}" data-tool="${escapeHtml(t.name)}" data-enabled="${enabled}">${toggleTxt}</button>
        `;
        item.querySelector(".skill-toggle").onclick = (e) => {
          const btn = e.target;
          const currentEnabled = btn.dataset.enabled === "true";
          const newEnabled = !currentEnabled;
          btn.dataset.enabled = String(newEnabled);
          btn.textContent = newEnabled ? "ON" : "OFF";
          btn.className = newEnabled ? "skill-toggle on" : "skill-toggle off";
          const nameEl = item.querySelector(".skill-name");
          if (nameEl) nameEl.style.color = newEnabled ? "var(--text-primary)" : "var(--text-muted)";
          toolChanges[btn.dataset.tool] = newEnabled;
        };
        elToolsList.appendChild(item);
      });
    } catch (e) {
      console.error("Failed to load tools", e);
    }
  }

  async function saveToolConfig() {
    if (Object.keys(toolChanges).length === 0) {
      alert("没有修改任何工具配置");
      return;
    }
    if (!confirm("确定保存工具配置？")) return;
    try {
      for (const [name, enabled] of Object.entries(toolChanges)) {
        await fetch(`${API_BASE}/tools/${encodeURIComponent(name)}?enabled=${enabled}`, { method: "PATCH" });
      }
      toolChanges = {};
      loadTools();
      refreshIntroHints();
    } catch (e) {
      console.error("Save tool config failed", e);
    }
  }

  if ($("#btnCloseTools")) {
    $("#btnCloseTools").addEventListener("click", closeAllPanels);
  }
  if ($("#btnSaveToolConfig")) {
    $("#btnSaveToolConfig").addEventListener("click", saveToolConfig);
  }

  if ($("#btnCloseMemory")) {
    $("#btnCloseMemory").addEventListener("click", closeAllPanels);
  }
  if ($("#btnAddFact")) {
    $("#btnAddFact").addEventListener("click", openFactModal);
  }
  if ($("#btnCloseFactModal")) {
    $("#btnCloseFactModal").addEventListener("click", closeFactModal);
  }
  if ($("#btnCancelFactModal")) {
    $("#btnCancelFactModal").addEventListener("click", closeFactModal);
  }
  if ($("#btnConfirmFactModal")) {
    $("#btnConfirmFactModal").addEventListener("click", addMemoryFact);
  }
  if ($("#memoryFilterCategory")) {
    $("#memoryFilterCategory").addEventListener("change", loadMemory);
  }
  if ($("#btnSaveConfig")) {
    $("#btnSaveConfig").addEventListener("click", saveMemoryConfig);
  }
  if ($("#btnReloadMemory")) {
    $("#btnReloadMemory").addEventListener("click", reloadMemory);
  }
  if ($("#btnClearMemory")) {
    $("#btnClearMemory").addEventListener("click", async () => {
      if (!confirm("确定清空全部记忆（包括事实和历史总结信息）？此操作不可恢复！")) return;
      try {
        await fetch(`${API_BASE}/memory/clear${memAgentParam()}`, { method: "POST" });
        loadMemory();
      } catch (e) {
        console.error("Clear memory failed", e);
      }
    });
  }
  if ($("#btnCloseSkills")) {
    $("#btnCloseSkills").addEventListener("click", closeAllPanels);
  }
  if ($("#btnSaveSkillConfig")) {
    $("#btnSaveSkillConfig").addEventListener("click", saveSkillConfig);
  }
  if ($("#btnInstallSkill")) {
    $("#btnInstallSkill").addEventListener("click", installSkill);
  }
  if ($("#skillFileInput")) {
    $("#skillFileInput").addEventListener("change", handleSkillFileUpload);
  }
  if (elPanelOverlay) {
    elPanelOverlay.addEventListener("click", closeAllPanels);
  }

  // Uploads panel
  async function loadUploads() {
    if (!elUploadsList || !currentThreadId) {
      if (elUploadsList) elUploadsList.innerHTML = '<div style="color:var(--text-muted);font-size:13px;text-align:center;padding:20px;">请先选择或创建一个对话</div>';
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/uploads/${currentThreadId}`);
      const data = await res.json();
      const files = data.files || data.uploads || [];
      elUploadsList.innerHTML = "";
      if (files.length === 0) {
        elUploadsList.innerHTML = '<div style="color:var(--text-muted);font-size:13px;text-align:center;padding:20px;">暂无已上传文件</div>';
        return;
      }
      files.forEach((f) => {
        const fname = typeof f === "string" ? f : (f.name || f.filename || "");
        const item = document.createElement("div");
        item.className = "upload-item";
        item.innerHTML = `
          <span class="upload-name">${escapeHtml(fname)}</span>
          <button class="btn-upload-delete" title="删除">×</button>
        `;
        item.querySelector(".btn-upload-delete").onclick = async () => {
          try {
            await fetch(`${API_BASE}/uploads/${currentThreadId}/${encodeURIComponent(fname)}`, { method: "DELETE" });
          } catch (err) { console.error("Delete upload failed", err); }
          loadUploads();
        };
        elUploadsList.appendChild(item);
      });
    } catch (e) {
      console.error("Failed to load uploads", e);
    }
  }

  if ($("#btnUploadList")) {
    $("#btnUploadList").addEventListener("click", () => {
      openPanel(elUploadsPanel);
      loadUploads();
    });
  }
  if ($("#btnCloseUploads")) {
    $("#btnCloseUploads").addEventListener("click", closeAllPanels);
  }

  // Agents panel
  let agentsList = [];
  let pendingAgentName = null;

  async function loadAgents() {
    try {
      const res = await fetch(`${API_BASE}/agents`);
      agentsList = await res.json();
      const sel = $("#agentSelect");
      if (!sel) return;
      sel.innerHTML = '<option value="">默认</option>';
      (agentsList || []).forEach((a) => {
        const opt = document.createElement("option");
        opt.value = a.agent_name;
        opt.textContent = a.agent_name;
        if (a.agent_name === selectedAgentName) opt.selected = true;
        sel.appendChild(opt);
      });
      if (!selectedAgentName) sel.value = "";
      showAgentDetail(sel.value);
    } catch (e) {
      console.error("Failed to load agents", e);
    }
  }

  function showAgentDetail(agentName) {
    const elDesc = $("#agentDesc");
    const elSoul = $("#agentSoul");
    if (!elDesc || !elSoul) return;
    if (!agentName) {
      elDesc.textContent = "使用系统默认Agent配置";
      elSoul.textContent = "";
      pendingAgentName = "";
      return;
    }
    const agent = (agentsList || []).find((a) => a.agent_name === agentName);
    elDesc.textContent = agent ? (agent.description || "无描述") : "无描述";
    elSoul.textContent = "加载中...";
    fetch(`${API_BASE}/agents/${encodeURIComponent(agentName)}/soul`)
      .then((r) => r.json())
      .then((data) => { elSoul.textContent = data.soul || ""; })
      .catch(() => { elSoul.textContent = "加载失败"; });
    pendingAgentName = agentName;
  }

  if ($("#agentSelect")) {
    $("#agentSelect").addEventListener("change", (e) => {
      showAgentDetail(e.target.value);
    });
  }

  function closeMcpPopup() {
    if (elMcpPopupOverlay) elMcpPopupOverlay.style.display = "none";
  }

  async function loadMcpPopup() {
    if (!elMcpPopupList) return;
    try {
      const res = await fetch(`${API_BASE}/mcp`);
      const data = await res.json();
      const servers = data.mcpServers || {};
      const enabled = Object.entries(servers).filter(([, s]) => s.enabled);
      elMcpPopupList.innerHTML = "";
      if (enabled.length === 0) {
        elMcpPopupList.innerHTML = '<div class="skills-popup-empty">暂无已启用的MCP服务</div>';
        return;
      }
      enabled.forEach(([name, srv]) => {
        const item = document.createElement("div");
        item.className = "skills-popup-item";
        item.innerHTML = `
          <span class="skills-popup-name">${escapeHtml(name)}</span>
          <span class="skills-popup-category">${escapeHtml(srv.type || "stdio")}</span>
          <span class="skills-popup-status on">启用</span>
        `;
        elMcpPopupList.appendChild(item);
      });
    } catch (e) {
      console.error("Failed to load MCP popup", e);
    }
  }

  if (elSkillsBadge) {
    elSkillsBadge.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (elSkillsModal && elSkillsModal.style.display === "flex") {
        closeSkillsModal();
        return;
      }
      await loadSkillsPopup();
      if (elSkillsModal) elSkillsModal.style.display = "flex";
    });
  }
  if (elMcpBadge) {
    elMcpBadge.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (elMcpPopupOverlay && elMcpPopupOverlay.style.display === "flex") {
        closeMcpPopup();
        return;
      }
      await loadMcpPopup();
      if (elMcpPopupOverlay) elMcpPopupOverlay.style.display = "flex";
    });
  }
  if ($("#btnCloseSkillsModal")) {
    $("#btnCloseSkillsModal").addEventListener("click", closeSkillsModal);
  }
  if ($("#btnCloseMcpPopup")) {
    $("#btnCloseMcpPopup").addEventListener("click", closeMcpPopup);
  }
  if (elSkillsModal) {
    elSkillsModal.addEventListener("click", (e) => {
      if (e.target === elSkillsModal) closeSkillsModal();
    });
  }
  if (elMcpPopupOverlay) {
    elMcpPopupOverlay.addEventListener("click", (e) => {
      if (e.target === elMcpPopupOverlay) closeMcpPopup();
    });
  }

  if ($("#btnCloseAgents")) {
    $("#btnCloseAgents").addEventListener("click", closeAllPanels);
  }
  if ($("#btnConfirmAgent")) {
    $("#btnConfirmAgent").addEventListener("click", async () => {
      const agentName = pendingAgentName !== null ? pendingAgentName : selectedAgentName;
      const label = agentName || "默认";
      if (!confirm(`确认选择Agent「${label}」？`)) return;
      selectedAgentName = agentName || "";
      localStorage.setItem("optclaw_agent", selectedAgentName);
      updateAgentLabel();
      refreshIntroHints();
      closeAllPanels();
      loadThreads();
    });
  }
  function openAgentModal() {
    const overlay = $("#agentModalOverlay");
    if (overlay) overlay.style.display = "flex";
    const nameEl = $("#modalAgentName");
    if (nameEl) { nameEl.value = ""; nameEl.classList.remove("input-error"); nameEl.focus(); }
    const hintEl = $("#agentNameHint");
    if (hintEl) { hintEl.textContent = ""; hintEl.style.display = "none"; }
    const descEl = $("#modalAgentDesc");
    if (descEl) descEl.value = "";
    const soulEl = $("#modalAgentSoul");
    if (soulEl) soulEl.value = "";
  }

  function closeAgentModal() {
    const overlay = $("#agentModalOverlay");
    if (overlay) overlay.style.display = "none";
  }

  const AGENT_NAME_REGEX = /^[A-Za-z0-9-]+$/;

  function validateAgentName() {
    const nameEl = $("#modalAgentName");
    const hintEl = $("#agentNameHint");
    if (!nameEl) return false;
    const val = nameEl.value;
    if (!val.trim()) {
      nameEl.classList.add("input-error");
      if (hintEl) { hintEl.textContent = "Agent名称不能为空"; hintEl.style.display = "block"; }
      return false;
    }
    if (!AGENT_NAME_REGEX.test(val)) {
      nameEl.classList.add("input-error");
      if (hintEl) { hintEl.textContent = "仅允许字母、数字和连字符(-)"; hintEl.style.display = "block"; }
      return false;
    }
    if ((agentsList || []).some(a => a.agent_name === val)) {
      nameEl.classList.add("input-error");
      if (hintEl) { hintEl.textContent = "该Agent名称已存在"; hintEl.style.display = "block"; }
      return false;
    }
    nameEl.classList.remove("input-error");
    if (hintEl) { hintEl.textContent = ""; hintEl.style.display = "none"; }
    return true;
  }

  async function createAgent() {
    if (!validateAgentName()) return;
    const name = ($("#modalAgentName") || {}).value || "";
    const desc = ($("#modalAgentDesc") || {}).value || "";
    const soul = ($("#modalAgentSoul") || {}).value || "";
    try {
      const res = await fetch(`${API_BASE}/agents`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ agent_name: name, description: desc, soul }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const hintEl = $("#agentNameHint");
        const nameEl = $("#modalAgentName");
        if (nameEl) nameEl.classList.add("input-error");
        if (hintEl) { hintEl.textContent = err.detail || "创建失败"; hintEl.style.display = "block"; }
        return;
      }
      closeAgentModal();
      loadAgents();
    } catch (e) {
      console.error("Create agent failed", e);
    }
  }

  if ($("#btnCreateAgent")) {
    $("#btnCreateAgent").addEventListener("click", openAgentModal);
  }
  if ($("#btnCloseAgentModal")) {
    $("#btnCloseAgentModal").addEventListener("click", closeAgentModal);
  }
  if ($("#btnCancelAgentModal")) {
    $("#btnCancelAgentModal").addEventListener("click", closeAgentModal);
  }
  if ($("#btnConfirmAgentModal")) {
    $("#btnConfirmAgentModal").addEventListener("click", createAgent);
  }
  if ($("#modalAgentName")) {
    $("#modalAgentName").addEventListener("input", validateAgentName);
  }

  // MCP management
  let mcpServerData = {};
  let mcpEditingServerName = null;

  async function loadMcpServers() {
    if (!elMcpList) return;
    try {
      const res = await fetch(`${API_BASE}/mcp`);
      const data = await res.json();
      mcpServerData = data.mcpServers || {};
      renderMcpServers();
    } catch (e) {
      console.error("Failed to load MCP config", e);
    }
  }

  function renderMcpServers() {
    if (!elMcpList) return;
    const names = Object.keys(mcpServerData);
    elMcpList.innerHTML = "";
    if (names.length === 0) {
      elMcpList.innerHTML = '<div style="color:var(--text-muted);font-size:13px;text-align:center;padding:20px;">暂无MCP服务器</div>';
      return;
    }
    names.forEach((name) => {
      const srv = mcpServerData[name];
      const item = document.createElement("div");
      item.className = "mcp-item";
      const enabled = srv.enabled;
      item.innerHTML = `
        <div class="mcp-item-main">
          <div class="mcp-item-name-row">
            <span class="mcp-item-name">${escapeHtml(name)}</span>
            <button class="mcp-item-edit" title="编辑">✎</button>
            <button class="mcp-item-delete" title="删除">🗑</button>
          </div>
          <div class="mcp-item-desc">${escapeHtml(srv.description || "")}</div>
          <div class="mcp-item-type">${escapeHtml(srv.type || "stdio")}${srv.command ? " · " + escapeHtml(srv.command) : ""}</div>
        </div>
        <label class="mcp-toggle-switch">
          <input type="checkbox" class="mcp-toggle-checkbox" data-server="${escapeHtml(name)}" ${enabled ? "checked" : ""} />
          <span class="mcp-toggle-slider"></span>
        </label>
      `;

      item.querySelector(".mcp-item-edit").addEventListener("click", (e) => {
        e.stopPropagation();
        openMcpModal(name);
      });

      item.querySelector(".mcp-item-delete").addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm(`确定删除MCP服务器 "${name}"？此操作不可撤销。`)) return;
        try {
          const res = await fetch(`${API_BASE}/mcp/${encodeURIComponent(name)}`, { method: "DELETE" });
          if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            alert(err.detail || "删除失败");
            return;
          }
          delete mcpServerData[name];
          renderMcpServers();
          refreshIntroHints();
        } catch (err) {
          console.error("Delete MCP server failed", err);
          alert("删除失败");
        }
      });

      const checkbox = item.querySelector(".mcp-toggle-checkbox");
      checkbox.addEventListener("change", async (e) => {
        e.stopPropagation();
        const newEnabled = checkbox.checked;
        try {
          await fetch(`${API_BASE}/mcp/${encodeURIComponent(name)}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ enabled: newEnabled }),
          });
          mcpServerData[name].enabled = newEnabled;
          refreshIntroHints();
        } catch (err) {
          console.error("Toggle MCP server failed", err);
          checkbox.checked = !newEnabled;
        }
      });

      elMcpList.appendChild(item);
    });
  }

  function openMcpModal(serverName) {
    mcpEditingServerName = serverName || null;
    const title = $("#mcpModalTitle");
    if (title) title.textContent = serverName ? "编辑MCP服务器" : "添加MCP服务器";

    const nameEl = $("#modalMcpName");
    if (nameEl) {
      nameEl.value = serverName || "";
    }

    const srv = serverName ? (mcpServerData[serverName] || {}) : {};
    const typeEl = $("#modalMcpType");
    if (typeEl) typeEl.value = srv.type || "stdio";
    const cmdEl = $("#modalMcpCommand");
    if (cmdEl) cmdEl.value = srv.command || "";
    const argsEl = $("#modalMcpArgs");
    if (argsEl) argsEl.value = (srv.args || []).join("\n");
    const urlEl = $("#modalMcpUrl");
    if (urlEl) urlEl.value = srv.url || "";
    const envEl = $("#modalMcpEnv");
    if (envEl && srv.env) {
      envEl.value = Object.entries(srv.env).map(([k, v]) => `${k}=${v}`).join("\n");
    } else if (envEl) {
      envEl.value = "";
    }
    const headersEl = $("#modalMcpHeaders");
    if (headersEl && srv.headers) {
      headersEl.value = Object.entries(srv.headers).map(([k, v]) => `${k}: ${v}`).join("\n");
    } else if (headersEl) {
      headersEl.value = "";
    }
    const descEl = $("#modalMcpDesc");
    if (descEl) descEl.value = srv.description || "";
    const enabledEl = $("#modalMcpEnabled");
    if (enabledEl) enabledEl.checked = serverName ? (srv.enabled !== false) : true;

    if (elMcpModalOverlay) elMcpModalOverlay.style.display = "flex";
  }

  function closeMcpModal() {
    if (elMcpModalOverlay) elMcpModalOverlay.style.display = "none";
    mcpEditingServerName = null;
  }

  function parseMultiline(text) {
    if (!text || !text.trim()) return [];
    return text.split("\n").map((l) => l.trim()).filter((l) => l);
  }

  function parseEnvLines(text) {
    const entries = parseMultiline(text);
    const env = {};
    entries.forEach((line) => {
      const idx = line.indexOf("=");
      if (idx > 0) {
        env[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
      }
    });
    return env;
  }

  function parseHeaderLines(text) {
    const entries = parseMultiline(text);
    const headers = {};
    entries.forEach((line) => {
      const idx = line.indexOf(":");
      if (idx > 0) {
        headers[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
      }
    });
    return headers;
  }

  async function saveMcpServer() {
    const name = ($("#modalMcpName") || {}).value || "";
    if (!name.trim()) {
      alert("请输入服务器名称");
      return;
    }
    const config = {
      type: ($("#modalMcpType") || {}).value || "stdio",
      command: ($("#modalMcpCommand") || {}).value || null,
      args: parseMultiline(($("#modalMcpArgs") || {}).value),
      url: ($("#modalMcpUrl") || {}).value || null,
      env: parseEnvLines(($("#modalMcpEnv") || {}).value),
      headers: parseHeaderLines(($("#modalMcpHeaders") || {}).value),
      description: ($("#modalMcpDesc") || {}).value || "",
      enabled: ($("#modalMcpEnabled") || {}).checked,
    };

    try {
      if (mcpEditingServerName) {
        // Handle rename if name changed
        if (name !== mcpEditingServerName) {
          const renameRes = await fetch(`${API_BASE}/mcp/${encodeURIComponent(mcpEditingServerName)}/rename`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ new_name: name }),
          });
          if (!renameRes.ok) {
            const err = await renameRes.json().catch(() => ({}));
            alert(err.detail || "重命名失败");
            return;
          }
        }
        const res = await fetch(`${API_BASE}/mcp/${encodeURIComponent(name)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(config),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          alert(err.detail || "更新失败");
          return;
        }
      } else {
        const res = await fetch(`${API_BASE}/mcp?server_name=${encodeURIComponent(name)}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(config),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          alert(err.detail || "创建失败");
          return;
        }
      }
      closeMcpModal();
      loadMcpServers();
      refreshIntroHints();
    } catch (e) {
      console.error("Save MCP server failed", e);
    }
  }

  if ($("#btnCloseMcp")) {
    $("#btnCloseMcp").addEventListener("click", () => {
      closeAllPanels();
      loadMcpServers();
    });
  }
  if ($("#btnAddMcpServer")) {
    $("#btnAddMcpServer").addEventListener("click", () => openMcpModal(null));
  }
  if ($("#btnCloseMcpModal")) {
    $("#btnCloseMcpModal").addEventListener("click", closeMcpModal);
  }
  if ($("#btnCancelMcpModal")) {
    $("#btnCancelMcpModal").addEventListener("click", closeMcpModal);
  }
  if ($("#btnConfirmMcpModal")) {
    $("#btnConfirmMcpModal").addEventListener("click", saveMcpServer);
  }
  if (elMcpModalOverlay) {
    elMcpModalOverlay.addEventListener("click", (e) => {
      if (e.target === elMcpModalOverlay) closeMcpModal();
    });
  }

  // Init
  loadModels();
  loadThreads();
  checkHealth();
  setInterval(checkHealth, 30000);

  // Persist user preferences
  const savedThinking = localStorage.getItem("optclaw_thinking");
  const savedSubagent = localStorage.getItem("optclaw_subagent");
  const savedPlan = localStorage.getItem("optclaw_plan");
  if (savedThinking !== null) elToggleThinking.checked = savedThinking === "true";
  if (savedSubagent !== null) elToggleSubagent.checked = savedSubagent === "true";
  if (savedPlan !== null) elTogglePlan.checked = savedPlan === "true";
  else elTogglePlan.checked = true;

  elModelSelect.addEventListener("change", () => {
    localStorage.setItem("optclaw_model", elModelSelect.value);
    updateUploadButtonForModel();
    updateThinkingToggleForModel();
  });
  elToggleThinking.addEventListener("change", () => {
    localStorage.setItem("optclaw_thinking", elToggleThinking.checked);
  });
  elToggleSubagent.addEventListener("change", () => {
    localStorage.setItem("optclaw_subagent", elToggleSubagent.checked);
  });
  elTogglePlan.addEventListener("change", () => {
    localStorage.setItem("optclaw_plan", elTogglePlan.checked);
  });

  // Intro page
  (function initIntro() {
    const introPage = document.getElementById("introPage");
    const btnStart = document.getElementById("btnStart");
    const appMain = document.getElementById("appMain");
    const canvas = document.getElementById("introCanvas");
    const configOverlay = document.getElementById("introConfigOverlay");
    if (!introPage || !btnStart) return;

    const visited = sessionStorage.getItem("optclaw_visited");
    if (visited) {
      introPage.style.display = "none";
      if (appMain) appMain.style.display = "flex";
      return;
    }

    btnStart.addEventListener("click", () => {
      if (configOverlay) {
        configOverlay.style.display = "flex";
        refreshIntroHints();
      }
    });

    // Auto-open config overlay when returning from knowledge page
    if (sessionStorage.getItem("optclaw_show_config") === "1") {
      sessionStorage.removeItem("optclaw_show_config");
      if (configOverlay) {
        configOverlay.style.display = "flex";
        refreshIntroHints();
      }
    }

    const introBtnCancel = document.getElementById("introBtnCancel");
    if (introBtnCancel) {
      introBtnCancel.addEventListener("click", () => {
        if (configOverlay) configOverlay.style.display = "none";
      });
    }

    const introBtnConfirm = document.getElementById("introBtnConfirm");
    if (introBtnConfirm) {
      introBtnConfirm.addEventListener("click", async () => {
        sessionStorage.setItem("optclaw_visited", "1");
        try {
          await fetch(`${API_BASE}/reset-agent`, { method: "POST" });
        } catch (e) {
          console.error("Reset agent failed", e);
        }
        introPage.classList.add("fade-out");
        setTimeout(() => {
          introPage.style.display = "none";
          if (appMain) appMain.style.display = "flex";
        }, 600);
      });
    }

    const introBtnAgents = document.getElementById("introBtnAgents");
    const introBtnSkills = document.getElementById("introBtnSkills");
    const introBtnMemory = document.getElementById("introBtnMemory");
    if (introBtnAgents) {
      introBtnAgents.addEventListener("click", () => {
        if (elPanelOverlay) elPanelOverlay.classList.add("visible");
        if (elAgentsPanel) elAgentsPanel.classList.add("open");
        loadAgents();
      });
    }
    if (introBtnSkills) {
      introBtnSkills.addEventListener("click", () => {
        if (elPanelOverlay) elPanelOverlay.classList.add("visible");
        if (elSkillsPanel) elSkillsPanel.classList.add("open");
        loadSkills();
      });
    }
    if (introBtnMemory) {
      introBtnMemory.addEventListener("click", () => {
        if (elPanelOverlay) elPanelOverlay.classList.add("visible");
        if (elMemoryPanel) elMemoryPanel.classList.add("open");
        loadMemoryConfig();
        loadMemory();
      });
    }
    const introBtnMcp = document.getElementById("introBtnMcp");
    if (introBtnMcp) {
      introBtnMcp.addEventListener("click", () => {
        if (elPanelOverlay) elPanelOverlay.classList.add("visible");
        if (elMcpPanel) elMcpPanel.classList.add("open");
        loadMcpServers();
      });
    }
    const introBtnTools = document.getElementById("introBtnTools");
    if (introBtnTools) {
      introBtnTools.addEventListener("click", () => {
        if (elPanelOverlay) elPanelOverlay.classList.add("visible");
        if (elToolsPanel) elToolsPanel.classList.add("open");
        loadTools();
      });
    }
    const introBtnKnowledge = document.getElementById("introBtnKnowledge");
    if (introBtnKnowledge) {
      introBtnKnowledge.addEventListener("click", () => {
        const agent = selectedAgentName || "default";
        window.location.href = `/knowledge.html?agent=${encodeURIComponent(agent)}`;
      });
    }

    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let w, h, particles = [], animId;

    function resize() {
      w = canvas.width = window.innerWidth;
      h = canvas.height = window.innerHeight;
    }
    resize();
    window.addEventListener("resize", resize);

    for (let i = 0; i < 80; i++) {
      particles.push({
        x: Math.random() * w,
        y: Math.random() * h,
        vx: (Math.random() - 0.5) * 0.4,
        vy: (Math.random() - 0.5) * 0.4,
        r: Math.random() * 1.5 + 0.5,
        a: Math.random() * 0.5 + 0.2,
      });
    }

    function draw() {
      ctx.clearRect(0, 0, w, h);
      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];
        p.x += p.vx;
        p.y += p.vy;
        if (p.x < 0) p.x = w;
        if (p.x > w) p.x = 0;
        if (p.y < 0) p.y = h;
        if (p.y > h) p.y = 0;

        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(0,212,255,${p.a})`;
        ctx.fill();

        for (let j = i + 1; j < particles.length; j++) {
          const q = particles[j];
          const dx = p.x - q.x;
          const dy = p.y - q.y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 120) {
            ctx.beginPath();
            ctx.moveTo(p.x, p.y);
            ctx.lineTo(q.x, q.y);
            ctx.strokeStyle = `rgba(0,212,255,${0.15 * (1 - dist / 120)})`;
            ctx.lineWidth = 0.5;
            ctx.stroke();
          }
        }
      }
      animId = requestAnimationFrame(draw);
    }
    draw();

    const observer = new MutationObserver(() => {
      if (introPage.style.display === "none") {
        cancelAnimationFrame(animId);
        observer.disconnect();
      }
    });
    observer.observe(introPage, { attributes: true, attributeFilter: ["style"] });
  })();
})();
