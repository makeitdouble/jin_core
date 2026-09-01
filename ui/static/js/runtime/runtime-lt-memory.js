(function () {
  "use strict";

  window.JinRuntime = window.JinRuntime || {};

  const storage = window.JinRuntime.storage;
  if (!storage) {
    throw new Error(
      "JinRuntime.storage must be loaded before runtime-lt-memory.js"
    );
  }

  const longTermFactsStorageKey = "jin.longTermFacts.v1";

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

  function normalizeFactId(value, pending) {
    const text = normalizeText(value).toUpperCase();
    const pattern = pending ? /^PF([1-9]\d*)$/ : /^F([1-9]\d*)$/;
    const match = text.match(pattern);
    if (!match) {
      return "";
    }
    return `${pending ? "PF" : "F"}${Number(match[1])}`;
  }

  function factIdNumber(value, pending) {
    const id = normalizeFactId(value, pending);
    if (!id) {
      return 0;
    }
    return Number(id.slice(pending ? 2 : 1)) || 0;
  }

  function normalizeFact(value, pending, assignedId) {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      return null;
    }

    const key = normalizeText(value.key);
    const factValue = normalizeText(value.value || value.content);
    if (!key || !factValue) {
      return null;
    }

    const id = normalizeFactId(assignedId || value.id, pending);
    if (!id) {
      return null;
    }

    return {
      id,
      key,
      value: factValue,
      category: normalizeText(value.category || "other") || "other",
      mention_count: Math.max(
        1,
        Math.floor(normalizeNumber(value.mention_count, 1))
      ),
      last_mentioned_at: normalizeText(
        value.last_mentioned_at || value.updated_at || value.created_at
      ),
      created_at: normalizeText(value.created_at),
      updated_at: normalizeText(value.updated_at),
      source_fact_ids: normalizeList(
        value.source_fact_ids || value.source_fact_id
      ),
    };
  }

  function migrateStoreIds(value) {
    const source = value && typeof value === "object" && !Array.isArray(value)
      ? value
      : {};
    const rawFacts = Array.isArray(source.facts) ? source.facts : [];
    const rawPending = Array.isArray(source.pending_facts)
      ? source.pending_facts
      : [];
    const rawDeleted = Array.isArray(source.deleted_fact_ids)
      ? source.deleted_fact_ids
      : [];
    const rawIgnoredPending = Array.isArray(source.ignored_pending_fact_ids)
      ? source.ignored_pending_fact_ids
      : [];

    const usedFacts = new Set();
    const usedPending = new Set();
    rawFacts.forEach((fact) => {
      const number = factIdNumber(fact && fact.id, false);
      if (number) usedFacts.add(number);
    });
    rawPending.forEach((fact) => {
      const number = factIdNumber(fact && fact.id, true);
      if (number) usedPending.add(number);
    });

    let nextFact = Math.max(
      1,
      Math.floor(normalizeNumber(source.next_fact_id, 1)),
      Math.max(0, ...usedFacts) + 1
    );
    let nextPending = Math.max(
      1,
      Math.floor(normalizeNumber(source.next_pending_fact_id, 1)),
      Math.max(0, ...usedPending) + 1
    );
    const idMap = new Map();
    let migrated = Number(source.version || 0) < 2;

    function allocate(rawId, pending) {
      const text = normalizeText(rawId);
      const current = normalizeFactId(text, pending);
      if (current) {
        return current;
      }
      if (text && idMap.has(text)) {
        return idMap.get(text);
      }

      const legacy = pending
        ? /^ltp_[a-z0-9_-]+$/i.test(text)
        : /^lt_[a-z0-9_-]+$/i.test(text);
      if (text && !legacy) {
        return "";
      }

      const used = pending ? usedPending : usedFacts;
      let number = pending ? nextPending : nextFact;
      while (used.has(number)) number += 1;
      used.add(number);
      const id = `${pending ? "PF" : "F"}${number}`;
      if (pending) nextPending = number + 1;
      else nextFact = number + 1;
      if (text) idMap.set(text, id);
      migrated = true;
      return id;
    }

    const facts = [];
    rawFacts.forEach((rawFact) => {
      if (!rawFact || typeof rawFact !== "object" || Array.isArray(rawFact)) {
        return;
      }
      const oldId = normalizeText(rawFact.id);
      const id = allocate(oldId, false) || allocate("", false);
      if (oldId && oldId !== id) idMap.set(oldId, id);
      const fact = normalizeFact(rawFact, false, id);
      if (fact) facts.push(fact);
    });

    const pendingFacts = [];
    rawPending.forEach((rawFact) => {
      if (!rawFact || typeof rawFact !== "object" || Array.isArray(rawFact)) {
        return;
      }
      const oldId = normalizeText(rawFact.id);
      const id = allocate(oldId, true) || allocate("", true);
      if (oldId && oldId !== id) idMap.set(oldId, id);
      const fact = normalizeFact(rawFact, true, id);
      if (fact) pendingFacts.push(fact);
    });

    const deletedFactIds = [];
    rawDeleted.forEach((rawId) => {
      const text = normalizeText(rawId);
      const id = normalizeFactId(text, false)
        || idMap.get(text)
        || (/^lt_[a-z0-9_-]+$/i.test(text) ? allocate(text, false) : "");
      if (id && !deletedFactIds.includes(id)) deletedFactIds.push(id);
    });

    const ignoredPendingFactIds = [];
    rawIgnoredPending.forEach((rawId) => {
      const id = normalizeFactId(rawId, true);
      if (id && !ignoredPendingFactIds.includes(id)) {
        ignoredPendingFactIds.push(id);
      }
    });

    function remapSourceIds(fact) {
      fact.source_fact_ids = normalizeList(fact.source_fact_ids)
        .map((rawId) => {
          return normalizeFactId(rawId, true)
            || normalizeFactId(rawId, false)
            || idMap.get(rawId)
            || (/^ltp_[a-z0-9_-]+$/i.test(rawId) ? allocate(rawId, true) : "")
            || (/^lt_[a-z0-9_-]+$/i.test(rawId) ? allocate(rawId, false) : "");
        })
        .filter(Boolean);
    }
    facts.forEach(remapSourceIds);
    pendingFacts.forEach(remapSourceIds);

    return {
      version: 2,
      revision: Math.max(
        0,
        Math.floor(normalizeNumber(source.revision, 0))
      ) + (migrated ? 1 : 0),
      updated_at: normalizeText(source.updated_at),
      facts,
      pending_facts: pendingFacts,
      deleted_fact_ids: deletedFactIds,
      ignored_pending_fact_ids: ignoredPendingFactIds,
      next_fact_id: nextFact,
      next_pending_fact_id: nextPending,
    };
  }

  function normalizeStore(value) {
    const migrated = migrateStoreIds(value);
    const seenFacts = new Set();
    const seenPending = new Set();

    migrated.facts = migrated.facts.filter((fact) => {
      if (seenFacts.has(fact.id)) return false;
      seenFacts.add(fact.id);
      return !migrated.deleted_fact_ids.includes(fact.id);
    });
    const processedPendingIds = new Set();
    migrated.facts.forEach((fact) => {
      normalizeList(fact.source_fact_ids).forEach((sourceId) => {
        const pendingId = normalizeFactId(sourceId, true);
        if (pendingId) processedPendingIds.add(pendingId);
      });
    });
    normalizeList(migrated.ignored_pending_fact_ids).forEach((sourceId) => {
      const pendingId = normalizeFactId(sourceId, true);
      if (pendingId) processedPendingIds.add(pendingId);
    });
    migrated.pending_facts = migrated.pending_facts.filter((fact) => {
      if (seenPending.has(fact.id) || processedPendingIds.has(fact.id)) {
        return false;
      }
      seenPending.add(fact.id);
      return true;
    });

    return migrated;
  }

  function getLongTermFactsStorageKey() {
    return longTermFactsStorageKey;
  }

  function readAnonymousStore() {
    const anonymousMode =
      window.JinRuntime
      && window.JinRuntime.anonymousMode;
    const snapshot = (
      anonymousMode
      && typeof anonymousMode.readSnapshot === "function"
    )
      ? anonymousMode.readSnapshot()
      : null;

    return snapshot && snapshot.long_term_memory;
  }

  function writeAnonymousStore(store) {
    const anonymousMode =
      window.JinRuntime
      && window.JinRuntime.anonymousMode;

    return Boolean(
      anonymousMode
      && typeof anonymousMode.updateSnapshotField === "function"
      && anonymousMode.updateSnapshotField(
        "long_term_memory",
        store
      )
    );
  }

  function readStore() {
    const isolated = Boolean(
      storage.shouldIsolateAnonymousStorage
      && storage.shouldIsolateAnonymousStorage()
    );

    return normalizeStore(
      isolated
        ? readAnonymousStore()
        : storage.readBrowserMemory(getLongTermFactsStorageKey())
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
    const isolated = Boolean(
      storage.shouldIsolateAnonymousStorage
      && storage.shouldIsolateAnonymousStorage()
    );

    if (isolated) {
      writeAnonymousStore(normalized);
    } else {
      storage.writeBrowserMemory(
        getLongTermFactsStorageKey(),
        normalized
      );
    }

    return normalized;
  }

  function syncLTMemoryStateToAvatar() {
    if (
      window.JinRuntime.avatar
      && typeof window.JinRuntime.avatar.syncLTMemoryState === "function"
    ) {
      return window.JinRuntime.avatar.syncLTMemoryState();
    }

    if (
      window.JinRuntime.avatar
      && typeof window.JinRuntime.avatar.refresh === "function"
    ) {
      window.JinRuntime.avatar.refresh();
      return true;
    }

    return false;
  }

  function getFacts() {
    return readStore().facts;
  }

  function getArchivedFactIdSet() {
    const reports =
      storage && typeof storage.readDelayedMemoryReports === "function"
        ? storage.readDelayedMemoryReports()
        : {};

    if (
      !reports
      || typeof reports !== "object"
      || Array.isArray(reports)
    ) {
      return new Set();
    }

    const archivedIds = new Set();
    const anchorIds = new Set();

    Object.entries(reports).forEach(([reportId, report]) => {
      if (
        !report
        || typeof report !== "object"
        || Array.isArray(report)
      ) {
        return;
      }

      normalizeList(report.anchor_fact_ids).forEach((rawId) => {
        const factId = normalizeFactId(rawId, false);
        if (factId) {
          anchorIds.add(factId);
        }
      });

      [
        report.facts_ids,
        report.absorbed_fact_ids,
        report.long_term_facts_ids,
      ].forEach((rawIds) => {
        normalizeList(rawIds).forEach((rawId) => {
          const factId = normalizeFactId(rawId, false);
          if (factId) {
            archivedIds.add(factId);
          }
        });
      });

    });

    anchorIds.forEach((factId) => {
      archivedIds.delete(factId);
    });
    return archivedIds;
  }

  function getArchivedFactIds() {
    return Array.from(getArchivedFactIdSet())
      .sort((left, right) => String(left).localeCompare(String(right)));
  }

  function isArchivedFact(factId) {
    const normalizedId =
      normalizeFactId(factId, false);

    return Boolean(
      normalizedId
      && getArchivedFactIdSet().has(normalizedId)
    );
  }

  function factMatchesArchivedIds(fact, archivedIds) {
    if (
      !fact
      || typeof fact !== "object"
      || Array.isArray(fact)
      || !archivedIds
      || archivedIds.size < 1
    ) {
      return false;
    }

    return [
      fact.id,
      ...normalizeList(fact.source_fact_ids),
    ].some((rawId) => {
      const factId =
        normalizeFactId(rawId, false);

      return Boolean(
        factId
        && archivedIds.has(factId)
      );
    });
  }

  function getVisibleFacts() {
    const archivedIds =
      getArchivedFactIdSet();

    return getFacts().filter((fact) => (
      !factMatchesArchivedIds(fact, archivedIds)
    ));
  }

  function getFactsWithArchiveState() {
    const archivedIds =
      getArchivedFactIdSet();

    return getFacts().map((fact) => {
      const archived =
        factMatchesArchivedIds(fact, archivedIds);

      return {
        ...fact,
        archived,
        hidden_from_context: archived,
      };
    });
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
      type: "lt_memory_store_sync",
      store: readStore(),
    };
  }

  function syncFactsMemoryToRuntime() {
    return sendIfOpen(buildFactsMemorySyncPayload());
  }

  function syncLongTermMemoryToRuntime() {
    return sendIfOpen(buildStoreSyncPayload());
  }

  function deleteFactLocally(factId) {
    const id =
      normalizeFactId(factId, false);

    if (!id) {
      return false;
    }

    const store =
      readStore();
    const facts =
      (Array.isArray(store.facts) ? store.facts : [])
        .filter(fact => fact && fact.id !== id);
    const deletedFactIds =
      normalizeList(store.deleted_fact_ids)
        .map(rawId => normalizeFactId(rawId, false))
        .filter(Boolean);
    const removedFact =
      facts.length !== (Array.isArray(store.facts) ? store.facts.length : 0);

    if (!deletedFactIds.includes(id)) {
      deletedFactIds.push(id);
    }

    if (!removedFact && store.deleted_fact_ids.includes(id)) {
      return false;
    }

    writeStore({
      ...store,
      facts,
      deleted_fact_ids: deletedFactIds,
      revision: Math.max(
        0,
        Math.floor(normalizeNumber(store.revision, 0))
      ) + 1,
      updated_at: new Date().toISOString(),
    });

    if (
      window.JinRuntime.runtime
      && window.JinRuntime.runtime.renderRuntimeMemorySnapshot
    ) {
      window.JinRuntime.runtime.renderRuntimeMemorySnapshot();
    }
    syncLTMemoryStateToAvatar();

    return true;
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
    syncLTMemoryStateToAvatar();
    return store;
  }

  function requestFactDelete(factId) {
    const id = normalizeText(factId);
    if (!id) {
      return false;
    }
    const sent = sendIfOpen({
      type: "lt_memory_delete_fact",
      fact_id: id,
    });
    if (sent && deleteFactLocally(id)) {
      syncLongTermMemoryToRuntime();
    }
    return sent;
  }

  function requestFactRestore(fact) {
    const normalized = normalizeFact(
      fact,
      false
    );
    if (!normalized) {
      return false;
    }
    const restoreMeta =
      fact
      && typeof fact === "object"
      && !Array.isArray(fact)
      && fact._restore_meta
      && typeof fact._restore_meta === "object"
        ? fact._restore_meta
        : null;

    return sendIfOpen({
      type: "lt_memory_restore_fact",
      fact: restoreMeta
        ? {
            ...normalized,
            _restore_meta: restoreMeta,
          }
        : normalized,
    });
  }

  const api = {
    readStore,
    writeStore,
    normalizeStore,
    getFacts,
    getArchivedFactIds,
    isArchivedFact,
    getVisibleFacts,
    getFactsWithArchiveState,
    getPendingFacts,
    buildFactsMemorySyncPayload,
    buildStoreSyncPayload,
    syncFactsMemoryToRuntime,
    syncLongTermMemoryToRuntime,
    applyFactsMemoryRecordsUpdate,
    applyServerUpdate,
    deleteFactLocally,
    requestFactDelete,
    requestFactRestore,
  };

  window.JINRuntimeLTMemory = api;
  window.JinRuntime.ltMemory = api;
  window.syncFactsMemoryToRuntime = syncFactsMemoryToRuntime;
  window.syncLongTermMemoryToRuntime = syncLongTermMemoryToRuntime;
}());
