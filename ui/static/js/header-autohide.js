(function () {
    "use strict";

    const header = document.getElementById("app-header");
    const consolePanel = document.getElementById("console-panel");
    const memoryPanel = document.getElementById("memory-panel");
    const chatHistory = document.getElementById("chat-history");

    if (!header) {
        return;
    }

    const panels = [
        consolePanel,
        memoryPanel,
    ].filter(Boolean);

    const HEADER_VISIBLE_CLASS = "app-header-visible";
    const HEADER_HEIGHT_VAR = "--app-header-height";
    const PANEL_SHIFT_VAR = "--app-header-panel-shift";
    const DEFAULT_PANEL_GAP = 8;
    const CHAT_CONTENT_SELECTOR = [
        ".jin-chat-avatar",
        ".jin-chat-bubble",
        ".jin-message-copy-control",
        ".jin-think-content",
        ".jin-runtime-action-row > *",
        ".jin-session-restore-divider",
    ].join(", ");
    const SHOW_DELAY_MS = 333;
    const HIDE_DELAY_MS = 1000;

    let headerHeight = 40;
    let revealZoneHeight = 80;
    let lastPointerY = Number.POSITIVE_INFINITY;
    let interactionHeld = false;
    let pointerOccludedByPanel = false;
    let pointerOccludedByChatContent = false;
    let visible = false;
    let panelSyncFrameId = null;
    let showTimerId = null;
    let hideTimerId = null;

    function finiteNumber(value, fallback = 0) {
        const number = Number(value);
        return Number.isFinite(number)
            ? number
            : fallback;
    }

    function parsePanelGap(panel) {
        const root = panel && panel.parentElement
            ? panel.parentElement
            : document.documentElement;
        const raw = getComputedStyle(root)
            .getPropertyValue("--panel-gap")
            .trim();
        const parsed = Number.parseFloat(raw);

        return Number.isFinite(parsed)
            ? parsed
            : DEFAULT_PANEL_GAP;
    }

    function measureHeader() {
        const rect = header.getBoundingClientRect();
        const measured = rect.height || header.offsetHeight || 40;

        headerHeight = Math.max(1, measured);
        revealZoneHeight = headerHeight * 2;
        document.documentElement.style.setProperty(
            HEADER_HEIGHT_VAR,
            `${headerHeight}px`
        );
    }

    function setPanelShift(panel, shift) {
        const safeShift = Math.max(0, finiteNumber(shift, 0));
        const next = `${safeShift}px`;

        if (panel.style.getPropertyValue(PANEL_SHIFT_VAR) === next) {
            return;
        }

        panel.style.setProperty(
            PANEL_SHIFT_VAR,
            next
        );
    }

    function getLogicalPanelViewportTop(panel) {
        const parent = panel.offsetParent || panel.parentElement;
        const parentRect = parent
            ? parent.getBoundingClientRect()
            : { top: 0 };

        return parentRect.top + finiteNumber(panel.offsetTop, 0);
    }

    function syncPanelShifts() {
        panelSyncFrameId = null;

        for (const panel of panels) {
            if (!visible) {
                setPanelShift(panel, 0);
                continue;
            }

            const gap = parsePanelGap(panel);
            const logicalTop = getLogicalPanelViewportTop(panel);
            const clearanceBottom = headerHeight + gap;
            const shift = Math.max(
                0,
                clearanceBottom - logicalTop
            );

            setPanelShift(panel, shift);
        }

        if (visible) {
            panelSyncFrameId = window.requestAnimationFrame(
                syncPanelShifts
            );
        }
    }

    function startPanelSync() {
        if (panelSyncFrameId !== null) {
            return;
        }

        panelSyncFrameId = window.requestAnimationFrame(
            syncPanelShifts
        );
    }

    function stopPanelSync() {
        if (panelSyncFrameId !== null) {
            window.cancelAnimationFrame(panelSyncFrameId);
            panelSyncFrameId = null;
        }

        for (const panel of panels) {
            setPanelShift(panel, 0);
        }
    }

    function setVisible(nextVisible) {
        const next = Boolean(nextVisible);

        if (visible === next) {
            if (visible) {
                startPanelSync();
            }
            return;
        }

        visible = next;
        document.body.classList.toggle(
            HEADER_VISIBLE_CLASS,
            visible
        );

        if (visible) {
            measureHeader();
            startPanelSync();
        } else {
            stopPanelSync();
        }
    }

    function shouldReveal() {
        return interactionHeld
            || (
                !pointerOccludedByPanel
                && !pointerOccludedByChatContent
                && lastPointerY <= revealZoneHeight
            );
    }

    function cancelPendingReveal() {
        if (showTimerId === null) {
            return;
        }

        window.clearTimeout(showTimerId);
        showTimerId = null;
    }

    function scheduleReveal() {
        if (visible || showTimerId !== null) {
            return;
        }

        showTimerId = window.setTimeout(() => {
            showTimerId = null;

            if (shouldReveal()) {
                cancelPendingHide();
                setVisible(true);
            }
        }, SHOW_DELAY_MS);
    }

    function cancelPendingHide() {
        if (hideTimerId === null) {
            return;
        }

        window.clearTimeout(hideTimerId);
        hideTimerId = null;
    }

    function scheduleHide() {
        if (!visible || hideTimerId !== null) {
            return;
        }

        hideTimerId = window.setTimeout(() => {
            hideTimerId = null;

            if (!shouldReveal()) {
                setVisible(false);
            }
        }, HIDE_DELAY_MS);
    }

    function refreshVisibility() {
        if (shouldReveal()) {
            cancelPendingHide();

            if (visible) {
                return;
            }

            scheduleReveal();
            return;
        }

        cancelPendingReveal();
        scheduleHide();
    }

    function pointerIsOnOccludingPanel(target) {
        return Boolean(
            target
            && panels.some((panel) => panel.contains(target))
        );
    }

    function pointerIsOnChatContent(target) {
        return Boolean(
            chatHistory
            && target
            && typeof target.closest === "function"
            && chatHistory.contains(target)
            && target.closest(CHAT_CONTENT_SELECTOR)
        );
    }

    function pointerIsOnHeldSurface(target) {
        return Boolean(
            target
            && (
                header.contains(target)
                || pointerIsOnOccludingPanel(target)
            )
        );
    }

    function updatePointerState(event, fallbackY) {
        const target = event ? event.target : null;

        lastPointerY = finiteNumber(
            event ? event.clientY : fallbackY,
            fallbackY
        );
        pointerOccludedByPanel = pointerIsOnOccludingPanel(target);
        pointerOccludedByChatContent = pointerIsOnChatContent(target);
    }

    function handlePointerMove(event) {
        updatePointerState(
            event,
            Number.POSITIVE_INFINITY
        );
        refreshVisibility();
    }

    function handlePointerDown(event) {
        updatePointerState(event, lastPointerY);

        if (
            visible
            && pointerIsOnHeldSurface(event.target)
        ) {
            interactionHeld = true;
        }

        refreshVisibility();
    }

    function releaseInteraction(event) {
        interactionHeld = false;
        updatePointerState(event, lastPointerY);
        refreshVisibility();
    }

    function handleDocumentLeave() {
        lastPointerY = Number.POSITIVE_INFINITY;
        pointerOccludedByPanel = false;
        pointerOccludedByChatContent = false;
        interactionHeld = false;
        refreshVisibility();
    }

    function getComputedPanelShift(panel) {
        if (!panel) {
            return 0;
        }

        const transform = getComputedStyle(panel).transform;

        if (!transform || transform === "none") {
            return 0;
        }

        if (typeof DOMMatrixReadOnly === "function") {
            try {
                return finiteNumber(
                    new DOMMatrixReadOnly(transform).m42,
                    0
                );
            } catch (_error) {
                // Fall through to the matrix parser below.
            }
        }

        const matrix3d = transform.match(/^matrix3d\((.+)\)$/);
        if (matrix3d) {
            const values = matrix3d[1]
                .split(",")
                .map((value) => Number.parseFloat(value.trim()));
            return finiteNumber(values[13], 0);
        }

        const matrix2d = transform.match(/^matrix\((.+)\)$/);
        if (matrix2d) {
            const values = matrix2d[1]
                .split(",")
                .map((value) => Number.parseFloat(value.trim()));
            return finiteNumber(values[5], 0);
        }

        return 0;
    }

    window.JinHeaderAutoHide = Object.assign(
        window.JinHeaderAutoHide || {},
        {
            getPanelShift: getComputedPanelShift,
            isVisible: () => visible,
            refresh: () => {
                measureHeader();
                refreshVisibility();
                if (visible) {
                    startPanelSync();
                }
            },
        }
    );

    measureHeader();
    setVisible(false);

    window.addEventListener(
        "pointermove",
        handlePointerMove,
        { passive: true }
    );
    window.addEventListener(
        "pointerdown",
        handlePointerDown,
        { passive: true }
    );
    window.addEventListener(
        "pointerup",
        releaseInteraction,
        { passive: true }
    );
    window.addEventListener(
        "pointercancel",
        releaseInteraction,
        { passive: true }
    );
    window.addEventListener(
        "blur",
        handleDocumentLeave
    );
    window.addEventListener(
        "resize",
        () => {
            measureHeader();
            refreshVisibility();
            if (visible) {
                startPanelSync();
            }
        }
    );
    document.documentElement.addEventListener(
        "mouseleave",
        handleDocumentLeave
    );
})();
