// Persistent JIN attachment library. Files are copied to /assets/files immediately
// on drop/paste and the pinned subset is attached to every following user turn.

const chatColumn = document.querySelector("#chat-drop-zone");
const fileInput = document.querySelector("#file-input");
const attachedFiles = document.querySelector("#attached-files");
const MAX_JIN_ATTACHMENTS = 5;
const MEMORY_ROW_AVATAR_HOVER_EVENT = "jin:memory-row-avatar-hover";


let dragDepth = 0;
let dropOverlay = null;
let fileStore = [];
let pinnedIds = [];
let fileStoreLoaded = false;
let uploadQueue = Promise.resolve();
const deletedFileRestoreCache = new Map();

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function formatBytes(bytes) {
  const size = Number(bytes || 0);
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function pinSvg() {
  return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.7 3.3 20.7 9.3 18.6 11.4 16.9 9.7 13.7 12.9 14.4 15.7 12.9 17.2 9.4 13.7 5.3 17.8 4.2 16.7 8.3 12.6 4.8 9.1 6.3 7.6 9.1 8.3 12.3 5.1 10.6 3.4 12.7 1.3Z"/></svg>';
}

function compareFileRecords(left, right) {
  const pinDiff = Number(Boolean(right && right.pinned)) - Number(Boolean(left && left.pinned));
  if (pinDiff) return pinDiff;

  if (left && right && left.pinned && right.pinned) {
    const pinTimeDiff = Number(right.pinned_at || 0) - Number(left.pinned_at || 0);
    if (pinTimeDiff) return pinTimeDiff;
  }

  const createdDiff = Number(right && right.created_at || 0) - Number(left && left.created_at || 0);
  if (createdDiff) return createdDiff;

  const idDiff = String(left && left.id || "").localeCompare(String(right && right.id || ""));
  if (idDiff) return idDiff;
  return String(left && left.name || "").localeCompare(String(right && right.name || ""));
}

function normalizeSnapshot(payload) {
  fileStoreLoaded = true;
  fileStore = Array.isArray(payload && payload.files)
    ? payload.files.filter((item) => item && item.id)
    : [];
  pinnedIds = Array.isArray(payload && payload.pinned_ids)
    ? payload.pinned_ids.slice(0, MAX_JIN_ATTACHMENTS).map((value) => String(value || "").toLowerCase())
    : fileStore.filter((item) => item.pinned).map((item) => item.id).slice(0, MAX_JIN_ATTACHMENTS);

  const pinnedSet = new Set(pinnedIds);
  fileStore.forEach((record) => {
    record.pinned = pinnedSet.has(String(record.id || "").toLowerCase());
    record.size_label = record.size_label || formatBytes(record.size_bytes);
  });
  fileStore.sort(compareFileRecords);
  pinnedIds = fileStore
    .filter((record) => record && record.pinned)
    .map((record) => String(record.id || "").toLowerCase())
    .filter(Boolean)
    .slice(0, MAX_JIN_ATTACHMENTS);
}

function dispatchStoreChanged() {
  renderAttachedFilesPlaque();
  window.dispatchEvent(new CustomEvent("jin:files-store-changed", {
    detail: {
      files: fileStore.map((item) => ({...item})),
      pinned_ids: [...pinnedIds],
    },
  }));
}

function buildFileAvatarHoverId(fileId) {
  if (!(window.JinRuntime && typeof window.JinRuntime.buildAvatarMemoryHoverId === "function")) {
    return "";
  }
  return window.JinRuntime.buildAvatarMemoryHoverId("file", fileId);
}

function dispatchAttachedFileAvatarHover(fileId, active) {
  const avatarMemoryHoverId = buildFileAvatarHoverId(fileId);
  window.dispatchEvent(new CustomEvent(MEMORY_ROW_AVATAR_HOVER_EVENT, {
    detail: active && avatarMemoryHoverId
      ? {active: true, avatarMemoryHoverId}
      : {active: false},
  }));
}

function bindAttachedFilesPlaqueAvatarHover(element, fileId) {
  if (!element || !fileId) return;
  const activate = () => dispatchAttachedFileAvatarHover(fileId, true);
  const deactivate = () => dispatchAttachedFileAvatarHover(fileId, false);
  element.addEventListener("mouseenter", activate);
  element.addEventListener("mouseleave", deactivate);
  element.addEventListener("focus", activate);
  element.addEventListener("blur", deactivate);
}

function syncAttachmentContext() {
  if (!fileStoreLoaded || typeof window.sendSocketMessage !== "function") return false;
  return window.sendSocketMessage({
    type: "attachment_context_sync",
    ids: [...pinnedIds],
  });
}

async function refreshFiles({sync = false} = {}) {
  try {
    const response = await fetch("/api/files", {cache: "no-store"});
    if (!response.ok) return false;
    normalizeSnapshot(await response.json());
    dispatchStoreChanged();
    if (sync || window.jinWebSocketConnected === true) syncAttachmentContext();
    return true;
  } catch (_error) {
    return false;
  }
}

function getFileRecord(id) {
  const normalized = String(id || "").toLowerCase();
  return fileStore.find((item) => String(item.id || "").toLowerCase() === normalized) || null;
}

async function readImageDimensions(file) {
  if (!file || !String(file.type || "").toLowerCase().startsWith("image/")) {
    return {width: null, height: null};
  }
  return new Promise((resolve) => {
    const image = new Image();
    const url = URL.createObjectURL(file);
    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve({width: image.naturalWidth || null, height: image.naturalHeight || null});
    };
    image.onerror = () => {
      URL.revokeObjectURL(url);
      resolve({width: null, height: null});
    };
    image.src = url;
  });
}

async function uploadFile(file) {
  if (!file) return false;
  const dimensions = await readImageDimensions(file);
  const body = new FormData();
  body.append("file", file, file.name || "attachment");
  if (dimensions.width) body.append("width", String(dimensions.width));
  if (dimensions.height) body.append("height", String(dimensions.height));

  try {
    const response = await fetch("/api/files/upload", {method: "POST", body});
    if (!response.ok) return false;
    normalizeSnapshot(await response.json());
    dispatchStoreChanged();
    syncAttachmentContext();
    if (
      window.JinPanels
      && typeof window.JinPanels.expandConsolePanelForContextAttachment === "function"
    ) {
      window.JinPanels.expandConsolePanelForContextAttachment();
    }
    return true;
  } catch (_error) {
    return false;
  }
}

function addFiles(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length) return;
  // Serialize uploads so identical drops cannot race the SHA-256 dedupe.
  uploadQueue = files.reduce(
    (chain, file) => chain.then(() => uploadFile(file)),
    uploadQueue
  );
  if (fileInput) fileInput.value = "";
}

async function setPinned(id, pinned) {
  const record = getFileRecord(id);
  if (!record) return false;
  if (Boolean(record.pinned) === Boolean(pinned)) return true;
  try {
    const response = await fetch(
      `/api/files/${encodeURIComponent(id)}/pin?pinned=${pinned ? "true" : "false"}`,
      {method: "POST"}
    );
    if (!response.ok) return false;
    normalizeSnapshot(await response.json());
    dispatchStoreChanged();
    syncAttachmentContext();
    return true;
  } catch (_error) {
    return false;
  }
}

async function deleteFile(id) {
  const record = getFileRecord(id);
  if (!record) return false;

  const restoreSource = String(record.url || record.context_path || "").trim();
  if (!restoreSource) return false;

  try {
    const backupResponse = await fetch(restoreSource, {cache: "no-store"});
    if (!backupResponse.ok) return false;
    const blob = await backupResponse.blob();

    const response = await fetch(`/api/files/${encodeURIComponent(id)}`, {method: "DELETE"});
    if (!response.ok) return false;

    const normalizedId = String(record.id || id || "").trim().toLowerCase();
    deletedFileRestoreCache.set(normalizedId, {
      record: {...record},
      blob,
    });

    normalizeSnapshot(await response.json());
    dispatchStoreChanged();
    syncAttachmentContext();

    if (typeof window.appendLog === "function") {
      window.appendLog(
        "[MEMORY:FILES:DELETED]",
        "File deleted",
        JSON.stringify({
          kind: "file",
          file: record,
        }, null, 2),
        {
          memory_event: "file_deleted",
          deleted_file: {...record},
        }
      );
    }

    return true;
  } catch (_error) {
    return false;
  }
}

async function restoreDeletedFile(id) {
  const normalizedId = String(id || "").trim().toLowerCase();
  const state = deletedFileRestoreCache.get(normalizedId);
  if (!state || !state.record || !state.blob) return false;

  const body = new FormData();
  body.append(
    "file",
    state.blob,
    String(state.record.name || "attachment")
  );
  body.append("record", JSON.stringify(state.record));

  try {
    const response = await fetch(
      `/api/files/${encodeURIComponent(normalizedId)}/restore`,
      {method: "POST", body}
    );
    if (!response.ok) return false;

    normalizeSnapshot(await response.json());
    deletedFileRestoreCache.delete(normalizedId);
    dispatchStoreChanged();
    syncAttachmentContext();
    return true;
  } catch (_error) {
    return false;
  }
}

async function resolvePersistentAttachment(record) {
  const base = {...record, size_label: record.size_label || formatBytes(record.size_bytes)};
  if (base.kind !== "text") return base;
  try {
    const response = await fetch(`/api/files/${encodeURIComponent(base.id)}/preview`, {cache: "no-store"});
    if (!response.ok) return base;
    const payload = await response.json();
    return {...base, ...(payload.file || {}), text_content: payload.text_content || ""};
  } catch (_error) {
    return base;
  }
}

function attachmentViewRecord(record) {
  const attachment = {...record, size_label: record.size_label || formatBytes(record.size_bytes)};
  attachment.resolve_modal_attachment = () => resolvePersistentAttachment(attachment);
  return attachment;
}

function bindAttachedFilesPlaqueName(element, record) {
  if (!element || !record) return;
  const attachment = attachmentViewRecord(record);

  const bind = () => {
    if (element.dataset.jinAttachmentBound === "1") return true;
    if (typeof window.bindJinAttachmentBubble !== "function") return false;
    window.bindJinAttachmentBubble(element, attachment, {
      hoverPreviewMaxPx: 100,
    });
    element.dataset.jinAttachmentBound = "1";
    return true;
  };

  if (!bind()) {
    window.addEventListener("jin:attachment-ui-ready", bind, {once: true});
  }
}

function bindAttachedFilesPlaquePinPreview(element, record) {
  if (!element || !record) return;
  const attachment = attachmentViewRecord(record);

  const bind = () => {
    if (element.dataset.jinAttachmentHoverBound === "1") return true;
    if (typeof window.bindJinAttachmentHoverPreview !== "function") return false;
    window.bindJinAttachmentHoverPreview(element, attachment, {
      hoverPreviewMaxPx: 100,
    });
    element.dataset.jinAttachmentHoverBound = "1";
    return true;
  };

  if (!bind()) {
    window.addEventListener("jin:attachment-ui-ready", bind, {once: true});
  }
}

function clearAttachedFilesPlaqueHoverPreview() {
  if (!attachedFiles) return;

  // Removing a hovered attachment node does not fire a native mouseleave.
  // Explicitly notify the existing hover bindings before the plaque is rebuilt
  // so the shared image preview cannot remain orphaned after unpin/delete.
  attachedFiles
    .querySelectorAll(
      '[data-jin-attachment-bound="1"], [data-jin-attachment-hover-bound="1"]'
    )
    .forEach((element) => {
      element.dispatchEvent(new Event("mouseleave"));
    });
}

function renderAttachedFilesPlaque() {
  if (!attachedFiles) return;
  const records = pinnedIds.map(getFileRecord).filter(Boolean);
  clearAttachedFilesPlaqueHoverPreview();
  attachedFiles.replaceChildren();
  attachedFiles.classList.toggle("hidden", records.length === 0);
  if (!records.length) return;

  const title = document.createElement("div");
  title.className = "jin-attached-files-title";
  title.textContent = "[ ATTACHED_FILES ]";
  attachedFiles.appendChild(title);

  const list = document.createElement("div");
  list.className = "jin-attached-files-list";
  records.forEach((record) => {
    const row = document.createElement("div");
    const fileId = String(record.id || "").toLowerCase();
    row.className = "jin-attached-files-row runtime-memory-delayed-row-pinned";
    row.dataset.fileId = fileId;
    row.dataset.avatarMemoryHoverId = buildFileAvatarHoverId(fileId);
    bindAttachedFilesPlaqueAvatarHover(row, fileId);
    const pin = document.createElement("button");
    pin.type = "button";
    pin.className = "delayed-memory-modal-icon-button delayed-memory-modal-pin runtime-memory-delayed-pin is-pinned";
    pin.innerHTML = pinSvg();
    pin.title = String(record.id || "");
    pin.setAttribute("aria-label", `Remove ${record.id || "file"} from JIN context`);
    pin.dataset.fileId = String(record.id || "");
    bindAttachedFilesPlaquePinPreview(pin, record);
    bindAttachedFilesPlaqueAvatarHover(pin, fileId);
    pin.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      void setPinned(record.id, false);
    });
    const name = document.createElement("span");
    name.className = "jin-attached-files-name";
    name.textContent = record.name || "attachment";
    name.title = `${record.name || "attachment"} · ${formatBytes(record.size_bytes)}`;
    bindAttachedFilesPlaqueName(name, record);
    bindAttachedFilesPlaqueAvatarHover(name, fileId);
    row.append(pin, name);
    list.appendChild(row);
  });
  attachedFiles.appendChild(list);
}

function hasDraggedFiles(event) {
  return Array.from(event && event.dataTransfer && event.dataTransfer.types || []).includes("Files");
}

function ensureDropOverlay() {
  if (dropOverlay || !chatColumn) return dropOverlay;
  dropOverlay = document.createElement("div");
  dropOverlay.id = "chat-drop-overlay";
  dropOverlay.className = "pointer-events-none absolute inset-3 z-30 hidden items-center justify-center rounded-lg border border-sky-400/60 bg-sky-950/45 text-sky-100 shadow-[0_0_36px_rgba(56,189,248,0.18)] backdrop-blur-sm";
  dropOverlay.innerHTML = '<div class="rounded border border-sky-300/30 bg-black/45 px-5 py-4 text-center font-mono"><div class="text-[11px] uppercase tracking-[0.22em] text-sky-300">drop files</div><div class="mt-2 text-sm text-sky-50">copy to JIN files + attach</div></div>';
  chatColumn.appendChild(dropOverlay);
  return dropOverlay;
}

function showDropOverlay() {
  const overlay = ensureDropOverlay();
  if (!overlay) return;
  overlay.classList.remove("hidden");
  overlay.classList.add("flex");
  chatColumn.classList.add("jin-drop-zone-active");
}

function hideDropOverlay() {
  const overlay = ensureDropOverlay();
  if (!overlay) return;
  overlay.classList.add("hidden");
  overlay.classList.remove("flex");
  chatColumn.classList.remove("jin-drop-zone-active");
}

async function prepareJinAttachments() {
  await uploadQueue;
  return pinnedIds
    .map(getFileRecord)
    .filter(Boolean)
    .slice(0, MAX_JIN_ATTACHMENTS)
    .map(attachmentViewRecord);
}

if (chatColumn && fileInput) {
  ensureDropOverlay();
  ["dragenter", "dragover", "dragleave", "drop"].forEach((eventName) => {
    document.addEventListener(eventName, (event) => {
      if (!hasDraggedFiles(event)) return;
      event.preventDefault();
      event.stopPropagation();
    });
  });
  document.addEventListener("dragenter", (event) => {
    if (!hasDraggedFiles(event)) return;
    dragDepth += 1;
    showDropOverlay();
  });
  document.addEventListener("dragover", (event) => {
    if (hasDraggedFiles(event)) showDropOverlay();
  });
  document.addEventListener("dragleave", (event) => {
    if (!hasDraggedFiles(event)) return;
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) hideDropOverlay();
  });
  document.addEventListener("drop", (event) => {
    if (!hasDraggedFiles(event)) return;
    dragDepth = 0;
    hideDropOverlay();
    addFiles(event.dataTransfer && event.dataTransfer.files);
  });
  document.addEventListener("paste", (event) => {
    const files = Array.from(event.clipboardData && event.clipboardData.files || []);
    if (files.length) addFiles(files);
  });
  fileInput.addEventListener("change", (event) => addFiles(event.target.files));
}

window.prepareJinAttachments = prepareJinAttachments;
window.clearJinAttachments = function () {
  Promise.all(pinnedIds.map((id) => setPinned(id, false)));
};
window.hasJinAttachments = () => pinnedIds.length > 0;
window.JinFiles = {
  refresh: refreshFiles,
  syncContext: syncAttachmentContext,
  getFiles: () => fileStore.map((item) => ({...item})),
  getPinnedIds: () => [...pinnedIds],
  getFile: (id) => {
    const record = getFileRecord(id);
    return record ? {...record} : null;
  },
  setPinned,
  deleteFile,
  restoreDeletedFile,
  resolveAttachment: resolvePersistentAttachment,
  applySnapshot(payload) {
    normalizeSnapshot(payload || {});
    dispatchStoreChanged();
  },
};

void refreshFiles();


window.addEventListener(MEMORY_ROW_AVATAR_HOVER_EVENT, (event) => {
  const hoverId = String(event && event.detail && event.detail.avatarMemoryHoverId || "").trim();
  const active = Boolean(event && event.detail && event.detail.active === true && hoverId);
  if (!attachedFiles) return;
  attachedFiles.querySelectorAll(".jin-attached-files-row[data-avatar-memory-hover-id]").forEach((row) => {
    row.classList.toggle("jin-attached-files-row-avatar-hover", active && String(row.dataset.avatarMemoryHoverId || "").trim() === hoverId);
  });
});
