(function () {
  "use strict";

  window.JinRuntime = window.JinRuntime || {};

  const storage = window.JinRuntime.storage;
  if (!storage) {
    throw new Error(
      "JinRuntime.storage must be loaded before runtime-l4-memory.js"
    );
  }

  const longTermFactsStorageKey = "jin.longTermFacts.v1";
  const idleTickIntervalMs = 15000;

  let lastIdleTickAt = 0;
  let idleTimer = null;

  function normalizeText(value) {
    return String(value || "")
      .replace(/\s+/g, " ")
      .trim();
  }

  function normalizeList(value) {
    const source = Array.isArray(value) ? value : [value];
    const result = [];
    const seen = new Set();

    source.forEach((item) => {
      const text = normalizeText(item);
      if (!text || seen.has(text)) {
        return;
      }
      seen.add(text);
      result.push(text);
    });

    return result;
  }

  function normalizeNumber(value, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallback;
  }

  function normalizeFact(value, pending) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return null;
    }

    const key = normalizeText(value.key);
    const factValue = normalizeText(value.value || value.content);
    if (!key || !factValue) {
      return null;
    }

    const idPrefix = pending ? "l4p_" : "l4_";
    const rawId = normalizeText(value.id);
    const generatedId = storage.buildFactsMemoryContentHash(
      `${key}\n${factValue}`
    ).replace(/^h/, "");

    return {
      id: rawId.startsWith(idPrefix) ? rawId : `${idPrefix}${generatedId}`,
      key,
      value: factValue,
      category: normalizeText(value.category || "other") || "other",
      mention_count: Math.max(
        1,
        Math.floor(normalizeNumber(value.mention_count, 1))
      ),
      created_at: normalizeText(value.created_at),
      updated_at: normalizeText(value.updated_at),
      source_session_ids: normalizeList(
        value.source_session_ids || value.source_session_id
      ),
      source_runtime_snapshot_ids: normalizeList(
        value.source_runtime_snapshot_ids || value.source_runtime_snapshot_id
      ),
      source_keys: normalizeList(value.source_keys),
      source_fact_ids: normalizeList(
        value.source_fact_ids || value.source_fact_id
      ),
    };
  }

  function normalizeFacts(values, pending) {
    const result = [];
    const seen = new Set();

    (Array.isArray(values) ? values : []).forEach((value) => {
      const fact = normalizeFact(value, pending);
      if (!fact || seen.has(fact.id)) {
        return;
      }
      seen.add(fact.id);
      result.push(fact);
    });

    return result;
  }

  function normalizeStore(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return {
        version: 1,
        revision: 0,
        updated_at: "",
        facts: [],
        pending_facts: [],
      };
    }

    return {
      version: 1,
      revision: Math.max(
        0,
        Math.floor(normalizeNumber(value.revision, 0))
      ),
      updated_at: normalizeText(value.updated_at),
      facts: normalizeFacts(value.facts, false),
      pending_facts: normalizeFacts(value.pending_facts, true),
    };
  }

  function readStore() {
    return normalizeStore(
      storage.readBrowserMemory(longTermFactsStorageKey)
    );
  }

  function countStoreItems(store) {
    return (
      (Array.isArray(store && store.facts) ? store.facts.length : 0)
      + (
        Array.isArray(store && store.pending_facts)
          ? store.pending_facts.length
          : 0
      )
    );
  }

  function writeStore(store) {
    const normalized = normalizeStore(store);
    storage.writeBrowserMemory(longTermFactsStorageKey, normalized);
    return normalized;
  }

  function getFacts() {
    return readStore().facts;
  }

  function getPendingFacts() {
    return readStore().pending_facts;
  }

  function sendIfOpen(payload) {
    if (typeof window.sendSocketMessage !== "function") {
      return false;
    }
    return window.sendSocketMessage(payload);
  }

  function buildFactsMemorySyncPayload() {
    return {
      type: "facts_memory_store_sync",
      records: storage.collectFactsMemoryRecords
        ? storage.collectFactsMemoryRecords()
        : [],
    };
  }

  function buildStoreSyncPayload() {
    return {
      type: "l4_memory_store_sync",
      store: readStore(),
    };
  }

  function syncFactsMemoryToRuntime() {
    return sendIfOpen(buildFactsMemorySyncPayload());
  }

  function syncLongTermMemoryToRuntime() {
    return sendIfOpen(buildStoreSyncPayload());
  }

  function applyFactsMemoryRecordsUpdate(payload) {
    const records = payload && Array.isArray(payload.records)
      ? payload.records
      : [];

    records.forEach((record) => {
      if (
        !record
        || typeof record !== "object"
        || Array.isArray(record)
        || !record.session_id
        || !record.signals
        || typeof record.signals !== "object"
        || Array.isArray(record.signals)
      ) {
        return;
      }

      const signals =
        storage.writeFactsMemory(record.signals, record.session_id);

      const removedFullyAnalyzedSnapshot =
        storage.clearFactsMemorySessionIfFullyAnalyzed
        && storage.clearFactsMemorySessionIfFullyAnalyzed(
          record.session_id,
          signals
        );

      if (
          removedFullyAnalyzedSnapshot
          && typeof window.refreshFactsMemoryAppendButtons === "function"
      ) {
        window.refreshFactsMemoryAppendButtons();
      }
    });

    if (
      window.JinRuntime.runtime
      && window.JinRuntime.runtime.renderRuntimeMemorySnapshot
    ) {
      window.JinRuntime.runtime.renderRuntimeMemorySnapshot();
    }
  }

  function applyServerUpdate(payload) {
    const incoming = normalizeStore(payload && payload.store);
    const local = readStore();

    if (incoming.revision < local.revision) {
      return local;
    }

    if (
      incoming.revision === local.revision
      && countStoreItems(local) > countStoreItems(incoming)
    ) {
      return local;
    }

    const store = writeStore(incoming);
    if (
      window.JinRuntime.runtime
      && window.JinRuntime.runtime.renderRuntimeMemorySnapshot
    ) {
      window.JinRuntime.runtime.renderRuntimeMemorySnapshot();
    }
    return store;
  }

  function requestFactDelete(factId) {
    const id = normalizeText(factId);
    if (!id) {
      return false;
    }
    return sendIfOpen({
      type: "l4_memory_delete_fact",
      fact_id: id,
    });
  }

  function maybeSendIdleTick() {
    if (
      typeof window.getJinUserIdleContext !== "function"
      || typeof window.isJinGenerationRunning !== "function"
      || window.isJinGenerationRunning()
    ) {
      return false;
    }

    const idleContext = window.getJinUserIdleContext();
    if (!idleContext) {
      return false;
    }

    const now = Date.now();
    if (now - lastIdleTickAt < idleTickIntervalMs) {
      return false;
    }

    const sent = sendIfOpen({
      type: "l4_memory_idle_tick",
      user_idle_seconds: Math.floor(
        Number(idleContext.user_idle_seconds || 0)
      ),
      records: storage.collectFactsMemoryRecords
        ? storage.collectFactsMemoryRecords()
        : [],
      store: readStore(),
    });

    if (sent) {
      lastIdleTickAt = now;
    }
    return sent;
  }

  function startIdleMonitor() {
    if (idleTimer !== null) {
      return;
    }
    idleTimer = window.setInterval(maybeSendIdleTick, 5000);
  }

  const api = {
    readStore,
    writeStore,
    normalizeStore,
    getFacts,
    getPendingFacts,
    buildFactsMemorySyncPayload,
    buildStoreSyncPayload,
    syncFactsMemoryToRuntime,
    syncLongTermMemoryToRuntime,
    applyFactsMemoryRecordsUpdate,
    applyServerUpdate,
    requestFactDelete,
    maybeSendIdleTick,
    startIdleMonitor,
  };

  window.JINRuntimeL4Memory = api;
  window.JinRuntime.l4Memory = api;
  window.syncFactsMemoryToRuntime = syncFactsMemoryToRuntime;
  window.syncLongTermMemoryToRuntime = syncLongTermMemoryToRuntime;

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startIdleMonitor, {
      once: true,
    });
  } else {
    window.setTimeout(startIdleMonitor, 0);
  }
}());
