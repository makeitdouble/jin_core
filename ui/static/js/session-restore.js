(function () {
  "use strict";

  const params =
    new URLSearchParams(
      window.location.search
    );
  const sourceSessionId =
    String(
      params.get("restore_session")
      || ""
    ).trim();

  if (!sourceSessionId) {
    window.jinArchivedSessionRestoreReady =
      Promise.resolve(null);
    return;
  }

  const chatHistory =
    document.getElementById(
      "chat-history"
    );

  function stripLoggedAttachmentContext(
    text,
    attachments
  ) {
    const source =
      String(text || "");

    if (
      !Array.isArray(attachments)
      || !attachments.length
    ) {
      return source;
    }

    return source.replace(
      /\n\nAttached context:\n(?:- .*\n?)+$/u,
      ""
    ).trimEnd();
  }

  function normalizeRole(
    role,
    runtimeMode
  ) {
    const normalized =
      String(role || "")
        .trim()
        .toLowerCase();

    if (normalized === "user") {
      return "user";
    }

    if (normalized === "service") {
      return "service";
    }

    return String(runtimeMode || "")
      .trim()
      .toUpperCase() === "SERVICE"
        ? "service"
        : "brain";
  }

  function buildContextSnapshot(
    payload,
    message,
    isLastJin
  ) {
    if (
      !isLastJin
      || !payload.archived_context
    ) {
      return null;
    }

    return {
      system_prompt:
        String(
          payload.archived_context
          || ""
        ),
      user_prompt:
        String(
          message.text
          || ""
        ),
      context_role:
        normalizeRole(
          message.role,
          payload.runtime_mode
        ),
      archived_session_id:
        String(
          payload.source_session_id
          || ""
        ),
    };
  }

  const restoreMonths = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
  ];

  const restoreWeekdays = [
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
  ];

  function formatRestoreBoundaryTimestamp(
    value
  ) {
    const source = String(value || "").trim();
    const match = source.match(
      /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/
    );

    if (!match) {
      return source;
    }

    const year = Number(match[1]);
    const monthIndex = Number(match[2]) - 1;
    const day = Number(match[3]);
    const hour = match[4];
    const minute = match[5];

    if (
      monthIndex < 0
      || monthIndex >= restoreMonths.length
      || day <= 0
    ) {
      return source;
    }

    const weekdayIndex = new Date(
      Date.UTC(year, monthIndex, day)
    ).getUTCDay();

    return `${day} ${restoreMonths[monthIndex]} ${hour}:${minute}  ${restoreWeekdays[weekdayIndex]}`;
  }

  function appendRestoreBoundary(
    payload
  ) {
    if (!chatHistory) {
      return;
    }

    const messages = Array.isArray(payload.messages)
      ? payload.messages
      : [];
    const lastMessage = messages.length
      ? messages[messages.length - 1]
      : null;
    const timestamp = String(
      lastMessage && lastMessage.ts
        ? lastMessage.ts
        : ""
    ).trim();

    if (!timestamp) {
      return;
    }

    const labelText = formatRestoreBoundaryTimestamp(timestamp);
    const divider = document.createElement("div");
    divider.className = "jin-session-restore-divider";
    divider.setAttribute("role", "separator");
    divider.setAttribute(
      "aria-label",
      `Session restored after ${labelText}`
    );

    const label = document.createElement("span");
    label.className = "jin-session-restore-divider-label";
    label.textContent = labelText;
    divider.appendChild(label);
    chatHistory.appendChild(divider);
  }

  function renderArchivedMessages(
    payload
  ) {
    if (
      !chatHistory
      || !Array.isArray(payload.messages)
    ) {
      return;
    }

    chatHistory.replaceChildren();

    let lastJinIndex = -1;
    payload.messages.forEach(
      (message, index) => {
        if (
          String(message.role || "")
            .trim()
            .toLowerCase() !== "user"
        ) {
          lastJinIndex = index;
        }
      }
    );

    payload.messages.forEach(
      (message, index) => {
        const role =
          normalizeRole(
            message.role,
            payload.runtime_mode
          );
        const attachments =
          Array.isArray(message.attachments)
            ? message.attachments
            : [];
        const text =
          role === "user"
            ? stripLoggedAttachmentContext(
                message.text,
                attachments
              )
            : String(message.text || "");

        if (role === "user") {
          if (
            typeof window.appendChatMessage
            === "function"
          ) {
            window.appendChatMessage(
              role,
              text,
              null,
              attachments
            );
          }
          return;
        }

        const messageId =
          `archive-${String(
            message.turn_id
            || index
          )}`;
        const contextSnapshot =
          buildContextSnapshot(
            payload,
            message,
            index === lastJinIndex
          );

        if (
          typeof window.startStreamMessage
          === "function"
          && typeof window.appendStreamChunk
          === "function"
          && typeof window.finishStreamMessage
          === "function"
        ) {
          window.startStreamMessage(
            messageId,
            role,
            contextSnapshot
          );

          if (
            message.reasoning
            && typeof window.appendThinkingChunk
              === "function"
          ) {
            window.appendThinkingChunk(
              messageId,
              String(message.reasoning)
            );
          }

          window.appendStreamChunk(
            messageId,
            text
          );
          window.finishStreamMessage(
            messageId
          );
        } else if (
          typeof window.appendChatMessage
          === "function"
        ) {
          window.appendChatMessage(
            role,
            text,
            contextSnapshot
          );
        }
      }
    );

    appendRestoreBoundary(payload);

    requestAnimationFrame(() => {
      chatHistory.scrollTop =
        chatHistory.scrollHeight;
    });
  }

  function restoreDelayedMemoryStore(
    payload
  ) {
    const runtime =
      window.JinRuntime
      && window.JinRuntime.runtime;

    if (
      runtime
      && typeof runtime.mergeDelayedMemoryReports
        === "function"
      && payload.delayed_memory_reports
      && typeof payload.delayed_memory_reports === "object"
    ) {
      // Restore report records into the local store so they are available for
      // the next normal turn, but intentionally do NOT mark them loaded here.
      // The backend reactivates the archived loaded ids only after the hidden
      // restore greeting is finished and then publishes the real load state.
      runtime.mergeDelayedMemoryReports(
        payload.delayed_memory_reports
      );
    }

    if (
      runtime
      && typeof runtime.replaceLoadedDelayedMemoryReportIds
        === "function"
    ) {
      // The hidden restore turn must start with zero loaded report bodies.
      // Archived load ids are staged on the backend and are re-enabled only
      // after JIN has produced the one-shot restore greeting.
      runtime.replaceLoadedDelayedMemoryReportIds(
        [],
        { render: false }
      );
    }
  }


  function restoreSessionActions(
    payload
  ) {
    if (
      !Array.isArray(payload.session_actions)
      || !payload.session_actions.length
      || typeof window.updateSessionActionsLog
        !== "function"
    ) {
      return;
    }

    window.updateSessionActionsLog({
      mode: "session_actions",
      items: payload.session_actions,
    });
  }

  function mergeLatestVisualCheckpoint(
    payload
  ) {
    const merged = {
      ...(payload || {}),
    };
    const storage =
      window.JinRuntime
      && window.JinRuntime.storage;

    if (
      !storage
      || typeof storage.readLatestSavedSessionSnapshot
        !== "function"
    ) {
      return merged;
    }

    const checkpoint =
      storage.readLatestSavedSessionSnapshot();
    const snapshot =
      checkpoint
      && String(checkpoint.session_id || "").trim()
        === String(
          merged.source_session_id
          || sourceSessionId
          || ""
        ).trim()
      && checkpoint.session_snapshot
      && typeof checkpoint.session_snapshot === "object"
        ? checkpoint.session_snapshot
        : null;

    if (!snapshot) {
      return merged;
    }

    const color =
      String(snapshot.current_jin_color || "").trim();

    if (color) {
      merged.current_jin_color = color;
    }

    for (const key of [
      "current_jin_size",
      "current_jin_position",
      "current_window_size",
      "room_state",
    ]) {
      const value = snapshot[key];

      if (
        value
        && typeof value === "object"
        && !Array.isArray(value)
      ) {
        merged[key] = { ...value };
      }
    }

    const speed =
      Number(snapshot.current_jin_speed || 0);

    if (speed > 0) {
      merged.current_jin_speed = speed;
    }

    if (
      Object.prototype.hasOwnProperty.call(
        snapshot,
        "current_jin_collapsed"
      )
    ) {
      merged.current_jin_collapsed =
        Boolean(snapshot.current_jin_collapsed);
    }

    return merged;
  }


  function restoreVisualState(
    payload
  ) {
    const roomState =
      payload.room_state
      && typeof payload.room_state === "object"
      && !Array.isArray(payload.room_state)
        ? payload.room_state
        : null;

    if (
      roomState
      && window.JinPanels
      && typeof window.JinPanels.applyRoomState
        === "function"
      && window.JinPanels.applyRoomState(
        roomState,
        { persist: false }
      )
    ) {
      return;
    }

    const color =
      String(
        payload.current_jin_color
        || ""
      ).trim();

    if (
      color
      && window.JinRuntime
      && window.JinRuntime.avatar
      && typeof window.JinRuntime.avatar.setCenterColor
        === "function"
    ) {
      window.JinRuntime.avatar.setCenterColor(
        color
      );
    }

    const size =
      payload.current_jin_size
      && typeof payload.current_jin_size === "object"
      && !Array.isArray(payload.current_jin_size)
        ? payload.current_jin_size
        : String(
            payload.current_jin_size
            || ""
          ).trim();
    const position =
      payload.current_jin_position
      && typeof payload.current_jin_position === "object"
        ? payload.current_jin_position
        : null;
    const legacyCollapsed =
      Object.prototype.hasOwnProperty.call(
        payload,
        "current_jin_collapsed"
      )
        ? Boolean(payload.current_jin_collapsed)
        : Boolean(size && position);

    if (
      legacyCollapsed
      && window.JinPanels
      && typeof window.JinPanels.applyRoomState
        === "function"
    ) {
      const normalizedSize =
        size
        && typeof size === "object"
          ? size
          : null;

      if (
        window.JinPanels.applyRoomState(
          {
            version: 1,
            avatar: {
              collapsed: true,
              color,
              geometry_known:
                Boolean(normalizedSize && position),
              width:
                normalizedSize && normalizedSize.width,
              height:
                normalizedSize && normalizedSize.height,
              x: position && position.x,
              y: position && position.y,
              speed_px_per_second:
                Number(payload.current_jin_speed || 900),
              memory_layers_hidden: false,
            },
          },
          { persist: false }
        )
      ) {
        return;
      }
    }

    if (
      size
      && window.JinPanels
      && typeof window.JinPanels.setPendingJinSize
        === "function"
    ) {
      window.JinPanels.setPendingJinSize(
        size
      );
    }

    const speed = Number(
      payload.current_jin_speed
      || 0
    );

    if (
      speed > 0
      && window.JinPanels
      && typeof window.JinPanels.setJinMoveSpeed
        === "function"
    ) {
      window.JinPanels.setJinMoveSpeed(
        speed
      );
    }

    if (
      position
      && window.JinPanels
      && typeof window.JinPanels.setPendingJinPosition
        === "function"
    ) {
      window.JinPanels.setPendingJinPosition(
        position
      );
    }
  }

  function buildBootstrap(
    payload
  ) {
    return {
      type: "session_bootstrap",
      source_session_id:
        String(
          payload.source_session_id
          || sourceSessionId
        ).trim(),
      source_session_date:
        String(
          payload.source_session_date
          || ""
        ).trim(),
      archived_session_restore: true,
      restore_reasoning_dump:
        String(
          payload.restore_reasoning_dump
          || ""
        ),
      restore_l4_fact_ids:
        Array.isArray(payload.restore_l4_fact_ids)
          ? payload.restore_l4_fact_ids
          : [],
      restore_delayed_memory_metadata:
        Array.isArray(payload.restore_delayed_memory_metadata)
          ? payload.restore_delayed_memory_metadata
          : [],
      restore_attached_file_metadata:
        Array.isArray(payload.restore_attached_file_metadata)
          ? payload.restore_attached_file_metadata
          : [],
      runtime_memory:
        String(
          payload.runtime_memory
          || ""
        ),
      runtime_memory_updates:
        Number(
          payload.runtime_memory_updates
          || 0
        ),
      loaded_memory_ids:
        Array.isArray(payload.loaded_memory_ids)
          ? payload.loaded_memory_ids
          : [],
      delayed_memory_reports:
        payload.delayed_memory_reports
        && typeof payload.delayed_memory_reports === "object"
          ? payload.delayed_memory_reports
          : {},
      active_memory_records:
        Array.isArray(payload.active_memory_records)
          ? payload.active_memory_records
          : [],
      attached_file_ids:
        Array.isArray(payload.attached_file_ids)
          ? payload.attached_file_ids
          : [],
      recent_turns:
        Array.isArray(payload.recent_turns)
          ? payload.recent_turns
          : [],
      dialog_context:
        String(
          payload.dialog_context
          || ""
        ),
      previous_reasoning:
        String(
          payload.previous_reasoning
          || ""
        ),
      session_actions:
        Array.isArray(payload.session_actions)
          ? payload.session_actions
          : [],
      runtime_turn_counter:
        Number(
          payload.runtime_turn_counter
          || 0
        ),
      turn_number:
        Number(
          payload.turn_number
          || 0
        ),
      user_message_count:
        Number(
          payload.user_message_count
          || 0
        ),
      assistant_message_count:
        Number(
          payload.assistant_message_count
          || 0
        ),
      current_jin_color:
        String(
          payload.current_jin_color
          || ""
        ).trim(),
      current_jin_size:
        payload.current_jin_size
        && typeof payload.current_jin_size === "object"
          ? payload.current_jin_size
          : null,
      current_jin_position:
        payload.current_jin_position
        && typeof payload.current_jin_position === "object"
          ? payload.current_jin_position
          : null,
      current_jin_speed:
        Number(payload.current_jin_speed || 900),
      current_jin_collapsed:
        Object.prototype.hasOwnProperty.call(
          payload,
          "current_jin_collapsed"
        )
          ? Boolean(payload.current_jin_collapsed)
          : Boolean(
              payload.current_jin_size
              && payload.current_jin_position
            ),
      current_window_size:
        payload.current_window_size
        && typeof payload.current_window_size === "object"
          ? payload.current_window_size
          : null,
      room_state:
        payload.room_state
        && typeof payload.room_state === "object"
        && !Array.isArray(payload.room_state)
          ? payload.room_state
          : null,
    };
  }

  async function restoreArchivedSession() {
    if (
        window.JinRuntime
        && window.JinRuntime.anonymousMode
        && window.JinRuntime.anonymousMode.ready
    ) {
      try {
        await window.JinRuntime.anonymousMode.ready;
      } catch (error) {
        // Detection failure falls back to normal restore behavior.
      }
    }

    if (
        window.JinRuntime
        && window.JinRuntime.anonymousMode
        && typeof window.JinRuntime.anonymousMode.isEnabled === "function"
        && window.JinRuntime.anonymousMode.isEnabled()
    ) {
      return null;
    }

    const response = await fetch(
      `/api/sessions/${encodeURIComponent(sourceSessionId)}/restore`,
      {
        cache: "no-store",
      }
    );

    if (!response.ok) {
      throw new Error(
        `session restore failed: ${response.status}`
      );
    }

    const payload =
      mergeLatestVisualCheckpoint(
        await response.json()
      );

    const bootstrap =
      buildBootstrap(payload);

    window.jinArchivedSessionBootstrap =
      bootstrap;
    window.jinArchivedSessionRestorePayload =
      payload;

    renderArchivedMessages(payload);
    restoreDelayedMemoryStore(payload);
    restoreSessionActions(payload);
    restoreVisualState(payload);

    // Paint PREVIOUS_RUNTIME_STATE immediately as runtime page 1. This replaces
    // the brand-new-session placeholder before websocket bootstrap chatter can
    // become visible, and also arms duplicate suppression for the server echo.
    if (
      typeof window.applyPersistedSessionBootstrap
        === "function"
    ) {
      window.applyPersistedSessionBootstrap(
        bootstrap
      );
    }

    if (typeof window.appendLog === "function") {
      window.appendLog(
        "[SESSION]",
        `restored archive ${payload.source_session_id}`
      );
    }

    return payload;
  }

  window.jinArchivedSessionRestoreReady =
    restoreArchivedSession()
      .catch((error) => {
        console.error(
          "[SESSION RESTORE]",
          error
        );

        if (typeof window.appendLog === "function") {
          window.appendLog(
            "[SESSION]",
            `restore failed: ${error.message || error}`
          );
        }

        return null;
      });
}());
