const chatHistory =
  document.getElementById(
    "chat-history"
  );

const streamMessages =
  new Map();

const STREAM_FRAME_WARNING_MS = 12;
const STREAM_NEAR_BOTTOM_PX = 72;

let streamFrameScheduled = false;
const deferredRuntimeActionsAfterResponse = [];
let runtimeActionRowCounter = 0;

const jinInputLoopState = {
  previousInput: "",
  repeatCount: 0,
};

let jinConversationTurnCounter = 0;
window.jinConversationTurnCounter =
  jinConversationTurnCounter;

const SCENE_SEARCH_RUNTIME_ACTION = "web_search";
let sceneSearchFadeTimer = null;

function getSceneRoot() {
  return document.querySelector("main");
}

function setSceneSearchScreenActive(active) {
  const sceneRoot = getSceneRoot();

  if (!sceneRoot) {
    return;
  }

  if (sceneSearchFadeTimer) {
    clearTimeout(sceneSearchFadeTimer);
    sceneSearchFadeTimer = null;
  }

  if (active) {
    sceneRoot.classList.add(
      "scene-searching"
    );
    return;
  }

  sceneRoot.classList.remove(
    "scene-searching"
  );
}

function syncSceneSearchScreenForRuntimeAction(
  action,
  active
) {
  if (
    String(action || "").toLowerCase()
    !== SCENE_SEARCH_RUNTIME_ACTION
  ) {
    return;
  }

  setSceneSearchScreenActive(
    active
  );
}

function normalizeJinLoopInput(text) {

  const raw = String(
    text
    || ""
  ).toLowerCase();

  const normalized = raw.normalize
    ? raw.normalize("NFKC")
    : raw;

  try {
    return normalized.replace(
      /[\p{P}\p{S}\s]+/gu,
      ""
    );
  } catch (error) {
    return normalized.replace(
      /[^a-zа-яёіїєґ0-9]+/gi,
      ""
    );
  }

}

function updateJinInputLoopCounter(text) {

  const normalizedInput =
    normalizeJinLoopInput(
      text
    );

  if (!normalizedInput) {
    jinInputLoopState.previousInput = "";
    jinInputLoopState.repeatCount = 0;

    return {
      repeatCount: 0,
      repeated: 0,
      normalizedInput: "",
    };
  }

  if (
    normalizedInput
    === jinInputLoopState.previousInput
  ) {
    jinInputLoopState.repeatCount += 1;
  } else {
    jinInputLoopState.previousInput = normalizedInput;
    jinInputLoopState.repeatCount = 0;
  }

  const repeated =
    jinInputLoopState.repeatCount > 0
      ? jinInputLoopState.repeatCount + 1
      : 0;

  return {
    repeatCount: jinInputLoopState.repeatCount,
    repeated,
    normalizedInput,
  };

}

/**
 * @typedef {Object} ContextSnapshot
 * @property {string=} system_prompt
 * @property {string=} visible_system_prompt
 * @property {string=} user_prompt
 * @property {string=} context_role
 * @property {boolean=} hide_internal_action_rules
 * @property {boolean=} preserve_runtime_action_markers
 */


// ESCAPE HTML

function escapeHtml(text) {

  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

}

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

function isStreamDebugEnabled() {

  return Boolean(
    window.jinStreamDebug
    || window.jinDebugMode
  );

}


function nowMs() {

  return (
    window.performance
    && window.performance.now
  )
    ? window.performance.now()
    : Date.now();

}


function requestStreamFrame(callback) {

  if (window.requestAnimationFrame) {
    window.requestAnimationFrame(
      callback
    );

    return;
  }

  setTimeout(
    callback,
    16
  );

}

function shouldAutoScroll() {

  if (!chatHistory) {
    return false;
  }

  const distanceFromBottom =
    chatHistory.scrollHeight
    - chatHistory.scrollTop
    - chatHistory.clientHeight;

  return (
    distanceFromBottom
    <= STREAM_NEAR_BOTTOM_PX
  );

}


function appendTextNodeData(
  element,
  nodeKey,
  text
) {

  if (
    !element
    || !text
  ) {
    return null;
  }

  let textNode =
    element[nodeKey];

  if (!textNode) {
    textNode =
      document.createTextNode(
        ""
      );

    element.appendChild(
      textNode
    );

    element[nodeKey] =
      textNode;
  }

  textNode.appendData(
    text
  );

  return textNode;

}


function scheduleStreamFrameUpdate() {

  if (streamFrameScheduled) {
    return;
  }

  streamFrameScheduled = true;

  requestStreamFrame(
    flushStreamFrame
  );

}


function flushStreamFrame() {

  const startedAt =
    nowMs();

  streamFrameScheduled = false;

  const autoscroll =
    shouldAutoScroll();

  streamMessages.forEach((stream) => {

    if (
      !stream.pendingThinking
      && !stream.pendingAnswer
    ) {
      return;
    }

    ensureStreamGroup(
      stream
    );

    if (stream.pendingThinking) {

      if (
        !stream.group.createdThinking
      ) {

        stream.group.wrapper.appendChild(
          stream.group.thinkWrapper
        );

        stream.group.createdThinking =
          true;

      }

      appendTextNodeData(
        stream.group.thinkContent,
        "__jinThinkTextNode",
        stream.pendingThinking
      );

      updateThinkExpandedHeight(
        stream.group.thinkContent
      );

      stream.pendingThinking =
        "";

    }

    if (stream.pendingAnswer) {

      if (
        !stream.group.createdAnswer
      ) {

        stream.group.wrapper.appendChild(
          stream.group.messageRow
        );

        stream.group.createdAnswer =
          true;

      }

      appendTextNodeData(
        stream.group.answerContent,
        "__jinAnswerTextNode",
        stream.pendingAnswer
      );

      stream.pendingAnswer =
        "";

    }

  });

  if (
    autoscroll
    && chatHistory
  ) {
    chatHistory.scrollTop =
      chatHistory.scrollHeight;
  }

  const elapsed =
    nowMs() - startedAt;

  if (
    isStreamDebugEnabled()
    && elapsed > STREAM_FRAME_WARNING_MS
  ) {
    console.warn(
      "[stream] frame update took",
      `${elapsed.toFixed(1)}ms`
    );
  }

}


// ROLE CONFIG

function getRoleConfig(role) {

  switch (role) {

    case "user":
      return {
        avatar: "US",
        bubbleClass:
          "jin-chat-bubble jin-chat-bubble-user",
        avatarClass:
          "jin-chat-avatar-user"
      };

    case "service":
      return {
        avatar: "SV",
        bubbleClass:
          "jin-chat-bubble jin-chat-bubble-service jin-chat-bubble-rateable",
        avatarClass:
          "jin-chat-avatar-service"
      };
      
    case "translator":
      return {
        avatar: "TR",
        bubbleClass:
            "jin-chat-bubble jin-chat-bubble-translator",
        avatarClass:
            "jin-chat-avatar-translator"
      };

    case "brain":
    default:
      return {
        avatar: "BR",
        bubbleClass:
          "jin-chat-bubble jin-chat-bubble-brain jin-chat-bubble-rateable",
        avatarClass:
          "jin-chat-avatar-brain"
      };

  }

}

function formatContextSnapshot(
  role,
  contextSnapshot
) {

  /** @type {ContextSnapshot|null} */
  const snapshot =
    contextSnapshot;

  if (!snapshot) {
    return "";
  }

  const hideInternalActionRules =
    Boolean(
      snapshot.hide_internal_action_rules
    );

  const systemPrompt =
    (
      hideInternalActionRules
      && snapshot.visible_system_prompt
    )
    || snapshot.system_prompt
    || "";

  const userPrompt =
    snapshot.user_prompt
    || "";

  return [
    hideInternalActionRules
      ? "SYSTEM PROMPT (INTERNAL ACTION RULES HIDDEN)"
      : "SYSTEM PROMPT",
    "-------------",
    systemPrompt || "(empty)",
    "",
    "USER PROMPT / CONTEXT PAYLOAD",
    "-----------------------------",
    userPrompt || "(empty)",
  ].join("\n");

}


function formatContextTitle(
  role,
  contextSnapshot
) {

  /** @type {ContextSnapshot|null} */
  const snapshot =
    contextSnapshot;

  const messageRole =
    String(
      role || "unknown"
    ).toUpperCase();

  const contextRole =
    String(
      (
        snapshot
        && snapshot.context_role
      )
      || role
      || "unknown"
    ).toUpperCase();

  return (
    `MESSAGE: ${messageRole} `
    + `| CONTEXT: ${contextRole}`
  );

}

function formatRuntimeActionContextTitle(
  action,
  contextSnapshot
) {

  const actionName =
    String(
      action || "runtime_action"
    ).toUpperCase();

  const contextRole =
    String(
      (
        contextSnapshot
        && contextSnapshot.context_role
      )
      || "unknown"
    ).toUpperCase();

  return (
    `ACTION: ${actionName} `
    + `| CONTEXT: ${contextRole}`
  );

}


function createAvatarElement(
  role,
  contextSnapshot = null
) {

  const config =
    getRoleConfig(role);

  const avatar =
    document.createElement(
      contextSnapshot
        ? "button"
        : "div"
    );

  if (contextSnapshot) {
    avatar.type =
      "button";

    avatar.title =
      "show current context";
  }

  avatar.className =
    `jin-chat-avatar ${config.avatarClass || ""}`;

  if (contextSnapshot) {
    avatar.className +=
      " cursor-help transition";
  }

  avatar.textContent =
    config.avatar;

  if (contextSnapshot) {
    avatar.addEventListener(
      "click",
      function () {
        const details =
          formatContextSnapshot(
            role,
            contextSnapshot
          );

        if (window.showTrace) {
          window.showTrace(
            details,
            formatContextTitle(
              role,
              contextSnapshot
            )
          );
        }
      }
    );
  }

  return avatar;

}


// CREATE NORMAL MESSAGE

function createMessageElement(
  role,
  contextSnapshot = null
) {

  const config =
    getRoleConfig(role);

  const msgDiv =
    document.createElement("div");

  msgDiv.className =
    "jin-message-row jin-message-shell mx-auto w-full max-w-4xl";

  msgDiv.dataset.role =
    role;

  const pre =
    document.createElement("pre");

  pre.className =
    "jin-chat-pre";

  const bubble =
    document.createElement("div");

  bubble.className =
    config.bubbleClass;

  bubble.appendChild(pre);

  msgDiv.appendChild(
    createAvatarElement(
      role,
      contextSnapshot
    )
  );

  msgDiv.appendChild(
    bubble
  );

  chatHistory.appendChild(
    msgDiv
  );

  chatHistory.scrollTop =
    chatHistory.scrollHeight;

  return pre;

}


// NORMAL MESSAGE

function createMessageAttachmentChips(
  attachments = []
) {
  if (!Array.isArray(attachments) || !attachments.length) {
    return null;
  }

  const container =
    document.createElement("div");

  container.className =
    "mt-3 flex flex-wrap gap-2";

  attachments.forEach((attachment) => {
    const chip =
      document.createElement("button");

    chip.type =
      "button";
    chip.className =
      "max-w-full rounded border border-sky-400/25 bg-sky-950/35 px-2 py-1 text-left font-mono text-[11px] text-sky-100 transition hover:border-sky-300/50 hover:bg-sky-900/45";

    chip.textContent =
      formatAttachmentChipLabel(
        attachment
      );

    bindJinAttachmentBubble(
      chip,
      attachment
    );

    container.appendChild(
      chip
    );
  });

  return container;
}

function appendChatMessage(
  role,
  text,
  contextSnapshot = null,
  attachments = []
) {

  const pre =
    createMessageElement(
      role,
      contextSnapshot
    );

  pre.innerHTML =
    escapeHtml(text);

  if (role === "user") {
    const chips =
      createMessageAttachmentChips(
        attachments
      );

    if (chips && pre.parentElement) {
      pre.parentElement.appendChild(
        chips
      );
    }
  }

  if (role === "user") {
    jinConversationTurnCounter += 1;
    window.jinConversationTurnCounter =
      jinConversationTurnCounter;
  }

  flushRuntimeActionsAfterResponse(
    role
  );

}

window.bindJinAttachmentBubble =
  bindJinAttachmentBubble;
window.openJinAttachmentModal =
  openJinAttachmentModal;
window.formatJinAttachmentChipLabel =
  formatAttachmentChipLabel;


// RUNTIME ACTION

const runtimeActionGuardDecisionClasses = [
  "jin-runtime-action-guard-pending",
  "jin-runtime-action-guard-rejected",
  "jin-runtime-action-guard-continued",
];
const RUNTIME_ACTION_GUARD_CONFIRMATION_DELAY_MS = 15000;
const RUNTIME_ACTION_GUARD_ANIMATION_DURATION_MS = 3200;
const RUNTIME_ACTION_GUARD_GEOMETRY_REFERENCE_WIDTH = 10;
const RUNTIME_ACTION_GUARD_GREEN_BASE_X = 1;
const RUNTIME_ACTION_GUARD_RED_BASE_X = -1;
const RUNTIME_ACTION_GUARD_GREEN_WIDTH_FACTOR = 0.006;
const RUNTIME_ACTION_GUARD_RED_WIDTH_FACTOR = -0.006;
const RUNTIME_ACTION_GUARD_BASE_PERSPECTIVE = 100;
const RUNTIME_ACTION_GUARD_GREEN_BASE_ROTATE_DEG = -1;
const RUNTIME_ACTION_GUARD_RED_BASE_ROTATE_DEG = 1;
const RUNTIME_ACTION_GUARD_BASE_Z = 10;
const RUNTIME_ACTION_GUARD_BASE_SCALE_X = 1.00;
const RUNTIME_ACTION_GUARD_MIN_MOTION_SCALE = 0.62;
const RUNTIME_ACTION_GUARD_MAX_MOTION_SCALE = 1.18;
const RUNTIME_ACTION_GUARD_MIN_ROTATION_SCALE = 2;
const RUNTIME_ACTION_GUARD_MAX_ROTATION_SCALE = 0.15;
const RUNTIME_ACTION_GUARD_MIN_ROTATION_WIDTH = 220;
const RUNTIME_ACTION_GUARD_MAX_ROTATION_WIDTH = 760;
const RUNTIME_ACTION_GUARD_MIN_ICON_GAP = 8;
let runtimeActionGuardGeometryFrame = null;

function resolveRuntimeActionGuardConfirmationDelayMs(
  confirmation = {}
) {

  const configuredDelay =
    Number(
      confirmation.timeoutMs
      || confirmation.timeout_ms
      || RUNTIME_ACTION_GUARD_CONFIRMATION_DELAY_MS
    );

  return Number.isFinite(
    configuredDelay
  ) && configuredDelay > 0
    ? configuredDelay
    : RUNTIME_ACTION_GUARD_CONFIRMATION_DELAY_MS;

}

function clampRuntimeActionGuardValue(
  value,
  min,
  max
) {

  return Math.min(
    max,
    Math.max(
      min,
      value
    )
  );

}

function updateRuntimeActionGuardGeometry(
  row,
  label
) {

  if (
      !row
      || !label
  ) {
    return;
  }

  const labelRect =
    label.getBoundingClientRect();
  const icon =
    row.querySelector(
      ":scope > div:not(.jin-runtime-action-label), :scope > button"
    );
  const iconRect =
    icon
      ? icon.getBoundingClientRect()
      : null;

  const width =
    Math.max(
      0,
      Number(
        labelRect.width || 0
      )
    );
  const extraWidth =
    Math.max(
      0,
      width - RUNTIME_ACTION_GUARD_GEOMETRY_REFERENCE_WIDTH
    );
  const currentGap =
    iconRect
      ? labelRect.left - iconRect.right
      : RUNTIME_ACTION_GUARD_MIN_ICON_GAP;
  const gapCompensation =
    Math.max(
      0,
      RUNTIME_ACTION_GUARD_MIN_ICON_GAP - currentGap
    );
  const greenX =
    RUNTIME_ACTION_GUARD_GREEN_BASE_X
    + gapCompensation
    + (
      extraWidth
      * RUNTIME_ACTION_GUARD_GREEN_WIDTH_FACTOR
    );
  const redX =
    RUNTIME_ACTION_GUARD_RED_BASE_X
    + gapCompensation
    + (
      extraWidth
      * RUNTIME_ACTION_GUARD_RED_WIDTH_FACTOR
    );
  const rotationWidthSpan =
    Math.max(
      1,
      RUNTIME_ACTION_GUARD_MAX_ROTATION_WIDTH
      - RUNTIME_ACTION_GUARD_MIN_ROTATION_WIDTH
    );
  const rotationWidthProgress =
    clampRuntimeActionGuardValue(
      (
        width
        - RUNTIME_ACTION_GUARD_MIN_ROTATION_WIDTH
      )
      / rotationWidthSpan,
      0,
      1
    );
  const rotationScale =
    RUNTIME_ACTION_GUARD_MIN_ROTATION_SCALE
    + (
      rotationWidthProgress
      * (
        RUNTIME_ACTION_GUARD_MAX_ROTATION_SCALE
        - RUNTIME_ACTION_GUARD_MIN_ROTATION_SCALE
      )
    );
  const motionScale =
    clampRuntimeActionGuardValue(
      Math.sqrt(
        RUNTIME_ACTION_GUARD_GEOMETRY_REFERENCE_WIDTH
        / Math.max(
          width,
          1
        )
      ),
      RUNTIME_ACTION_GUARD_MIN_MOTION_SCALE,
      RUNTIME_ACTION_GUARD_MAX_MOTION_SCALE
    );
  const perspective =
    RUNTIME_ACTION_GUARD_BASE_PERSPECTIVE
    / motionScale;
  const greenRotate =
    RUNTIME_ACTION_GUARD_GREEN_BASE_ROTATE_DEG
    * rotationScale;
  const redRotate =
    RUNTIME_ACTION_GUARD_RED_BASE_ROTATE_DEG
    * rotationScale;
  const depthZ =
    RUNTIME_ACTION_GUARD_BASE_Z
    * motionScale;
  const scaleX =
    1
    + (
      (
        RUNTIME_ACTION_GUARD_BASE_SCALE_X
        - 1
      )
      * motionScale
    );

  label.style.setProperty(
    "--jin-runtime-action-guard-green-x",
    `${greenX.toFixed(2)}px`
  );
  label.style.setProperty(
    "--jin-runtime-action-guard-red-x",
    `${redX.toFixed(2)}px`
  );
  label.style.setProperty(
    "--jin-runtime-action-guard-perspective",
    `${perspective.toFixed(2)}px`
  );
  label.style.setProperty(
    "--jin-runtime-action-guard-green-rotate",
    `${greenRotate.toFixed(2)}deg`
  );
  label.style.setProperty(
    "--jin-runtime-action-guard-red-rotate",
    `${redRotate.toFixed(2)}deg`
  );
  label.style.setProperty(
    "--jin-runtime-action-guard-z",
    `${depthZ.toFixed(2)}px`
  );
  label.style.setProperty(
    "--jin-runtime-action-guard-scale-x",
    scaleX.toFixed(4)
  );

}

function updateRuntimeActionGuardGeometries(
  root = document
) {

  const scope =
    root instanceof Element
      ? root
      : document;

  scope
    .querySelectorAll(
      ".jin-runtime-action-guard-pending"
    )
    .forEach((row) => {
      updateRuntimeActionGuardGeometry(
        row,
        row.querySelector(
          ".jin-runtime-action-guard-label"
        )
      );
    });

}

function scheduleRuntimeActionGuardGeometryUpdate() {

  if (runtimeActionGuardGeometryFrame) {
    return;
  }

  runtimeActionGuardGeometryFrame =
    window.requestAnimationFrame(
      () => {
        runtimeActionGuardGeometryFrame = null;
        updateRuntimeActionGuardGeometries();
      }
    );

}

function normalizeRuntimeActionKeyPart(value) {

  return String(
    value || ""
  ).trim().toLowerCase();

}

function buildRuntimeActionVisibleKey(
  action,
  options = {}
) {

  const actionName =
    normalizeRuntimeActionKeyPart(
      action
    );

  const actionId =
    normalizeRuntimeActionKeyPart(
      options.id
    );

  if (actionId) {
    return `${actionName}:${actionId}`;
  }

  runtimeActionRowCounter += 1;

  return `${jinConversationTurnCounter}:${actionName}:${runtimeActionRowCounter}`;

}

function clearRuntimeActionGuardConfirmation(
  row
) {

  if (!row) {
    return;
  }

  if (row._runtimeActionGuardTimer) {
    window.clearTimeout(
      row._runtimeActionGuardTimer
    );
    row._runtimeActionGuardTimer = null;
  }

  row.classList.remove(
    ...runtimeActionGuardDecisionClasses
  );

  const label =
    row.querySelector(
      ".jin-runtime-action-label"
    );

  if (!label) {
    return;
  }

  label.classList.remove(
    "jin-runtime-action-guard-label"
  );
  label.style.removeProperty(
    "--jin-runtime-action-guard-motion"
  );
  label.style.removeProperty(
    "--jin-runtime-action-guard-green-x"
  );
  label.style.removeProperty(
    "--jin-runtime-action-guard-red-x"
  );
  label.style.removeProperty(
    "--jin-runtime-action-guard-perspective"
  );
  label.style.removeProperty(
    "--jin-runtime-action-guard-green-rotate"
  );
  label.style.removeProperty(
    "--jin-runtime-action-guard-red-rotate"
  );
  label.style.removeProperty(
    "--jin-runtime-action-guard-z"
  );
  label.style.removeProperty(
    "--jin-runtime-action-guard-scale-x"
  );

  label
    .querySelectorAll(
      ":scope > .jin-runtime-action-guard-zones"
    )
    .forEach((zones) => {
      zones.remove();
    });

  delete row.dataset.runtimeActionGuardConfirmationId;
  delete row.dataset.runtimeActionGuardDecision;

}

function settleRuntimeActionGuardConfirmation(
  row,
  decision
) {

  if (!row) {
    return;
  }

  if (row._runtimeActionGuardTimer) {
    window.clearTimeout(
      row._runtimeActionGuardTimer
    );
    row._runtimeActionGuardTimer = null;
  }

  row.classList.remove(
    "jin-runtime-action-guard-pending"
  );

  row.classList.add(
    decision === "reject"
      ? "jin-runtime-action-guard-rejected"
      : "jin-runtime-action-guard-continued"
  );

  row.dataset.runtimeActionGuardDecision =
    decision;

  const zones =
    row.querySelector(
      ".jin-runtime-action-guard-zones"
    );

  if (zones) {
    zones.remove();
  }

  normalizeCompletedRuntimeActionLabel(
    row
  );

}

function bindRuntimeActionGuardConfirmation(
  row,
  label,
  action,
  options = {}
) {

  const confirmation =
    options.guardConfirmation || {};
  const confirmationId =
    String(
      confirmation.confirmationId
      || confirmation.confirmation_id
      || ""
    ).trim();

  if (
      !row
      || !label
      || !confirmationId
  ) {
    return;
  }

  row.classList.remove(
    "opacity-45",
    "jin-runtime-action-guard-rejected",
    "jin-runtime-action-guard-continued"
  );
  row.classList.add(
    "jin-runtime-action-guard-pending"
  );
  row.dataset.runtimeActionGuardConfirmationId =
    confirmationId;

  label.classList.add(
    "jin-runtime-action-guard-label"
  );
  label.style.setProperty(
    "--jin-runtime-action-guard-motion",
    `${RUNTIME_ACTION_GUARD_ANIMATION_DURATION_MS}ms`
  );
  updateRuntimeActionGuardGeometry(
    row,
    label
  );

  window.requestAnimationFrame(
    () => {
      updateRuntimeActionGuardGeometry(
        row,
        label
      );
    }
  );

  const timeoutMs =
    resolveRuntimeActionGuardConfirmationDelayMs(
      confirmation
    );

  if (
    label.querySelector(
      ":scope > .jin-runtime-action-guard-zones"
    )
  ) {
    return;
  }

  const zones =
    document.createElement("div");
  zones.className =
    "jin-runtime-action-guard-zones";
  zones.setAttribute(
    "aria-hidden",
    "true"
  );

  [
    [
      "reject",
      "jin-runtime-action-guard-zone jin-runtime-action-guard-zone-reject",
      "cancel this action",
    ],
    [
      "continue",
      "jin-runtime-action-guard-zone jin-runtime-action-guard-zone-continue",
      "continue this action",
    ],
  ].forEach(([decision, className, title]) => {
    const zone =
      document.createElement("button");
    zone.type =
      "button";
    zone.className =
      className;
    zone.title =
      title;
    zone.dataset.runtimeActionGuardDecision =
      decision;

    zone.addEventListener(
      "click",
      (event) => {
        event.preventDefault();
        event.stopPropagation();

        if (
          row.dataset.runtimeActionGuardDecision
        ) {
          return;
        }

        const sent =
          window.sendSocketMessage
            ? window.sendSocketMessage({
              type: "runtime_action_guard_confirmation",
              confirmation_id: confirmationId,
              action: action || "",
              id: options.id || "",
              guard: confirmation.guard || "",
              decision,
            })
            : false;

        if (!sent) {
          return;
        }

        settleRuntimeActionGuardConfirmation(
          row,
          decision
        );
      }
    );

    zones.appendChild(
      zone
    );
  });

  label.appendChild(
    zones
  );

  if (timeoutMs > 0) {
    if (row._runtimeActionGuardTimer) {
      window.clearTimeout(
        row._runtimeActionGuardTimer
      );
    }

    row._runtimeActionGuardTimer =
      window.setTimeout(
        () => {
          if (
            row.dataset.runtimeActionGuardDecision
          ) {
            return;
          }

          settleRuntimeActionGuardConfirmation(
            row,
            "continue"
          );
        },
        timeoutMs
      );
  }

}

function updateRuntimeActionRow(
  row,
  action,
  text,
  options = {}
) {

  const label =
    row.querySelector(
      ".jin-runtime-action-label"
    );

  if (!label) {
    return false;
  }

  label.textContent =
    text;

  const detail =
    String(
      options.detail || ""
    ).trim();

  if (detail) {
    label.title = detail;
    label.classList.add(
      "cursor-help"
    );
  } else {
    label.removeAttribute(
      "title"
    );
    label.classList.remove(
      "cursor-help"
    );
  }

  if (action === "asset_action") {
    bindAssetResultPreview(
      label,
      options.assetResult || null
    );
  }

  if (action === "save_delayed_memory_content") {
    bindDelayedMemoryReportPreview(
      label,
      options.delayedMemoryReport || null,
      options.delayedMemoryReportId || ""
    );
  }

  if (options.guardConfirmation) {
    bindRuntimeActionGuardConfirmation(
      row,
      label,
      action,
      options
    );
  } else {
    clearRuntimeActionGuardConfirmation(
      row
    );
  }

  if (options.completed) {
    markRuntimeActionRowCompleted(
      row
    );
  }

  return true;

}

function normalizeCompletedRuntimeActionLabel(
  row
) {

  const label =
    row
      ? row.querySelector(
        ".jin-runtime-action-label"
      )
      : null;

  if (!label) {
    return;
  }

  const normalizedText =
    String(
      label.textContent || ""
    ).replace(
      /^CONFIRM:\s*/i,
      ""
    ).trim();

  if (normalizedText) {
    label.textContent =
      normalizedText;
  }

}

function markRuntimeActionRowCompleted(
  row
) {

  if (!row) {
    return;
  }

  row.dataset.runtimeActionCompleted =
    "true";

  clearRuntimeActionGuardConfirmation(
    row
  );

  normalizeCompletedRuntimeActionLabel(
    row
  );

  row.classList.add(
    "opacity-45"
  );

  row
    .querySelectorAll("div, button")
    .forEach((element) => {
      element.classList.add(
        "border-zinc-700/50",
        "bg-zinc-900/30",
        "text-zinc-400"
      );
    });

}

function appendRuntimeAction(
  action,
  text,
  options = {}
) {

  const actionText =
    String(
      text || ""
    );

  if (!actionText.trim()) {
    return false;
  }

  const shouldUpdateExisting =
    options.updateExisting !== false;

  const actionKey =
    buildRuntimeActionVisibleKey(
      action,
      options
    );

  if (shouldUpdateExisting) {
    const existingRows =
      options.id
        ? chatHistory.querySelectorAll(
          `[data-runtime-action-key="${actionKey}"]`
        )
        : [];

    let existingRow =
      Array.from(
        existingRows
      ).find((row) => {
        return row.dataset.runtimeActionCompleted !== "true";
      });

    const guardConfirmationId =
      String(
        options.guardConfirmationId
        || options.confirmationId
        || ""
      ).trim();

    if (
        !existingRow
        && guardConfirmationId
    ) {
      existingRow =
        Array.from(
          chatHistory.querySelectorAll(
            ".jin-runtime-action-row.jin-runtime-action-guard-pending"
          )
        ).find((row) => {
          return (
            row.dataset.runtimeActionCompleted !== "true"
            && row.dataset.runtimeActionGuardConfirmationId
              === guardConfirmationId
          );
        });
    }

    if (
        !existingRow
        && action
    ) {
      existingRow =
        Array.from(
          chatHistory.querySelectorAll(
            `.jin-runtime-action-row[data-runtime-action="${action}"].jin-runtime-action-guard-pending`
          )
        ).find((row) => {
          return row.dataset.runtimeActionCompleted !== "true";
        });
    }

    if (
        existingRow
        && updateRuntimeActionRow(
          existingRow,
          action,
          actionText,
          options
        )
    ) {
      return true;
    }
  }

  if (options.activateScene !== false) {
    syncSceneSearchScreenForRuntimeAction(
      action,
      true
    );
  }

  const row =
    document.createElement("div");

  row.className =
    "jin-message-row jin-runtime-action-row mx-auto w-full max-w-4xl text-xs text-cyan-100 transition duration-500";

  row.dataset.runtimeAction =
    action || "";

  row.dataset.runtimeActionKey =
    actionKey || "";

  if (options.completed) {
    row.dataset.runtimeActionCompleted =
      "true";
  }

  const icon =
    document.createElement(
      options.contextSnapshot
        ? "button"
        : "div"
    );

  if (options.contextSnapshot) {
    icon.type =
      "button";
  }

  icon.className =
    "h-6 w-6 rounded bg-cyan-950/70 border border-cyan-700 flex items-center justify-center text-[12px] shrink-0";

  icon.textContent =
    action === "web_search"
      ? "🔍"
      : action === "list_skills"
        ? "📘"
        : action === "asset_action"
          ? "▣"
      : "●";

  if (options.contextSnapshot) {
    icon.className +=
      " cursor-help hover:bg-cyan-900/70 transition";

    icon.title =
      "show action context";

    icon.addEventListener(
      "click",
      function () {
        if (!window.showTrace) {
          return;
        }

        window.showTrace(
          formatContextSnapshot(
            "action",
            options.contextSnapshot
          ),
          formatRuntimeActionContextTitle(
            action,
            options.contextSnapshot
          )
        );
      }
    );
  }

  const label =
    document.createElement("div");

  label.className =
    "jin-runtime-action-label px-3 py-2 rounded-lg border border-cyan-700/70 bg-cyan-950/40 font-mono transition duration-500";

  label.textContent =
    actionText;

  const detail =
    String(
      options.detail || ""
    ).trim();

  if (detail) {
    label.title = detail;
    label.classList.add(
      "cursor-help"
    );
  }

  if (action === "asset_action") {
    bindAssetResultPreview(
      label,
      options.assetResult || null
    );
  }

  if (action === "save_delayed_memory_content") {
    bindDelayedMemoryReportPreview(
      label,
      options.delayedMemoryReport || null,
      options.delayedMemoryReportId || ""
    );
  }

  if (options.guardConfirmation) {
    bindRuntimeActionGuardConfirmation(
      row,
      label,
      action,
      options
    );
  }

  row.appendChild(
    icon
  );

  row.appendChild(
    label
  );

  if (options.completed) {
    markRuntimeActionRowCompleted(
      row
    );
  }

  chatHistory.appendChild(
    row
  );

  chatHistory.scrollTop =
    chatHistory.scrollHeight;

  return true;

}

window.addEventListener(
  "resize",
  scheduleRuntimeActionGuardGeometryUpdate
);

window.requestAnimationFrame(
  () => {
    updateRuntimeActionGuardGeometries();
  }
);


function queueRuntimeActionAfterNextResponse(
  action,
  text,
  options = {}
) {

  const actionText =
    String(
      text || ""
    );

  if (!actionText.trim()) {
    return;
  }

  deferredRuntimeActionsAfterResponse.push({
    action:
      action || "",
    text: actionText,
    id: options.id || "",
    contextSnapshot:
      options.contextSnapshot || null,
    assetResult:
      options.assetResult || null,
    detail:
      options.detail || "",
    completed: false,
  });

}


function isResponseRole(
  role
) {

  return ![
    "user",
    "system",
  ].includes(
    String(role || "").toLowerCase()
  );

}


function flushRuntimeActionsAfterResponse(
  role
) {

  if (
    !isResponseRole(role)
    || !deferredRuntimeActionsAfterResponse.length
  ) {
    return;
  }

  const actions =
    deferredRuntimeActionsAfterResponse.splice(0);

  actions.forEach((entry) => {
    appendRuntimeAction(
      entry.action,
      entry.text,
      {
        id: entry.id || "",
        contextSnapshot:
          entry.contextSnapshot || null,
        assetResult:
          entry.assetResult || null,
        detail:
          entry.detail || "",
        completed:
          entry.completed,
        activateScene: !entry.completed,
      }
    );

    if (entry.completed) {
      fadeRuntimeAction(
        entry.action
      );
    }
  });

}


function fadeRuntimeAction(
  action,
  options = {}
) {

  const actionKey =
    options.id
      ? buildRuntimeActionVisibleKey(
        action,
        options
      )
      : "";

  deferredRuntimeActionsAfterResponse.forEach((entry) => {
    if (
      entry.action === action
      && (
        !options.id
        || entry.id === options.id
      )
    ) {
      entry.completed = true;
    }
  });

  syncSceneSearchScreenForRuntimeAction(
    action,
    false
  );

  const rows =
    actionKey
      ? chatHistory.querySelectorAll(
        `[data-runtime-action-key="${actionKey}"]`
      )
      : chatHistory.querySelectorAll(
        `[data-runtime-action="${action}"]`
      );

  rows.forEach((row) => {
    markRuntimeActionRowCompleted(
      row
    );
  });

}


// CREATE STREAM GROUP

function updateThinkExpandedHeight(
  thinkContent
) {

  if (!thinkContent) {
    return;
  }

  thinkContent.style.setProperty(
    "--jin-think-expanded-height",
    `${thinkContent.scrollHeight}px`
  );

}

let thinkResizeFrame = null;

window.addEventListener(
  "resize",
  () => {

    if (thinkResizeFrame) {
      return;
    }

    thinkResizeFrame = requestAnimationFrame(
      () => {

        thinkResizeFrame = null;

        document
          .querySelectorAll(
            ".jin-think-content"
          )
          .forEach(
            updateThinkExpandedHeight
          );

      }
    );

  }
);

function createStreamGroup(
  role,
  contextSnapshot = null
) {

  const config =
    getRoleConfig(role);

  const wrapper =
    document.createElement("div");

  wrapper.className =
    "jin-stream-wrapper mx-auto w-full max-w-4xl space-y-3";

  // THINKING

  const thinkWrapper =
    document.createElement("div");

  thinkWrapper.className =
    "jin-think-wrapper";

  const thinkContent =
    document.createElement("div");

  thinkContent.className =
    "jin-think-content";

  thinkContent.setAttribute(
    "role",
    "button"
  );

  thinkContent.setAttribute(
    "tabindex",
    "0"
  );

  thinkContent.setAttribute(
    "aria-expanded",
    "true"
  );

  thinkContent.setAttribute(
    "aria-label",
    "Toggle thinking block"
  );

  let collapsed = false;

  const setCollapsed = (nextCollapsed) => {

    collapsed =
      nextCollapsed;

    thinkContent.classList.toggle(
      "is-collapsed",
      collapsed
    );

    thinkContent.setAttribute(
      "aria-expanded",
      collapsed
        ? "false"
        : "true"
    );

  };

  thinkContent.addEventListener(
    "click",
    () => {
      setCollapsed(
        !collapsed
      );
    }
  );

  thinkContent.addEventListener(
    "keydown",
    (event) => {

      if (
        event.key !== "Enter"
        && event.key !== " "
      ) {
        return;
      }

      event.preventDefault();

      setCollapsed(
        !collapsed
      );

    }
  );

  [
    "mouseenter",
    "mouseleave",
  ].forEach((eventName) => {
    thinkContent.addEventListener(
      eventName,
      () => {
        window.JinThinkCitations.syncThinkRuntimeCitationHighlight(
          thinkContent
        );
      }
    );
  });

  thinkWrapper.appendChild(
    thinkContent
  );

  // ANSWER

  const messageRow =
    document.createElement("div");

  messageRow.className =
    "jin-message-row";

  const pre =
    document.createElement("pre");

  pre.className =
    "jin-chat-pre";

  const bubble =
    document.createElement("div");

  bubble.className =
    config.bubbleClass;

  bubble.appendChild(pre);

  messageRow.appendChild(
    createAvatarElement(
      role,
      contextSnapshot
    )
  );

  messageRow.appendChild(
    bubble
  );

  chatHistory.appendChild(
    wrapper
  );

  chatHistory.scrollTop =
    chatHistory.scrollHeight;

  return {
    wrapper,
    thinkWrapper,
    thinkContent,
    messageRow,
    answerContent: pre,
  };

}


// ENSURE STREAM GROUP

function ensureStreamGroup(
  stream
) {

  // already initialized

  if (
    stream.group.wrapper
    && stream.group.answerContent
    && stream.group.thinkContent
  ) {

    return;

  }

  const realGroup =
    createStreamGroup(
      stream.role,
      stream.context
    );

  stream.group.wrapper =
    realGroup.wrapper;

  stream.group.thinkWrapper =
    realGroup.thinkWrapper;

  stream.group.thinkContent =
    realGroup.thinkContent;

  stream.group.thinkContent.dataset.thinkId =
    stream.messageId;

  stream.group.messageRow =
    realGroup.messageRow;

  stream.group.answerContent =
    realGroup.answerContent;

  stream.group.createdThinking =
    false;

  stream.group.createdAnswer =
    false;

}


// STREAM START

function startStreamMessage(
  messageId,
  role,
  contextSnapshot = null
) {

  const group = {
    createdThinking: false,
    createdAnswer: false,
    wrapper: null,
    thinkWrapper: null,
    thinkContent: null,
    messageRow: null,
    answerContent: null,
  };

  streamMessages.set(
    messageId,
    {
      role,
      messageId,
      context: contextSnapshot,
      group,
      thinking: "",
      answer: "",
      pendingThinking: "",
      pendingAnswer: "",
    }
  );

}


// THINKING CHUNK

function stripInternalActionMarkers(
  text
) {

  return String(text || "")
    .replace(
      /(^|\n)[^\S\r\n]*<(?:INTERNAL_ACTION_)?SAVE_SESSION>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /(^|\n)[^\S\r\n]*<(?:INTERNAL_ACTION_)?WEB_SEARCH:[^>\n]*>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /(^|\n)[^\S\r\n]*<(?:INTERNAL_ACTION_)?LIST_SKILLS(?::[^>\n]*)?>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /(^|\n)[^\S\r\n]*<(?:INTERNAL_ACTION_)?APPEND_SKILLS?:[^>\n]*>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /(^|\n)[^\S\r\n]*<(?:INTERNAL_ACTION_)?REMOVE_SKILLS?:[^>\n]*>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /(^|\n)[^\S\r\n]*<(?:INTERNAL_ACTION_)?ASSET_ACTION>[\s\S]*?<\/(?:INTERNAL_ACTION_)?ASSET_ACTION>[^\S\r\n]*(?=\n|$)/gi,
      "$1"
    )
    .replace(
      /\n{3,}/g,
      "\n\n"
    );

}

function collapseAnswerMarkerGap(
  text
) {

  return String(text || "")
    .replace(
      /\n{3,}/g,
      "\n\n"
    );

}

function appendThinkingChunk(
  messageId,
  chunk
) {

  const stream =
    streamMessages.get(
      messageId
    );

  if (!stream) {
    return;
  }

  if (
    !stream.thinking
  ) {

    chunk =
      String(chunk || "").replace(
        /^\s+/,
        ""
      );

    if (!chunk) {
      return;
    }

  }

  stream.thinking += chunk;
  stream.pendingThinking += chunk;

  scheduleStreamFrameUpdate();

}


// ANSWER CHUNK

function appendStreamChunk(
  messageId,
  chunk
) {

  if (
    chunk === null
    || chunk === undefined
    || chunk === ""
  ) {
    return;
  }

  const stream =
    streamMessages.get(
      messageId
    );

  if (!stream) {
    return;
  }

  const preserveRuntimeActionMarkers =
    Boolean(
      stream.context
      && stream.context.preserve_runtime_action_markers
    );

  if (!preserveRuntimeActionMarkers) {
    chunk =
      stripInternalActionMarkers(
        chunk
      );
  }

  if (!stream.answer.trim()) {
    chunk =
      chunk.replace(
        /^\s+/,
        ""
      );
  }

  if (!chunk) {
    return;
  }

  stream.answer += chunk;
  stream.pendingAnswer += chunk;

  stream.answer =
    collapseAnswerMarkerGap(
      stream.answer
    );
  stream.pendingAnswer =
    collapseAnswerMarkerGap(
      stream.pendingAnswer
    );

  scheduleStreamFrameUpdate();

}


// STREAM END

function finishStreamMessage(
  messageId
) {

  const stream =
    streamMessages.get(
      messageId
    );

  if (stream) {

    flushStreamFrame();

    if (
      stream.group.createdAnswer
      && !stream.answer.trim()
      && stream.group.messageRow
    ) {
      stream.group.messageRow.remove();
    }

    if (
      stream.group.createdThinking
      && !stream.thinking.trim()
      && stream.group.thinkWrapper
    ) {
      stream.group.thinkWrapper.remove();
    }

    if (
      stream.group.wrapper
      && stream.group.wrapper.childElementCount === 0
    ) {
      stream.group.wrapper.remove();
    }

    if (stream.answer.trim()) {
      flushRuntimeActionsAfterResponse(
        stream.role
      );
    }

    window.JinThinkCitations.startThinkRuleCitationAnalysis(
      messageId,
      stream
    );

  }

  streamMessages.delete(
    messageId
  );

}


window.normalizeJinLoopInput =
  normalizeJinLoopInput;

window.updateJinInputLoopCounter =
  updateJinInputLoopCounter;

window.setSceneSearchScreenActive =
  setSceneSearchScreenActive;

window.appendChatMessage =
  appendChatMessage;

window.appendRuntimeAction =
  appendRuntimeAction;

window.queueRuntimeActionAfterNextResponse =
  queueRuntimeActionAfterNextResponse;

window.fadeRuntimeAction =
  fadeRuntimeAction;

window.stripInternalActionMarkers =
  stripInternalActionMarkers;

window.startStreamMessage =
  startStreamMessage;

window.appendStreamChunk =
  appendStreamChunk;

window.finishStreamMessage =
  finishStreamMessage;

window.appendThinkingChunk =
  appendThinkingChunk;

window.flushStreamFrame =
  flushStreamFrame;
