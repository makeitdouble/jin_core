const ATTACHMENT_IMAGE_PREVIEW_MAX_PX = 200;
const ASSET_TEXT_PREVIEW_ENDPOINT = "/api/assets/text-preview";
const ASSET_TEXT_PREVIEW_MAX_CHARS = 60000;

let attachmentHoverPreview = null;
let attachmentHoverPreviewImage = null;
let attachmentModal = null;
let attachmentModalTitle = null;
let attachmentModalContent = null;

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
    attachment && attachment.name
      ? attachment.name
      : "attachment"
  );
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
    attachment.size_label
      ? normalizeAttachmentValue(attachment.size_label)
      : "",
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

function positionAttachmentHoverPreview(event) {
  const preview =
    ensureAttachmentHoverPreview();

  if (!event) {
    return;
  }

  const offset = 14;
  const rect =
    preview.getBoundingClientRect();
  const width =
    rect.width || ATTACHMENT_IMAGE_PREVIEW_MAX_PX;
  const height =
    rect.height || ATTACHMENT_IMAGE_PREVIEW_MAX_PX;
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

function showAttachmentHoverPreview(attachment, event) {
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

  attachmentHoverPreviewImage.src =
    source;

  positionAttachmentHoverPreview(
    event
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

  const closeButton =
    document.createElement("button");
  closeButton.type =
    "button";
  closeButton.className =
    "shrink-0 rounded border border-zinc-700 px-2 py-1 text-[11px] text-zinc-300 transition hover:border-red-300/50 hover:text-red-200";
  closeButton.textContent =
    "x";

  closeButton.addEventListener(
    "click",
    closeJinAttachmentModal
  );

  attachmentModalContent =
    document.createElement("div");
  attachmentModalContent.className =
    "delayed-memory-modal-content min-h-0 flex-1 overflow-auto p-4 text-[12px] leading-relaxed text-zinc-200";

  header.appendChild(
    attachmentModalTitle
  );
  header.appendChild(
    closeButton
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

  attachmentModal.addEventListener(
    "click",
    (event) => {
      if (event.target === attachmentModal) {
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
  info.textContent =
    getAttachmentDetailParts(
      attachment
    ).join(" - ");

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

  return attachment;
}

async function openJinAttachmentModal(attachment) {
  const resolvedAttachment =
    await resolveAttachmentForModal(
      attachment
    );

  ensureJinAttachmentModal();

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

function bindJinAttachmentBubble(element, attachment) {
  if (!element || !attachment) {
    return;
  }

  element.classList.add(
    "jin-attachment-bubble"
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

  element.addEventListener(
    "mouseenter",
    (event) => {
      showAttachmentHoverPreview(
        attachment,
        event
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
          event
        );
      }
    }
  );

  element.addEventListener(
    "mouseleave",
    hideAttachmentHoverPreview
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
    `Preview ${attachment.name}`;

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
    ).trim();

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
      delayedMemoryReport,
      delayedMemoryReportId
    );

  element._jinDelayedMemoryReport =
    report;

  if (!report) {
    element.removeAttribute(
      "role"
    );
    element.removeAttribute(
      "tabindex"
    );
    return;
  }

  element.setAttribute(
    "role",
    "button"
  );
  element.tabIndex = 0;
  element.classList.add(
    "cursor-help"
  );

  if (!element.title) {
    element.title =
      "Open delayed memory report";
  }

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
window.openJinAttachmentModal =
  openJinAttachmentModal;
window.formatJinAttachmentChipLabel =
  formatAttachmentChipLabel;
