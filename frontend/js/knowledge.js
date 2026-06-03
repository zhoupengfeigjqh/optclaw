(function () {
  "use strict";

  const API_BASE = "/api/knowledge";
  const $ = (sel) => document.querySelector(sel);

  const urlParams = new URLSearchParams(window.location.search);
  const AGENT_NAME = urlParams.get("agent") || "default";
  const AGENT_QS = `?agent_name=${encodeURIComponent(AGENT_NAME)}`;

  // DOM refs
  const elFileInput = $("#kbFileInput");
  const elBtnUpload = $("#btnKbUpload");
  const elUploadProgress = $("#kbUploadProgress");
  const elProgressFill = $("#kbProgressFill");
  const elUploadStatus = $("#kbUploadStatus");
  const elDocList = $("#kbDocList");
  const elDocViewer = $("#kbDocViewer");
  const elDocViewerTitle = $("#kbDocViewerTitle");
  const elDocViewerContent = $("#kbDocViewerContent");
  const elRecallResults = $("#kbRecallResults");
  const elStatsBadge = $("#kbStatsBadge");
  const elRefreshDocs = $("#btnRefreshDocs");
  const elCloseDocViewer = $("#btnCloseDocViewer");
  const elBtnKbBack = $("#btnKbBack");

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // Upload
  elBtnUpload.addEventListener("click", (e) => { e.stopPropagation(); elFileInput.click(); });
  elFileInput.addEventListener("click", (e) => e.stopPropagation());
  elFileInput.addEventListener("change", () => {
    if (elFileInput.files.length) uploadFile(elFileInput.files[0]);
  });

  async function uploadFile(file) {
    const ext = file.name.split(".").pop().toLowerCase();
    if (!["pdf", "csv", "md", "docx", "txt"].includes(ext)) {
      alert("仅支持 PDF、CSV、MD、DOCX、TXT 格式");
      return;
    }
    const MAX_SIZE = 1 * 1024 * 1024;
    if (file.size > MAX_SIZE) {
      const sizeMB = (file.size / 1024 / 1024).toFixed(1);
      alert(`文件大小超过限制（最大 1MB），当前文件: ${sizeMB}MB`);
      return;
    }

    const smartParse = ($("#kbSmartParse") || {}).checked;
    if (smartParse) {
      return uploadWithSmartParse(file);
    }

    const fd = new FormData();
    fd.append("file", file);

    elUploadProgress.style.display = "block";
    elUploadStatus.textContent = "上传解析中...";
    elProgressFill.style.width = "30%";

    try {
      fd.append("agent_name", AGENT_NAME);
      const res = await fetch(`${API_BASE}/upload`, { method: "POST", body: fd });
      elProgressFill.style.width = "90%";
      elUploadStatus.textContent = "处理完成";
      const data = await res.json();
      if (!res.ok) { alert(data.detail || "上传失败"); return; }
      elProgressFill.style.width = "100%";
      elUploadStatus.textContent = `${file.name} — ${data.chunks_count} 个切片`;
      elFileInput.value = "";
      setTimeout(() => { elUploadProgress.style.display = "none"; }, 2500);
      loadDocuments();
      loadStats();
    } catch (e) {
      elUploadStatus.textContent = "上传失败: " + e.message;
    }
  }

  let pendingSmartFile = null;
  let pendingSmartFileType = "";

  async function uploadWithSmartParse(file) {
    const model = ($("#kbParseModel") || {}).value || "";
    const prompt = ($("#kbParsePrompt") || {}).value || "";
    const fd = new FormData();
    fd.append("file", file);
    fd.append("model", model);
    fd.append("prompt", prompt);

    elUploadProgress.style.display = "block";
    elUploadStatus.textContent = "智能解析中，请稍候...";
    elProgressFill.style.width = "40%";

    try {
      const res = await fetch(`${API_BASE}/smart-parse`, { method: "POST", body: fd });
      elProgressFill.style.width = "80%";
      const data = await res.json();
      if (!res.ok) { alert(data.detail || "智能解析失败"); elUploadProgress.style.display = "none"; return; }
      elProgressFill.style.width = "100%";
      elUploadStatus.textContent = `解析完成 — ${data.results.length} 条记录`;
      pendingSmartFile = file;
      pendingSmartFileType = data.file_type || ext;
      elFileInput.value = "";
      setTimeout(() => { elUploadProgress.style.display = "none"; }, 2000);
      showSmartResultDialog(data.file_name, data.results);
    } catch (e) {
      elUploadStatus.textContent = "智能解析失败: " + e.message;
    }
  }

  function showSmartResultDialog(fileName, results) {
    const body = $("#smartResultBody");
    $("#smartResultFileName").textContent = fileName;
    body.innerHTML = "";

    results.forEach((item, idx) => {
      const keywords = Array.isArray(item.keywords) ? item.keywords : [];
      const div = document.createElement("div");
      div.className = "smart-result-item";
      div.innerHTML = `
        <div class="sr-row">
          <label>#${idx+1} 标题</label>
          <input type="text" class="sr-title" value="${escapeHtml(item.title || "")}" />
        </div>
        <div class="sr-row">
          <label>内容</label>
          <textarea class="sr-content" rows="3">${escapeHtml(item.content || item.text || "")}</textarea>
        </div>
        <div class="sr-row">
          <label>关键词</label>
          <div class="sr-keywords-tags" data-idx="${idx}">
            ${keywords.map((kw, ki) => `<span class="sr-tag">${escapeHtml(kw)}<span class="sr-tag-remove" data-idx="${idx}" data-ki="${ki}">&times;</span></span>`).join("")}
            <input class="sr-keywords-input" placeholder="输入后回车添加" />
          </div>
        </div>
      `;
      // Wire keyword input
      const kwInput = div.querySelector(".sr-keywords-input");
      kwInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          const val = kwInput.value.trim();
          if (!val) return;
          const tagsDiv = kwInput.parentElement;
          const tag = document.createElement("span");
          tag.className = "sr-tag";
          tag.innerHTML = escapeHtml(val) + '<span class="sr-tag-remove">&times;</span>';
          tag.querySelector(".sr-tag-remove").addEventListener("click", () => tag.remove());
          tagsDiv.insertBefore(tag, kwInput);
          kwInput.value = "";
        }
      });
      // Wire tag remove
      div.querySelectorAll(".sr-tag-remove").forEach(btn => {
        btn.addEventListener("click", () => btn.parentElement.remove());
      });
      body.appendChild(div);
    });

    $("#smartResultOverlay").style.display = "flex";
    if ($("#btnCloseSmartResult")) $("#btnCloseSmartResult").onclick = () => { $("#smartResultOverlay").style.display = "none"; };
    if ($("#btnCancelSmartResult")) $("#btnCancelSmartResult").onclick = () => { $("#smartResultOverlay").style.display = "none"; };
    if ($("#btnConfirmSmartResult")) $("#btnConfirmSmartResult").onclick = confirmSmartSave;
  }

  async function confirmSmartSave() {
    const items = document.querySelectorAll(".smart-result-item");
    const results = [];
    items.forEach(item => {
      const title = (item.querySelector(".sr-title") || {}).value || "";
      const content = (item.querySelector(".sr-content") || {}).value || "";
      const tags = item.querySelectorAll(".sr-tag");
      const keywords = [];
      tags.forEach(t => {
        const txt = t.textContent.replace(/×/g, "").trim();
        if (txt) keywords.push(txt);
      });
      if (content.trim()) {
        results.push({ title, content, keywords });
      }
    });

    if (results.length === 0) { alert("无有效数据"); return; }

    const fileName = $("#smartResultFileName").textContent;
    try {
      const res = await fetch(`${API_BASE}/smart-save`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_name: fileName, file_type: pendingSmartFileType, agent_name: AGENT_NAME, results }),
      });
      const data = await res.json();
      if (!res.ok) { alert(data.detail || "保存失败"); return; }
      $("#smartResultOverlay").style.display = "none";
      pendingSmartFile = null;
      alert(`保存成功 — ${data.chunks_count} 个切片`);
      loadDocuments();
      loadStats();
    } catch (e) {
      alert("保存失败: " + e.message);
    }
  }

  // Documents
  elRefreshDocs.addEventListener("click", loadDocuments);

  async function loadDocuments() {
    try {
      const res = await fetch(`${API_BASE}/documents${AGENT_QS}`);
      const data = await res.json();
      const files = data.files || [];
      elDocList.innerHTML = "";
      if (files.length === 0) {
        elDocList.innerHTML = '<div class="kb-empty-state">暂无文档，请上传文件</div>';
        return;
      }
      files.forEach((f) => {
        const item = document.createElement("div");
        item.className = "kb-doc-item";
        item.innerHTML = `
          <div class="kb-doc-info">
            <div class="kb-doc-name">
              <span class="kb-doc-type">${escapeHtml(f.file_type || "")}</span>
              ${escapeHtml(f.file_name)}
            </div>
            <div class="kb-doc-meta">${f.chunks_count} 个切片 · ${f.upload_time ? f.upload_time.slice(0,16) : ""}</div>
          </div>
          <div style="display:flex;gap:8px;align-items:center;">
            <button class="btn-kb-delete" data-file="${escapeHtml(f.file_name)}">删除</button>
          </div>
        `;
        item.querySelector(".kb-doc-info").addEventListener("click", () => loadChunks(f.file_name));
        item.querySelector(".btn-kb-delete").addEventListener("click", (e) => {
          e.stopPropagation();
          deleteDocument(f.file_name);
        });
        elDocList.appendChild(item);
      });
    } catch (e) {
      console.error("Failed to load documents", e);
    }
  }

  async function deleteDocument(fileName) {
    if (!confirm(`确定删除文档「${fileName}」及其所有切片？`)) return;
    try {
      const res = await fetch(`${API_BASE}/documents/${encodeURIComponent(fileName)}${AGENT_QS}`, { method: "DELETE" });
      const data = await res.json();
      if (!res.ok) { alert(data.detail || "删除失败"); return; }
      loadDocuments();
      loadStats();
      elDocViewer.style.display = "none";
    } catch (e) {
      console.error("Delete failed", e);
    }
  }

  // Document viewer
  elCloseDocViewer.addEventListener("click", () => {
    elDocViewer.style.display = "none";
  });

  async function loadChunks(fileName) {
    try {
      const res = await fetch(`${API_BASE}/chunks/${encodeURIComponent(fileName)}${AGENT_QS}`);
      const data = await res.json();
      const chunks = data.chunks || [];
      elDocViewerTitle.textContent = fileName + " (" + chunks.length + " 个切片)";
      elDocViewerContent.innerHTML = "";
      chunks.forEach((c) => {
        const item = document.createElement("div");
        item.className = "kb-chunk-item";
        item.innerHTML = `
          <div class="kb-chunk-header">
            <span>#${c.chunk_index}</span>
            <span>${escapeHtml(c.chunk_id).slice(0,8)}...</span>
          </div>
          <div class="kb-chunk-text">${escapeHtml(c.content)}</div>
        `;
        elDocViewerContent.appendChild(item);
      });
      elDocViewer.style.display = "block";
    } catch (e) {
      console.error("Failed to load chunks", e);
    }
  }

  // Settings
  async function loadSettings() {
    try {
      const res = await fetch(`${API_BASE}/config`);
      const data = await res.json();
      const cs = $("#kbChunkSize");
      const os = $("#kbOverlapSize");
      const em = $("#kbEmbedModel");
      const rm = $("#kbRecallRerankModel");
      if (cs) cs.value = data.chunk_size || 500;
      if (os) os.value = data.overlap_size || 50;
      if (em && data.embed_model) em.value = data.embed_model;
      if (rm && data.rerank_model !== undefined) rm.value = data.rerank_model;
    } catch (e) {
      console.error("Failed to load settings", e);
    }
  }

  // ---- Model connectivity test ----
  const elEmbedStatus = $("#embedStatus");
  const elEmbedHint = $("#embedHint");
  const elRerankStatus = $("#rerankStatus");
  const elRerankHint = $("#rerankHint");

  function setStatus(el, hintEl, state, msg) {
    el.className = "kb-model-status " + state;
    el.title = msg || "";
    if (hintEl) {
      hintEl.textContent = msg || "";
      hintEl.className = "kb-model-hint " + state;
    }
  }

  async function testEmbed(model) {
    if (!model) return;
    setStatus(elEmbedStatus, elEmbedHint, "checking", "检测中...");
    try {
      const res = await fetch(`${API_BASE}/test-embed?model=${encodeURIComponent(model)}`);
      if (res.ok) {
        setStatus(elEmbedStatus, elEmbedHint, "online", "嵌入模型连接正常");
      } else {
        const data = await res.json();
        setStatus(elEmbedStatus, elEmbedHint, "offline", data.detail || "嵌入模型不可用");
      }
    } catch (e) {
      setStatus(elEmbedStatus, elEmbedHint, "offline", "嵌入模型连接失败: " + e.message);
    }
  }

  async function testRerank(model) {
    if (!model) {
      setStatus(elRerankStatus, elRerankHint, "offline", "已关闭重排序");
      return;
    }
    setStatus(elRerankStatus, elRerankHint, "checking", "检测中...");
    try {
      const res = await fetch(`${API_BASE}/test-rerank?model=${encodeURIComponent(model)}`);
      if (res.ok) {
        setStatus(elRerankStatus, elRerankHint, "online", "重排模型连接正常");
      } else {
        const data = await res.json();
        setStatus(elRerankStatus, elRerankHint, "offline", data.detail || "重排模型不可用");
      }
    } catch (e) {
      setStatus(elRerankStatus, elRerankHint, "offline", "重排模型连接失败: " + e.message);
    }
  }

  // ---- Settings - auto save on change (validate silently, revert invalid to defaults) ----
  async function saveSettings() {
    const csEl = $("#kbChunkSize");
    const osEl = $("#kbOverlapSize");
    const rawCs = parseInt(csEl?.value);
    const rawOs = parseInt(osEl?.value);

    let chunk_size = Number.isInteger(rawCs) && rawCs >= 100 && rawCs <= 500 ? rawCs : 500;
    let overlap_size = Number.isInteger(rawOs) && rawOs >= 10 && rawOs <= 100 ? rawOs : 50;

    if (overlap_size >= chunk_size || chunk_size < 100 || chunk_size > 500 || overlap_size < 10 || overlap_size > 100) {
      chunk_size = 500;
      overlap_size = 50;
      csEl.value = 500;
      osEl.value = 50;
    }

    const embed_model = ($("#kbEmbedModel") || {}).value || "nomic-embed-text";
    const rerank_model = ($("#kbRecallRerankModel") || {}).value || "";

    const qs = new URLSearchParams({ embed_model, rerank_model });
    try {
      await fetch(`${API_BASE}/config?` + qs.toString(), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chunk_size, overlap_size }),
      });
    } catch (e) {
      console.error("Save settings failed", e);
    }
  }

  if ($("#kbChunkSize")) {
    $("#kbChunkSize").addEventListener("change", saveSettings);
  }
  if ($("#kbOverlapSize")) {
    $("#kbOverlapSize").addEventListener("change", saveSettings);
  }
  if ($("#kbEmbedModel")) {
    $("#kbEmbedModel").addEventListener("change", () => {
      saveSettings();
      testEmbed($("#kbEmbedModel").value);
    });
  }
  if ($("#kbRecallRerankModel")) {
    $("#kbRecallRerankModel").addEventListener("change", () => {
      saveSettings();
      testRerank($("#kbRecallRerankModel").value);
    });
  }

  // Recall Test — threshold toggle by search type
  const elSearchType = $("#kbSearchType");
  const elRecallThreshold = $("#kbRecallThreshold");
  const elTopK = $("#kbTopK");

  function validateTopK() {
    const v = parseInt(elTopK?.value);
    if (!Number.isInteger(v) || v < 1 || v > 10) {
      elTopK.value = 5;
    }
  }
  if (elTopK) {
    elTopK.addEventListener("change", validateTopK);
  }

  function validateThreshold() {
    const v = parseFloat(elRecallThreshold?.value);
    if (isNaN(v) || v < 0 || v > 1) {
      elRecallThreshold.value = 0.5;
    }
  }
  if (elRecallThreshold) {
    elRecallThreshold.addEventListener("change", validateThreshold);
  }

  function updateThresholdState() {
    const isKeyword = (elSearchType?.value || "") === "keyword";
    if (elRecallThreshold) {
      elRecallThreshold.disabled = isKeyword;
      elRecallThreshold.style.opacity = isKeyword ? "0.4" : "1";
    }
  }
  if (elSearchType) {
    elSearchType.addEventListener("change", updateThresholdState);
  }

  $("#btnRecallSearch").addEventListener("click", async () => {
    const query = ($("#kbRecallQuery") || {}).value || "";
    if (!query.trim()) { alert("请输入查询内容"); return; }
    const search_type = elSearchType?.value || "hybrid";
    let top_k = parseInt(elTopK?.value);
    if (!Number.isInteger(top_k) || top_k < 1 || top_k > 10) {
      top_k = 5;
      if (elTopK) elTopK.value = 5;
    }
    const threshold = search_type === "keyword" ? 0 : (parseFloat(elRecallThreshold?.value) || 0.5);
    const use_rerank = (($("#kbRecallRerankModel") || {}).value || "") !== "";

    elRecallResults.innerHTML = '<div class="kb-empty-state">搜索中...</div>';
    try {
      const res = await fetch(`${API_BASE}/recall${AGENT_QS}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query, top_k, search_type, use_rerank, score_threshold: threshold }),
      });
      const data = await res.json();
      const results = data.results || [];
      elRecallResults.innerHTML = "";
      if (results.length === 0) {
        elRecallResults.innerHTML = '<div class="kb-empty-state">无匹配结果</div>';
        return;
      }
      results.forEach((r, i) => {
        const item = document.createElement("div");
        item.className = "kb-recall-item";
        item.innerHTML = `
          <div class="kb-recall-header">
            <span class="kb-recall-source ${r.source_type || "keyword"}">${r.source_type || ""}</span>
            <span class="kb-recall-score">#${i+1} · 相似度: ${(r.score||0).toFixed(4)}</span>
            <span style="font-size:11px;color:var(--text-muted);">${escapeHtml(r.file_name||"")}</span>
          </div>
          <div class="kb-recall-text">${escapeHtml(r.content || "")}</div>
        `;
        elRecallResults.appendChild(item);
      });
    } catch (e) {
      elRecallResults.innerHTML = '<div class="kb-empty-state">搜索失败</div>';
    }
  });

  // Stats
  async function loadStats() {
    try {
      const res = await fetch(`${API_BASE}/stats${AGENT_QS}`);
      const data = await res.json();
      elStatsBadge.textContent = `Agent: ${AGENT_NAME} | 文档: ${data.total_documents} | MongoDB切片: ${data.total_chunks} | FAISS向量: ${data.faiss_vectors}`;
    } catch (e) {
      console.error("Failed to load stats", e);
    }
  }

  // Back button — return to intro config page
  elBtnKbBack.addEventListener("click", (e) => {
    e.preventDefault();
    sessionStorage.removeItem("optclaw_visited");
    sessionStorage.setItem("optclaw_show_config", "1");
    window.location.href = "/";
  });

  // ---- Smart Parse ----
  const elSmartToggle = $("#kbSmartParse");
  const elSmartSettings = $("#kbSmartParseSettings");
  const elParseModel = $("#kbParseModel");
  const elParseStatus = $("#parseStatus");
  const elParseHint = $("#parseHint");

  async function loadParseModelOptions() {
    try {
      const res = await fetch(`${API_BASE}/config`);
      const data = await res.json();
      if (elParseModel) {
        const val = data.parse_model || "qwen3:8b";
        elParseModel.innerHTML = `<option value="${escapeHtml(val)}" selected>${escapeHtml(val)}</option>`;
      }
      if ($("#kbParsePrompt")) {
        const res2 = await fetch(`/api/knowledge/config`);
        // prompt is loaded from config via a dedicated call
      }
    } catch (e) { console.error("Failed to load parse model", e); }
  }

  async function loadParsePrompt() {
    try {
      const res = await fetch(`${API_BASE}/config`);
      const data = await res.json();
      if ($("#kbParsePrompt") && data.parse_prompt) {
        $("#kbParsePrompt").value = data.parse_prompt;
      }
    } catch (e) { console.error("Failed to load parse prompt", e); }
  }

  async function testParse(model) {
    if (!model) return;
    setStatus(elParseStatus, elParseHint, "checking", "检测中...");
    try {
      const res = await fetch(`${API_BASE}/test-parse?model=${encodeURIComponent(model)}`);
      if (res.ok) {
        setStatus(elParseStatus, elParseHint, "online", "解析模型连接正常");
      } else {
        const data = await res.json();
        setStatus(elParseStatus, elParseHint, "offline", data.detail || "解析模型不可用");
      }
    } catch (e) {
      setStatus(elParseStatus, elParseHint, "offline", "解析模型连接失败: " + e.message);
    }
  }

  function setSmartParseDisabled(on) {
    const ids = ["kbChunkSize", "kbOverlapSize", "kbEmbedModel"];
    ids.forEach(id => {
      const el = $("#" + id);
      if (!el) return;
      const group = el.closest(".kb-form-group");
      if (group) group.classList.toggle("disabled", on);
    });
  }

  if (elSmartToggle) {
    elSmartToggle.addEventListener("change", () => {
      const on = elSmartToggle.checked;
      elSmartSettings.style.display = on ? "flex" : "none";
      setSmartParseDisabled(on);
      if (on) {
        const m = (elParseModel || {}).value;
        if (m) testParse(m);
      }
    });
  }

  if (elParseModel) {
    elParseModel.addEventListener("change", () => testParse(elParseModel.value));
  }

  // Parse Prompt Dialog
  if ($("#btnParseSettings")) {
    $("#btnParseSettings").addEventListener("click", () => {
      $("#parsePromptOverlay").style.display = "flex";
    });
  }
  if ($("#btnCloseParsePrompt")) {
    $("#btnCloseParsePrompt").addEventListener("click", () => {
      $("#parsePromptOverlay").style.display = "none";
    });
  }
  if ($("#btnCancelParsePrompt")) {
    $("#btnCancelParsePrompt").addEventListener("click", () => {
      $("#parsePromptOverlay").style.display = "none";
    });
  }
  if ($("#btnSaveParsePrompt")) {
    $("#btnSaveParsePrompt").addEventListener("click", async () => {
      const prompt = ($("#kbParsePrompt") || {}).value || "";
      const embed_model = ($("#kbEmbedModel") || {}).value || "nomic-embed-text";
      const rerank_model = ($("#kbRecallRerankModel") || {}).value || "";
      const csEl = $("#kbChunkSize");
      const osEl = $("#kbOverlapSize");
      const chunk_size = parseInt(csEl?.value) || 500;
      const overlap_size = parseInt(osEl?.value) || 50;
      try {
        await fetch(`${API_BASE}/config?embed_model=${encodeURIComponent(embed_model)}&rerank_model=${encodeURIComponent(rerank_model)}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ chunk_size, overlap_size, parse_prompt: prompt }),
        });
        $("#parsePromptOverlay").style.display = "none";
      } catch (e) { console.error("Save prompt failed", e); }
    });
  }

  // Init
  updateThresholdState();
  loadSettings();
  loadDocuments();
  loadStats();
  loadParseModelOptions();
  loadParsePrompt();
  testEmbed(($("#kbEmbedModel") || {}).value || "nomic-embed-text");
  testRerank(($("#kbRecallRerankModel") || {}).value || "");
  // Test parse model on load if smart parse is enabled
  if (elSmartToggle && elSmartToggle.checked) {
    const m = (elParseModel || {}).value;
    if (m) testParse(m);
  }
})();
