function handleRuntimeActionGuardConfirmation(
  data
) {

  const action =
    String(
      data.action || ""
    ).toLowerCase();
  const text =
    String(
      data.text || ""
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

  const runtimeDetail =
    String(
      data.detail
      || (
        data.asset_result
        && (
          data.asset_result.detail
          || data.asset_result.error
        )
      )
      || data.payload
      || ""
    ).trim();

  const cancelledByUser =
    status === "failed"
    && Boolean(guardConfirmationId)
    && /\bcancelled\s*$/i.test(
      text.trim()
    );

  if (
    cancelledByUser
    && window.markSessionActionCancelled
  ) {
    window.markSessionActionCancelled(
      action,
      data.color || data.payload || ""
    );
  }

  const displayText =
    action === "resolve_active_memory"
      ? buildResolveActiveMemoryRuntimeActionText(
        data,
        text
      )
      : text;

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

  const aggregateMarkers =
    data.aggregate_markers === true
    || counterOnly
    || markerCount > 0
    || Boolean(
      window.hasActiveRuntimeActionCounter
      && window.hasActiveRuntimeActionCounter(
        action
      )
    );

  const actionDisplayId =
    data.counter_id
    || data.id
    || "";

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

    if (
      displayText.trim()
      && window.appendRuntimeAction
    ) {
      window.appendRuntimeAction(
        action,
        "JIN_COLOR",
        {
          id: actionId,
          color,
          detail: color,
          reuseCompleted:
            counterOnly,
          aggregateMarkers,
          counterOnly,
          markerCount,
          colors:
            Array.isArray(data.colors)
              ? data.colors
              : counterPayloads,
          contextSnapshot:
            data.context || null,
          guardConfirmationId,
          cancelled:
            cancelledByUser,
          preserveLabel:
            cancelledByUser
            || counterOnly,
        }
      );
    }

    if (
      (
        status === "completed"
        || status === "complete"
        || status === "done"
      )
      && color
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
        counterFinal
        || (
          !aggregateMarkers
          && (
            status === "completed"
            || status === "complete"
            || status === "done"
            || status === "failed"
            || status === "interrupted"
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
            }
          );
        },
        60
      );
    }

    return;
  }

  if (
    action === "create_active_memory"
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
          guardConfirmationId,
          updateExisting: true,
          aggregateMarkers,
          counterOnly,
          markerCount,
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
            !aggregateMarkers,
          detail: runtimeDetail,
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
      !aggregateMarkers
      && window.fadeRuntimeAction
    ) {
      window.fadeRuntimeAction(
        action,
        {
          id: actionDisplayId,
        }
      );
    }

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
      guardConfirmationId,
      aggregateMarkers,
      counterOnly,
      markerCount,
      reuseCompleted:
        counterOnly,
      cancelled:
        cancelledByUser,
      preserveLabel:
        cancelledByUser
        || counterOnly,
      contextSnapshot:
        data.context || null,
      assetResult:
        data.asset_result || null,
      detail: runtimeDetail,
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
      || (
        !aggregateMarkers
        && (
          status === "failed"
          || status === "interrupted"
        )
      )
    )
    && window.fadeRuntimeAction
  ) {
    window.fadeRuntimeAction(
      action,
      {
        id: actionDisplayId,
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
