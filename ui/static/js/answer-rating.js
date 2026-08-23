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
    const ratingPressClasses = [
        "jin-rating-press-minus",
        "jin-rating-press-neutral",
        "jin-rating-press-plus",
    ];
    const ratingVisualClasses = ratingSelectionClasses.filter(
        (className) => className !== "jin-rating-committed"
    );
    const ratingCountLabels = {
        minus: "Dislikes",
        plus: "Likes",
    };
    const ratingHoverLabels = {
        minus: "Dislike answer",
        plus: "Like answer",
    };
    const ratingBubbleSelector =
        ".jin-chat-bubble-rateable, .jin-chat-bubble-service, .jin-chat-bubble-brain";
    const activeRatingBubbleSelector =
        ".jin-chat-bubble-rateable.jin-rating-selected-active:not(.jin-rating-committed), "
        + ".jin-chat-bubble-service.jin-rating-selected-active:not(.jin-rating-committed), "
        + ".jin-chat-bubble-brain.jin-rating-selected-active:not(.jin-rating-committed)";
    let latestRatingBubbleSequence = 0;

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

    function getBubbleRatingSequence(bubble) {
        return Number(bubble && bubble.dataset.ratingBubbleSequence || 0);
    }

    function ensureBubbleRatingSequence(bubble) {
        if (!bubble) {
            return 0;
        }

        const existingSequence = getBubbleRatingSequence(bubble);
        if (existingSequence > 0) {
            latestRatingBubbleSequence = Math.max(
                latestRatingBubbleSequence,
                existingSequence
            );
            return existingSequence;
        }

        latestRatingBubbleSequence += 1;
        bubble.dataset.ratingBubbleSequence = String(latestRatingBubbleSequence);
        return latestRatingBubbleSequence;
    }

    function getRatingBubblesInScope(scope) {
        const bubbles = Array.from(
            scope.querySelectorAll(ratingBubbleSelector)
        );

        if (
            scope !== document
            && scope.matches
            && scope.matches(ratingBubbleSelector)
        ) {
            bubbles.unshift(scope);
        }

        return bubbles;
    }

    function markBubbleAsPastTurn(bubble) {
        if (!bubble) {
            return;
        }

        const previousRating = bubble.dataset.ratingSelected || null;
        if (
            previousRating
            && bubble.dataset.ratingPending === "true"
            && window.clearJinAnswerRating
        ) {
            window.clearJinAnswerRating({
                previousRating,
                reason: "superseded-by-newer-answer",
                runtimeSnapshotIndex: bubble.dataset.runtimeSnapshotIndex || null,
                ratingGateGeneration: bubble.dataset.ratingGateGeneration || null,
                ratingBubbleSequence: bubble.dataset.ratingBubbleSequence || null,
            });
        }

        bubble.classList.remove(...ratingPressClasses);
        bubble.classList.remove("jin-rating-disabled");
        delete bubble.dataset.ratingDisabled;
        clearBubbleRatingModeTitle(bubble);
        bubble.classList.add("jin-rating-committed");
        bubble.dataset.ratingPending = "false";
        bubble.dataset.ratingCommitted = "true";
        bubble.dataset.ratingPastTurn = "true";

        if (!previousRating) {
            bubble.classList.remove(...ratingVisualClasses);
            clearBubbleRatingIntensity(bubble);
            setBubbleRatingClickAlt(bubble, 0);
        }

        const zones = bubble.querySelector(":scope > .jin-rating-hover-zones");
        if (zones && !previousRating) {
            zones.title = "";
        }
    }

    function syncLatestRateableBubbleState(root = document) {
        const scope = root instanceof Element ? root : document;
        getRatingBubblesInScope(scope).forEach(ensureBubbleRatingSequence);

        const allBubbles = Array.from(
            document.querySelectorAll(ratingBubbleSelector)
        );

        let latestBubble = null;
        let latestSequence = 0;

        allBubbles.forEach((bubble) => {
            const sequence = ensureBubbleRatingSequence(bubble);
            if (sequence >= latestSequence) {
                latestSequence = sequence;
                latestBubble = bubble;
            }
        });

        allBubbles.forEach((bubble) => {
            if (bubble !== latestBubble) {
                markBubbleAsPastTurn(bubble);
            }
        });

        return latestBubble;
    }

    function isLatestRateableBubble(bubble) {
        return bubble && bubble === syncLatestRateableBubbleState();
    }

    function isBubbleLockedBelowCurrentGeneration(bubble) {
        const bubbleGeneration = Number(
            bubble && bubble.dataset.ratingGateGeneration || 0
        );
        const gateState = window.getJinAnswerRatingL1GateState
            ? window.getJinAnswerRatingL1GateState()
            : {};
        const lockedBelow = Number(gateState.lockedBelowGeneration || 0);

        return Boolean(
            bubbleGeneration > 0
            && lockedBelow > 0
            && bubbleGeneration < lockedBelow
        );
    }

    function clearBubbleRatingModeTitle(bubble) {
        if (!bubble || bubble.dataset.ratingModeTitle !== "enable rating") {
            return;
        }

        bubble.removeAttribute("alt");
        bubble.removeAttribute("aria-label");
        bubble.removeAttribute("title");
        delete bubble.dataset.ratingModeTitle;
    }

    function setBubbleRatingModeTitle(bubble) {
        if (!bubble) {
            return;
        }

        const label = "enable rating";
        bubble.dataset.ratingModeTitle = label;
        bubble.setAttribute("alt", label);
        bubble.setAttribute("aria-label", label);
        bubble.setAttribute("title", label);
    }

    function disableBubbleRating(bubble) {
        if (
            !bubble
            || bubble.classList.contains("jin-rating-committed")
            || bubble.dataset.ratingCommitted === "true"
            || bubble.dataset.ratingPastTurn === "true"
        ) {
            return false;
        }

        if (!isLatestRateableBubble(bubble)) {
            markBubbleAsPastTurn(bubble);
            return false;
        }

        if (isBubbleLockedBelowCurrentGeneration(bubble)) {
            markBubbleAsPastTurn(bubble);
            return false;
        }

        const previousRating = bubble.dataset.ratingSelected || null;

        bubble.classList.remove(...ratingSelectionClasses);
        delete bubble.dataset.ratingSelected;
        delete bubble.dataset.ratingPending;
        clearBubbleRatingIntensity(bubble);
        setBubbleRatingClickAlt(bubble, 0);

        if (previousRating) {
            if (window.clearJinAnswerRating) {
                window.clearJinAnswerRating({
                    previousRating,
                    reason: "rating-disabled",
                    runtimeSnapshotIndex: bubble.dataset.runtimeSnapshotIndex || null,
                    ratingGateGeneration: bubble.dataset.ratingGateGeneration || null,
                    ratingBubbleSequence: bubble.dataset.ratingBubbleSequence || null,
                });
            }

            bubble.dispatchEvent(new CustomEvent("jin:answer-rating-cleared", {
                bubbles: true,
                detail: {
                    previousRating,
                    reason: "rating-disabled",
                },
            }));
        }

        bubble.classList.add("jin-rating-disabled");
        bubble.dataset.ratingDisabled = "true";
        setBubbleRatingModeTitle(bubble);

        bubble.dispatchEvent(new CustomEvent("jin:answer-rating-disabled", {
            bubbles: true,
        }));

        return true;
    }

    function enableBubbleRating(bubble) {
        if (
            !bubble
            || bubble.dataset.ratingDisabled !== "true"
            || bubble.classList.contains("jin-rating-committed")
            || bubble.dataset.ratingCommitted === "true"
            || bubble.dataset.ratingPastTurn === "true"
        ) {
            return false;
        }

        if (!isLatestRateableBubble(bubble) || isBubbleLockedBelowCurrentGeneration(bubble)) {
            markBubbleAsPastTurn(bubble);
            return false;
        }

        bubble.classList.remove("jin-rating-disabled");
        delete bubble.dataset.ratingDisabled;
        clearBubbleRatingModeTitle(bubble);
        markBubbleRatingL1State(bubble);

        bubble.dispatchEvent(new CustomEvent("jin:answer-rating-enabled", {
            bubbles: true,
        }));

        return true;
    }

    function clearBrowserTextSelection() {
        const clearSelection = () => {
            const selection = window.getSelection ? window.getSelection() : null;
            if (selection && selection.rangeCount) {
                selection.removeAllRanges();
            }
        };

        clearSelection();
        window.requestAnimationFrame(clearSelection);
    }

    function bindBubbleRatingModeInteractions(bubble, zones) {
        if (!bubble || bubble.dataset.ratingModeBound === "true") {
            return;
        }

        bubble.dataset.ratingModeBound = "true";

        bubble.addEventListener("dblclick", (event) => {
            if (bubble.dataset.ratingDisabled !== "true") {
                return;
            }

            if (event.target.closest && event.target.closest(".jin-chat-reference-id")) {
                return;
            }

            event.preventDefault();
            event.stopPropagation();
            if (enableBubbleRating(bubble)) {
                clearBrowserTextSelection();
            }
        });

        bubble.addEventListener("click", (event) => {
            const reference = event.target.closest
                ? event.target.closest(".jin-chat-reference-id")
                : null;

            if (!reference || bubble.dataset.ratingDisabled === "true") {
                return;
            }

            if (
                bubble.classList.contains("jin-rating-committed")
                || bubble.dataset.ratingCommitted === "true"
                || bubble.dataset.ratingPastTurn === "true"
            ) {
                return;
            }

            const rect = bubble.getBoundingClientRect();
            if (!rect.width) {
                return;
            }

            const ratio = Math.max(0, Math.min(0.999, (event.clientX - rect.left) / rect.width));
            const zoneIndex = ratio < (1 / 3)
                ? 0
                : (ratio < (2 / 3) ? 1 : 2);
            const zone = zones && zones.children
                ? zones.children[zoneIndex]
                : null;

            if (!zone) {
                return;
            }

            event.preventDefault();
            event.stopPropagation();
            zone.click();
        });
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
        const pastTurn = bubble.dataset.ratingPastTurn === "true";
        const l1Ready = isBubbleRatingL1Ready(bubble);
        const ready = !blocked && !pastTurn && l1Ready;
        const waitingForL1 = !blocked && !pastTurn && !l1Ready;
        bubble.dataset.ratingL1Ready = ready ? "true" : "false";
        bubble.classList.toggle("jin-rating-l1-waiting", waitingForL1);
        bubble.classList.toggle("jin-rating-interaction-blocked", blocked);

        const zones = bubble.querySelector(":scope > .jin-rating-hover-zones");
        if (zones && blocked) {
            zones.title = "rating is locked while JIN is generating";
        } else if (zones && waitingForL1 && !bubble.dataset.ratingSelected) {
            zones.title = "waiting for L1 snapshot before rating";
        } else if (zones && !bubble.dataset.ratingSelected) {
            zones.title = "";
        }
    }

    function getBubbleRatingCountKey(ratingValue) {
        const value = String(ratingValue || "");
        if (!value) {
            return "";
        }

        return `rating${value[0].toUpperCase()}${value.slice(1)}Count`;
    }

    function getBubbleRatingValueCount(bubble, ratingValue) {
        const key = getBubbleRatingCountKey(ratingValue);
        if (!bubble || !key) {
            return 0;
        }

        const value = Number(bubble.dataset[key] || 0);
        return Number.isFinite(value) ? Math.max(0, Math.trunc(value)) : 0;
    }

    function formatRatingValueLabel(bubble, ratingValue) {
        const count = getBubbleRatingValueCount(bubble, ratingValue);
        const countLabel = ratingCountLabels[ratingValue];

        if (countLabel && count > 0) {
            return `${countLabel}: ${count}`;
        }

        return ratingHoverLabels[ratingValue] || "";
    }

    function syncBubbleRatingZoneTitles(bubble) {
        if (!bubble) {
            return;
        }

        const zones = bubble.querySelector(":scope > .jin-rating-hover-zones");
        if (!zones) {
            return;
        }

        Array.from(zones.children || []).forEach((zone) => {
            const ratingValue = zone.dataset.ratingValue || "";
            const label = formatRatingValueLabel(bubble, ratingValue);
            if (label) {
                zone.title = label;
                zone.setAttribute("aria-label", label);
            }
        });
    }

    function setBubbleRatingClickAlt(bubble, count, ratingValue = "") {
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

        const ratingLabel = ratingCountLabels[ratingValue];
        const label = ratingLabel
            ? `${ratingLabel}: ${Math.trunc(value)}`
            : String(Math.trunc(value));
        bubble.dataset.ratingClickAlt = label;
        bubble.setAttribute("alt", label);
        bubble.setAttribute("aria-label", label);
        bubble.removeAttribute("title");
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
        syncLatestRateableBubbleState(scope);

        getRatingBubblesInScope(scope).forEach((bubble) => {
            bubble.classList.add("jin-chat-bubble-rateable");
            ensureBubbleRatingSequence(bubble);

            if (bubble.querySelector(":scope > .jin-rating-hover-zones")) {
                markBubbleRatingL1State(bubble);
                syncBubbleRatingZoneTitles(bubble);
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
                ["jin-rating-zone jin-rating-zone-minus", "minus", "Dislike answer"],
                ["jin-rating-zone jin-rating-zone-neutral", "disable", "disable rating"],
                ["jin-rating-zone jin-rating-zone-plus", "plus", "Like answer"],
            ].forEach(([className, ratingValue, label]) => {
                const zone = document.createElement("div");
                zone.className = className;
                zone.dataset.ratingValue = ratingValue;
                zone.dataset.ratingHover = label;
                zone.title = label;
                zone.setAttribute("aria-label", label);

                zone.addEventListener("click", (event) => {
                    event.preventDefault();
                    event.stopPropagation();

                    if (ratingValue === "disable") {
                        disableBubbleRating(bubble);
                        return;
                    }

                    if (
                        bubble.classList.contains("jin-rating-committed")
                        || bubble.dataset.ratingCommitted === "true"
                        || bubble.dataset.ratingPastTurn === "true"
                        || isRatingInteractionBlocked()
                    ) {
                        markBubbleRatingL1State(bubble);
                        return;
                    }

                    if (!isLatestRateableBubble(bubble)) {
                        markBubbleAsPastTurn(bubble);
                        markBubbleRatingL1State(bubble);
                        return;
                    }

                    // Generation guard: if a newer turn has already been
                    // submitted, this bubble's gate generation is below the
                    // lock threshold — treat it as permanently committed.
                    if (isBubbleLockedBelowCurrentGeneration(bubble)) {
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
                    const bubbleRatingCountKey = getBubbleRatingCountKey(ratingValue);
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

                    setBubbleRatingClickAlt(bubble, activeRatingClickCount, ratingValue);
                    zones.title = "";
                    syncBubbleRatingZoneTitles(bubble);

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
                        ratingBubbleSequence: bubble.dataset.ratingBubbleSequence || null,
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
            bindBubbleRatingModeInteractions(bubble, zones);
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
                .querySelectorAll(ratingBubbleSelector)
                .forEach((bubble) => {
                    if (
                        bubble.dataset.ratingDisabled === "true"
                        && bubble.dataset.ratingPastTurn !== "true"
                    ) {
                        markBubbleAsPastTurn(bubble);
                    }
                });

            document
                .querySelectorAll(activeRatingBubbleSelector)
                .forEach((bubble) => {
                    const committedRating =
                        bubble.dataset.ratingSelected || null;
                    const committedClickCount =
                        Number(bubble.dataset.ratingClickCount || 0);

                    bubble.classList.remove(...ratingPressClasses);
                    bubble.classList.add("jin-rating-committed");
                    bubble.dataset.ratingPending = "false";
                    bubble.dataset.ratingCommitted = "true";
                    bubble.dataset.ratingPastTurn = "true";

                    const zones = bubble.querySelector(":scope > .jin-rating-hover-zones");
                    if (!committedRating) {
                        bubble.classList.remove(...ratingVisualClasses);
                        clearBubbleRatingIntensity(bubble);
                        setBubbleRatingClickAlt(bubble, 0);
                    }

                    if (zones && !committedRating) {
                        zones.title = "";
                    }

                    bubble.dispatchEvent(new CustomEvent("jin:answer-rating-committed", {
                        bubbles: true,
                        detail: {
                            rating: committedRating,
                            bubbleClickCount: committedClickCount,
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
