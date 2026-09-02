// Shared by sent messages and the composer attachment strip.
const JIN_ATTACHMENT_CHIP_CLASS =
  "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded border border-sky-400/25 bg-sky-950/35 p-0 text-[18px] leading-none text-sky-100 transition hover:border-sky-300/50 hover:bg-sky-900/45";
const ATTACHMENT_IMAGE_PREVIEW_MAX_PX = 200;
const ASSET_TEXT_PREVIEW_ENDPOINT = "/api/assets/text-preview";
const ASSET_TEXT_PREVIEW_MAX_CHARS = 60000;

let attachmentHoverPreview = null;
let attachmentHoverPreviewImage = null;
let attachmentHoverPreviewOwner = null;
let attachmentModal = null;
let attachmentModalTitle = null;
let attachmentModalContent = null;
let attachmentModalPinButton = null;
let attachmentModalDeleteButton = null;
let activeAttachmentModalRecord = null;

function normalizeAttachmentValue(value) {
  return String(
    value === null || value === undefined
      ? ""
      : value
  );
}

function getAttachmentKind(attachment) {
  return normalizeAttachmentValue(
    attachment && attachment.kind
      ? attachment.kind
      : "file"
  ).toLowerCase();
}

function getAttachmentName(attachment) {
  return normalizeAttachmentValue(
    attachment && (
      attachment.name
      || attachment.filename
    )
      ? (
        attachment.name
        || attachment.filename
      )
      : "attachment"
  );
}

function getAttachmentSizeLabel(attachment) {
  const explicitLabel =
    normalizeAttachmentValue(
      attachment && attachment.size_label
    ).trim();

  if (explicitLabel) {
    return explicitLabel;
  }

  return formatAssetBytes(
    attachment && attachment.size_bytes
  );
}

function formatAttachmentHoverTitle(attachment) {
  const name =
    getAttachmentName(
      attachment
    ).trim();
  const sizeLabel =
    getAttachmentSizeLabel(
      attachment
    ).trim();

  return [
    name || "attachment",
    sizeLabel,
  ].filter(Boolean).join(" · ");
}

function getAttachmentImageSource(attachment) {
  return normalizeAttachmentValue(
    attachment && (
      attachment.data_url
      || attachment.object_url
      || attachment.url
    )
  );
}

function getAttachmentTextContent(attachment) {
  if (!attachment) {
    return "";
  }

  if (attachment.text_content !== undefined) {
    return normalizeAttachmentValue(
      attachment.text_content
    );
  }

  if (attachment.text !== undefined) {
    return normalizeAttachmentValue(
      attachment.text
    );
  }

  if (attachment.text_preview !== undefined) {
    return normalizeAttachmentValue(
      attachment.text_preview
    );
  }

  return "";
}

function getAttachmentDetailParts(attachment) {
  if (!attachment) {
    return [
      "file",
    ];
  }

  return [
    attachment.kind
      ? normalizeAttachmentValue(attachment.kind)
      : "file",
    attachment.type
      ? normalizeAttachmentValue(attachment.type)
      : "",
    getAttachmentSizeLabel(attachment),
    attachment.width && attachment.height
      ? `${attachment.width}x${attachment.height}`
      : "",
  ].filter(Boolean);
}

function formatAttachmentChipLabel(attachment) {
  const name =
    getAttachmentName(
      attachment
    );

  const details =
    getAttachmentDetailParts(
      attachment
    ).filter((part) => {
      return (
        !attachment
        || !attachment.type
        || part !== normalizeAttachmentValue(
          attachment.type
        )
      );
    });

  return details.length
    ? `${name} - ${details.join(", ")}`
    : name;
}

function getAttachmentChipEmoji(attachment) {
  if (getAttachmentName(attachment).toLowerCase().endsWith(".jin-folder")) return "📁";
  const kind =
    getAttachmentKind(
      attachment
    );

  if (kind === "image") {
    return "🖼️";
  }

  if (kind === "text") {
    return "📄";
  }

  return "📎";
}

function ensureAttachmentHoverPreview() {
  if (attachmentHoverPreview) {
    return attachmentHoverPreview;
  }

  attachmentHoverPreview =
    document.createElement("div");
  attachmentHoverPreview.className =
    "jin-attachment-hover-preview hidden";

  attachmentHoverPreviewImage =
    document.createElement("img");
  attachmentHoverPreviewImage.alt = "";
  attachmentHoverPreviewImage.draggable = false;

  attachmentHoverPreview.appendChild(
    attachmentHoverPreviewImage
  );

  document.body.appendChild(
    attachmentHoverPreview
  );

  return attachmentHoverPreview;
}

function normalizeAttachmentPreviewMaxPx(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0
    ? parsed
    : ATTACHMENT_IMAGE_PREVIEW_MAX_PX;
}

function positionAttachmentHoverPreview(
  event,
  maxPx = ATTACHMENT_IMAGE_PREVIEW_MAX_PX
) {
  const preview =
    ensureAttachmentHoverPreview();
  const previewMaxPx =
    normalizeAttachmentPreviewMaxPx(maxPx);

  preview.style.setProperty(
    "--jin-attachment-preview-max-px",
    `${previewMaxPx}px`
  );

  if (!event) {
    return;
  }

  const offset = 14;
  const rect =
    preview.getBoundingClientRect();
  const width =
    rect.width || previewMaxPx;
  const height =
    rect.height || previewMaxPx;
  const viewportWidth =
    window.innerWidth || document.documentElement.clientWidth || width;
  const viewportHeight =
    window.innerHeight || document.documentElement.clientHeight || height;

  let left = event.clientX + offset;
  let top = event.clientY + offset;

  if (left + width + offset > viewportWidth) {
    left = event.clientX - width - offset;
  }

  if (top + height + offset > viewportHeight) {
    top = event.clientY - height - offset;
  }

  preview.style.left =
    `${Math.max(offset, left)}px`;
  preview.style.top =
    `${Math.max(offset, top)}px`;
}

function showAttachmentHoverPreview(
  attachment,
  event,
  maxPx = ATTACHMENT_IMAGE_PREVIEW_MAX_PX
) {
  if (
      getAttachmentKind(attachment) !== "image"
  ) {
    return;
  }

  const source =
    getAttachmentImageSource(
      attachment
    );

  if (!source) {
    return;
  }

  const preview =
    ensureAttachmentHoverPreview();

  attachmentHoverPreviewOwner = event && event.currentTarget
    ? event.currentTarget
    : null;
  attachmentHoverPreviewImage.src =
    source;

  positionAttachmentHoverPreview(
    event,
    maxPx
  );

  preview.classList.remove(
    "hidden"
  );
}

function hideAttachmentHoverPreview() {
  if (!attachmentHoverPreview) {
    return;
  }

  attachmentHoverPreview.classList.add(
    "hidden"
  );
  attachmentHoverPreviewOwner = null;

  if (attachmentHoverPreviewImage) {
    attachmentHoverPreviewImage.removeAttribute(
      "src"
    );
  }
}

function closeJinAttachmentModal() {
  if (!attachmentModal) {
    return;
  }

  attachmentModal.classList.add(
    "hidden"
  );
  attachmentModal.classList.remove(
    "flex"
  );
}

function ensureJinAttachmentModal() {
  if (attachmentModal) {
    return attachmentModal;
  }

  attachmentModal =
    document.createElement("div");
  attachmentModal.id =
    "jin-attachment-modal";
  attachmentModal.className =
    "fixed inset-0 z-50 hidden items-center justify-center bg-black/70 px-4 py-6 backdrop-blur-sm";

  const panel =
    document.createElement("div");
  panel.className =
    "delayed-memory-modal-panel w-full max-w-4xl max-h-[86vh] rounded border border-zinc-700 bg-zinc-950 shadow-2xl flex flex-col";

  const header =
    document.createElement("div");
  header.className =
    "flex items-center justify-between gap-3 border-b border-zinc-800 px-4 py-3";

  attachmentModalTitle =
    document.createElement("div");
  attachmentModalTitle.className =
    "min-w-0 truncate text-[12px] font-semibold uppercase tracking-[0.16em] text-zinc-100";

  const headerActions =
    document.createElement("div");
  headerActions.className =
    "flex shrink-0 items-center gap-2";

  attachmentModalPinButton =
    document.createElement("button");
  attachmentModalPinButton.type = "button";
  attachmentModalPinButton.className =
    "delayed-memory-modal-icon-button delayed-memory-modal-pin";
  attachmentModalPinButton.innerHTML =
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.7 3.3 20.7 9.3 18.6 11.4 16.9 9.7 13.7 12.9 14.4 15.7 12.9 17.2 9.4 13.7 5.3 17.8 4.2 16.7 8.3 12.6 4.8 9.1 6.3 7.6 9.1 8.3 12.3 5.1 10.6 3.4 12.7 1.3Z"/></svg>';

  attachmentModalDeleteButton =
    document.createElement("button");
  attachmentModalDeleteButton.type = "button";
  attachmentModalDeleteButton.className =
    "delayed-memory-modal-icon-button delayed-memory-modal-delete";
  attachmentModalDeleteButton.setAttribute("aria-label", "Hold to delete file");
  attachmentModalDeleteButton.title = "Hold to delete file";
  attachmentModalDeleteButton.innerHTML =
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 3h6l1 2h4v2H4V5h4l1-2Zm1 6h2v9h-2V9Zm4 0h2v9h-2V9ZM7 9h2l.7 10h4.6L15 9h2l-.8 11.1A2 2 0 0 1 14.2 22H9.8a2 2 0 0 1-2-1.9L7 9Z"/></svg>';

  const closeButton =
    document.createElement("button");
  closeButton.type =
    "button";
  closeButton.className =
    "delayed-memory-modal-icon-button delayed-memory-modal-close shrink-0";
  closeButton.setAttribute(
    "aria-label",
    "Close"
  );
  closeButton.textContent =
    "\u00d7";

  closeButton.addEventListener(
    "click",
    closeJinAttachmentModal
  );

  attachmentModalPinButton.addEventListener("click", async () => {
    const record = activeAttachmentModalRecord;
    if (!record || !record.id || !window.JinFiles) return;
    await window.JinFiles.setPinned(record.id, !Boolean(record.pinned));
    const refreshed = window.JinFiles.getFile(record.id);
    if (refreshed) {
      activeAttachmentModalRecord = refreshed;
      attachmentModalPinButton.classList.toggle(
        "delayed-memory-modal-pin-active",
        Boolean(refreshed.pinned)
      );
      attachmentModalPinButton.setAttribute(
        "aria-pressed",
        refreshed.pinned ? "true" : "false"
      );
      attachmentModalPinButton.title = refreshed.pinned
        ? "Remove file from JIN context"
        : "Attach file to JIN context";
    }
  });

  const deleteActiveAttachment = async () => {
    const record = activeAttachmentModalRecord;
    if (!record || !record.id || !window.JinFiles) return false;
    const deleted = await window.JinFiles.deleteFile(record.id);
    if (deleted) closeJinAttachmentModal();
    return deleted;
  };

  attachmentModalDeleteButton.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
  });

  if (
    window.JinRuntime
    && window.JinRuntime.memoryView
    && typeof window.JinRuntime.memoryView.configureDeleteHold === "function"
  ) {
    window.JinRuntime.memoryView.configureDeleteHold(
      attachmentModalDeleteButton,
      deleteActiveAttachment,
      {
        keepHiddenOnComplete: true,
      }
    );
  }

  headerActions.append(
    attachmentModalPinButton,
    attachmentModalDeleteButton,
    closeButton
  );

  attachmentModalContent =
    document.createElement("div");
  attachmentModalContent.className =
    "delayed-memory-modal-content min-h-0 flex-1 overflow-auto p-4 text-[12px] leading-relaxed text-zinc-200";

  header.appendChild(
    attachmentModalTitle
  );
  header.appendChild(
    headerActions
  );
  panel.appendChild(
    header
  );
  panel.appendChild(
    attachmentModalContent
  );
  attachmentModal.appendChild(
    panel
  );
  document.body.appendChild(
    attachmentModal
  );

  let attachmentModalBackdropPointerDown = false;

  attachmentModal.addEventListener(
    "pointerdown",
    (event) => {
      attachmentModalBackdropPointerDown =
        event.target === attachmentModal;
    }
  );

  attachmentModal.addEventListener(
    "click",
    (event) => {
      const shouldClose =
        event.target === attachmentModal
        && attachmentModalBackdropPointerDown;

      attachmentModalBackdropPointerDown = false;

      if (shouldClose) {
        closeJinAttachmentModal();
      }
    }
  );

  document.addEventListener(
    "keydown",
    (event) => {
      if (
          event.key === "Escape"
          && attachmentModal
          && !attachmentModal.classList.contains("hidden")
      ) {
        closeJinAttachmentModal();
      }
    }
  );

  return attachmentModal;
}

function createAttachmentInfoElement(attachment) {
  const info =
    document.createElement("div");

  info.className =
    "jin-attachment-modal-info";

  const detailParts =
    getAttachmentDetailParts(
      attachment
    );
  const systemId =
    normalizeAttachmentValue(
      attachment && attachment.id
    ).trim();

  if (systemId && detailParts.length) {
    detailParts[0] = systemId;
  } else if (systemId) {
    detailParts.push(systemId);
  }

  info.textContent =
    detailParts.join(" - ");

  return info;
}

function renderAttachmentImageModal(attachment) {
  const source =
    getAttachmentImageSource(
      attachment
    );

  if (!source) {
    return false;
  }

  const wrapper =
    document.createElement("div");
  wrapper.className =
    "jin-attachment-modal-image-wrap";

  const image =
    document.createElement("img");
  image.className =
    "jin-attachment-modal-image";
  image.alt =
    getAttachmentName(
      attachment
    );
  image.src =
    source;
  image.draggable =
    false;

  wrapper.appendChild(
    image
  );
  wrapper.appendChild(
    createAttachmentInfoElement(
      attachment
    )
  );

  attachmentModalContent.appendChild(
    wrapper
  );

  return true;
}

function renderAttachmentTextModal(attachment) {
  const info =
    createAttachmentInfoElement(
      attachment
    );
  const text =
    document.createElement("pre");

  text.className =
    "jin-attachment-modal-text";
  text.textContent =
    getAttachmentTextContent(
      attachment
    );

  attachmentModalContent.appendChild(
    info
  );
  attachmentModalContent.appendChild(
    text
  );
}

function renderAttachmentFallbackModal(attachment) {
  const info =
    createAttachmentInfoElement(
      attachment
    );

  attachmentModalContent.appendChild(
    info
  );
}

async function resolveAttachmentForModal(attachment) {
  if (
      attachment
      && typeof attachment.resolve_modal_attachment === "function"
  ) {
    return attachment.resolve_modal_attachment();
  }

  if (
      attachment
      && attachment.id
      && window.JinFiles
      && typeof window.JinFiles.resolveAttachment === "function"
  ) {
    return window.JinFiles.resolveAttachment(attachment);
  }

  return attachment;
}

async function openJinAttachmentModal(attachment) {
  const resolvedAttachment =
    await resolveAttachmentForModal(
      attachment
    );

  ensureJinAttachmentModal();

  activeAttachmentModalRecord =
    resolvedAttachment && resolvedAttachment.id && window.JinFiles
      ? (window.JinFiles.getFile(resolvedAttachment.id) || resolvedAttachment)
      : resolvedAttachment;

  const isPersistentFile = Boolean(
    activeAttachmentModalRecord && activeAttachmentModalRecord.id && window.JinFiles
  );
  attachmentModalPinButton.classList.toggle("hidden", !isPersistentFile);
  attachmentModalDeleteButton.classList.toggle("hidden", !isPersistentFile);
  attachmentModalDeleteButton.style.opacity = "";
  if (isPersistentFile) {
    attachmentModalPinButton.classList.toggle(
      "delayed-memory-modal-pin-active",
      Boolean(activeAttachmentModalRecord.pinned)
    );
    attachmentModalPinButton.setAttribute(
      "aria-pressed",
      activeAttachmentModalRecord.pinned ? "true" : "false"
    );
    attachmentModalPinButton.title = activeAttachmentModalRecord.pinned
      ? "Remove file from JIN context"
      : "Attach file to JIN context";
  }

  attachmentModalTitle.textContent =
    getAttachmentName(
      resolvedAttachment
    );
  attachmentModalContent.replaceChildren();

  const kind =
    getAttachmentKind(
      resolvedAttachment
    );

  if (kind === "image") {
    if (!renderAttachmentImageModal(resolvedAttachment)) {
      renderAttachmentFallbackModal(resolvedAttachment);
    }
  } else if (kind === "text") {
    renderAttachmentTextModal(
      resolvedAttachment
    );
  } else {
    renderAttachmentFallbackModal(
      resolvedAttachment
    );
  }

  attachmentModal.classList.remove(
    "hidden"
  );
  attachmentModal.classList.add(
    "flex"
  );
}

function bindJinAttachmentHoverPreview(
  element,
  attachment,
  options = {}
) {
  if (!element || !attachment) {
    return;
  }

  const hoverPreviewMaxPx =
    normalizeAttachmentPreviewMaxPx(
      options && options.hoverPreviewMaxPx
    );

  element.addEventListener(
    "mouseenter",
    (event) => {
      showAttachmentHoverPreview(
        attachment,
        event,
        hoverPreviewMaxPx
      );
    }
  );

  element.addEventListener(
    "mousemove",
    (event) => {
      if (
          attachmentHoverPreview
          && !attachmentHoverPreview.classList.contains("hidden")
      ) {
        positionAttachmentHoverPreview(
          event,
          hoverPreviewMaxPx
        );
      }
    }
  );

  element.addEventListener(
    "mouseleave",
    hideAttachmentHoverPreview
  );

  // Preview lifecycle invariant: attachment controls can hide or detach
  // themselves on interaction. mouseleave is not guaranteed in that case,
  // so cleanup must happen before any attachment UI mutation as well.
  const hideBeforeAttachmentMutation = () => {
    if (
        !attachmentHoverPreviewOwner
        || attachmentHoverPreviewOwner === element
        || !attachmentHoverPreviewOwner.isConnected
    ) {
      hideAttachmentHoverPreview();
    }
  };

  element.addEventListener(
    "pointerdown",
    hideBeforeAttachmentMutation
  );
  element.addEventListener(
    "keydown",
    (event) => {
      if (event.key === "Enter" || event.key === " ") {
        hideBeforeAttachmentMutation();
      }
    }
  );
}

function normalizeRuntimeActionAttachmentForModal(
  attachmentResult,
  attachmentId = ""
) {
  const result =
    attachmentResult
    && typeof attachmentResult === "object"
    && !Array.isArray(attachmentResult)
      ? attachmentResult
      : {};
  const id =
    normalizeAttachmentValue(
      result.id || attachmentId
    ).trim().toLowerCase();

  if (!id) {
    return null;
  }

  const storedRecord =
    window.JinFiles
    && typeof window.JinFiles.getFile === "function"
      ? window.JinFiles.getFile(id)
      : null;

  return {
    ...result,
    ...(storedRecord || {}),
    id,
    name:
      normalizeAttachmentValue(
        (storedRecord && storedRecord.name)
        || result.name
        || "attachment"
      ),
  };
}

function bindRuntimeActionAttachmentPreview(
  element,
  attachmentResult,
  attachmentId = ""
) {
  if (!element) {
    return;
  }

  const attachment =
    normalizeRuntimeActionAttachmentForModal(
      attachmentResult,
      attachmentId
    );

  element._jinRuntimeActionAttachment =
    attachment;

  if (!attachment) {
    element.removeAttribute("role");
    element.removeAttribute("tabindex");
    element.classList.remove(
      "cursor-pointer"
    );
    return;
  }

  element.setAttribute(
    "role",
    "button"
  );
  element.tabIndex = 0;
  element.classList.remove(
    "cursor-help"
  );
  element.classList.add(
    "cursor-pointer"
  );
  element.title =
    formatAttachmentHoverTitle(
      attachment
    )
    || element.title
    || "Open attachment preview";

  if (element._jinRuntimeActionAttachmentBound) {
    return;
  }

  element._jinRuntimeActionAttachmentBound =
    true;

  // Reuse the existing compact inline attachment hover preview, including
  // its mouseleave / pointerdown cleanup so the image cannot stay orphaned.
  bindJinAttachmentHoverPreview(
    element,
    attachment,
    {
      hoverPreviewMaxPx: 100,
    }
  );

  const openAttachment = () => {
    const currentAttachment =
      element._jinRuntimeActionAttachment;

    if (!currentAttachment) {
      return;
    }

    void openJinAttachmentModal(
      currentAttachment
    );
  };

  element.addEventListener(
    "click",
    (event) => {
      event.preventDefault();
      openAttachment();
    }
  );

  element.addEventListener(
    "keydown",
    (event) => {
      if (
          event.key !== "Enter"
          && event.key !== " "
      ) {
        return;
      }

      event.preventDefault();
      openAttachment();
    }
  );
}

function bindJinAttachmentBubble(
  element,
  attachment,
  options = {}
) {
  if (!element || !attachment) {
    return;
  }

  element.classList.add(
    "jin-attachment-bubble"
  );
  element.title =
    formatAttachmentHoverTitle(
      attachment
    );

  if (!element.hasAttribute("tabindex")) {
    element.tabIndex = 0;
  }

  if (!element.hasAttribute("role")) {
    element.setAttribute(
      "role",
      "button"
    );
  }

  bindJinAttachmentHoverPreview(
    element,
    attachment,
    options
  );

  element.addEventListener(
    "click",
    (event) => {
      event.preventDefault();
      openJinAttachmentModal(
        attachment
      );
    }
  );

  element.addEventListener(
    "keydown",
    (event) => {
      if (
          event.key === "Enter"
          || event.key === " "
      ) {
        event.preventDefault();
        openJinAttachmentModal(
          attachment
        );
      }
    }
  );
}

function getAssetResultPath(assetResult) {
  return normalizeAttachmentValue(
    assetResult
    && assetResult.path
  ).trim();
}

function isPreviewableTextAssetResult(assetResult) {
  const path =
    getAssetResultPath(
      assetResult
    );

  const isExistingFileResult =
    assetResult
    && assetResult.ok === false
    && assetResult.error === "file_exists";

  if (
      !assetResult
      || (
        assetResult.ok === false
        && !isExistingFileResult
      )
      || !path
      || !path.startsWith("assets/")
  ) {
    return false;
  }

  return true;
}

function formatAssetBytes(bytes) {
  const value =
    Number(bytes || 0);

  if (!Number.isFinite(value) || value <= 0) {
    return "";
  }

  const units = [
    "B",
    "KB",
    "MB",
    "GB",
  ];
  let size = value;
  let unitIndex = 0;

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }

  return `${size.toFixed(unitIndex ? 1 : 0)} ${units[unitIndex]}`;
}

async function fetchAssetTextPreview(path) {
  const url =
    new URL(
      ASSET_TEXT_PREVIEW_ENDPOINT,
      window.location.origin
    );

  url.searchParams.set(
    "path",
    path
  );
  url.searchParams.set(
    "max_chars",
    String(ASSET_TEXT_PREVIEW_MAX_CHARS)
  );

  const response =
    await fetch(
      url,
      {
        cache: "no-store",
      }
    );

  if (!response.ok) {
    throw new Error(
      `Asset preview failed: ${response.status}`
    );
  }

  const result =
    await response.json();
  const text =
    normalizeAttachmentValue(
      result.text_content
    );
  const truncatedNote =
    result.truncated
      ? `\n\n[preview truncated at ${result.preview_limit || ASSET_TEXT_PREVIEW_MAX_CHARS} chars]`
      : "";

  return {
    name:
      result.name || result.path || path,
    type:
      result.type || "text/plain",
    kind: "text",
    size_bytes:
      result.size_bytes || 0,
    size_label:
      formatAssetBytes(
        result.size_bytes
      ),
    text_content:
      text + truncatedNote,
  };
}

function createAssetTextAttachment(assetResult) {
  if (assetResult && assetResult.ok === true
      && ["project_tree", "project_search", "project_read"].includes(assetResult.action)) {
    return {
      name: `${assetResult.action} · ${assetResult.attachment || ""} · ${assetResult.path || "."}`,
      type: "text/plain",
      kind: "text",
      text_content: [
        assetResult.query ? `Query: ${assetResult.query}` : "",
        assetResult.range || assetResult.page || "",
        assetResult.notice || "",
        "",
        assetResult.content || "",
      ].join("\n"),
    };
  }
  if (!isPreviewableTextAssetResult(assetResult)) {
    return null;
  }

  const path =
    getAssetResultPath(
      assetResult
    );

  const attachment = {
    name: path,
    type: "text/plain",
    kind: "text",
    size_bytes:
      assetResult.size_bytes || 0,
    size_label:
      assetResult.size_label || (
        assetResult.size_bytes
          ? formatAssetBytes(
            assetResult.size_bytes
          )
          : ""
      ),
    line_count:
      assetResult.line_count || 0,
    text_preview:
      Array.isArray(assetResult.examples)
        ? assetResult.examples.join("\n")
        : "",
  };

  attachment.resolve_modal_attachment =
    async () => {
      try {
        return {
          ...attachment,
          ...await fetchAssetTextPreview(
            path
          ),
        };
      } catch (error) {
        return {
          ...attachment,
          text_content:
            `Unable to load asset preview for ${path}.\n\n${error && error.message ? error.message : error}`,
        };
      }
    };

  return attachment;
}

function bindAssetResultPreview(element, assetResult) {
  const attachment =
    createAssetTextAttachment(
      assetResult
    );

  if (!attachment) {
    return;
  }

  element.title =
    formatAttachmentHoverTitle(
      attachment
    );

  bindJinAttachmentBubble(
    element,
    attachment
  );
}

function normalizeDelayedMemoryReportForModal(
  delayedMemoryReport,
  delayedMemoryReportId = ""
) {

  if (
    !delayedMemoryReport
    || typeof delayedMemoryReport !== "object"
    || Array.isArray(delayedMemoryReport)
  ) {
    return null;
  }

  const requestedId =
    String(
      delayedMemoryReportId || ""
    ).trim()
    .toLowerCase();

  if (
    requestedId
    && delayedMemoryReport[requestedId]
    && typeof delayedMemoryReport[requestedId] === "object"
  ) {
    return {
      _storage_key: requestedId,
      ...delayedMemoryReport[requestedId],
    };
  }

  if (
    delayedMemoryReport.title
    || delayedMemoryReport.summary
    || delayedMemoryReport.body
  ) {
    return {
      _storage_key:
        requestedId
        || String(delayedMemoryReport.id || "").trim(),
      ...delayedMemoryReport,
    };
  }

  const reportEntry =
    Object.entries(
      delayedMemoryReport
    ).find(([, report]) => {
      return (
        report
        && typeof report === "object"
        && !Array.isArray(report)
      );
    });

  if (!reportEntry) {
    return null;
  }

  return {
    _storage_key: reportEntry[0],
    ...reportEntry[1],
  };

}

function getDelayedMemoryReportPreviewSource(
  delayedMemoryReport,
  delayedMemoryReportId = ""
) {

  if (
    delayedMemoryReport
    && typeof delayedMemoryReport === "object"
    && !Array.isArray(delayedMemoryReport)
  ) {
    return delayedMemoryReport;
  }

  const requestedId =
    String(
      delayedMemoryReportId || ""
    ).trim()
    .toLowerCase();

  if (
    !requestedId
    || !window.JinRuntime
    || !window.JinRuntime.runtime
    || !window.JinRuntime.runtime.getDelayedMemoryReports
  ) {
    return null;
  }

  const reports =
    window.JinRuntime.runtime.getDelayedMemoryReports();
  const report =
    reports
    && typeof reports === "object"
    && !Array.isArray(reports)
      ? reports[requestedId]
      : null;

  if (
    !report
    || typeof report !== "object"
    || Array.isArray(report)
  ) {
    return null;
  }

  return {
    [requestedId]: report,
  };

}

function applyDelayedMemoryReportPreviewState(
  element,
  report
) {

  if (!element) {
    return;
  }

  const normalizedId =
    report
    && typeof report === "object"
    && !Array.isArray(report)
      ? String(
          report._storage_key
          || report.id
          || ""
        ).trim().toLowerCase()
      : "";
  const pinned =
    Boolean(
      report
      && typeof report === "object"
      && !Array.isArray(report)
      && report.pinned
    );

  if (normalizedId) {
    element.dataset.delayedMemoryReportId =
      normalizedId;
  } else {
    delete element.dataset.delayedMemoryReportId;
  }

  element.classList.toggle(
    "jin-runtime-action-delayed-memory-pinned",
    pinned
  );
}

function syncDelayedMemoryReportPreviewState(
  reportId,
  pinned
) {

  const normalizedId =
    String(reportId || "").trim().toLowerCase();

  if (!normalizedId) {
    return;
  }

  document.querySelectorAll(
    `[data-delayed-memory-report-id="${normalizedId}"]`
  ).forEach((element) => {
    if (!element || !element.classList) {
      return;
    }

    element.classList.toggle(
      "jin-runtime-action-delayed-memory-pinned",
      Boolean(pinned)
    );

    if (element._jinDelayedMemoryReport
      && typeof element._jinDelayedMemoryReport === "object"
      && !Array.isArray(element._jinDelayedMemoryReport)) {
      element._jinDelayedMemoryReport = {
        ...element._jinDelayedMemoryReport,
        pinned: Boolean(pinned),
      };
    }
  });
}

function bindDelayedMemoryReportPreview(
  element,
  delayedMemoryReport,
  delayedMemoryReportId = ""
) {

  if (!element) {
    return;
  }

  const report =
    normalizeDelayedMemoryReportForModal(
      getDelayedMemoryReportPreviewSource(
        delayedMemoryReport,
        delayedMemoryReportId
      ),
      delayedMemoryReportId
    );

  element._jinDelayedMemoryReport =
    report;
  applyDelayedMemoryReportPreviewState(
    element,
    report
  );

  if (!report) {
    element.removeAttribute(
      "role"
    );
    element.removeAttribute(
      "tabindex"
    );
    element.classList.remove(
      "cursor-pointer"
    );
    return;
  }

  element.setAttribute(
    "role",
    "button"
  );
  element.tabIndex = 0;
  element.classList.remove(
    "cursor-help"
  );
  element.classList.add(
    "cursor-pointer"
  );

  element.title =
    String(
      report.title
      || report.name
      || ""
    ).trim()
    || element.title
    || "Open delayed memory report";

  if (element._jinDelayedMemoryReportBound) {
    return;
  }

  element._jinDelayedMemoryReportBound =
    true;

  const openReport = () => {
    const currentReport =
      element._jinDelayedMemoryReport;

    if (
      !currentReport
      || !window.JinRuntime
      || !window.JinRuntime.memoryView
      || !window.JinRuntime.memoryView.openDelayedMemoryReportModal
    ) {
      return;
    }

    window.JinRuntime.memoryView.openDelayedMemoryReportModal(
      currentReport
    );
  };

  element.addEventListener(
    "click",
    (event) => {
      event.preventDefault();
      openReport();
    }
  );

  element.addEventListener(
    "keydown",
    (event) => {
      if (
        event.key !== "Enter"
        && event.key !== " "
      ) {
        return;
      }

      event.preventDefault();
      openReport();
    }
  );

}

window.bindJinAttachmentBubble =
  bindJinAttachmentBubble;
window.bindRuntimeActionAttachmentPreview =
  bindRuntimeActionAttachmentPreview;
window.hideJinAttachmentHoverPreview =
  hideAttachmentHoverPreview;
window.bindJinAttachmentHoverPreview =
  bindJinAttachmentHoverPreview;
window.openJinAttachmentModal =
  openJinAttachmentModal;
window.formatJinAttachmentChipLabel =
  formatAttachmentChipLabel;
window.syncDelayedMemoryReportPreviewState =
  syncDelayedMemoryReportPreviewState;
window.dispatchEvent(
  new CustomEvent("jin:attachment-ui-ready")
);
