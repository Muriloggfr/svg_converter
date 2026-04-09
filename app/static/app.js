/**
 * SVG Converter — Frontend logic
 *
 * Handles drag-and-drop upload, form submission, SVG preview, and download.
 */

"use strict";

// ---------------------------------------------------------------------------
// DOM references
// ---------------------------------------------------------------------------

const dropZone      = document.getElementById("drop-zone");
const fileInput     = document.getElementById("file-input");
const fileInfo      = document.getElementById("file-info");
const fileNameEl    = document.getElementById("file-name");
const fileSizeEl    = document.getElementById("file-size");
const clearBtn      = document.getElementById("clear-btn");
const presetSelect  = document.getElementById("preset");
const removeBgCheck = document.getElementById("remove-bg");
const convertBtn    = document.getElementById("convert-btn");

const resultEmpty   = document.getElementById("result-empty");
const resultContent = document.getElementById("result-content");
const originalPrev  = document.getElementById("original-preview");
const svgPrev       = document.getElementById("svg-preview");
const svgSizeEl     = document.getElementById("svg-size");
const svgPresetEl   = document.getElementById("svg-preset");
const downloadBtn   = document.getElementById("download-btn");

const loadingOverlay = document.getElementById("loading-overlay");
const statusBar      = document.getElementById("status-bar");

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

let currentFile      = null;
let currentObjectUrl = null;  // for original preview
let currentSvgUrl    = null;  // for SVG blob URL
let isConverting     = false;
let statusTimer      = null;

// ---------------------------------------------------------------------------
// Accepted MIME types (client-side pre-check only — server validates too)
// ---------------------------------------------------------------------------

const ACCEPTED_TYPES = new Set([
  "image/png", "image/jpeg", "image/jpg", "image/gif",
  "image/bmp", "image/x-bmp", "image/x-ms-bmp",
  "image/webp", "image/tiff",
]);

const MAX_BYTES = 10 * 1024 * 1024;  // 10 MB

// ---------------------------------------------------------------------------
// File handling
// ---------------------------------------------------------------------------

function formatBytes(bytes) {
  if (bytes < 1024)        return `${bytes} B`;
  if (bytes < 1048576)     return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

function handleFile(file) {
  if (!file) return;

  // Client-side type check for immediate feedback
  const mime = file.type || "";
  const isImage = mime.startsWith("image/") || ACCEPTED_TYPES.has(mime);
  if (!isImage) {
    showError("Please select an image file (PNG, JPG, GIF, BMP, WEBP, or TIFF).");
    return;
  }

  if (file.size > MAX_BYTES) {
    showError(`File is too large (${formatBytes(file.size)}). Maximum is 10 MB.`);
    return;
  }

  currentFile = file;
  clearResult();

  // Show file info pill
  fileNameEl.textContent = file.name;
  fileSizeEl.textContent = formatBytes(file.size);
  fileInfo.classList.remove("hidden");

  // Show original preview
  if (currentObjectUrl) URL.revokeObjectURL(currentObjectUrl);
  currentObjectUrl = URL.createObjectURL(file);
  originalPrev.src = currentObjectUrl;

  // Update drop zone appearance
  dropZone.classList.add("has-file");

  // Enable convert button
  convertBtn.disabled = false;

  hideError();
}

function clearFile() {
  currentFile = null;
  fileInput.value = "";
  fileInfo.classList.add("hidden");
  fileNameEl.textContent = "";
  fileSizeEl.textContent = "";
  dropZone.classList.remove("has-file");
  convertBtn.disabled = true;

  if (currentObjectUrl) {
    URL.revokeObjectURL(currentObjectUrl);
    currentObjectUrl = null;
  }

  clearResult();
}

// ---------------------------------------------------------------------------
// Drag & drop
// ---------------------------------------------------------------------------

dropZone.addEventListener("dragenter", (e) => {
  e.preventDefault();
  dropZone.classList.add("drag-over");
});

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("drag-over");
});

dropZone.addEventListener("dragleave", (e) => {
  if (!dropZone.contains(e.relatedTarget)) {
    dropZone.classList.remove("drag-over");
  }
});

dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("drag-over");
  const file = e.dataTransfer.files[0];
  if (file) handleFile(file);
});

// Keyboard: activate drop zone with Enter/Space
dropZone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    fileInput.click();
  }
});

// Click on drop zone (but not on the hidden input itself)
dropZone.addEventListener("click", () => fileInput.click());

fileInput.addEventListener("change", () => {
  if (fileInput.files.length > 0) handleFile(fileInput.files[0]);
});

clearBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  clearFile();
});

// ---------------------------------------------------------------------------
// Conversion
// ---------------------------------------------------------------------------

convertBtn.addEventListener("click", doConvert);

async function doConvert() {
  if (!currentFile || isConverting) return;

  isConverting = true;
  setLoading(true);
  clearResult();
  hideError();

  const formData = new FormData();
  formData.append("file", currentFile);
  formData.append("preset", presetSelect.value);
  formData.append("remove_bg", removeBgCheck.checked ? "true" : "false");

  try {
    const resp = await fetch("/api/convert", {
      method: "POST",
      body: formData,
    });

    if (!resp.ok) {
      let detail = `Server error (${resp.status})`;
      try {
        const err = await resp.json();
        detail = err.detail || detail;
      } catch (_) { /* ignore JSON parse error */ }
      throw new Error(detail);
    }

    const svgText = await resp.text();
    showResult(svgText);
  } catch (err) {
    showError(err.message || "An unexpected error occurred. Please try again.");
  } finally {
    isConverting = false;
    setLoading(false);
  }
}

// ---------------------------------------------------------------------------
// Result display
// ---------------------------------------------------------------------------

function showResult(svgText) {
  // Revoke previous SVG blob URL
  if (currentSvgUrl) {
    URL.revokeObjectURL(currentSvgUrl);
    currentSvgUrl = null;
  }

  const blob = new Blob([svgText], { type: "image/svg+xml" });
  currentSvgUrl = URL.createObjectURL(blob);

  // Render SVG as an <img> so it is displayed as a vector graphic
  svgPrev.src = currentSvgUrl;

  // Keep original preview
  originalPrev.src = currentObjectUrl;

  // Meta tags
  svgSizeEl.textContent = `SVG ${formatBytes(blob.size)}`;
  const presetLabels = {
    fast: "Fast",
    balanced: "Balanced",
    high_quality: "High Quality",
  };
  svgPresetEl.textContent = presetLabels[presetSelect.value] || presetSelect.value;

  // Download link
  const stem = currentFile.name.replace(/\.[^/.]+$/, "");
  downloadBtn.href = currentSvgUrl;
  downloadBtn.download = `${stem}.svg`;

  // Show result section
  resultEmpty.classList.add("hidden");
  resultContent.classList.remove("hidden");
}

function clearResult() {
  resultEmpty.classList.remove("hidden");
  resultContent.classList.add("hidden");
  svgPrev.src = "";
  originalPrev.src = "";

  if (currentSvgUrl) {
    URL.revokeObjectURL(currentSvgUrl);
    currentSvgUrl = null;
  }
}

// ---------------------------------------------------------------------------
// Loading state
// ---------------------------------------------------------------------------

function setLoading(state) {
  loadingOverlay.classList.toggle("hidden", !state);
  convertBtn.disabled = state;
}

// ---------------------------------------------------------------------------
// Error / status messages
// ---------------------------------------------------------------------------

function showError(message) {
  statusBar.textContent = message;
  statusBar.classList.remove("hidden");

  // Auto-hide after 6 seconds
  clearTimeout(statusTimer);
  statusTimer = setTimeout(hideError, 6000);
}

function hideError() {
  statusBar.classList.add("hidden");
  clearTimeout(statusTimer);
}
