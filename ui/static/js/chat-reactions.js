(function () {
  "use strict";

  const pendingByMessage = new Map();
  const completedByMessage = new Map();
  const answerElementByMessage = new Map();
  const REACTION_CLEANUP_MS = 30000;
  const REACTION_FLIGHT_MS = 620;

  function normalizeEmoji(value) {
    return String(value || "").trim();
  }

  function findReactionAnchor(answerElement, emoji) {
    if (!answerElement) {
      return null;
    }

    return Array.from(
      answerElement.querySelectorAll(
        ".jin-chat-jin-reaction-anchor"
      )
    ).find((anchor) => (
      normalizeEmoji(anchor.dataset.jinReactionEmoji) === emoji
    )) || null;
  }

  function hideReactionAnchors(answerElement, emoji) {
    if (!answerElement) {
      return;
    }

    answerElement.querySelectorAll(
      ".jin-chat-jin-reaction-anchor"
    ).forEach((anchor) => {
      if (
        !emoji
        || normalizeEmoji(anchor.dataset.jinReactionEmoji) === emoji
      ) {
        anchor.classList.add(
          "is-consumed"
        );
      }
    });
  }

  function findTargetUserBubble(answerElement) {
    const streamWrapper =
      answerElement
      && typeof answerElement.closest === "function"
        ? answerElement.closest(".jin-stream-wrapper")
        : null;

    let current =
      streamWrapper
        ? streamWrapper.previousElementSibling
        : null;

    while (current) {
      if (
        current.matches
        && current.matches(
          '.jin-message-shell[data-role="user"]'
        )
      ) {
        return current.querySelector(
          ".jin-chat-bubble-user"
        );
      }

      current = current.previousElementSibling;
    }

    return null;
  }

  function ensureReactionBadge(userBubble, emoji) {
    let badge = userBubble.querySelector(
      ":scope > .jin-user-reaction-badge"
    );

    if (!badge) {
      badge = document.createElement("span");
      badge.className = "jin-user-reaction-badge";
      badge.setAttribute("aria-hidden", "true");
      userBubble.appendChild(badge);
    }

    badge.textContent = emoji;
    badge.dataset.jinReactionEmoji = emoji;
    badge.classList.remove("is-visible");

    return badge;
  }

  function showReactionBadge(badge) {
    if (!badge) {
      return;
    }

    void badge.offsetWidth;
    badge.classList.add("is-visible");
  }

  function animateReaction(anchor, badge, emoji) {
    const sourceRect = anchor.getBoundingClientRect();
    const targetRect = badge.getBoundingClientRect();
    const sourceX = sourceRect.left + (sourceRect.width / 2);
    const sourceY = sourceRect.top + (sourceRect.height / 2);
    const targetX = targetRect.left + (targetRect.width / 2);
    const targetY = targetRect.top + (targetRect.height / 2);

    if (
      !Number.isFinite(sourceX)
      || !Number.isFinite(sourceY)
      || !Number.isFinite(targetX)
      || !Number.isFinite(targetY)
    ) {
      showReactionBadge(badge);
      return;
    }

    const flight = document.createElement("span");
    flight.className = "jin-reaction-flight";
    flight.textContent = emoji;
    flight.setAttribute("aria-hidden", "true");
    flight.style.left = `${sourceX}px`;
    flight.style.top = `${sourceY}px`;
    document.body.appendChild(flight);

    const finish = () => {
      flight.remove();
      showReactionBadge(badge);
    };

    const reduceMotion =
      window.matchMedia
      && window.matchMedia(
        "(prefers-reduced-motion: reduce)"
      ).matches;

    if (
      reduceMotion
      || typeof flight.animate !== "function"
    ) {
      finish();
      return;
    }

    const dx = targetX - sourceX;
    const dy = targetY - sourceY;
    const arcY = dy * 0.52 - 18;

    const animation = flight.animate(
      [
        {
          transform: "translate(-50%, -50%) translate(0px, 0px) scale(0.86) rotate(-7deg)",
          opacity: 0.2,
        },
        {
          transform: `translate(-50%, -50%) translate(${dx * 0.54}px, ${arcY}px) scale(1.16) rotate(6deg)`,
          opacity: 1,
          offset: 0.52,
        },
        {
          transform: `translate(-50%, -50%) translate(${dx}px, ${dy}px) scale(0.94) rotate(0deg)`,
          opacity: 1,
        },
      ],
      {
        duration: REACTION_FLIGHT_MS,
        easing: "cubic-bezier(0.22, 0.78, 0.2, 1)",
        fill: "forwards",
      }
    );

    animation.addEventListener(
      "finish",
      finish,
      { once: true }
    );
    animation.addEventListener(
      "cancel",
      finish,
      { once: true }
    );
  }

  function completeReaction(messageId, answerElement, emoji) {
    const anchor = findReactionAnchor(
      answerElement,
      emoji
    );
    const userBubble = findTargetUserBubble(
      answerElement
    );

    if (!anchor || !userBubble) {
      return false;
    }

    completedByMessage.set(
      messageId,
      emoji
    );
    pendingByMessage.delete(
      messageId
    );

    const badge = ensureReactionBadge(
      userBubble,
      emoji
    );

    // Keep the zero-width marker in layout until animateReaction has read
    // its real inline position. Hiding it first collapses the source rect
    // to (0, 0), making the emoji appear to fly out of the left console.
    animateReaction(
      anchor,
      badge,
      emoji
    );

    hideReactionAnchors(
      answerElement,
      emoji
    );

    window.setTimeout(
      () => {
        pendingByMessage.delete(messageId);
        completedByMessage.delete(messageId);
        answerElementByMessage.delete(messageId);
      },
      REACTION_CLEANUP_MS
    );

    return true;
  }

  function syncMessage(messageId, answerElement) {
    const resolvedMessageId =
      String(messageId || "").trim();

    if (!resolvedMessageId || !answerElement) {
      return;
    }

    answerElementByMessage.set(
      resolvedMessageId,
      answerElement
    );

    const completedEmoji =
      completedByMessage.get(
        resolvedMessageId
      );

    if (completedEmoji) {
      hideReactionAnchors(
        answerElement,
        completedEmoji
      );
      return;
    }

    const pending =
      pendingByMessage.get(
        resolvedMessageId
      );

    if (!pending) {
      return;
    }

    completeReaction(
      resolvedMessageId,
      answerElement,
      pending.emoji
    );
  }

  function handleRuntimeAction(data) {
    const action =
      String(data && data.action || "")
        .trim()
        .toLowerCase();

    if (action !== "jin_reaction") {
      return false;
    }

    const status =
      String(data.status || "")
        .trim()
        .toLowerCase();

    if (
      ![
        "completed",
        "complete",
        "done",
      ].includes(status)
    ) {
      return true;
    }

    const messageId =
      String(
        data.runtime_message_id
        || data.message_id
        || ""
      ).trim();
    const emoji = normalizeEmoji(
      data.emoji
      || data.payload
      || ""
    );

    if (!messageId || !emoji) {
      return true;
    }

    if (
      completedByMessage.has(messageId)
      || pendingByMessage.has(messageId)
    ) {
      return true;
    }

    pendingByMessage.set(
      messageId,
      { emoji }
    );

    const answerElement =
      answerElementByMessage.get(
        messageId
      );

    if (answerElement) {
      window.requestAnimationFrame(
        () => syncMessage(
          messageId,
          answerElement
        )
      );
    }

    return true;
  }

  window.JinChatReactions = {
    handleRuntimeAction,
    syncMessage,
  };
}());
