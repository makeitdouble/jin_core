(function () {
  const REFERENCE_CLASS = "jin-chat-reference-id";
  const REFERENCE_SELECTOR = `.${REFERENCE_CLASS}`;
  const RESPONSE_SELECTOR =
    ".jin-chat-bubble-brain .jin-chat-pre, .jin-chat-bubble-service .jin-chat-pre";
  const FILES_CHANGED_EVENT = "jin:files-store-changed";
  const DELAYED_CHANGED_EVENT = "jin:delayed-memory-store-changed";
  const ATTACHMENT_UI_READY_EVENT = "jin:attachment-ui-ready";

  let referenceCache = null;

  function normalizeId(value) {
    return String(value || "").trim().toLowerCase();
  }

  function escapeRegex(value) {
    return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }

  function cleanPersistentFileName(record) {
    if (!record) return "";

    const id = normalizeId(record.id);
    const raw = String(
      record.name
      || record.filename
      || record.stored_name
      || ""
    ).trim();

    if (!raw) return id;

    const prefixed = id
      ? new RegExp(`^${escapeRegex(id)}[_-]`, "i")
      : null;

    return prefixed
      ? raw.replace(prefixed, "")
      : raw;
  }

  function getPersistentFiles() {
    if (!window.JinFiles || typeof window.JinFiles.getFiles !== "function") {
      return [];
    }

    try {
      return window.JinFiles.getFiles() || [];
    } catch (_error) {
      return [];
    }
  }

  function getDelayedReports() {
    const runtime =
      window.JinRuntime
      && window.JinRuntime.runtime;
    if (!runtime || typeof runtime.getDelayedMemoryReports !== "function") {
      return [];
    }

    let reports = null;
    try {
      reports = runtime.getDelayedMemoryReports();
    } catch (_error) {
      return [];
    }

    if (Array.isArray(reports)) {
      return reports;
    }

    if (!reports || typeof reports !== "object") {
      return [];
    }

    return Object.entries(reports).map(([storageKey, report]) => {
      if (!report || typeof report !== "object" || Array.isArray(report)) {
        return null;
      }

      return {
        ...report,
        _storage_key: report._storage_key || storageKey,
      };
    }).filter(Boolean);
  }

  function buildReferenceCache() {
    const references = new Map();

    getPersistentFiles().forEach((record) => {
      const id = normalizeId(record && record.id);
      if (!/^[a-z0-9]{6}$/.test(id)) return;

      references.set(id, {
        kind: "file",
        id,
        record,
      });
    });

    getDelayedReports().forEach((report) => {
      const id = normalizeId(
        report && (
          report._storage_key
          || report.id
        )
      );
      if (!/^[a-z0-9]{6}$/.test(id) || references.has(id)) return;

      references.set(id, {
        kind: "delayed",
        id,
        record: report,
      });
    });

    const ids = Array.from(references.keys());
    const pattern = ids.length
      ? new RegExp(`\\b(?:${ids.map(escapeRegex).join("|")})\\b`, "gi")
      : null;

    referenceCache = {
      references,
      pattern,
    };

    return referenceCache;
  }

  function getReferenceCache() {
    return referenceCache || buildReferenceCache();
  }

  function invalidateReferenceCache() {
    referenceCache = null;
  }

  function isBubbleRatingCapturingClick(element) {
    const bubble = element && element.closest
      ? element.closest(".jin-chat-bubble-rateable")
      : null;

    if (!bubble) return false;

    return !(
      bubble.classList.contains("jin-rating-disabled")
      || bubble.classList.contains("jin-rating-committed")
      || bubble.dataset.ratingCommitted === "true"
      || bubble.dataset.ratingPastTurn === "true"
    );
  }

  function hasActiveSelection() {
    const selection = window.getSelection && window.getSelection();
    return Boolean(selection && !selection.isCollapsed && String(selection).trim());
  }

  function openDelayedReference(reference) {
    const memoryView =
      window.JinRuntime
      && window.JinRuntime.memoryView;

    if (
      memoryView
      && typeof memoryView.openDelayedMemoryReportModal === "function"
    ) {
      memoryView.openDelayedMemoryReportModal(reference.record);
    }
  }

  function openFileReference(reference) {
    if (typeof window.openJinAttachmentModal === "function") {
      window.openJinAttachmentModal(reference.record);
    }
  }

  function openReference(reference) {
    if (!reference) return;

    if (reference.kind === "delayed") {
      openDelayedReference(reference);
      return;
    }

    if (reference.kind === "file") {
      openFileReference(reference);
    }
  }

  function bindImageHoverPreview(element, reference) {
    if (
      !element
      || !reference
      || reference.kind !== "file"
      || String(reference.record && reference.record.kind || "").toLowerCase() !== "image"
    ) {
      return;
    }

    const bind = () => {
      if (element.dataset.jinReferenceHoverBound === "1") return true;
      if (typeof window.bindJinAttachmentHoverPreview !== "function") return false;

      window.bindJinAttachmentHoverPreview(
        element,
        reference.record,
        { hoverPreviewMaxPx: 100 }
      );
      element.dataset.jinReferenceHoverBound = "1";
      return true;
    };

    if (!bind()) {
      window.addEventListener(
        ATTACHMENT_UI_READY_EVENT,
        bind,
        { once: true }
      );
    }
  }

  function configureReferenceElement(element, reference) {
    element.className = REFERENCE_CLASS;
    element.dataset.jinReferenceId = reference.id;
    element.dataset.jinReferenceKind = reference.kind;

    if (reference.kind === "delayed") {
      const title = String(
        reference.record && reference.record.title
        || reference.id
      ).trim();
      element.title = title || reference.id;
    } else if (reference.kind === "file") {
      const kind = String(reference.record && reference.record.kind || "").toLowerCase();
      if (kind === "text") {
        element.title = cleanPersistentFileName(reference.record) || reference.id;
      }
      bindImageHoverPreview(element, reference);
    }

    element.addEventListener("click", (event) => {
      if (isBubbleRatingCapturingClick(element)) {
        return;
      }

      if (hasActiveSelection()) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();
      openReference(reference);
    });
  }

  function shouldSkipTextNode(node, root) {
    const parent = node && node.parentElement;
    if (!parent) return true;
    if (parent.closest(REFERENCE_SELECTOR)) return true;
    if (parent.closest("code, a, button, input, textarea, select")) return true;
    return !root.contains(parent);
  }

  function decorateTextNode(node, root, references, pattern) {
    if (!node || !node.nodeValue || shouldSkipTextNode(node, root)) return;

    const text = node.nodeValue;
    pattern.lastIndex = 0;

    let match = pattern.exec(text);
    if (!match) return;

    const fragment = document.createDocumentFragment();
    let lastIndex = 0;

    do {
      const matchedText = match[0];
      const id = normalizeId(matchedText);
      const reference = references.get(id);

      if (!reference) {
        match = pattern.exec(text);
        continue;
      }

      if (match.index > lastIndex) {
        fragment.appendChild(
          document.createTextNode(text.slice(lastIndex, match.index))
        );
      }

      const element = document.createElement("span");
      element.textContent = matchedText;
      configureReferenceElement(element, reference);
      fragment.appendChild(element);

      lastIndex = match.index + matchedText.length;
      match = pattern.exec(text);
    } while (match);

    if (lastIndex < text.length) {
      fragment.appendChild(
        document.createTextNode(text.slice(lastIndex))
      );
    }

    node.replaceWith(fragment);
  }

  function decorate(element) {
    if (!element) return;

    const { references, pattern } = getReferenceCache();
    if (!pattern || !references.size) return;

    const nodes = [];
    const walker = document.createTreeWalker(
      element,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode(node) {
          if (shouldSkipTextNode(node, element)) {
            return NodeFilter.FILTER_REJECT;
          }
          return NodeFilter.FILTER_ACCEPT;
        },
      }
    );

    let node = walker.nextNode();
    while (node) {
      nodes.push(node);
      node = walker.nextNode();
    }

    nodes.forEach((textNode) => {
      decorateTextNode(textNode, element, references, pattern);
    });
  }

  function decorateAll(root = document) {
    const scope = root && root.querySelectorAll ? root : document;
    const elements = Array.from(scope.querySelectorAll(RESPONSE_SELECTOR));

    if (scope.matches && scope.matches(RESPONSE_SELECTOR)) {
      elements.unshift(scope);
    }

    elements.forEach(decorate);
  }

  function clearDecorations(root = document) {
    const scope = root && root.querySelectorAll ? root : document;
    const elements = Array.from(scope.querySelectorAll(REFERENCE_SELECTOR));

    if (scope.matches && scope.matches(REFERENCE_SELECTOR)) {
      elements.unshift(scope);
    }

    const parents = new Set();
    elements.forEach((element) => {
      if (!element || !element.parentNode) return;
      parents.add(element.parentNode);
      element.replaceWith(
        document.createTextNode(element.textContent || "")
      );
    });

    parents.forEach((parent) => {
      if (parent && typeof parent.normalize === "function") {
        parent.normalize();
      }
    });
  }

  function refreshReferences() {
    invalidateReferenceCache();
    clearDecorations(document);
    decorateAll(document);
  }

  window.addEventListener(FILES_CHANGED_EVENT, refreshReferences);
  window.addEventListener(DELAYED_CHANGED_EVENT, refreshReferences);
  window.addEventListener(ATTACHMENT_UI_READY_EVENT, () => {
    decorateAll(document);
  });

  window.JinChatReferenceIds = {
    decorate,
    decorateAll,
    refresh: refreshReferences,
  };

  decorateAll(document);
})();
