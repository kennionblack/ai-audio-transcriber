const refs = {
  statusBadge: document.getElementById("statusBadge"),
  noticeText: document.getElementById("noticeText"),
  runForm: document.getElementById("runForm"),
  audioFileInput: document.getElementById("audioFileInput"),
  audioDropZone: document.getElementById("audioDropZone"),
  audioDropHint: document.getElementById("audioDropHint"),
  languageSelect: document.getElementById("languageSelect"),
  clearBtn: document.getElementById("clearBtn"),
  bundleBtn: document.getElementById("bundleBtn"),
  artifactSelect: document.getElementById("artifactSelect"),
  artifactStatus: document.getElementById("artifactStatus"),
  artifactDownloadLink: document.getElementById("artifactDownloadLink"),
  metricStatus: document.getElementById("metricStatus"),
  metricRuntime: document.getElementById("metricRuntime"),
  metricWords: document.getElementById("metricWords"),
  metricBullets: document.getElementById("metricBullets"),
  metricView: document.getElementById("metricView"),
  metricExports: document.getElementById("metricExports"),
  timelineList: document.getElementById("timelineList"),
  transcriptOutput: document.getElementById("transcriptOutput"),
  summaryOutput: document.getElementById("summaryOutput"),
  logOutput: document.getElementById("logOutput"),
  copyTranscriptBtn: document.getElementById("copyTranscriptBtn"),
  copyToast: document.getElementById("copyToast"),
  lookupInput: document.getElementById("lookupInput"),
  lookupBtn: document.getElementById("lookupBtn"),
  lookupOutput: document.getElementById("lookupOutput"),
  tabButtons: Array.from(document.querySelectorAll(".tab-btn")),
  tabPanels: Array.from(document.querySelectorAll(".tab-panel")),
  wsBadge: document.getElementById("wsBadge"),
  lastRefreshText: document.getElementById("lastRefreshText"),
  opsLanguage: document.getElementById("opsLanguage"),
  opsSourceFile: document.getElementById("opsSourceFile"),
  opsLastUpdated: document.getElementById("opsLastUpdated"),
  opsConnection: document.getElementById("opsConnection"),
  checkInput: document.getElementById("checkInput"),
  checkRun: document.getElementById("checkRun"),
  checkExport: document.getElementById("checkExport"),
};

let latestState = null;
let socket = null;
let connectionState = "connecting";
let latestArtifactUrls = {
  pdf: null,
  docx: null,
  json: null,
  bundle: null,
};

const ARTIFACT_LABELS = {
  pdf: "PDF Report",
  docx: "DOCX Report",
  json: "JSON Package",
  bundle: "Bundle (ZIP)",
};
const ACCEPTED_AUDIO_EXTENSIONS = new Set([".mp3", ".wav", ".m4a", ".flac"]);
let audioDropDragDepth = 0;

function getSelectedLanguage() {
  const code = (refs.languageSelect.value || "").trim().toLowerCase();
  return code || null;
}

function formatRuntime(startedAt, completedAt) {
  if (!startedAt) return "--:--";
  const start = new Date(startedAt);
  const end = completedAt ? new Date(completedAt) : new Date();
  const seconds = Math.max(0, Math.floor((end - start) / 1000));
  const min = String(Math.floor(seconds / 60)).padStart(2, "0");
  const sec = String(seconds % 60).padStart(2, "0");
  return `${min}:${sec}`;
}

function formatDateTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleString();
}

function countWords(text) {
  if (!text) return 0;
  return text.trim().split(/\s+/).filter(Boolean).length;
}

function countBullets(text) {
  if (!text) return 0;
  return text.split("\n").filter((line) => line.trim().startsWith("-")).length;
}

function setStatusBadge(status) {
  const s = status || "Idle";
  const cssClass =
    s === "Running" ? "running" : s.startsWith("Completed") ? "completed" : s.startsWith("Failed") ? "failed" : "idle";
  refs.statusBadge.className = `status-pill ${cssClass}`;
  refs.statusBadge.querySelector(".label").textContent = s;
}

function setDownloadState(link, url) {
  if (!link) return;
  if (url) {
    link.href = url;
    link.classList.remove("disabled");
    link.setAttribute("aria-disabled", "false");
  } else {
    link.href = "#";
    link.classList.add("disabled");
    link.setAttribute("aria-disabled", "true");
  }
}

function setChecklistState(node, done) {
  if (!node) return;
  node.classList.toggle("done", done);
}

function setConnectionState(nextState) {
  connectionState = nextState;
  const label = nextState === "connected" ? "Connected" : nextState === "disconnected" ? "Disconnected" : "Connecting";
  refs.wsBadge.textContent = label;
  refs.wsBadge.className = `ws-badge ${nextState}`;
  refs.opsConnection.textContent = label;
}

function autoSizeOutput(node) {
  if (!node) return;
  node.style.height = "auto";
  node.style.height = `${node.scrollHeight}px`;
}

function resizeResultOutputs() {
  autoSizeOutput(refs.transcriptOutput);
  autoSizeOutput(refs.summaryOutput);
}

function buildDisplayState(state) {
  const selectedLanguage = getSelectedLanguage();
  const runLanguage = state.translate_lang;
  let transcript = state.transcription_output || state.output || "";
  let summary = state.summary_output || "";
  let viewName = "Original";
  let pdfUrl = state.pdf_output ? "/api/download/pdf" : null;
  let docxUrl = state.export_files && state.export_files.docx ? "/api/download/docx" : null;
  let jsonUrl = state.export_files && state.export_files.json ? "/api/download/json" : null;

  if (selectedLanguage && selectedLanguage === runLanguage) {
    const languageName = state.supported_languages[selectedLanguage] || selectedLanguage;
    transcript = state.translations[selectedLanguage] || transcript;
    if (state.translated_summaries[selectedLanguage]) {
      summary = state.translated_summaries[selectedLanguage];
    } else if (state.status === "Running") {
      summary = `Translation to ${languageName} loading...`;
    }
    viewName = languageName;
    pdfUrl = state.pdf_output ? `/api/download/pdf?language=${encodeURIComponent(selectedLanguage)}` : null;
    docxUrl =
      state.export_files && state.export_files.docx
        ? `/api/download/docx?language=${encodeURIComponent(selectedLanguage)}`
        : null;
    jsonUrl =
      state.export_files && state.export_files.json
        ? `/api/download/json?language=${encodeURIComponent(selectedLanguage)}`
        : null;
  }

  if (state.status && String(state.status).startsWith("Failed")) {
    transcript = `Transcription failed.\n\n${state.output || "[No output returned]"}`;
    summary = "";
    pdfUrl = null;
    docxUrl = null;
    jsonUrl = null;
  }

  if (!transcript && state.status === "Running") transcript = "Transcription running...";
  if (!transcript && (!state.status || state.status === "Idle")) transcript = "Ready.";

  return { transcript, summary, viewName, pdfUrl, docxUrl, jsonUrl };
}

function renderArtifactSelection(running) {
  const selected = refs.artifactSelect.value || "pdf";
  const label = ARTIFACT_LABELS[selected] || "Artifact";
  const url = latestArtifactUrls[selected] || null;
  setDownloadState(refs.artifactDownloadLink, url);
  refs.artifactDownloadLink.textContent = `Download ${label}`;

  if (url) {
    refs.artifactStatus.textContent = "Available";
    return;
  }
  if (selected === "bundle" && !running) {
    refs.artifactStatus.textContent = "Not built";
    return;
  }
  refs.artifactStatus.textContent = running ? "In progress" : "Pending";
}

function renderTimeline(items) {
  if (!items || !items.length) {
    refs.timelineList.innerHTML = "<li class='timeline-empty'>Start a run to populate timeline events.</li>";
    return;
  }
  refs.timelineList.innerHTML = items
    .slice()
    .reverse()
    .map((item) => {
      const time = item.time || "--:--";
      const label = item.label || "Event";
      const detail = item.detail || "";
      return `<li>
        <span class="timeline-time">${time}</span>
        <div>
          <p class="timeline-label">${label}</p>
          <p class="timeline-detail">${detail}</p>
        </div>
      </li>`;
    })
    .join("");
}

function renderState(state) {
  latestState = state;
  const display = buildDisplayState(state);
  const running = state.status === "Running";
  const hasExports = Object.keys(state.export_files || {}).length > 0;

  setStatusBadge(state.status || "Idle");
  refs.noticeText.textContent = state.notice || "Ready.";
  refs.transcriptOutput.value = display.transcript || "";
  refs.summaryOutput.value = display.summary || "";
  resizeResultOutputs();
  refs.logOutput.textContent = state.log_tail || "No log output yet.";

  refs.metricStatus.textContent = state.status || "Idle";
  refs.metricRuntime.textContent = formatRuntime(state.started_at, state.completed_at);
  refs.metricWords.textContent = String(countWords(display.transcript));
  refs.metricBullets.textContent = String(countBullets(display.summary));
  refs.metricView.textContent = display.viewName;
  refs.metricExports.textContent = String(Object.keys(state.export_files || {}).length);

  refs.opsLanguage.textContent = display.viewName;
  refs.opsSourceFile.textContent = state.active_audio_name || "Not set";
  refs.opsLastUpdated.textContent = formatDateTime(state.completed_at || state.started_at);
  refs.lastRefreshText.textContent = `Last refresh: ${new Date().toLocaleTimeString()}`;

  setChecklistState(refs.checkInput, Boolean(state.active_audio_name));
  setChecklistState(refs.checkRun, running || String(state.status || "").startsWith("Completed"));
  setChecklistState(refs.checkExport, hasExports);

  latestArtifactUrls = {
    pdf: display.pdfUrl,
    docx: display.docxUrl,
    json: display.jsonUrl,
    bundle: state.bundle_output ? "/api/download/bundle" : null,
  };
  renderArtifactSelection(running);

  renderTimeline(state.timeline || []);
}

function getFileExtension(name) {
  const value = String(name || "");
  const dotIndex = value.lastIndexOf(".");
  if (dotIndex < 0) return "";
  return value.slice(dotIndex).toLowerCase();
}

function isAcceptedAudioFile(file) {
  if (!file) return false;
  const extension = getFileExtension(file.name);
  if (ACCEPTED_AUDIO_EXTENSIONS.has(extension)) return true;
  if (extension) return false;
  const type = String(file.type || "").toLowerCase();
  return ["audio/mpeg", "audio/wav", "audio/x-wav", "audio/flac", "audio/x-flac", "audio/mp4", "audio/x-m4a"].includes(
    type
  );
}

function dragEventHasFiles(event) {
  if (!event.dataTransfer) return false;
  return Array.from(event.dataTransfer.types || []).includes("Files");
}

function setAudioDropDragging(active) {
  if (!refs.audioDropZone) return;
  refs.audioDropZone.classList.toggle("dragging", Boolean(active));
}

function syncAudioDropHint() {
  if (!refs.audioDropHint) return;
  const file = refs.audioFileInput.files && refs.audioFileInput.files[0];
  refs.audioDropHint.textContent = file ? `Selected file: ${file.name}` : "Or drag and drop an audio file here.";
}

function assignAudioFile(file) {
  if (!file) return false;
  try {
    if (typeof DataTransfer === "function") {
      const transfer = new DataTransfer();
      transfer.items.add(file);
      refs.audioFileInput.files = transfer.files;
    } else {
      return false;
    }
    refs.audioFileInput.dispatchEvent(new Event("change", { bubbles: true }));
    return true;
  } catch {
    return false;
  }
}

function onAudioDropZoneDragEnter(event) {
  if (!dragEventHasFiles(event)) return;
  event.preventDefault();
  audioDropDragDepth += 1;
  setAudioDropDragging(true);
}

function onAudioDropZoneDragOver(event) {
  if (!dragEventHasFiles(event)) return;
  event.preventDefault();
  if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
}

function onAudioDropZoneDragLeave(event) {
  if (!dragEventHasFiles(event)) return;
  event.preventDefault();
  audioDropDragDepth = Math.max(0, audioDropDragDepth - 1);
  if (audioDropDragDepth === 0) setAudioDropDragging(false);
}

function onAudioDropZoneDrop(event) {
  if (!dragEventHasFiles(event)) return;
  event.preventDefault();
  audioDropDragDepth = 0;
  setAudioDropDragging(false);

  const files = event.dataTransfer.files || [];
  if (!files.length) return;
  const file = files[0];
  if (!isAcceptedAudioFile(file)) {
    refs.noticeText.textContent = "Unsupported file type. Use .mp3, .wav, .m4a, or .flac.";
    return;
  }
  if (!assignAudioFile(file)) {
    refs.noticeText.textContent = "Drop detected, but file assignment was blocked. Use Choose File.";
    return;
  }
  refs.noticeText.textContent = `Loaded ${file.name}. Click Start Run to begin.`;
}

function onAudioDropZoneClick(event) {
  if (!refs.audioFileInput) return;
  if (event.target === refs.audioDropZone || event.target === refs.audioDropHint) {
    refs.audioFileInput.click();
  }
}

function onAudioDropZoneKeydown(event) {
  if (!refs.audioFileInput) return;
  if (event.target !== refs.audioDropZone) return;
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    refs.audioFileInput.click();
  }
}

function setupAudioDropZone() {
  if (!refs.audioDropZone || !refs.audioFileInput) return;
  refs.audioDropZone.addEventListener("dragenter", onAudioDropZoneDragEnter);
  refs.audioDropZone.addEventListener("dragover", onAudioDropZoneDragOver);
  refs.audioDropZone.addEventListener("dragleave", onAudioDropZoneDragLeave);
  refs.audioDropZone.addEventListener("drop", onAudioDropZoneDrop);
  refs.audioDropZone.addEventListener("click", onAudioDropZoneClick);
  refs.audioDropZone.addEventListener("keydown", onAudioDropZoneKeydown);
  refs.audioFileInput.addEventListener("change", () => {
    syncAudioDropHint();
    const file = refs.audioFileInput.files && refs.audioFileInput.files[0];
    if (file) refs.noticeText.textContent = `Loaded ${file.name}. Click Start Run to begin.`;
  });
  syncAudioDropHint();
}

async function callJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  if (!response.ok) {
    const details = await response.json().catch(() => ({}));
    throw new Error(details.detail || `Request failed (${response.status})`);
  }
  return response.json();
}

async function submitRun(event) {
  event.preventDefault();
  const file = refs.audioFileInput.files[0];
  if (!file) {
    refs.noticeText.textContent = "Select an audio file first.";
    return;
  }

  const language = getSelectedLanguage();
  const data = new FormData();
  data.append("audio_file", file);
  if (language) data.append("language", language);

  try {
    const response = await fetch("/api/transcribe", { method: "POST", body: data });
    if (!response.ok) {
      const details = await response.json().catch(() => ({}));
      throw new Error(details.detail || `Request failed (${response.status})`);
    }
    const state = await response.json();
    renderState(state);
  } catch (error) {
    refs.noticeText.textContent = String(error.message || error);
  }
}

async function clearRun() {
  try {
    const state = await callJson("/api/clear", {});
    refs.lookupOutput.textContent = "";
    renderState(state);
  } catch (error) {
    refs.noticeText.textContent = String(error.message || error);
  }
}

async function buildBundle() {
  try {
    await callJson("/api/bundle", { language: getSelectedLanguage() });
    if (latestState) {
      latestState.bundle_output = "ready";
      renderState(latestState);
    }
    refs.noticeText.textContent = "Bundle ready for download.";
  } catch (error) {
    refs.noticeText.textContent = String(error.message || error);
  }
}

async function runLookup() {
  try {
    const payload = { query: refs.lookupInput.value || "", language: getSelectedLanguage() };
    const response = await callJson("/api/lookup", payload);
    refs.lookupOutput.textContent = response.result || "";
  } catch (error) {
    refs.lookupOutput.textContent = String(error.message || error);
  }
}

async function copyTranscript() {
  try {
    await navigator.clipboard.writeText(refs.transcriptOutput.value || "");
    refs.copyToast.textContent = "Transcript copied.";
  } catch {
    refs.copyToast.textContent = "Copy failed.";
  }
  refs.copyToast.classList.add("show");
  setTimeout(() => refs.copyToast.classList.remove("show"), 1600);
}

function activateTab(tabName) {
  refs.tabButtons.forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tabName);
  });
  refs.tabPanels.forEach((panel) => {
    panel.classList.toggle("active", panel.id === `tab-${tabName}`);
  });
  resizeResultOutputs();
}

function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  setConnectionState("connecting");
  socket = new WebSocket(`${protocol}://${window.location.host}/ws/state`);

  socket.onopen = () => {
    setConnectionState("connected");
  };

  socket.onmessage = (event) => {
    const state = JSON.parse(event.data);
    renderState(state);
  };

  socket.onerror = () => {
    setConnectionState("disconnected");
  };

  socket.onclose = () => {
    setConnectionState("disconnected");
    setTimeout(connectWebSocket, 1400);
  };
}

async function initialLoad() {
  try {
    const response = await fetch("/api/state");
    if (!response.ok) return;
    const state = await response.json();
    renderState(state);
  } catch {
    // no-op
  }
}

refs.runForm.addEventListener("submit", submitRun);
refs.clearBtn.addEventListener("click", clearRun);
refs.bundleBtn.addEventListener("click", buildBundle);
refs.lookupBtn.addEventListener("click", runLookup);
refs.lookupInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    runLookup();
  }
});
refs.copyTranscriptBtn.addEventListener("click", copyTranscript);
refs.languageSelect.addEventListener("change", () => {
  if (latestState) renderState(latestState);
});
refs.artifactSelect.addEventListener("change", () => {
  const running = latestState && latestState.status === "Running";
  renderArtifactSelection(Boolean(running));
});
refs.tabButtons.forEach((button) => {
  button.addEventListener("click", () => activateTab(button.dataset.tab));
});
window.addEventListener("resize", resizeResultOutputs);

setupAudioDropZone();
initialLoad();
connectWebSocket();
