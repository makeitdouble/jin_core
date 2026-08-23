// Temporary UI-only switch. Runtime parsing, execution, avatar updates and
// logger entries stay active; flip this to true to restore the two chat bubbles.
const ENABLE_JIN_VISUAL_ACTION_BUBBLES = false;
const THINK_RUNTIME_CITATION_HIGHLIGHT_EVENT =
  "jin:think-runtime-citation-highlight";

const JIN_VISUAL_SEQUENCE_ACTIONS = new Set([
  "jin_color",
  "jin_size",
  "jin_speed",
  "jin_position",
]);
const JIN_VISUAL_SEQUENCE_COLOR_MS = 160;
const JIN_VISUAL_SEQUENCE_SIZE_MS = 320;
const JIN_VISUAL_SEQUENCE_CROSS_STAGE_RATIO = 0.58;
const jinVisualSequenceBuffers = new Map();
let jinVisualSequencePlayback = Promise.resolve();

function waitForJinVisualSequence(ms) {
  const delay = Math.max(0, Number(ms) || 0);

  if (!delay) {
    return Promise.resolve();
  }

  return new Promise((resolve) => {
    window.setTimeout(resolve, delay);
  });
}

function applyJinVisualSequenceCommand(command) {
  if (
    !command
    || !JIN_VISUAL_SEQUENCE_ACTIONS.has(command.action)
  ) {
    return { action: "", duration: 0 };
  }

  if (command.action === "jin_color") {
    const applied =
      Boolean(
        command.color
        && window.JinRuntime
        && window.JinRuntime.avatar
        && typeof window.JinRuntime.avatar.setCenterColor === "function"
        && window.JinRuntime.avatar.setCenterColor(command.color)
      );

    return {
      action: command.action,
      duration: applied ? JIN_VISUAL_SEQUENCE_COLOR_MS : 0,
    };
  }

  if (command.action === "jin_speed") {
    if (
      Number.isFinite(command.speed)
      && command.speed > 0
      && window.JinPanels
      && typeof window.JinPanels.setJinMoveSpeed === "function"
    ) {
      window.JinPanels.setJinMoveSpeed(command.speed);
    }

    return { action: command.action, duration: 0 };
  }

  if (command.action === "jin_size") {
    const result =
      window.JinPanels
      && typeof window.JinPanels.setPendingJinSize === "function"
        ? window.JinPanels.setPendingJinSize({
          size: command.size,
          width: command.width,
          height: command.height,
        })
        : null;

    return {
      action: command.action,
      duration:
        result && Number.isFinite(Number(result.duration))
          ? Math.max(0, Number(result.duration))
          : (result ? JIN_VISUAL_SEQUENCE_SIZE_MS : 0),
    };
  }

  const result =
    window.JinPanels
    && typeof window.JinPanels.setPendingJinPosition === "function"
      ? window.JinPanels.setPendingJinPosition({
        x: command.x,
        y: command.y,
      })
      : null;

  return {
    action: command.action,
    duration:
      result && Number.isFinite(Number(result.duration))
        ? Math.max(0, Number(result.duration))
        : 0,
  };
}

function resolveJinVisualSequenceStageDelay(current, next) {
  const duration = Math.max(
    0,
    Number(current && current.duration) || 0
  );

  if (!duration) {
    return 0;
  }

  if (
    !next
    || !next.action
    || next.action === current.action
  ) {
    return duration;
  }

  return Math.max(
    48,
    duration * JIN_VISUAL_SEQUENCE_CROSS_STAGE_RATIO
  );
}

async function playJinVisualSequence(commands) {
  const sequence =
    Array.isArray(commands)
      ? commands.filter(Boolean)
      : [];

  for (let index = 0; index < sequence.length; index += 1) {
    const current =
      applyJinVisualSequenceCommand(sequence[index]);
    const next = sequence[index + 1] || null;
    const delay =
      resolveJinVisualSequenceStageDelay(current, next);

    if (delay > 0) {
      await waitForJinVisualSequence(delay);
    }
  }
}

function queueJinVisualSequenceCommand(data, command) {
  const sequenceId =
    String(data.jin_sequence_id || "").trim();
  const sequenceIndex =
    Number.parseInt(data.jin_sequence_index, 10);
  const sequenceCount =
    Number.parseInt(data.jin_sequence_count, 10);

  if (
    !sequenceId
    || !Number.isInteger(sequenceIndex)
    || sequenceIndex < 0
    || !Number.isInteger(sequenceCount)
    || sequenceCount < 1
    || sequenceIndex >= sequenceCount
  ) {
    return false;
  }

  let buffer = jinVisualSequenceBuffers.get(sequenceId);

  if (!buffer) {
    buffer = {
      count: sequenceCount,
      commands: new Array(sequenceCount),
      received: 0,
    };
    jinVisualSequenceBuffers.set(sequenceId, buffer);
  }

  if (!buffer.commands[sequenceIndex]) {
    buffer.received += 1;
  }

  buffer.commands[sequenceIndex] = command;

  if (buffer.received < buffer.count) {
    return true;
  }

  jinVisualSequenceBuffers.delete(sequenceId);

  const completedSequence =
    buffer.commands.filter(Boolean);

  jinVisualSequencePlayback =
    jinVisualSequencePlayback
      .catch(() => undefined)
      .then(() => playJinVisualSequence(completedSequence));

  return true;
}
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

  const runtimeMessageId =
    getRuntimeActionMessageId(data);

  if (runtimeMessageId && window.markStreamAnswerPhase) {
    window.markStreamAnswerPhase(
      runtimeMessageId
    );
  }

  const action =
    String(
      data.action || ""
    ).toLowerCase();
  const updateL4FactsMessage =
    action === "update_l4_facts"
      ? getUpdateL4FactsMessage(data)
      : "";
  const baseText =
    buildRuntimeActionDisplayText(
      data,
      action,
      data.text || "",
      {
        fallbackToName: true,
      }
    );
  const text =
    updateL4FactsMessage
      ? (
        `${getRuntimeActionDisplayName(data, action)}: `
        + updateL4FactsMessage
      )
      : baseText;

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
        runtimeMessageId,
        color:
          data.color
          || data.payload
          || "",
        size:
          data.size
          || data.payload
          || "",
        width:
          data.width,
        height:
          data.height,
        reuseCompleted:
          action === "jin_color"
          || action === "jin_size",
        aggregateMarkers: true,
        contextSnapshot:
          data.context || null,
        detail:
          updateL4FactsMessage
          || data.detail
          || "",
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
          retryUserMessage:
            String(
              data.retry_user_message || ""
            ),
          retryAttempt:
            Number(data.retry_attempt || 1),
          retryContextSnapshot:
            data.context || null,
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

function getUpdateL4FactsMessage(data) {

  if (!data || typeof data !== "object") {
    return "";
  }

  const directMessage =
    String(
      data.message || ""
    ).trim();

  if (directMessage) {
    return directMessage;
  }

  const payloadCandidates = [
    data.payload,
    data.action_payload,
    data.runtime_action_payload,
  ];

  for (const candidate of payloadCandidates) {
    if (
      candidate === undefined
      || candidate === null
      || candidate === ""
    ) {
      continue;
    }

    const parsed =
      tryParseRuntimeActionJson(
        candidate
      );

    if (
      parsed
      && typeof parsed === "object"
      && !Array.isArray(parsed)
    ) {
      const message =
        String(
          parsed.message || ""
        ).trim();

      if (message) {
        return message;
      }

      continue;
    }

    if (typeof parsed === "string") {
      const message =
        parsed
          .replace(/\s+/g, " ")
          .trim();

      if (message) {
        return message;
      }
    }
  }

  return "";

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

function highlightUpdatedActiveMemory(activeMemoryId) {
  const normalizedId =
    String(activeMemoryId || "")
      .trim()
      .toLowerCase();

  if (!/^[a-z0-9]{6}$/.test(normalizedId)) {
    return;
  }

  window.dispatchEvent(
    new CustomEvent(
      THINK_RUNTIME_CITATION_HIGHLIGHT_EVENT,
      {
        detail: {
          sourceId: `runtime-action:update-active-memory:${normalizedId}`,
          active: true,
          activeMemoryIds: [normalizedId],
        },
      }
    )
  );
}

function formatActiveMemoryUpdateDetail(
  data
) {

  const activeMemoryId = String(
    data && (
      data.active_memory_id
      || data.id
      || (
        data.active_memory_result
        && data.active_memory_result.id
      )
    )
    || ""
  ).trim();
  const requestedChanges = Array.isArray(
    data && data.active_memory_requested_changes
  )
    ? data.active_memory_requested_changes
    : (
      Array.isArray(
        data
        && data.active_memory_result
        && data.active_memory_result.requested_changes
      )
        ? data.active_memory_result.requested_changes
        : []
    );
  const appliedChanges = Array.isArray(
    data && data.active_memory_changes
  )
    ? data.active_memory_changes
    : [];
  const changes = requestedChanges.length
    ? requestedChanges
    : appliedChanges;
  const lines = activeMemoryId
    ? [`active_memory_id: ${activeMemoryId}`]
    : [];

  changes
    .map((change) => {
      const field = String(
        change && change.field || ""
      ).trim();
      const after = String(
        change && change.after || ""
      ).trim();

      if (!field) {
        return "";
      }

      return `${field}: ${after}`;
    })
    .filter(Boolean)
    .forEach(line => lines.push(line));

  return lines.join("\n");

}

function formatActiveMemoryRecordDetail(
  data
) {

  const activeMemoryId = String(
    data && (
      data.active_memory_id
      || data.id
      || (
        data.active_memory_result
        && data.active_memory_result.id
      )
    )
    || ""
  ).trim().toLowerCase();
  let record = String(
    data && (
      data.active_memory
      || data.active_memory_record
      || (
        data.active_memory_result
        && data.active_memory_result.record
      )
    )
    || ""
  ).trim();
  const activeMemoryRecords = (
    window.JinRuntime
    && window.JinRuntime.runtime
    && typeof window.JinRuntime.runtime.getActiveMemoryRecords === "function"
  )
    ? (
      window.JinRuntime.runtime.getActiveMemoryRecords()
      || []
    )
      .map(item => String(item || "").trim())
      .filter(Boolean)
    : [];

  if (
    !record
    && activeMemoryId
  ) {
    record = activeMemoryRecords
      .find(item => item.toLowerCase().includes(
        `[ active_memory_id: ${activeMemoryId} ]`
      ))
      || "";
  }

  if (!record && activeMemoryRecords.length) {
    const action = String(data && data.action || "")
      .trim()
      .toLowerCase();
    let conditions = String(
      data && (
        data.active_memory_title
        || (
          data.active_memory_result
          && data.active_memory_result.title
        )
      )
      || ""
    ).trim();

    if (!conditions && action === "save_active_memory") {
      const payload = String(data && data.payload || "").trim();

      if (payload.startsWith("{")) {
        try {
          conditions = String(
            JSON.parse(payload).conditions || ""
          ).trim();
        } catch (error) {
          conditions = "";
        }
      }
    }

    if (!conditions) {
      const text = String(data && data.text || "").trim();
      const separatorIndex = text.indexOf(":");

      conditions = separatorIndex >= 0
        ? text.slice(separatorIndex + 1).trim()
        : "";
    }

    if (conditions) {
      const normalizedConditions = conditions.toLowerCase();

      record = activeMemoryRecords
        .slice()
        .reverse()
        .find(item => (
          item.toLowerCase().includes(
            `[ conditions: ${normalizedConditions} ]`
          )
          || item.toLowerCase().includes(
            `: ${normalizedConditions} [`
          )
        ))
        || "";
    }

    if (!record && action === "save_active_memory") {
      record = activeMemoryRecords[activeMemoryRecords.length - 1] || "";
    }

    if (!record && activeMemoryRecords.length === 1) {
      record = activeMemoryRecords[0];
    }
  }

  if (!record) {
    return "";
  }

  return record
    .split(/\r?\n/)
    .map((line) => {
      const trimmed = String(line || "").trim();

      if (!trimmed) {
        return "";
      }

      const parts = [];
      let lastIndex = 0;

      trimmed.replace(
        /\s*(\[[^\]]+\])/gi,
        (match, suffix, offset) => {
          if (!parts.length) {
            const body = trimmed.slice(0, offset).trim();

            if (body) {
              parts.push(body);
            }
          }

          parts.push(String(suffix || "").trim());
          lastIndex = offset + match.length;

          return match;
        }
      );

      if (!parts.length) {
        return trimmed;
      }

      const tail = trimmed.slice(lastIndex).trim();

      if (tail) {
        parts.push(tail);
      }

      return parts.join("\n");
    })
    .join("\n");

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
  "update_active_memory",
  "resolve_active_memory",
  "save_delayed_memory",
  "load_delayed_memory",
  "unload_delayed_memory",
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

function normalizeDelayedMemoryRuntimeActionId(
  value
) {

  const reportId = String(
    value || ""
  ).trim().toLowerCase();

  return /^[a-z0-9]{6}$/.test(reportId)
    ? reportId
    : "";

}

function getDelayedMemoryRuntimeActionPreview(
  data,
  action = ""
) {

  const delayedMemoryResult =
    data
    && data.delayed_memory_result
    && typeof data.delayed_memory_result === "object"
    && !Array.isArray(data.delayed_memory_result)
      ? data.delayed_memory_result
      : null;
  const report =
    data.delayed_memory_report
    || (
      delayedMemoryResult
        ? delayedMemoryResult.report
        : null
    )
    || null;
  const reportId =
    normalizeDelayedMemoryRuntimeActionId(
      data.delayed_memory_report_id
      || (
        delayedMemoryResult
          ? delayedMemoryResult.id
          : ""
      )
      || (
        report
        && typeof report === "object"
        && !Array.isArray(report)
          ? report.id
          : ""
      )
      || (
        [
          "load_delayed_memory",
          "unload_delayed_memory",
        ].includes(action)
          ? data.payload
          : ""
      )
      || ""
    );
  const title = String(
    report
    && typeof report === "object"
    && !Array.isArray(report)
      ? report.title || ""
      : (
        delayedMemoryResult
        && typeof delayedMemoryResult === "object"
          ? delayedMemoryResult.title || ""
          : ""
      )
  ).trim();

  return {
    report,
    reportId,
    title,
  };

}

function getDelayedMemoryTriggeredByTags(
  data
) {

  const values = [];
  const seen = new Set();
  const push = function (value) {
    const tag = String(value || "").trim();
    const key = tag.toLocaleLowerCase();

    if (!tag || seen.has(key)) {
      return;
    }

    seen.add(key);
    values.push(tag);
  };

  if (
    data
    && Array.isArray(data.triggered_by_tags)
  ) {
    data.triggered_by_tags.forEach(push);
  }

  if (data) {
    push(data.triggered_by_tag);
  }

  return values;

}

function formatDelayedMemoryTriggeredByTags(
  data
) {

  const tags =
    getDelayedMemoryTriggeredByTags(data);

  if (!tags.length) {
    return "";
  }

  const rendered = tags
    .map((tag) => `"${tag.replaceAll('"', '\\\"')}"`)
    .join(", ");

  return tags.length === 1
    ? `triggered_by_tag: ${rendered}`
    : `triggered_by_tags: ${rendered}`;

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

  if (runtimeMessageId && window.markStreamAnswerPhase) {
    window.markStreamAnswerPhase(
      runtimeMessageId
    );
  }

  const delayedMemoryPreview =
    getDelayedMemoryRuntimeActionPreview(
      data,
      action
    );
  const reportScopedDelayedAction =
    [
      "load_delayed_memory",
      "unload_delayed_memory",
    ].includes(action)
    && Boolean(
      delayedMemoryPreview.reportId
    );

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
  const restrictedWriteFailure =
    status === "failed"
    && (
      String(data.error || "").trim().toLowerCase()
      === "restricted_write"
      || /restricted\s+write/i.test(text)
    );
  const strikeThroughFailure =
    cancelledByUser
    || abortedByUser
    || restrictedWriteFailure;
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

  const baseDisplayText =
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

  const delayedMemoryTriggerDetail =
    action === "load_delayed_memory"
      ? formatDelayedMemoryTriggeredByTags(
        data
      )
      : "";

  const updateL4FactsMessage =
    action === "update_l4_facts"
      ? getUpdateL4FactsMessage(data)
      : "";

  const activeMemoryUpdateTitle =
    action === "update_active_memory"
      ? String(
        data.active_memory_title
        || (
          data.active_memory_result
          && data.active_memory_result.title
        )
        || ""
      ).trim()
      : "";

  const displayText =
    activeMemoryUpdateTitle
      ? (
        `${getRuntimeActionDisplayName(data, action)}: `
        + activeMemoryUpdateTitle
      )
      : updateL4FactsMessage
      ? (
        `${getRuntimeActionDisplayName(data, action)}: `
        + updateL4FactsMessage
      )
      : reportScopedDelayedAction
      && delayedMemoryPreview.title
      ? (
        `${getRuntimeActionDisplayName(data, action)}: `
        + delayedMemoryPreview.title
        + (
          delayedMemoryTriggerDetail
            ? ` - ${delayedMemoryTriggerDetail}`
            : ""
        )
      )
      : baseDisplayText;

  const displayName =
    getRuntimeActionDisplayName(
      data,
      action
    );

  const sceneEffect =
    getRuntimeActionSceneEffect(
      data
    );

  const deepSearchChild =
    data.deep_search_child === true
    || data.deepSearchChild === true;
  const deepSearchParent =
    data.deep_search_parent === true
    || data.deepSearchParent === true;
  const deepSearchParentId =
    String(
      data.deep_search_parent_id
      || data.deepSearchParentId
      || ""
    ).trim();
  const deepSearchObjective =
    String(
      data.deep_search_objective
      || data.deepSearchObjective
      || ""
    ).trim();

  const closeTag =
    isRuntimeActionCloseTag(
      data
    );

  const runtimeDetail =
    (
      [
        "save_active_memory",
        "update_active_memory",
      ].includes(action)
        ? formatActiveMemoryRecordDetail(data)
        : ""
    )
      || (
        action === "update_active_memory"
          ? formatActiveMemoryUpdateDetail(data)
          : ""
      )
      || updateL4FactsMessage
      || buildRuntimeActionDetail(
        data,
        closeTag
      );

  const suppressMarkerCount = [
    "load_skill",
    "load_skills",
    "jin_size",
  ].includes(action);

  // JIN_SIZE is an ordered visual gesture. Counter-only events are legacy
  // telemetry for the whole response and must never collapse separate size
  // markers into one visible bubble (for example 290px -> text -> 280px).
  if (
    action === "jin_size"
    && data.counter_only === true
  ) {
    return;
  }

  const markerCount = suppressMarkerCount
    ? 0
    : Math.max(
      0,
      Number.parseInt(
        data.marker_count || 0,
        10
      ) || 0
    );

  const counterOnly =
    data.counter_only === true
    && !suppressMarkerCount;

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
    !reportScopedDelayedAction
    && !splitPayloadDistinctMarkers
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
    action === "update_active_memory"
      ? (
        data.active_memory_id
        || data.id
        || data.counter_id
        || ""
      )
      : reportScopedDelayedAction
      ? (
        delayedMemoryPreview.reportId
        || data.id
        || data.counter_id
        || ""
      )
      : (
        data.counter_id
        || data.id
        || ""
      );

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

  if (
    counterOnly
    && (
      reportScopedDelayedAction
      || action === "attach_file"
    )
  ) {
    return;
  }

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
      ENABLE_JIN_VISUAL_ACTION_BUBBLES
      &&
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
          reuseCompleted: true,
          reviveCompleted:
            !counterFinal,
          // Every applied color belongs to one live sequence row.
          // Counter events use another display id, so the shared turn/message
          // scope keeps them attached to this same aggregate bubble.
          aggregateMarkers: true,
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
            strikeThroughFailure
              ? true
              : undefined,
          preserveLabel:
            cancelledByUser
            || restrictedWriteFailure,
          fallbackToLatestActive:
            abortedByUser,
        }
      );
    }

    if (colorApplied) {
      const queued =
        queueJinVisualSequenceCommand(
          data,
          {
            action: "jin_color",
            color,
          }
        );

      if (
        !queued
        && window.JinRuntime
        && window.JinRuntime.avatar
        && typeof window.JinRuntime.avatar.setCenterColor === "function"
      ) {
        window.JinRuntime.avatar.setCenterColor(
          color
        );
      }
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
      ENABLE_JIN_VISUAL_ACTION_BUBBLES
      &&
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

  if (action === "jin_size") {
    const size =
      String(
        data.size
        || data.payload
        || ""
      );
    const width =
      Number.parseInt(
        data.width || 0,
        10
      );
    const height =
      Number.parseInt(
        data.height || 0,
        10
      );
    const actionId =
      actionDisplayId;
    const sizeApplied =
      (
        status === "completed"
        || status === "complete"
        || status === "done"
      )
      && Boolean(
        size
        || width
      );

    if (
      ENABLE_JIN_VISUAL_ACTION_BUBBLES
      &&
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
          size,
          width,
          height,
          payload: size,
          detail: size,
          displayName,
          sceneEffect,
          closeTag,
          reuseCompleted: false,
          reviveCompleted: false,
          // Keep every emitted size marker as its own ordered bubble.
          // The backend gives each marker a distinct display id.
          aggregateMarkers: false,
          counterOnly: false,
          markerCount: 0,
          sizes: size ? [size] : [],
          contextSnapshot:
            data.context || null,
          guardConfirmationId,
          cancelled:
            strikeThroughFailure
              ? true
              : undefined,
          preserveLabel:
            cancelledByUser
            || restrictedWriteFailure,
          fallbackToLatestActive:
            abortedByUser,
        }
      );
    }

    if (sizeApplied) {
      const queued =
        queueJinVisualSequenceCommand(
          data,
          {
            action: "jin_size",
            size,
            width,
            height,
          }
        );

      if (
        !queued
        && window.JinPanels
        && typeof window.JinPanels.setPendingJinSize === "function"
      ) {
        window.JinPanels.setPendingJinSize({
          size,
          width,
          height,
        });
      }
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
      ENABLE_JIN_VISUAL_ACTION_BUBBLES
      &&
      (
        sizeApplied
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
                sizeApplied,
            }
          );
        },
        60
      );
    }

    return;
  }

  if (action === "jin_speed") {
    const speed = Number.parseInt(
      data.speed || data.payload || 0,
      10
    );
    const speedApplied = (
      status === "completed"
      || status === "complete"
      || status === "done"
    ) && Number.isFinite(speed) && speed > 0;

    if (speedApplied) {
      const queued =
        queueJinVisualSequenceCommand(
          data,
          {
            action: "jin_speed",
            speed,
          }
        );

      if (
        !queued
        && window.JinPanels
        && typeof window.JinPanels.setJinMoveSpeed === "function"
      ) {
        window.JinPanels.setJinMoveSpeed(
          speed
        );
      }
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

    // Intentionally no chat bubble: JIN motion actions are silent avatar
    // gestures, like JIN_COLOR/JIN_SIZE while visual action bubbles are off.
    return;
  }

  if (action === "jin_position") {
    const x = Number.parseInt(
      data.x,
      10
    );
    const y = Number.parseInt(
      data.y,
      10
    );
    const positionApplied = (
      status === "completed"
      || status === "complete"
      || status === "done"
    )
      && Number.isFinite(x)
      && Number.isFinite(y);

    if (positionApplied) {
      const queued =
        queueJinVisualSequenceCommand(
          data,
          {
            action: "jin_position",
            x,
            y,
          }
        );

      if (
        !queued
        && window.JinPanels
        && typeof window.JinPanels.setPendingJinPosition === "function"
      ) {
        window.JinPanels.setPendingJinPosition({
          x,
          y,
        });
      }
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
    action === "update_active_memory"
    && data.active_memory
    && (data.active_memory_id || data.id)
    && window.JinRuntime
    && window.JinRuntime.runtime
    && window.JinRuntime.runtime.replaceActiveMemoryRecordById
  ) {
    const activeMemoryId =
      data.active_memory_id || data.id;

    window.JinRuntime.runtime.replaceActiveMemoryRecordById(
      activeMemoryId,
      data.active_memory
    );
    highlightUpdatedActiveMemory(
      activeMemoryId
    );
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
    action === "save_delayed_memory"
    && data.delayed_memory_report
    && window.JinRuntime
    && window.JinRuntime.runtime
    && window.JinRuntime.runtime.mergeDelayedMemoryReports
  ) {
    window.JinRuntime.runtime.mergeDelayedMemoryReports(
      data.delayed_memory_report
    );
  }

  if (
    action === "load_delayed_memory"
    && data.delayed_memory_result
    && data.delayed_memory_result.report
    && data.delayed_memory_result.id
    && window.JinRuntime
    && window.JinRuntime.runtime
    && window.JinRuntime.runtime.mergeDelayedMemoryReports
  ) {
    window.JinRuntime.runtime.mergeDelayedMemoryReports({
      [data.delayed_memory_result.id]:
        data.delayed_memory_result.report,
    });
  }

  if (
    (
      status === "completed"
      || status === "complete"
      || status === "done"
    )
    && delayedMemoryPreview.reportId
    && window.JinRuntime
    && window.JinRuntime.runtime
    && (
      typeof window.JinRuntime.runtime.markDelayedMemoryReportLoaded
        === "function"
    )
  ) {
    if (
      action === "load_delayed_memory"
      && typeof window.JinRuntime.runtime.markDelayedMemoryReportLoaded
        === "function"
    ) {
      window.JinRuntime.runtime.markDelayedMemoryReportLoaded(
        delayedMemoryPreview.reportId,
        true,
        { forceRender: true }
      );
    }


    if (
      action === "unload_delayed_memory"
      && typeof window.JinRuntime.runtime.markDelayedMemoryReportLoaded
        === "function"
    ) {
      window.JinRuntime.runtime.markDelayedMemoryReportLoaded(
        delayedMemoryPreview.reportId,
        false
      );
    }
  }

  if (
    status === "completed"
    || status === "complete"
    || status === "done"
  ) {
    if (
      action === "clean_tool_results"
      && window.JinRuntime
      && window.JinRuntime.session
      && typeof window.JinRuntime.session.clearPersistedToolResultsCheckpoint
        === "function"
    ) {
      window.JinRuntime.session.clearPersistedToolResultsCheckpoint();
    }

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
          reuseCompleted:
            action === "update_l4_facts",
          contextSnapshot:
            data.context || null,
          assetResult:
            data.asset_result || null,
          attachmentResult:
            data.attachment_result || null,
          delayedMemoryReportId:
            delayedMemoryPreview.reportId,
          delayedMemoryReport:
            delayedMemoryPreview.report,
          completed:
            !aggregateMarkers
            || completeImmediately,
          detail: runtimeDetail,
          displayName,
          sceneEffect,
          status,
          deepSearchParent,
          deepSearchChild,
          deepSearchParentId,
          deepSearchObjective,
          closeTag,
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
          deepSearchParent,
          deepSearchChild,
          deepSearchParentId,
          deepSearchObjective,
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
        strikeThroughFailure
          ? true
          : undefined,
      preserveLabel:
        cancelledByUser
        || restrictedWriteFailure
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
      attachmentResult:
        data.attachment_result || null,
      delayedMemoryReportId:
        delayedMemoryPreview.reportId,
      delayedMemoryReport:
        delayedMemoryPreview.report,
      detail: runtimeDetail,
      displayName,
      sceneEffect,
      status,
      deepSearchParent,
      deepSearchChild,
      deepSearchParentId,
      deepSearchObjective,
      closeTag,
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
        deepSearchParent,
        deepSearchChild,
        deepSearchParentId,
        deepSearchObjective,
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
