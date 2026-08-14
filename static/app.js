const refs = {
  togglePlatformMetaBtn: document.getElementById("togglePlatformMetaBtn"),
  platformMetaPills: document.getElementById("platformMetaPills"),
  statusBadge: document.getElementById("statusBadge"),
  noticeText: document.getElementById("noticeText"),
  runForm: document.getElementById("runForm"),
  audioFileInput: document.getElementById("audioFileInput"),
  audioDropZone: document.getElementById("audioDropZone"),
  audioDropHint: document.getElementById("audioDropHint"),
  languageSelect: document.getElementById("languageSelect"),
  previousUploadSelect: document.getElementById("previousUploadSelect"),
  clearBtn: document.getElementById("clearBtn"),
  bundleBtn: document.getElementById("bundleBtn"),
  showUploadsBtn: document.getElementById("showUploadsBtn"),
  uploadManagerPanel: document.getElementById("uploadManagerPanel"),
  refreshUploadsBtn: document.getElementById("refreshUploadsBtn"),
  closeUploadManagerBtn: document.getElementById("closeUploadManagerBtn"),
  selectAllUploads: document.getElementById("selectAllUploads"),
  deleteUploadsBtn: document.getElementById("deleteUploadsBtn"),
  deleteConfirmPopup: document.getElementById("deleteConfirmPopup"),
  deleteConfirmMessage: document.getElementById("deleteConfirmMessage"),
  cancelDeleteUploadsBtn: document.getElementById("cancelDeleteUploadsBtn"),
  confirmDeleteUploadsBtn: document.getElementById("confirmDeleteUploadsBtn"),
  uploadedFilesList: document.getElementById("uploadedFilesList"),
  showHistoryBtn: document.getElementById("showHistoryBtn"),
  historyPanel: document.getElementById("historyPanel"),
  toggleHistorySelectBtn: document.getElementById("toggleHistorySelectBtn"),
  refreshHistoryBtn: document.getElementById("refreshHistoryBtn"),
  closeHistoryBtn: document.getElementById("closeHistoryBtn"),
  historyBulkActions: document.getElementById("historyBulkActions"),
  selectAllHistory: document.getElementById("selectAllHistory"),
  deleteHistoryBtn: document.getElementById("deleteHistoryBtn"),
  historyList: document.getElementById("historyList"),
  historyDeleteConfirmPopup: document.getElementById("historyDeleteConfirmPopup"),
  historyDeleteConfirmMessage: document.getElementById("historyDeleteConfirmMessage"),
  cancelHistoryDeleteBtn: document.getElementById("cancelHistoryDeleteBtn"),
  confirmHistoryDeleteBtn: document.getElementById("confirmHistoryDeleteBtn"),
  artifactSelect: document.getElementById("artifactSelect"),
  artifactVerbatimToggle: document.getElementById("artifactVerbatimToggle"),
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
  toggleVerbatimBtn: document.getElementById("toggleVerbatimBtn"),
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
let lastStateSignature = null;
let lastRefreshAt = null;
let uploadedFiles = [];
let selectedUploadName = null;
let pendingDeleteNames = [];
let latestArtifactUrls = {
  pdf: { clean: null, verbatim: null },
  docx: { clean: null, verbatim: null },
  json: { clean: null, verbatim: null },
  bundle: null,
};
let showingVerbatimTranscript = false;
let historyEntries = [];
let pendingDeleteHistoryStems = [];
let historySelectionMode = false;

const ARTIFACT_LABELS = {
  pdf: "PDF Report",
  docx: "DOCX Report",
  json: "JSON Package",
  bundle: "Bundle (ZIP)",
};
const HISTORY_FORMAT_LABELS = { pdf: "PDF", docx: "DOCX", json: "JSON" };
const ACCEPTED_AUDIO_EXTENSIONS = new Set([".mp3", ".wav", ".m4a", ".flac", ".mp4"]);
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

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let size = bytes / 1024;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

function buildStateSignature(state) {
  const timeline = Array.isArray(state.timeline) ? state.timeline : [];
  const lastTimeline = timeline.length ? timeline[timeline.length - 1] : null;
  return JSON.stringify({
    status: state.status || "",
    notice: state.notice || "",
    started_at: state.started_at || "",
    completed_at: state.completed_at || "",
    active_audio_name: state.active_audio_name || "",
    translate_lang: state.translate_lang || "",
    output: state.output || "",
    transcription_output: state.transcription_output || "",
    raw_transcript_output: state.raw_transcript_output || "",
    summary_output: state.summary_output || "",
    translations: state.translations || {},
    translated_summaries: state.translated_summaries || {},
    pdf_output: state.pdf_output || "",
    export_files: state.export_files || {},
    verbatim_export_files: state.verbatim_export_files || {},
    bundle_output: state.bundle_output || "",
    log_tail: state.log_tail || "",
    last_timeline: lastTimeline,
  });
}

function countWords(text) {
  if (!text) return 0;
  return text.trim().split(/\s+/).filter(Boolean).length;
}

function countBullets(text) {
  if (!text) return 0;
  return text.split("\n").filter((line) => line.trim().startsWith("-")).length;
}

function getRunControlNotice(state) {
  const status = String((state && state.status) || "");
  if (status === "Idle" || !status) {
    const selectedFile = refs.audioFileInput.files && refs.audioFileInput.files[0];
    if (selectedUploadName) return `${selectedUploadName} Ready. File Selected`;
    if (selectedFile) return `${selectedFile.name} Ready. File Uploaded`;
  }
  return (state && state.notice) || "Ready.";
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
  const verbatimExports = state.verbatim_export_files || {};
  let pdfVerbatimUrl = verbatimExports.pdf ? "/api/download/pdf?verbatim=true" : null;
  let docxVerbatimUrl = verbatimExports.docx ? "/api/download/docx?verbatim=true" : null;
  let jsonVerbatimUrl = verbatimExports.json ? "/api/download/json?verbatim=true" : null;

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
    pdfVerbatimUrl = null;
    docxVerbatimUrl = null;
    jsonVerbatimUrl = null;
  }

  if (!transcript && state.status === "Running") transcript = "Transcription running...";
  if (!transcript && (!state.status || state.status === "Idle")) transcript = "Ready.";

  return {
    transcript,
    summary,
    viewName,
    pdfUrl,
    docxUrl,
    jsonUrl,
    pdfVerbatimUrl,
    docxVerbatimUrl,
    jsonVerbatimUrl,
  };
}

function renderArtifactSelection(running) {
  const selected = refs.artifactSelect.value || "pdf";
  const verbatim = Boolean(refs.artifactVerbatimToggle && refs.artifactVerbatimToggle.checked);
  const label = ARTIFACT_LABELS[selected] || "Artifact";
  const entry = latestArtifactUrls[selected];
  const url = entry && typeof entry === "object" ? (verbatim ? entry.verbatim : entry.clean) : entry || null;
  const supportsVerbatim = selected !== "bundle";

  if (selected === "bundle" && !url) {
    refs.artifactDownloadLink.href = "#";
    refs.artifactDownloadLink.dataset.mode = "build";
    if (running) {
      refs.artifactDownloadLink.classList.add("disabled");
      refs.artifactDownloadLink.setAttribute("aria-disabled", "true");
      refs.artifactDownloadLink.textContent = "Building...";
      refs.artifactStatus.textContent = "In progress";
    } else {
      refs.artifactDownloadLink.classList.remove("disabled");
      refs.artifactDownloadLink.setAttribute("aria-disabled", "false");
      refs.artifactDownloadLink.textContent = "Build Bundle (ZIP)";
      refs.artifactStatus.textContent = "Not built";
    }
    return;
  }

  delete refs.artifactDownloadLink.dataset.mode;
  setDownloadState(refs.artifactDownloadLink, url);
  refs.artifactDownloadLink.textContent = `Download ${label}${verbatim && supportsVerbatim ? " (Verbatim)" : ""}`;

  if (url) {
    refs.artifactStatus.textContent = "Available";
    return;
  }
  refs.artifactStatus.textContent = running ? "In progress" : "Pending";
}

function renderTimeline(items) {
  refs.timelineList.replaceChildren();
  if (!items || !items.length) {
    const emptyItem = document.createElement("li");
    emptyItem.className = "timeline-empty";
    emptyItem.textContent = "Start a run to populate timeline events.";
    refs.timelineList.append(emptyItem);
    return;
  }
  const fragment = document.createDocumentFragment();
  items
    .slice()
    .reverse()
    .forEach((item) => {
      const listItem = document.createElement("li");
      const time = document.createElement("span");
      const content = document.createElement("div");
      const label = document.createElement("p");
      const detail = document.createElement("p");

      time.className = "timeline-time";
      time.textContent = item.time || "--:--";
      label.className = "timeline-label";
      label.textContent = item.label || "Event";
      detail.className = "timeline-detail";
      detail.textContent = item.detail || "";

      content.append(label, detail);
      listItem.append(time, content);
      fragment.append(listItem);
    });
  refs.timelineList.append(fragment);
}

function getSelectedUploadNames() {
  return Array.from(refs.uploadedFilesList.querySelectorAll(".upload-select:checked")).map((input) => input.value);
}

function syncUploadSelectionState() {
  const checkboxes = Array.from(refs.uploadedFilesList.querySelectorAll(".upload-select"));
  const selectedCount = checkboxes.filter((input) => input.checked).length;
  refs.deleteUploadsBtn.disabled = selectedCount === 0;
  refs.deleteUploadsBtn.setAttribute("aria-disabled", selectedCount === 0 ? "true" : "false");
  refs.selectAllUploads.disabled = checkboxes.length === 0;
  refs.selectAllUploads.checked = checkboxes.length > 0 && selectedCount === checkboxes.length;
  refs.selectAllUploads.indeterminate = selectedCount > 0 && selectedCount < checkboxes.length;
}

function syncUploadedFileActions() {
  const running = latestState && latestState.status === "Running";
  refs.uploadedFilesList.querySelectorAll(".upload-file-row").forEach((row) => {
    row.classList.toggle("selected", row.dataset.fileName === selectedUploadName);
  });
  refs.uploadedFilesList.querySelectorAll("[data-action='select-upload']").forEach((button) => {
    button.disabled = Boolean(running);
    button.textContent = button.dataset.fileName === selectedUploadName ? "Selected" : "Use";
  });
  refs.previousUploadSelect.disabled = Boolean(running);
  refs.previousUploadSelect.value = selectedUploadName || "";
}

function clearSelectedUpload() {
  selectedUploadName = null;
  syncAudioDropHint();
  syncUploadedFileActions();
}

function selectUploadedFile(fileName) {
  if (!fileName) return;
  selectedUploadName = fileName;
  refs.audioFileInput.value = "";
  syncAudioDropHint();
  syncUploadedFileActions();
  refs.noticeText.textContent = `${selectedUploadName} Ready. File Selected`;
}

function populatePreviousUploadOptions() {
  const select = refs.previousUploadSelect;
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = uploadedFiles.length ? "Select an uploaded file..." : "No uploaded files found.";
  const options = [placeholder, ...uploadedFiles.map((file) => {
    const option = document.createElement("option");
    option.value = file.name || "";
    option.textContent = file.name || "Unnamed upload";
    return option;
  })];
  select.replaceChildren(...options);
  select.value = selectedUploadName || "";
}

function renderUploadedFiles(files) {
  uploadedFiles = Array.isArray(files) ? files : [];
  if (selectedUploadName && !uploadedFiles.some((file) => file.name === selectedUploadName)) {
    selectedUploadName = null;
    syncAudioDropHint();
  }
  populatePreviousUploadOptions();
  refs.uploadedFilesList.replaceChildren();
  if (!uploadedFiles.length) {
    const empty = document.createElement("p");
    empty.className = "upload-empty";
    empty.textContent = "No uploaded files found.";
    refs.uploadedFilesList.append(empty);
    syncUploadSelectionState();
    return;
  }

  const running = latestState && latestState.status === "Running";
  const fragment = document.createDocumentFragment();
  uploadedFiles.forEach((file) => {
    const row = document.createElement("article");
    const checkbox = document.createElement("input");
    const details = document.createElement("div");
    const name = document.createElement("p");
    const meta = document.createElement("p");
    const useButton = document.createElement("button");

    row.className = "upload-file-row";
    row.dataset.fileName = file.name || "";
    checkbox.className = "upload-select";
    checkbox.type = "checkbox";
    checkbox.value = file.name || "";
    checkbox.setAttribute("aria-label", `Select ${file.name || "uploaded file"}`);

    name.className = "upload-file-name";
    name.textContent = file.name || "Unnamed upload";
    meta.className = "upload-file-meta";
    meta.textContent = `${formatBytes(file.size)} | ${formatDateTime(file.modified_at)}`;

    useButton.type = "button";
    useButton.dataset.action = "select-upload";
    useButton.dataset.fileName = file.name || "";
    useButton.textContent = "Use";
    useButton.disabled = Boolean(running);

    details.append(name, meta);
    row.append(checkbox, details, useButton);
    fragment.append(row);
  });
  refs.uploadedFilesList.append(fragment);
  syncUploadSelectionState();
  syncUploadedFileActions();
}

function getTranscriptDisplayText(state, display) {
  if (!showingVerbatimTranscript) return display.transcript || "";
  if (state.raw_transcript_output) return state.raw_transcript_output;
  if (state.status === "Running") return "Transcription running...";
  if (!state.status || state.status === "Idle") return "Ready.";
  return "Verbatim transcript not available.";
}

function toggleVerbatimTranscriptView() {
  showingVerbatimTranscript = !showingVerbatimTranscript;
  if (latestState) renderState(latestState);
}

function renderState(state) {
  const signature = buildStateSignature(state);
  if (signature !== lastStateSignature) {
    lastStateSignature = signature;
    lastRefreshAt = new Date();
  }

  latestState = state;
  const display = buildDisplayState(state);
  const running = state.status === "Running";
  const hasExports = Object.keys(state.export_files || {}).length > 0;

  setStatusBadge(state.status || "Idle");
  refs.noticeText.textContent = getRunControlNotice(state);
  refs.transcriptOutput.value = getTranscriptDisplayText(state, display);
  refs.summaryOutput.value = display.summary || "";
  resizeResultOutputs();
  refs.logOutput.textContent = state.log_tail || "No log output yet.";

  refs.toggleVerbatimBtn.textContent = showingVerbatimTranscript ? "View Clean" : "View Verbatim";
  refs.toggleVerbatimBtn.setAttribute("aria-pressed", String(showingVerbatimTranscript));

  refs.metricStatus.textContent = state.status || "Idle";
  refs.metricRuntime.textContent = formatRuntime(state.started_at, state.completed_at);
  refs.metricWords.textContent = String(countWords(display.transcript));
  refs.metricBullets.textContent = String(countBullets(display.summary));
  refs.metricView.textContent = display.viewName;
  refs.metricExports.textContent = String(Object.keys(state.export_files || {}).length);

  refs.opsLanguage.textContent = display.viewName;
  refs.opsSourceFile.textContent = state.active_audio_name || "Not set";
  refs.opsLastUpdated.textContent = formatDateTime(state.completed_at || state.started_at);
  refs.lastRefreshText.textContent = `Last refresh: ${lastRefreshAt ? lastRefreshAt.toLocaleTimeString() : "--"}`;

  setChecklistState(refs.checkInput, Boolean(state.active_audio_name));
  setChecklistState(refs.checkRun, running || String(state.status || "").startsWith("Completed"));
  setChecklistState(refs.checkExport, hasExports);

  latestArtifactUrls = {
    pdf: { clean: display.pdfUrl, verbatim: display.pdfVerbatimUrl },
    docx: { clean: display.docxUrl, verbatim: display.docxVerbatimUrl },
    json: { clean: display.jsonUrl, verbatim: display.jsonVerbatimUrl },
    bundle: state.bundle_output ? "/api/download/bundle" : null,
  };
  renderArtifactSelection(running);

  renderTimeline(state.timeline || []);
  syncUploadedFileActions();
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
  return [
    "audio/mpeg",
    "audio/wav",
    "audio/x-wav",
    "audio/flac",
    "audio/x-flac",
    "audio/mp4",
    "audio/x-m4a",
    "video/mp4",
  ].includes(
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
  if (selectedUploadName) {
    refs.audioDropHint.textContent = `Selected uploaded file: ${selectedUploadName}`;
    return;
  }
  refs.audioDropHint.textContent = file ? `Selected file: ${file.name}` : "Or drag and drop an audio file here.";
}

function assignAudioFile(file) {
  if (!file) return false;
  try {
    if (typeof DataTransfer === "function") {
      const transfer = new DataTransfer();
      transfer.items.add(file);
      refs.audioFileInput.files = transfer.files;
      selectedUploadName = null;
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
    refs.noticeText.textContent = "Unsupported file type. Use .mp3, .wav, .m4a, .flac, or .mp4.";
    return;
  }
  if (!assignAudioFile(file)) {
    refs.noticeText.textContent = "Drop detected, but file assignment was blocked. Use Choose File.";
    return;
  }
  refs.noticeText.textContent = `${file.name} Ready. File Uploaded`;
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
    const file = refs.audioFileInput.files && refs.audioFileInput.files[0];
    if (file) {
      selectedUploadName = null;
      syncUploadedFileActions();
      refs.noticeText.textContent = `${file.name} Ready. File Uploaded`;
    }
    syncAudioDropHint();
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

async function loadUploads() {
  try {
    refs.noticeText.textContent = "Refreshing uploaded files.";
    const response = await fetch("/api/uploads");
    if (!response.ok) {
      const details = await response.json().catch(() => ({}));
      throw new Error(details.detail || `Request failed (${response.status})`);
    }
    const data = await response.json();
    renderUploadedFiles(data.files || []);
    refs.noticeText.textContent = `Loaded ${(data.files || []).length} uploaded file(s).`;
  } catch (error) {
    refs.noticeText.textContent = String(error.message || error);
  }
}

async function refreshUploadedFilesSilently() {
  try {
    const response = await fetch("/api/uploads");
    if (!response.ok) return;
    const data = await response.json();
    renderUploadedFiles(data.files || []);
  } catch {
    // no-op: this is a background refresh, surfaced errors would be noisy
  }
}

async function toggleUploadManager() {
  if (refs.uploadManagerPanel.hidden) {
    refs.uploadManagerPanel.hidden = false;
    refs.showUploadsBtn.textContent = "Hide uploaded files";
    await loadUploads();
    refs.refreshUploadsBtn.focus();
  } else {
    closeUploadManager();
  }
}

function closeUploadManager() {
  hideDeleteConfirmPopup();
  refs.uploadManagerPanel.hidden = true;
  refs.showUploadsBtn.textContent = "Manage uploaded files";
  refs.showUploadsBtn.focus();
}

function showDeleteConfirmPopup(fileNames) {
  pendingDeleteNames = fileNames;
  refs.deleteConfirmMessage.textContent = `Delete ${fileNames.length} selected uploaded file(s)? This cannot be undone.`;
  refs.deleteConfirmPopup.hidden = false;
  refs.confirmDeleteUploadsBtn.focus();
}

function hideDeleteConfirmPopup() {
  pendingDeleteNames = [];
  refs.deleteConfirmPopup.hidden = true;
}

function requestDeleteSelectedUploads() {
  const fileNames = getSelectedUploadNames();
  if (!fileNames.length) return;
  showDeleteConfirmPopup(fileNames);
}

async function deleteSelectedUploads() {
  const fileNames = pendingDeleteNames.slice();
  if (!fileNames.length) return;
  hideDeleteConfirmPopup();
  try {
    const data = await callJson("/api/uploads/delete", { file_names: fileNames });
    if (selectedUploadName && fileNames.includes(selectedUploadName)) {
      selectedUploadName = null;
      syncAudioDropHint();
    }
    renderUploadedFiles(data.files || []);
    refs.noticeText.textContent = data.deleted && data.deleted.length ? `Deleted ${data.deleted.length} upload(s).` : "No uploads deleted.";
    if (latestState && data.deleted && data.deleted.includes(latestState.active_audio_name)) {
      latestState.active_audio_name = null;
      renderState(latestState);
    }
  } catch (error) {
    refs.noticeText.textContent = String(error.message || error);
  }
}

function buildHistoryDownloadUrl(stem, format, verbatim) {
  const params = new URLSearchParams({ stem, format });
  if (verbatim) params.set("verbatim", "true");
  return `/api/history/download?${params.toString()}`;
}

function getSelectedHistoryStems() {
  return Array.from(refs.historyList.querySelectorAll(".history-select:checked")).map((input) => input.value);
}

function syncHistorySelectionState() {
  const checkboxes = Array.from(refs.historyList.querySelectorAll(".history-select"));
  const selectedCount = checkboxes.filter((input) => input.checked).length;
  refs.deleteHistoryBtn.disabled = selectedCount === 0;
  refs.deleteHistoryBtn.setAttribute("aria-disabled", selectedCount === 0 ? "true" : "false");
  refs.selectAllHistory.disabled = checkboxes.length === 0;
  refs.selectAllHistory.checked = checkboxes.length > 0 && selectedCount === checkboxes.length;
  refs.selectAllHistory.indeterminate = selectedCount > 0 && selectedCount < checkboxes.length;
  refs.historyBulkActions.hidden = selectedCount === 0;
}

function setHistorySelectionMode(active) {
  historySelectionMode = active;
  refs.historyList.classList.toggle("selecting", active);
  refs.toggleHistorySelectBtn.textContent = active ? "Cancel" : "Select";
  refs.toggleHistorySelectBtn.setAttribute("aria-pressed", String(active));
  if (!active) {
    refs.historyList.querySelectorAll(".history-select").forEach((input) => {
      input.checked = false;
    });
  }
  syncHistorySelectionState();
}

function toggleHistorySelectionMode() {
  setHistorySelectionMode(!historySelectionMode);
}

function renderHistory(entries) {
  historyEntries = Array.isArray(entries) ? entries : [];
  refs.historyList.replaceChildren();
  if (!historyEntries.length) {
    const empty = document.createElement("p");
    empty.className = "upload-empty";
    empty.textContent = "No transcriptions found.";
    refs.historyList.append(empty);
    syncHistorySelectionState();
    return;
  }

  const fragment = document.createDocumentFragment();
  historyEntries.forEach((entry) => {
    const row = document.createElement("article");
    row.className = "history-row";
    row.dataset.stem = entry.stem;

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "history-select";
    checkbox.value = entry.stem;
    checkbox.setAttribute("aria-label", `Select ${entry.audio_name || entry.stem}`);

    const details = document.createElement("div");
    details.className = "history-details";
    const name = document.createElement("p");
    name.className = "history-file-name";
    name.textContent = entry.audio_name || entry.stem;
    const meta = document.createElement("p");
    meta.className = "history-file-meta";
    meta.textContent = formatDateTime(entry.created_at);
    details.append(name, meta);

    const actions = document.createElement("div");
    actions.className = "history-row-actions";

    const hasVerbatim = Boolean(entry.verbatim_formats && entry.verbatim_formats.length);
    let verbatimToggle = null;
    if (hasVerbatim) {
      const toggleLabel = document.createElement("label");
      toggleLabel.className = "history-verbatim-toggle";
      verbatimToggle = document.createElement("input");
      verbatimToggle.type = "checkbox";
      const toggleText = document.createElement("span");
      toggleText.textContent = "Verbatim";
      toggleLabel.append(verbatimToggle, toggleText);
      actions.append(toggleLabel);
    }

    const downloadGroup = document.createElement("div");
    downloadGroup.className = "history-download-group";
    ["pdf", "docx", "json"].forEach((format) => {
      const link = document.createElement("a");
      link.className = "download";
      link.textContent = HISTORY_FORMAT_LABELS[format];

      const updateLink = () => {
        const verbatim = Boolean(verbatimToggle && verbatimToggle.checked);
        const available = verbatim ? entry.verbatim_formats : entry.formats;
        setDownloadState(link, available && available.includes(format) ? buildHistoryDownloadUrl(entry.stem, format, verbatim) : null);
      };
      updateLink();
      if (verbatimToggle) verbatimToggle.addEventListener("change", updateLink);
      downloadGroup.append(link);
    });
    actions.append(downloadGroup);

    const deleteBtn = document.createElement("button");
    deleteBtn.type = "button";
    deleteBtn.className = "danger";
    deleteBtn.dataset.action = "delete-history";
    deleteBtn.dataset.stem = entry.stem;
    deleteBtn.textContent = "Delete";

    row.append(checkbox, details, actions, deleteBtn);
    fragment.append(row);
  });
  refs.historyList.append(fragment);
  syncHistorySelectionState();
}

async function loadHistory() {
  try {
    refs.noticeText.textContent = "Refreshing history.";
    const response = await fetch("/api/history");
    if (!response.ok) {
      const details = await response.json().catch(() => ({}));
      throw new Error(details.detail || `Request failed (${response.status})`);
    }
    const data = await response.json();
    renderHistory(data.entries || []);
    refs.noticeText.textContent = `Loaded ${(data.entries || []).length} transcription(s).`;
  } catch (error) {
    refs.noticeText.textContent = String(error.message || error);
  }
}

async function toggleHistoryPanel() {
  if (refs.historyPanel.hidden) {
    refs.historyPanel.hidden = false;
    await loadHistory();
    refs.refreshHistoryBtn.focus();
  } else {
    closeHistoryPanel();
  }
}

function closeHistoryPanel() {
  hideHistoryDeleteConfirm();
  setHistorySelectionMode(false);
  refs.historyPanel.hidden = true;
  refs.showHistoryBtn.focus();
}

function showHistoryDeleteConfirm(stems) {
  if (!stems || !stems.length) return;
  pendingDeleteHistoryStems = stems;
  if (stems.length === 1) {
    const entry = historyEntries.find((item) => item.stem === stems[0]);
    const label = (entry && (entry.audio_name || entry.stem)) || stems[0];
    refs.historyDeleteConfirmMessage.textContent = `Delete "${label}"? This removes the uploaded audio and all transcript files. This cannot be undone.`;
  } else {
    refs.historyDeleteConfirmMessage.textContent = `Delete ${stems.length} selected transcription(s)? This removes the uploaded audio and all transcript files. This cannot be undone.`;
  }
  refs.historyDeleteConfirmPopup.hidden = false;
  refs.confirmHistoryDeleteBtn.focus();
}

function hideHistoryDeleteConfirm() {
  pendingDeleteHistoryStems = [];
  refs.historyDeleteConfirmPopup.hidden = true;
}

function requestDeleteSelectedHistory() {
  const stems = getSelectedHistoryStems();
  if (!stems.length) return;
  showHistoryDeleteConfirm(stems);
}

async function deleteSelectedHistory() {
  const stems = pendingDeleteHistoryStems.slice();
  if (!stems.length) return;
  hideHistoryDeleteConfirm();
  try {
    const data = await callJson("/api/history/delete", { stems });
    renderHistory(data.entries || []);
    refs.noticeText.textContent =
      data.deleted_stems && data.deleted_stems.length
        ? `Deleted ${data.deleted_stems.length} transcription history item(s).`
        : "No history items deleted.";
    await refreshUploadedFilesSilently();
    const deletedStems = data.deleted_stems || [];
    const activeStem = latestState && latestState.active_audio_name ? latestState.active_audio_name.replace(/\.[^./]+$/, "") : null;
    if (activeStem && deletedStems.includes(activeStem)) {
      const stateResponse = await fetch("/api/state");
      if (stateResponse.ok) renderState(await stateResponse.json());
    }
  } catch (error) {
    refs.noticeText.textContent = String(error.message || error);
  }
}

async function submitRun(event) {
  event.preventDefault();
  const file = refs.audioFileInput.files[0];
  if (!file && !selectedUploadName) {
    refs.noticeText.textContent = "Select an audio file first.";
    return;
  }

  const language = getSelectedLanguage();

  try {
    let state;
    if (selectedUploadName) {
      state = await callJson("/api/transcribe-existing", { file_name: selectedUploadName, language });
    } else {
      const data = new FormData();
      data.append("audio_file", file);
      if (language) data.append("language", language);
      const response = await fetch("/api/transcribe", { method: "POST", body: data });
      if (!response.ok) {
        const details = await response.json().catch(() => ({}));
        throw new Error(details.detail || `Request failed (${response.status})`);
      }
      state = await response.json();
    }
    renderState(state);
    await refreshUploadedFilesSilently();
  } catch (error) {
    refs.noticeText.textContent = String(error.message || error);
  }
}

async function clearRun() {
  try {
    const state = await callJson("/api/clear", {});
    clearSelectedUpload();
    refs.audioFileInput.value = "";
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

function togglePlatformMeta() {
  const expanded = refs.togglePlatformMetaBtn.getAttribute("aria-expanded") === "true";
  const next = !expanded;
  refs.togglePlatformMetaBtn.setAttribute("aria-expanded", String(next));
  refs.togglePlatformMetaBtn.setAttribute("aria-label", next ? "Collapse platform highlights" : "Expand platform highlights");
  refs.togglePlatformMetaBtn.title = next ? "Collapse" : "Expand";
  refs.platformMetaPills.hidden = !next;
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
  await refreshUploadedFilesSilently();
}

refs.runForm.addEventListener("submit", submitRun);
refs.clearBtn.addEventListener("click", clearRun);
refs.bundleBtn.addEventListener("click", buildBundle);
refs.showUploadsBtn.addEventListener("click", toggleUploadManager);
refs.closeUploadManagerBtn.addEventListener("click", closeUploadManager);
refs.selectAllUploads.addEventListener("change", () => {
  refs.uploadedFilesList.querySelectorAll(".upload-select").forEach((input) => {
    input.checked = refs.selectAllUploads.checked;
  });
  syncUploadSelectionState();
});
refs.uploadedFilesList.addEventListener("change", (event) => {
  if (!(event.target instanceof Element)) return;
  if (event.target && event.target.classList.contains("upload-select")) {
    syncUploadSelectionState();
  }
});
refs.uploadedFilesList.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) return;
  const button = event.target.closest("[data-action='select-upload']");
  if (button) {
    selectUploadedFile(button.dataset.fileName || "");
    return;
  }

  const row = event.target.closest(".upload-file-row");
  if (row && !event.target.closest("input")) {
    const checkbox = row.querySelector(".upload-select");
    if (checkbox) {
      checkbox.checked = !checkbox.checked;
      syncUploadSelectionState();
    }
  }
});
refs.uploadManagerPanel.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) return;
  if (event.target === refs.uploadManagerPanel) {
    closeUploadManager();
    return;
  }

  const refreshButton = event.target.closest("#refreshUploadsBtn");
  if (refreshButton) {
    event.preventDefault();
    loadUploads();
    return;
  }

  const deleteButton = event.target.closest("#deleteUploadsBtn");
  if (deleteButton && !refs.deleteUploadsBtn.disabled) {
    event.preventDefault();
    requestDeleteSelectedUploads();
  }
});
refs.cancelDeleteUploadsBtn.addEventListener("click", hideDeleteConfirmPopup);
refs.confirmDeleteUploadsBtn.addEventListener("click", deleteSelectedUploads);
refs.lookupBtn.addEventListener("click", runLookup);
refs.showHistoryBtn.addEventListener("click", toggleHistoryPanel);
refs.toggleHistorySelectBtn.addEventListener("click", toggleHistorySelectionMode);
refs.closeHistoryBtn.addEventListener("click", closeHistoryPanel);
refs.historyPanel.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) return;
  if (event.target === refs.historyPanel) {
    closeHistoryPanel();
    return;
  }
  const refreshButton = event.target.closest("#refreshHistoryBtn");
  if (refreshButton) {
    event.preventDefault();
    loadHistory();
  }
});
refs.historyList.addEventListener("click", (event) => {
  if (!(event.target instanceof Element)) return;
  const deleteButton = event.target.closest("[data-action='delete-history']");
  if (deleteButton) showHistoryDeleteConfirm([deleteButton.dataset.stem || ""].filter(Boolean));
});
refs.historyList.addEventListener("change", (event) => {
  if (!(event.target instanceof Element)) return;
  if (event.target.classList.contains("history-select")) syncHistorySelectionState();
});
refs.selectAllHistory.addEventListener("change", () => {
  refs.historyList.querySelectorAll(".history-select").forEach((input) => {
    input.checked = refs.selectAllHistory.checked;
  });
  syncHistorySelectionState();
});
refs.deleteHistoryBtn.addEventListener("click", () => {
  if (!refs.deleteHistoryBtn.disabled) requestDeleteSelectedHistory();
});
refs.cancelHistoryDeleteBtn.addEventListener("click", hideHistoryDeleteConfirm);
refs.confirmHistoryDeleteBtn.addEventListener("click", deleteSelectedHistory);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !refs.deleteConfirmPopup.hidden) {
    hideDeleteConfirmPopup();
    return;
  }
  if (event.key === "Escape" && !refs.historyDeleteConfirmPopup.hidden) {
    hideHistoryDeleteConfirm();
    return;
  }
  if (event.key === "Escape" && !refs.uploadManagerPanel.hidden) {
    closeUploadManager();
    return;
  }
  if (event.key === "Escape" && !refs.historyPanel.hidden) {
    closeHistoryPanel();
  }
});
refs.lookupInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    runLookup();
  }
});
refs.copyTranscriptBtn.addEventListener("click", copyTranscript);
refs.toggleVerbatimBtn.addEventListener("click", toggleVerbatimTranscriptView);
refs.languageSelect.addEventListener("change", () => {
  if (latestState) renderState(latestState);
});
refs.artifactDownloadLink.addEventListener("click", (event) => {
  if (refs.artifactDownloadLink.dataset.mode === "build") {
    event.preventDefault();
    if (!refs.artifactDownloadLink.classList.contains("disabled")) buildBundle();
  }
});
refs.artifactSelect.addEventListener("change", () => {
  const running = latestState && latestState.status === "Running";
  renderArtifactSelection(Boolean(running));
});
refs.artifactVerbatimToggle.addEventListener("change", () => {
  const running = latestState && latestState.status === "Running";
  renderArtifactSelection(Boolean(running));
});
refs.previousUploadSelect.addEventListener("change", () => {
  const fileName = refs.previousUploadSelect.value;
  if (fileName) {
    selectUploadedFile(fileName);
  } else {
    clearSelectedUpload();
  }
});
refs.tabButtons.forEach((button) => {
  button.addEventListener("click", () => activateTab(button.dataset.tab));
});
refs.togglePlatformMetaBtn.addEventListener("click", togglePlatformMeta);
window.addEventListener("resize", resizeResultOutputs);

setupAudioDropZone();
initialLoad();
connectWebSocket();
