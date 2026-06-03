(function () {
  "use strict";

  const API_BASE = "/api/knowledge";
  const $ = (sel) => document.querySelector(sel);

  const urlParams = new URLSearchParams(window.location.search);
  const AGENT_NAME = urlParams.get("agent") || "default";
  const AGENT_QS = `?agent_name=${encodeURIComponent(AGENT_NAME)}`;

  // DOM refs
  const elDropzone = $("#kbDropzone");
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

  elDropzone.addEventListener("dragover", (e) => { e.preventDefault(); elDropzone.classList.add("dragover"); });
  elDropzone.addEventListener("dragleave", () => elDropzone.classList.remove("dragover"));
  elDropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    elDropzone.classList.remove("dragover");
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  });
  elDropzone.addEventListener("click", () => elFileInput.click());

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

  // Init
  updateThresholdState();
  loadSettings();
  loadDocuments();
  loadStats();
  testEmbed(($("#kbEmbedModel") || {}).value || "nomic-embed-text");
  testRerank(($("#kbRecallRerankModel") || {}).value || "");
})();
