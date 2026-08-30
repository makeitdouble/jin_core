(function () {
  "use strict";

  const root = window.JinRuntime = window.JinRuntime || {};

  function normalizeCitationIdentity(value) {
    const source = String(value || "");
    const normalized = source.normalize
      ? source.normalize("NFKC")
      : source;

    return normalized
      .toLowerCase()
      .replace(/\s+/g, " ")
      .trim();
  }

  function buildCitationRecordIdentity(
    id,
    key,
    value
  ) {
    const parts = [
      id,
      key,
      value,
    ].map(normalizeCitationIdentity);

    if (parts.some(part => !part)) {
      return "";
    }

    // Keep the full normalized tuple instead of a lossy short hash. This is
    // still a compact identity token in the UI, but cannot collapse two L-T
    // records merely because they share the same human-readable key.
    return JSON.stringify(parts);
  }

  function buildAvatarMemoryHoverId(
    kind,
    id
  ) {
    const normalizedKind =
      normalizeCitationIdentity(kind);
    const normalizedId =
      normalizeCitationIdentity(id);

    if (!normalizedKind || !normalizedId) {
      return "";
    }

    return `${normalizedKind}:${normalizedId}`;
  }

  root.normalizeCitationIdentity =
    normalizeCitationIdentity;
  root.buildCitationRecordIdentity =
    buildCitationRecordIdentity;
  root.buildAvatarMemoryHoverId =
    buildAvatarMemoryHoverId;
}());
