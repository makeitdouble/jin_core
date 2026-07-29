function getRuntimeActionMessageId(data) {

  return String(
    data.runtime_message_id
    || data.message_id
    || ""
  ).trim();

}

function handleRuntimeActionGuardConfirmation(
  data
) {

  const action =
    String(
      data.action || ""
    ).toLowerCase();
  const text =
    buildRuntimeActionDisplayText(
      data,
      action,
      data.text || "",
      {
        fallbackToName: true,
      }
    );

  if (
    text.trim()
    && window.appendRuntimeAction
  ) {
    window.appendRuntimeAction(
      action,
      text,
      {
        id:
          data.counter_id
          || data.id
          || "",
        runtimeTurnId:
          data.runtime_turn_id || "",
        runtimeMessageId:
          getRuntimeActionMessageId(data),
        color:
          data.color
          || data.payload
          || "",
        reuseCompleted:
          action === "jin_color",
        aggregateMarkers: true,
        contextSnapshot:
          data.context || null,
        detail:
          data.detail || "",
        displayName:
          getRuntimeActionDisplayName(
            data,
            action
          ),
        sceneEffect:
          getRuntimeActionSceneEffect(
            data
          ),
        closeTag:
          isRuntimeActionCloseTag(
            data
          ),
        guardConfirmation: {
          confirmationId:
            data.confirmation_id || "",
          guard:
            data.guard || "",
          missingTriggers:
            Array.isArray(data.missing_triggers)
              ? data.missing_triggers
              : [],
          timeoutMs:
            Number(data.timeout_ms || 0),
        },
      }
    );
  }

  return;

}

function getRuntimeActionDisplayName(
  data,
  action
) {

  return (
    String(
      data.display_name
      || data.displayName
      || data.runtime_action
      || ""
    ).trim()
    || String(
      action || ""
    ).trim().toUpperCase()
  );

}

function getRuntimeActionSceneEffect(data) {

  return String(
    data.scene_effect
    || data.sceneEffect
    || ""
  ).trim().toLowerCase();

}

function isRuntimeActionCloseTag(data) {

  return (
    data.close_tag === true
    || data.closeTag === true
  );

}

function tryParseRuntimeActionJson(value) {

  if (typeof value !== "string") {
    return value;
  }

  const source =
    value.trim();

  if (
    !source
    || ![
      "{",
      "[",
    ].includes(source[0])
  ) {
    return value;
  }

  try {
    return JSON.parse(source);
  } catch (_error) {
    return value;
  }

}

function extractRuntimeActionObjectTitle(value) {

  const normalizedValue =
    tryParseRuntimeActionJson(
      value
    );

  if (
    !normalizedValue
    || typeof normalizedValue !== "object"
  ) {
    return "";
  }

  if (Array.isArray(normalizedValue)) {
    for (const item of normalizedValue) {
      const title =
        extractRuntimeActionObjectTitle(
          item
        );

      if (title) {
        return title;
      }
    }

    return "";
  }

  const directTitle =
    String(
      normalizedValue.title
      || normalizedValue.name
      || ""
    ).trim();

  if (directTitle) {
    return directTitle;
  }

  for (const key of [
    "report",
    "delayed_memory_report",
    "delayedMemoryReport",
    "delayed_memory_result",
    "asset_result",
    "skill_result",
    "runtime_todo_result",
  ]) {
    const nestedTitle =
      extractRuntimeActionObjectTitle(
        normalizedValue[key]
      );

    if (nestedTitle) {
      return nestedTitle;
    }
  }

  for (const item of Object.values(normalizedValue)) {
    const nestedTitle =
      extractRuntimeActionObjectTitle(
        item
      );

    if (nestedTitle) {
      return nestedTitle;
    }
  }

  return "";

}

function buildRuntimeActionDetail(
  data,
  closeTag
) {

  const explicitDetail =
    String(
      data.detail || ""
    ).trim();

  if (explicitDetail) {
    return explicitDetail;
  }

  const assetDetail =
    String(
      data.asset_result
      && (
        data.asset_result.detail
        || data.asset_result.error
      )
      || ""
    ).trim();

  if (assetDetail) {
    return assetDetail;
  }

  const objectTitle =
    extractRuntimeActionObjectTitle(
      data.delayed_memory_report
      || data.delayed_memory_result
      || data.asset_result
      || data.skill_result
      || data.runtime_todo_result
    );

  if (objectTitle) {
    return objectTitle;
  }

  return "";

}

function buildRuntimeActionDisplayText(
  data,
  action,
  text,
  options = {}
) {

  const normalizedAction =
    String(
      action || ""
    ).trim().toLowerCase();

  const explicitText =
    String(
      data.display_text
      || data.displayText
      || text
      || ""
    ).trim();

  if (
      explicitText
      && !(
        normalizedAction === "asset_action"
        && isGenericAssetActionDisplayText(
          explicitText,
          data,
          action
        )
      )
  ) {
    return explicitText;
  }

  if (normalizedAction === "asset_action") {
    const assetText =
      buildAssetActionRuntimeDisplayText(
        data,
        action
      );

    if (assetText) {
      return assetText;
    }
  }

  const payload =
    String(
      data.query
      || data.payload
      || (
        Array.isArray(data.payloads)
          ? data.payloads[data.payloads.length - 1]
          : ""
      )
      || ""
    ).trim();

  if (
    payload
    && !isRuntimeActionCloseTag(data)
  ) {
    return (
      `${getRuntimeActionDisplayName(data, action)}: `
      + payload
    );
  }

  return options.fallbackToName === true
    ? getRuntimeActionDisplayName(data, action)
    : "";

}

function readRuntimeActionObjectValue(
  value
) {

  const normalizedValue =
    tryParseRuntimeActionJson(
      value
    );

  return (
    normalizedValue
    && typeof normalizedValue === "object"
    && !Array.isArray(normalizedValue)
  )
    ? normalizedValue
    : null;

}

function collectAssetActionRuntimeObjects(
  data
) {

  const objects = [];

  [
    data.asset_result,
    data.assetResult,
    data.payload,
    data.query,
    data.detail,
  ].forEach((value) => {
    const objectValue =
      readRuntimeActionObjectValue(
        value
      );

    if (objectValue) {
      objects.push(
        objectValue
      );
    }
  });

  return objects;

}

function getAssetActionRuntimeField(
  data,
  field
) {

  for (const objectValue of collectAssetActionRuntimeObjects(data)) {
    const directValue =
      String(
        objectValue[field] || ""
      ).trim();

    if (directValue) {
      return directValue;
    }

    if (
        objectValue.args
        && typeof objectValue.args === "object"
        && !Array.isArray(objectValue.args)
    ) {
      const nestedValue =
        String(
          objectValue.args[field] || ""
        ).trim();

      if (nestedValue) {
        return nestedValue;
      }
    }
  }

  return "";

}

function normalizeAssetActionRuntimePath(
  path,
  assetAction
) {

  let normalizedPath =
    String(
      path || ""
    ).trim().replace(
      /\\/g,
      "/"
    );

  if (!normalizedPath) {
    return "";
  }

  if (assetAction === "run_document_reader") {
    return normalizedPath;
  }

  if (
      [
        "create_wildcard_file",
        "append_wildcard_file",
      ].includes(assetAction)
  ) {
    if (!normalizedPath.startsWith("assets/wildcards/")) {
      normalizedPath =
        `assets/wildcards/${normalizedPath}`;
    }
    if (!/\.txt$/i.test(normalizedPath)) {
      normalizedPath =
        `${normalizedPath}.txt`;
    }
    return normalizedPath;
  }

  if (!normalizedPath.startsWith("assets/")) {
    normalizedPath =
      `assets/${normalizedPath}`;
  }

  return normalizedPath;

}

function buildAssetActionRuntimeDisplayText(
  data,
  action
) {

  const assetAction =
    getAssetActionRuntimeField(
      data,
      "action"
    )
    || (
      String(data.error || "").trim()
        ? "invalid payload"
        : ""
    );

  if (!assetAction) {
    return "";
  }

  const path =
    normalizeAssetActionRuntimePath(
      getAssetActionRuntimeField(
        data,
        "path"
      )
      || getAssetActionRuntimeField(
        data,
        "output_file"
      )
      || getAssetActionRuntimeField(
        data,
        "attachment"
      ),
      assetAction
    );

  return (
    `${getRuntimeActionDisplayName(data, action)}: ${assetAction}`
    + (
      path
        ? ` - ${path}`
        : ""
    )
  );

}

function isGenericAssetActionDisplayText(
  text,
  data,
  action
) {

  const normalizedText =
    String(
      text || ""
    ).trim().toUpperCase();
  const displayName =
    getRuntimeActionDisplayName(
      data,
      action
    ).toUpperCase();

  return (
    normalizedText === displayName
    || normalizedText === "ASSET_ACTION"
    || normalizedText === "ACTION: ASSET_ACTION"
  );

}

const PAYLOAD_DISTINCT_RUNTIME_ACTIONS = new Set([
  "save_active_memory",
  "resolve_active_memory",
  "save_delayed_memory_content",
  "append_delayed_memory",
  "remove_delayed_memory",
]);

function normalizeRuntimeActionPayloadIdentity(value) {

  if (
    value
    && typeof value === "object"
  ) {
    const title =
      String(
        value.title
        || value.name
        || value.id
        || ""
      ).trim();

    if (title) {
      return title;
    }

    try {
      return JSON.stringify(value);
    } catch (_error) {
      return "";
    }
  }

  return String(
    value || ""
  ).trim();

}

function runtimeActionDistinctPayloads(data) {

  const payloads = Array.isArray(data.raw_payloads)
    ? data.raw_payloads
    : (
      Array.isArray(data.payloads)
        ? data.payloads
        : []
    );

  const identities = [];

  payloads.forEach((payload) => {
    const identity =
      normalizeRuntimeActionPayloadIdentity(
        payload
      );

    if (
      identity
      && !identities.includes(identity)
    ) {
      identities.push(
        identity
      );
    }
  });

  return identities;

}

function shouldSplitPayloadDistinctRuntimeAction(
  action,
  data
) {

  if (
    action === "jin_color"
    || !PAYLOAD_DISTINCT_RUNTIME_ACTIONS.has(action)
  ) {
    return false;
  }

  return runtimeActionDistinctPayloads(
    data
  ).length > 1;

}

function handleRuntimeAction(
  data
) {

  const action =
    String(
      data.action || ""
    ).toLowerCase();

  const status =
    String(
      data.status || ""
    ).toLowerCase();

  const runtimeTurnId =
    String(
      data.runtime_turn_id || ""
    ).trim();

  const runtimeMessageId =
    getRuntimeActionMessageId(data);

  const text =
    String(
      data.text || ""
    );

  const guardConfirmationId =
    String(
      data.confirmation_id
      || data.guard_confirmation_id
      || ""
    ).trim();

  const cancelledByUser =
    status === "failed"
    && Boolean(guardConfirmationId)
    && (
      /\bcancelled\s*$/i.test(
        text.trim()
      )
      || /^user_(?:did_not_confirm|did_not_explicitly_request|rejected)/i.test(
        String(data.error || "").trim()
      )
      || /^user_(?:did_not_confirm|did_not_explicitly_request|rejected)/i.test(
        text.trim()
      )
    );
  const abortedByUser =
    status === "aborted";
  const terminalStatus =
    [
      "completed",
      "complete",
      "done",
      "failed",
      "interrupted",
      "aborted",
      "counter_final",
    ].includes(status);
  const forceCompletePendingL3 =
    action === "save_session"
    && terminalStatus
    && ![
      "completed",
      "complete",
      "done",
    ].includes(status);

  if (
    (
      cancelledByUser
      || abortedByUser
    )
    && window.markSessionActionCancelled
  ) {
    window.markSessionActionCancelled(
      action,
      data.color || data.payload || "",
      {
        createdAfter:
          abortedByUser
            ? 0
            : undefined,
      }
    );
  }

  const displayText =
    action === "resolve_active_memory"
      ? buildResolveActiveMemoryRuntimeActionText(
        data,
        text
      )
      : buildRuntimeActionDisplayText(
        data,
        action,
        text,
        {
          fallbackToName:
            ![
              "completed",
              "complete",
              "done",
            ].includes(status),
        }
      );

  const displayName =
    getRuntimeActionDisplayName(
      data,
      action
    );

  const sceneEffect =
    getRuntimeActionSceneEffect(
      data
    );

  const closeTag =
    isRuntimeActionCloseTag(
      data
    );

  const runtimeDetail =
    buildRuntimeActionDetail(
      data,
      closeTag
    );

  const markerCount = Math.max(
    0,
    Number.parseInt(
      data.marker_count || 0,
      10
    ) || 0
  );

  const counterOnly =
    data.counter_only === true;

  const counterFinal =
    data.counter_final === true
    || status === "counter_final";
  const terminalFailure =
    [
      "failed",
      "interrupted",
      "aborted",
    ].includes(status);

  const splitPayloadDistinctMarkers =
    shouldSplitPayloadDistinctRuntimeAction(
      action,
      data
    );

  const aggregateMarkers =
    !splitPayloadDistinctMarkers
    && (
      data.aggregate_markers === true
      || counterOnly
      || markerCount > 0
      || Boolean(
        window.hasActiveRuntimeActionCounter
        && window.hasActiveRuntimeActionCounter(
          action,
          runtimeTurnId,
          runtimeMessageId
        )
      )
    );
  const displayCounterOnly =
    counterOnly
    && aggregateMarkers;
  const displayMarkerCount =
    aggregateMarkers
      ? markerCount
      : 0;

  const completeImmediately =
    [
      "completed",
      "complete",
      "done",
    ].includes(status)
    && !counterOnly
    && PAYLOAD_DISTINCT_RUNTIME_ACTIONS.has(action);

  const actionDisplayId =
    data.counter_id
    || data.id
    || "";

  const pendingUntilL3 =
    action === "save_session"
    && ![
      "failed",
      "interrupted",
      "aborted",
    ].includes(status)
    && forceCompletePendingL3 !== true;

  const counterPayloads =
    Array.isArray(data.payloads)
      ? data.payloads
      : [];

  const shouldLogRuntimeAction =
    ![
      "summary",
      "started",
      "start",
      "pending",
      "running",
      "counter_final",
    ].includes(
      status
    );

  if (action === "jin_color") {
    const color =
      String(
        data.color
        || data.payload
        || ""
      );
    const actionId =
      actionDisplayId;
    const colorApplied =
      (
        status === "completed"
        || status === "complete"
        || status === "done"
      )
      && Boolean(color);

    if (
      displayText.trim()
      && window.appendRuntimeAction
    ) {
      window.appendRuntimeAction(
        action,
        displayText,
        {
          id: actionId,
          runtimeTurnId,
          runtimeMessageId,
          color,
          detail: color,
          displayName,
          sceneEffect,
          closeTag,
          reuseCompleted:
            counterOnly,
          reviveCompleted:
            !counterFinal,
          aggregateMarkers,
          counterOnly:
            displayCounterOnly,
          markerCount:
            displayMarkerCount,
          colors:
            Array.isArray(data.colors)
              ? data.colors
              : counterPayloads,
          contextSnapshot:
            data.context || null,
          guardConfirmationId,
          cancelled:
            (
              cancelledByUser
              || abortedByUser
            )
              ? true
              : undefined,
          preserveLabel:
            cancelledByUser,
          fallbackToLatestActive:
            abortedByUser,
        }
      );
    }

    if (
      colorApplied
      && window.JinRuntime
      && window.JinRuntime.avatar
      && typeof window.JinRuntime.avatar.setCenterColor === "function"
    ) {
      window.JinRuntime.avatar.setCenterColor(
        color
      );
    }

    if (
      shouldLogRuntimeAction
      && window.log_internal_action
    ) {
      window.log_internal_action(
        action,
        data
      );
    }

    if (
      (
        colorApplied
        || counterFinal
        || (
          !aggregateMarkers
          && (
            status === "failed"
            || status === "interrupted"
            || status === "aborted"
          )
        )
      )
      && window.fadeRuntimeAction
    ) {
      window.setTimeout(
        () => {
          window.fadeRuntimeAction(
            action,
            {
              id: actionId,
              runtimeTurnId,
              runtimeMessageId,
              sceneEffect,
              fallbackToLatestActive:
                colorApplied,
            }
          );
        },
        60
      );
    }

    return;
  }

  if (
    action === "save_active_memory"
    && data.active_memory
    && window.JinRuntime
    && window.JinRuntime.runtime
    && window.JinRuntime.runtime.appendActiveMemoryRecords
  ) {
    window.JinRuntime.runtime.appendActiveMemoryRecords([
      data.active_memory
    ]);

  }

  if (
    action === "resolve_active_memory"
    && data.id
    && window.JinRuntime
    && window.JinRuntime.runtime
    && window.JinRuntime.runtime.removeActiveMemoryRecordById
  ) {
    window.JinRuntime.runtime.removeActiveMemoryRecordById(
      data.id
    );
  }

  if (
    action === "save_delayed_memory_content"
    && data.delayed_memory_report
    && window.JinRuntime
    && window.JinRuntime.runtime
    && window.JinRuntime.runtime.appendDelayedMemoryReports
  ) {
    window.JinRuntime.runtime.appendDelayedMemoryReports(
      data.delayed_memory_report
    );
  }

  if (
    action === "append_delayed_memory"
    && data.delayed_memory_result
    && data.delayed_memory_result.report
    && data.delayed_memory_result.id
    && window.JinRuntime
    && window.JinRuntime.runtime
    && window.JinRuntime.runtime.appendDelayedMemoryReports
  ) {
    window.JinRuntime.runtime.appendDelayedMemoryReports({
      [data.delayed_memory_result.id]:
        data.delayed_memory_result.report,
    });
  }

  if (
    status === "completed"
    || status === "complete"
    || status === "done"
  ) {
    if (displayText.trim()) {
      const appended = appendRuntimeAction(
        action,
        displayText,
        {
          id: actionDisplayId,
          runtimeTurnId,
          runtimeMessageId,
          guardConfirmationId,
          updateExisting: true,
          aggregateMarkers,
          counterOnly:
            displayCounterOnly,
          markerCount:
            displayMarkerCount,
          reuseCompleted: false,
          contextSnapshot:
            data.context || null,
          assetResult:
            data.asset_result || null,
          delayedMemoryReportId:
            data.delayed_memory_report_id || "",
          delayedMemoryReport:
            data.delayed_memory_report || null,
          completed:
            !aggregateMarkers
            || completeImmediately,
          detail: runtimeDetail,
          displayName,
          sceneEffect,
          closeTag,
          pendingUntilL3,
          forceCompletePendingL3,
        }
      );

      if (
        appended
        && window.log_internal_action
      ) {
        window.log_internal_action(
          action,
          data
        );
      }
    }

    if (
      (
        !aggregateMarkers
        || completeImmediately
      )
      && window.fadeRuntimeAction
    ) {
      window.fadeRuntimeAction(
        action,
        {
          id: actionDisplayId,
          runtimeTurnId,
          runtimeMessageId,
          sceneEffect,
        }
      );
    }

    return;
  }

  if (
    counterOnly
    && splitPayloadDistinctMarkers
  ) {
    return;
  }

  if (!displayText.trim()) {
    return;
  }

  const appended = appendRuntimeAction(
    action,
    displayText,
    {
      id: actionDisplayId,
      runtimeTurnId,
      runtimeMessageId,
      guardConfirmationId,
      aggregateMarkers,
      counterOnly:
        displayCounterOnly,
      markerCount:
        displayMarkerCount,
      reuseCompleted:
        counterOnly,
      reviveCompleted:
        !counterFinal,
      cancelled:
        (
          cancelledByUser
          || abortedByUser
        )
          ? true
          : undefined,
      preserveLabel:
        cancelledByUser
        || (
          displayCounterOnly
          && closeTag
        ),
      fallbackToLatestActive:
        abortedByUser
        || status === "failed"
        || status === "interrupted",
      contextSnapshot:
        data.context || null,
      assetResult:
        data.asset_result || null,
      detail: runtimeDetail,
      displayName,
      sceneEffect,
      closeTag,
      pendingUntilL3,
      forceCompletePendingL3,
    }
  );

  if (
    appended
    && shouldLogRuntimeAction
    && window.log_internal_action
  ) {
    window.log_internal_action(
      action,
      data
    );
  }

  if (
    (
      counterFinal
      || terminalFailure
    )
    && window.fadeRuntimeAction
  ) {
    window.fadeRuntimeAction(
      action,
      {
        id: actionDisplayId,
        runtimeTurnId,
        runtimeMessageId,
        sceneEffect,
        forceCompletePendingL3,
        fallbackToLatestActive:
          terminalFailure,
      }
    );
  }

  return;

}

registerSocketMessageHandler(
  "runtime_action_guard_confirmation",
  handleRuntimeActionGuardConfirmation
);

registerSocketMessageHandler(
  "runtime_action",
  handleRuntimeAction
);
