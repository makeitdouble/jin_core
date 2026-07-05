// dragdrop.js

const chatColumn = document.querySelector("#chat-drop-zone");
const fileInput = document.querySelector("#file-input");
const attachedFiles = document.querySelector("#attached-files");

const TEXT_PREVIEW_LIMIT = 2000;
const TEXT_EXTENSIONS = new Set([
  "txt",
  "md",
  "markdown",
  "py",
  "js",
  "jsx",
  "ts",
  "tsx",
  "json",
  "csv",
  "css",
  "html",
  "xml",
  "yaml",
  "yml",
  "toml",
  "log",
]);

let droppedFiles = [];
let dragDepth = 0;
let dropOverlay = null;

function escapeHtml(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function formatBytes(bytes) {
  const size = Number(bytes || 0);

  if (size < 1024) {
    return `${size} B`;
  }

  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }

  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function getFileExtension(file) {
  const name = String(
    file && file.name
      ? file.name
      : ""
  );

  const index = name.lastIndexOf(".");

  if (index === -1) {
    return "";
  }

  return name.slice(index + 1).toLowerCase();
}

function isTextLikeFile(file) {
  const type = String(file.type || "").toLowerCase();

  return (
    type.startsWith("text/")
    || type.includes("json")
    || type.includes("javascript")
    || type.includes("xml")
    || TEXT_EXTENSIONS.has(getFileExtension(file))
  );
}

function hasDraggedFiles(event) {
  const types = Array.from(
    event
    && event.dataTransfer
    && event.dataTransfer.types
      ? event.dataTransfer.types
      : []
  );

  return types.includes("Files");
}

function ensureDropOverlay() {
  if (
      dropOverlay
      || !chatColumn
  ) {
    return dropOverlay;
  }

  dropOverlay = document.createElement("div");
  dropOverlay.id = "chat-drop-overlay";
  dropOverlay.className =
    "pointer-events-none absolute inset-3 z-30 hidden items-center justify-center rounded-lg border border-sky-400/60 bg-sky-950/45 text-sky-100 shadow-[0_0_36px_rgba(56,189,248,0.18)] backdrop-blur-sm";
  dropOverlay.innerHTML = `
    <div class="rounded border border-sky-300/30 bg-black/45 px-5 py-4 text-center font-mono">
      <div class="text-[11px] uppercase tracking-[0.22em] text-sky-300">
        drop files
      </div>
      <div class="mt-2 text-sm text-sky-50">
        attach to next user turn
      </div>
      <div class="mt-1 text-[11px] text-sky-100/60">
        images, text, code, json, csv
      </div>
    </div>
  `;

  chatColumn.appendChild(dropOverlay);

  return dropOverlay;
}

function showDropOverlay() {
  const overlay = ensureDropOverlay();

  if (!overlay) {
    return;
  }

  overlay.classList.remove("hidden");
  overlay.classList.add("flex");
  chatColumn.classList.add("jin-drop-zone-active");
}

function hideDropOverlay() {
  const overlay = ensureDropOverlay();

  if (!overlay) {
    return;
  }

  overlay.classList.add("hidden");
  overlay.classList.remove("flex");
  chatColumn.classList.remove("jin-drop-zone-active");
}

function renderFiles() {
  if (!attachedFiles) {
    return;
  }

  attachedFiles.innerHTML = "";

  droppedFiles.forEach((file, index) => {
    const item = document.createElement("div");

    item.className =
      "flex max-w-full items-center gap-2 rounded border border-sky-500/25 bg-sky-950/35 px-3 py-2 text-xs text-sky-50 shadow";

    item.innerHTML = `
      <span class="truncate max-w-[220px]">
        ${escapeHtml(file.name)}
      </span>
      <span class="shrink-0 text-sky-100/50">
        ${escapeHtml(formatBytes(file.size))}
      </span>
      <button
        class="shrink-0 text-sky-200/70 hover:text-red-300 transition"
        data-index="${index}"
        title="Remove attachment"
        type="button"
      >
        x
      </button>
    `;

    attachedFiles.appendChild(item);
  });

  attachedFiles.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const index = Number(btn.dataset.index);

      droppedFiles.splice(index, 1);

      syncFileInput();
      renderFiles();
    });
  });
}

function syncFileInput() {
  if (!fileInput) {
    return;
  }

  const dt = new DataTransfer();

  droppedFiles.forEach((file) => {
    dt.items.add(file);
  });

  fileInput.files = dt.files;
}

function addFiles(fileList) {
  for (const file of Array.from(fileList || [])) {
    droppedFiles.push(file);
  }

  syncFileInput();
  renderFiles();
}

function clearFiles() {
  droppedFiles = [];

  syncFileInput();
  renderFiles();
}

function readImageDimensions(file) {
  return new Promise((resolve) => {
    const image = new Image();
    const url = URL.createObjectURL(file);

    image.onload = () => {
      URL.revokeObjectURL(url);
      resolve({
        width: image.naturalWidth || null,
        height: image.naturalHeight || null,
      });
    };

    image.onerror = () => {
      URL.revokeObjectURL(url);
      resolve({
        width: null,
        height: null,
      });
    };

    image.src = url;
  });
}

function readFileAsDataUrl(file) {
  return new Promise((resolve) => {
    const reader = new FileReader();

    reader.onload = () => {
      resolve(
        typeof reader.result === "string"
          ? reader.result
          : ""
      );
    };

    reader.onerror = () => {
      resolve("");
    };

    reader.readAsDataURL(file);
  });
}

async function buildAttachmentPayload(file, index) {
  const type = file.type || "application/octet-stream";
  const attachment = {
    id: `attachment-${Date.now()}-${index}`,
    name: file.name || `attachment-${index + 1}`,
    type,
    size_bytes: file.size || 0,
    size_label: formatBytes(file.size),
    last_modified: file.lastModified
      ? new Date(file.lastModified).toISOString()
      : null,
    kind: type.startsWith("image/")
      ? "image"
      : isTextLikeFile(file)
        ? "text"
        : "binary",
  };

  if (attachment.kind === "image") {
    const dimensions = await readImageDimensions(file);
    const dataUrl = await readFileAsDataUrl(file);

    attachment.width = dimensions.width;
    attachment.height = dimensions.height;

    if (dataUrl) {
      attachment.data_url = dataUrl;
      attachment.data_url_bytes = dataUrl.length;
    }
  }

  if (attachment.kind === "text") {
    const previewBlob = file.slice(0, TEXT_PREVIEW_LIMIT * 4);
    const rawPreview = await previewBlob.text();
    const preview = rawPreview.slice(0, TEXT_PREVIEW_LIMIT);

    attachment.preview_chars = preview.length;
    attachment.preview_limit = TEXT_PREVIEW_LIMIT;
    attachment.truncated =
      rawPreview.length > TEXT_PREVIEW_LIMIT
      || file.size > previewBlob.size;
    attachment.text_preview = preview;
  }

  return attachment;
}

async function prepareJinAttachments() {
  if (!droppedFiles.length) {
    return [];
  }

  return Promise.all(
    droppedFiles.map((file, index) => {
      return buildAttachmentPayload(file, index);
    })
  );
}

if (
    chatColumn
    && fileInput
    && attachedFiles
) {
  ensureDropOverlay();

  ["dragenter", "dragover", "dragleave", "drop"].forEach((eventName) => {
    document.addEventListener(eventName, (event) => {
      if (!hasDraggedFiles(event)) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();
    });
  });

  document.addEventListener("dragenter", (event) => {
    if (!hasDraggedFiles(event)) {
      return;
    }

    dragDepth += 1;
    showDropOverlay();
  });

  document.addEventListener("dragover", (event) => {
    if (!hasDraggedFiles(event)) {
      return;
    }

    showDropOverlay();
  });

  document.addEventListener("dragleave", (event) => {
    if (!hasDraggedFiles(event)) {
      return;
    }

    dragDepth = Math.max(0, dragDepth - 1);

    if (dragDepth === 0) {
      hideDropOverlay();
    }
  });

  document.addEventListener("drop", (event) => {
    if (!hasDraggedFiles(event)) {
      return;
    }

    dragDepth = 0;
    hideDropOverlay();

    const files =
      event.dataTransfer
      && event.dataTransfer.files;

    if (!files || !files.length) {
      return;
    }

    addFiles(files);
  });

  document.addEventListener("paste", (event) => {
    const files = Array.from(
      event.clipboardData
      && event.clipboardData.files
        ? event.clipboardData.files
        : []
    );

    if (!files.length) {
      return;
    }

    addFiles(files);
  });

  fileInput.addEventListener("change", (event) => {
    addFiles(event.target.files);
  });
}

window.prepareJinAttachments =
  prepareJinAttachments;

window.clearJinAttachments =
  clearFiles;

window.hasJinAttachments =
  function () {
    return droppedFiles.length > 0;
  };
