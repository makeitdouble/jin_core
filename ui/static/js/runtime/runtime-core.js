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

  root.normalizeCitationIdentity =
    normalizeCitationIdentity;
}());
