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
    text = text.replace(/<system-reminder>[\s\S]*?<\/system-reminder>/gi, "");
    text = text.replace(/\[ImageId:[^\]]*\]\s*This is an image\.\s*If the user needs to view or analyze this image.*?(?=\n|$)/gi, "");
    text = text.replace(/\[ImageId:[^\]]*\]/g, "");
    text = text.replace(/\n{3,}/g, "\n\n");
    return text.trim();
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
      textEl.innerHTML = renderMarkdown(cleanContent(content));
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

  function appendToMessage(body, delta, deltaType) {
    const indicator = body.querySelector(".typing-indicator");
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
      const saved = localStorage.getItem("optclaw_model");
      if (saved && elModelSelect.querySelector(`option[value="${saved}"]`)) {
        elModelSelect.value = saved;
      }
    } catch (e) {
      console.error("Failed to load models", e);
    }
  }

  async function loadThreads() {
    try {
      const res = await fetch(`${API_BASE}/threads?limit=10`);
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
    currentThreadId = threadId;
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
          if (c) addMessage("user", c);
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
    currentThreadId = null;
    clearMessages(true);
    $$(".thread-item").forEach((item) => item.classList.remove("active"));
    fetch(`${API_BASE}/reset-agent`, { method: "POST" }).catch(() => {});
  }

  async function sendMessage() {
    const text = elInput.value.trim();
    if (!text && pendingFiles.length === 0) return;
    if (isStreaming) return;

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

    if (pendingFiles.length > 0) {
      await uploadPendingFiles();
    }

    addMessage("user", text);

    const aiBody = addMessage("ai", "");
    setLoading(true);

    const payload = {
      message: text,
      thread_id: currentThreadId,
    };

    const selectedModel = elModelSelect.value;
    if (selectedModel) payload.model_name = selectedModel;
    payload.thinking_enabled = elToggleThinking.checked;
    payload.subagent_enabled = elToggleSubagent.checked;
    payload.plan_mode = elTogglePlan.checked;
    if (selectedAgentName) payload.agent_name = selectedAgentName;

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
      const reasoningEl = aiBody.querySelector(".stream-reasoning");
      if (reasoningEl) reasoningEl.remove();
      const toolCallsEl = aiBody.querySelector(".stream-tool-calls");
      if (toolCallsEl) toolCallsEl.remove();
      setLoading(false);
      loadThreads();
    }
  }

  function handleStreamEvent(event, aiBody) {
    const { type, data } = event;

    if (type === "delta") {
      if (data.content) {
        const deltaType = data.delta_type || "text";
        appendToMessage(aiBody, data.content, deltaType);
      }
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
  const elAgentLabel = $("#agentLabel");

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
  }

  function updateAgentLabel() {
    if (elAgentLabel) {
      if (selectedAgentName) {
        elAgentLabel.textContent = "Agent设置：" + selectedAgentName;
      } else {
        elAgentLabel.textContent = "Agent设置：默认";
      }
    }
  }
  updateAgentLabel();

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
    if (!confirm("确定刷新记忆？将重新加载配置并重置Agent。")) return;
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
        return;
      }
      facts.forEach((f) => {
        const item = document.createElement("div");
        item.className = "fact-item";
        const fid = f.id || f.fact_id || "";
        item.innerHTML = `
          <div class="fact-body">
            <div class="fact-content">${escapeHtml(f.content || f.text || "")}</div>
            <div class="fact-meta">${escapeHtml(f.category || "")} · 置信度 ${(f.confidence || 0).toFixed(2)}</div>
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
              <input type="text" class="edit-content" value="${escapeHtml(f.content || f.text || "")}" />
              <select class="edit-category">
                <option value="preference" ${f.category==="preference"?"selected":""}>偏好 (preference)</option>
                <option value="knowledge" ${f.category==="knowledge"?"selected":""}>知识 (knowledge)</option>
                <option value="context" ${(f.category||"")==="context"?"selected":""}>背景 (context)</option>
                <option value="behavior" ${f.category==="behavior"?"selected":""}>行为 (behavior)</option>
                <option value="goal" ${f.category==="goal"?"selected":""}>目标 (goal)</option>
                <option value="correction" ${f.category==="correction"?"selected":""}>纠正 (correction)</option>
              </select>
              <input type="number" class="edit-confidence" value="${f.confidence||0.5}" step="0.1" min="0" max="1" />
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

  async function loadSkills() {
    try {
      const res = await fetch(`${API_BASE}/skills`);
      const data = await res.json();
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

  async function saveSkillConfig() {
    if (Object.keys(skillChanges).length === 0) {
      alert("没有修改任何技能配置");
      return;
    }
    if (!confirm("确定保存技能配置？保存后将重置Agent使配置生效。")) return;
    try {
      for (const [name, enabled] of Object.entries(skillChanges)) {
        await fetch(`${API_BASE}/skills/${encodeURIComponent(name)}?enabled=${enabled}`, { method: "PATCH" });
      }
      await fetch(`${API_BASE}/reset-agent`, { method: "POST" });
      skillChanges = {};
      loadSkills();
    } catch (e) {
      console.error("Save skill config failed", e);
    }
  }

  if ($("#btnShowMemory")) {
    $("#btnShowMemory").addEventListener("click", () => {
      openPanel(elMemoryPanel);
      loadMemoryConfig();
      loadMemory();
    });
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
  if ($("#btnShowSkills")) {
    $("#btnShowSkills").addEventListener("click", () => {
      openPanel(elSkillsPanel);
      loadSkills();
    });
  }
  if ($("#btnCloseSkills")) {
    $("#btnCloseSkills").addEventListener("click", closeAllPanels);
  }
  if ($("#btnSaveSkillConfig")) {
    $("#btnSaveSkillConfig").addEventListener("click", saveSkillConfig);
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

  if ($("#btnShowAgents")) {
    $("#btnShowAgents").addEventListener("click", () => {
      openPanel(elAgentsPanel);
      loadAgents();
    });
  }
  if ($("#btnCloseAgents")) {
    $("#btnCloseAgents").addEventListener("click", closeAllPanels);
  }
  if ($("#btnConfirmAgent")) {
    $("#btnConfirmAgent").addEventListener("click", async () => {
      const agentName = pendingAgentName !== null ? pendingAgentName : selectedAgentName;
      const label = agentName || "默认";
      if (!confirm(`确认选择Agent「${label}」？将重置Agent并生效。`)) return;
      selectedAgentName = agentName || "";
      localStorage.setItem("optclaw_agent", selectedAgentName);
      updateAgentLabel();
      try {
        await fetch(`${API_BASE}/reset-agent`, { method: "POST" });
      } catch (e) {
        console.error("Reset agent failed", e);
      }
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
    if (!introPage || !btnStart) return;

    const visited = sessionStorage.getItem("optclaw_visited");
    if (visited) {
      introPage.style.display = "none";
      if (appMain) appMain.style.display = "flex";
      return;
    }

    btnStart.addEventListener("click", () => {
      sessionStorage.setItem("optclaw_visited", "1");
      introPage.classList.add("fade-out");
      setTimeout(() => {
        introPage.style.display = "none";
        if (appMain) appMain.style.display = "flex";
      }, 600);
    });

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
