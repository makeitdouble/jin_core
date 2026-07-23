(function () {
    const ratingSelectionClasses = [
        "jin-rating-selected-active",
        "jin-rating-committed",
        "jin-rating-selected-minus",
        "jin-rating-selected-neutral",
        "jin-rating-selected-plus",
        "jin-rating-press-minus",
        "jin-rating-press-neutral",
        "jin-rating-press-plus",
    ];
    const ratingBubbleSelector =
        ".jin-chat-bubble-rateable, .jin-chat-bubble-service, .jin-chat-bubble-brain";
    const activeRatingBubbleSelector =
        ".jin-chat-bubble-rateable.jin-rating-selected-active:not(.jin-rating-committed), "
        + ".jin-chat-bubble-service.jin-rating-selected-active:not(.jin-rating-committed), "
        + ".jin-chat-bubble-brain.jin-rating-selected-active:not(.jin-rating-committed)";

    function isRatingInteractionBlocked() {
        return Boolean(
            (
                window.isJinGenerationRunning
                && window.isJinGenerationRunning()
            )
            || window.jinGenerationRunning
        );
    }

    function clearBubbleRating(bubble, reason = "outside") {
        if (
            !bubble
            || bubble.classList.contains("jin-rating-committed")
            || bubble.dataset.ratingCommitted === "true"
            || isRatingInteractionBlocked()
        ) {
            return;
        }

        const previousRating = bubble.dataset.ratingSelected || null;

        bubble.classList.remove(...ratingSelectionClasses);
        delete bubble.dataset.ratingSelected;
        delete bubble.dataset.ratingPending;
        clearBubbleRatingIntensity(bubble);
        setBubbleRatingClickAlt(bubble, 0);

        const zones = bubble.querySelector(":scope > .jin-rating-hover-zones");
        if (zones) {
            zones.title = "";
        }

        if (previousRating) {
            if (window.clearJinAnswerRating) {
                window.clearJinAnswerRating({
                    previousRating,
                    reason,
                    runtimeSnapshotIndex: bubble.dataset.runtimeSnapshotIndex || null,
                });
            }

            bubble.dispatchEvent(new CustomEvent("jin:answer-rating-cleared", {
                bubbles: true,
                detail: {
                    previousRating,
                    reason,
                },
            }));
        }
    }

    function getCurrentRatingGateGeneration() {
        if (!window.getJinAnswerRatingL1GateState) {
            return 0;
        }

        const gateState = window.getJinAnswerRatingL1GateState() || {};
        return Number(gateState.waitingGeneration || gateState.generation || 0);
    }

    function isBubbleRatingL1Ready(bubble) {
        const generation = Number(bubble && bubble.dataset.ratingGateGeneration || 0);

        if (!generation) {
            return true;
        }

        if (!window.isJinAnswerRatingReadyForGateGeneration) {
            return false;
        }

        return Boolean(window.isJinAnswerRatingReadyForGateGeneration(generation));
    }

    function markBubbleRatingL1State(bubble) {
        if (!bubble) {
            return;
        }

        const blocked = isRatingInteractionBlocked();
        const ready = !blocked && isBubbleRatingL1Ready(bubble);
        bubble.dataset.ratingL1Ready = ready ? "true" : "false";
        bubble.classList.toggle("jin-rating-l1-waiting", !ready);
        bubble.classList.toggle("jin-rating-interaction-blocked", blocked);

        const zones = bubble.querySelector(":scope > .jin-rating-hover-zones");
        if (zones && blocked) {
            zones.title = "rating is locked while JIN is generating";
        } else if (zones && !ready && !bubble.dataset.ratingSelected) {
            zones.title = "waiting for L1 snapshot before rating";
        } else if (zones && !bubble.dataset.ratingSelected) {
            zones.title = "";
        }
    }

    function setBubbleRatingClickAlt(bubble, count) {
        if (!bubble) {
            return;
        }

        const value = Number(count || 0);
        if (!Number.isFinite(value) || value <= 0) {
            bubble.removeAttribute("alt");
            bubble.removeAttribute("aria-label");
            bubble.removeAttribute("title");
            delete bubble.dataset.ratingClickAlt;
            return;
        }

        const label = String(Math.trunc(value));
        bubble.dataset.ratingClickAlt = label;
        bubble.setAttribute("alt", label);
        bubble.setAttribute("aria-label", label);
        bubble.setAttribute("title", label);
    }

    function clearBubbleRatingIntensity(bubble) {
        if (!bubble) {
            return;
        }

        [
            "--jin-rating-glow-alpha",
            "--jin-rating-inner-alpha",
            "--jin-rating-text-alpha",
            "--jin-rating-edge-strong-alpha",
            "--jin-rating-edge-mid-alpha",
            "--jin-rating-edge-soft-alpha",
            "--jin-rating-edge-opacity",
            "--jin-rating-edge-flash-opacity",
            "--jin-rating-edge-mid-opacity",
            "--jin-rating-saturation",
            "--jin-rating-brightness",
        ].forEach((property) => {
            bubble.style.removeProperty(property);
        });
    }

    function setBubbleRatingIntensity(bubble, count) {
        if (!bubble) {
            return;
        }

        const rawCount = Number(count || 0);
        if (!Number.isFinite(rawCount) || rawCount <= 0) {
            clearBubbleRatingIntensity(bubble);
            return;
        }

        const clampedCount = Math.min(100, Math.max(1, Math.trunc(rawCount)));
        const progress = (clampedCount - 1) / 99;
        const easedProgress = progress * progress * (3 - (2 * progress));

        const glowAlpha = 0.115 + (easedProgress * 0.145);
        const innerAlpha = 0.060 + (easedProgress * 0.085);
        const textAlpha = 0.080 + (easedProgress * 0.065);
        const edgeStrongAlpha = 0.155 + (easedProgress * 0.145);
        const edgeMidAlpha = 0.065 + (easedProgress * 0.075);
        const edgeSoftAlpha = 0.020 + (easedProgress * 0.045);
        const edgeOpacity = 0.56 + (easedProgress * 0.28);
        const edgeFlashOpacity = 0.72 + (easedProgress * 0.18);
        const edgeMidOpacity = 0.62 + (easedProgress * 0.18);
        const saturation = 1.040 + (easedProgress * 0.075);
        const brightness = 1.020 + (easedProgress * 0.055);

        bubble.style.setProperty("--jin-rating-glow-alpha", glowAlpha.toFixed(3));
        bubble.style.setProperty("--jin-rating-inner-alpha", innerAlpha.toFixed(3));
        bubble.style.setProperty("--jin-rating-text-alpha", textAlpha.toFixed(3));
        bubble.style.setProperty("--jin-rating-edge-strong-alpha", edgeStrongAlpha.toFixed(3));
        bubble.style.setProperty("--jin-rating-edge-mid-alpha", edgeMidAlpha.toFixed(3));
        bubble.style.setProperty("--jin-rating-edge-soft-alpha", edgeSoftAlpha.toFixed(3));
        bubble.style.setProperty("--jin-rating-edge-opacity", edgeOpacity.toFixed(3));
        bubble.style.setProperty("--jin-rating-edge-flash-opacity", edgeFlashOpacity.toFixed(3));
        bubble.style.setProperty("--jin-rating-edge-mid-opacity", edgeMidOpacity.toFixed(3));
        bubble.style.setProperty("--jin-rating-saturation", saturation.toFixed(3));
        bubble.style.setProperty("--jin-rating-brightness", brightness.toFixed(3));
    }

    function addRatingHoverZones(root) {
        const scope = root instanceof Element ? root : document;

        scope.querySelectorAll(ratingBubbleSelector).forEach((bubble) => {
            bubble.classList.add("jin-chat-bubble-rateable");

            if (bubble.querySelector(":scope > .jin-rating-hover-zones")) {
                markBubbleRatingL1State(bubble);
                return;
            }

            if (!bubble.dataset.ratingGateGeneration) {
                bubble.dataset.ratingGateGeneration = String(getCurrentRatingGateGeneration());
            }

            markBubbleRatingL1State(bubble);

            const zones = document.createElement("div");
            zones.className = "jin-rating-hover-zones";
            zones.setAttribute("aria-hidden", "true");

            [
                ["jin-rating-zone jin-rating-zone-minus", "minus", "negative feedback hover zone"],
                ["jin-rating-zone jin-rating-zone-neutral", "neutral", "neutral feedback hover zone"],
                ["jin-rating-zone jin-rating-zone-plus", "plus", "positive feedback hover zone"],
            ].forEach(([className, ratingValue, label]) => {
                const zone = document.createElement("div");
                zone.className = className;
                zone.dataset.ratingValue = ratingValue;
                zone.dataset.ratingHover = label;

                zone.addEventListener("click", (event) => {
                    event.preventDefault();
                    event.stopPropagation();

                    if (
                        bubble.classList.contains("jin-rating-committed")
                        || bubble.dataset.ratingCommitted === "true"
                        || bubble.dataset.ratingPastTurn === "true"
                        || isRatingInteractionBlocked()
                    ) {
                        markBubbleRatingL1State(bubble);
                        return;
                    }

                    // Generation guard: if a newer turn has already been
                    // submitted, this bubble's gate generation is below the
                    // lock threshold — treat it as permanently committed.
                    const bubbleGen = Number(bubble.dataset.ratingGateGeneration || 0);
                    const gateState = window.getJinAnswerRatingL1GateState
                        ? window.getJinAnswerRatingL1GateState()
                        : {};
                    const lockedBelow = Number(gateState.lockedBelowGeneration || 0);
                    if (bubbleGen > 0 && bubbleGen < lockedBelow) {
                        bubble.classList.add("jin-rating-committed");
                        bubble.dataset.ratingCommitted = "true";
                        bubble.dataset.ratingPastTurn = "true";
                        markBubbleRatingL1State(bubble);
                        return;
                    }

                    markBubbleRatingL1State(bubble);

                    const globalCounts = window.jinAnswerRatingCounts || {
                        minus: 0,
                        neutral: 0,
                        plus: 0,
                        total: 0,
                    };

                    globalCounts[ratingValue] = (globalCounts[ratingValue] || 0) + 1;
                    globalCounts.total = (globalCounts.total || 0) + 1;
                    window.jinAnswerRatingCounts = globalCounts;

                    const bubbleClickCount = Number(bubble.dataset.ratingClickCount || 0) + 1;
                    const bubbleRatingCountKey = `rating${ratingValue[0].toUpperCase()}${ratingValue.slice(1)}Count`;
                    const previousRating = bubble.dataset.ratingSelected || null;
                    const activeRatingClickCount = Number(bubble.dataset[bubbleRatingCountKey] || 0) + 1;

                    bubble.dataset.ratingSelected = ratingValue;
                    bubble.dataset.ratingPending = "true";
                    bubble.dataset.ratingClickCount = String(bubbleClickCount);
                    bubble.dataset[bubbleRatingCountKey] = String(activeRatingClickCount);
                    setBubbleRatingIntensity(bubble, activeRatingClickCount);

                    bubble.classList.remove(...ratingSelectionClasses);

                    const pressClass = `jin-rating-press-${ratingValue}`;
                    // Restart click animation even if the same zone is clicked twice.
                    void bubble.offsetWidth;

                    bubble.classList.add(
                        "jin-rating-selected-active",
                        `jin-rating-selected-${ratingValue}`,
                        pressClass
                    );

                    window.setTimeout(() => {
                        bubble.classList.remove(pressClass);
                    }, 680);

                    setBubbleRatingClickAlt(bubble, activeRatingClickCount);
                    zones.title = String(activeRatingClickCount);

                    const ratingDetail = {
                        rating: ratingValue,
                        previousRating,
                        bubbleClickCount,
                        clicks_count: activeRatingClickCount,
                        activeRatingClickCount,
                        pending: true,
                        globalCounts: { ...globalCounts },
                        runtimeSnapshotIndex: bubble.dataset.runtimeSnapshotIndex || null,
                        ratingGateGeneration: bubble.dataset.ratingGateGeneration || null,
                    };

                    if (window.recordJinAnswerRating) {
                        window.recordJinAnswerRating(ratingDetail);
                    }

                    bubble.dispatchEvent(new CustomEvent("jin:answer-rating-clicked", {
                        bubbles: true,
                        detail: ratingDetail,
                    }));
                });

                zones.appendChild(zone);
            });

            bubble.appendChild(zones);
        });
    }

    window.addEventListener("jin:l1-rating-gate-ready", () => {
        addRatingHoverZones(document);
    });

    window.addEventListener("jin:generation-state-changed", () => {
        document
            .querySelectorAll(ratingBubbleSelector)
            .forEach(markBubbleRatingL1State);
    });

    addRatingHoverZones(document);

    document.addEventListener("click", (event) => {
        if (event.target.closest(ratingBubbleSelector)) {
            return;
        }

        const answerRow = event.target.closest(".jin-message-row");
        if (
            !answerRow
            || !answerRow.querySelector(ratingBubbleSelector)
        ) {
            return;
        }

        answerRow
            .querySelectorAll(activeRatingBubbleSelector)
            .forEach((bubble) => clearBubbleRating(bubble, "answer-row-outside-bubble"));
    });

    const chatForm = document.getElementById("chat-form");
    if (chatForm) {
        chatForm.addEventListener("submit", () => {
            document
                .querySelectorAll(activeRatingBubbleSelector)
                .forEach((bubble) => {
                    bubble.classList.remove("jin-rating-selected-active");
                    bubble.classList.add("jin-rating-committed");
                    bubble.dataset.ratingPending = "false";
                    bubble.dataset.ratingCommitted = "true";

                    const zones = bubble.querySelector(":scope > .jin-rating-hover-zones");
                    if (zones) {
                        zones.title = bubble.dataset.ratingClickAlt || "";
                    }

                    bubble.dispatchEvent(new CustomEvent("jin:answer-rating-committed", {
                        bubbles: true,
                        detail: {
                            rating: bubble.dataset.ratingSelected || null,
                            bubbleClickCount: Number(bubble.dataset.ratingClickCount || 0),
                        },
                    }));
                });
        });
    }

    const chatHistory = document.getElementById("chat-history");
    if (!chatHistory) {
        return;
    }

    const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
            mutation.addedNodes.forEach((node) => {
                if (node.nodeType === Node.ELEMENT_NODE) {
                    addRatingHoverZones(node);
                }
            });
        });
    });

    observer.observe(chatHistory, {
        childList: true,
        subtree: true,
    });
})();
