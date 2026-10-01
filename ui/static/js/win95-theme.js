(function () {
    const themeKey = "jin_theme_win95";
    const themeClass = "theme-win95";
    const bubbleSkinKey = "jin_bubble_skin";
    const bubbleSkinPinnedKey = "jin_bubble_skin_pinned";
    const bubbleSkinClasses = {
        dark: "jin-bubble-skin-dark",
        light: "jin-bubble-skin-light",
        bamboo: "jin-bubble-skin-bamboo",
    };
    const validBubbleSkins = new Set(
        Object.keys(bubbleSkinClasses)
    );
    const titleButton = document.getElementById("app-title");
    let bubbleSkinPinned = false;

    function readStoredValue(key) {
        try {
            return window.localStorage
                ? window.localStorage.getItem(key)
                : null;
        } catch (error) {
            return null;
        }
    }

    function writeStoredValue(key, value) {
        try {
            if (window.localStorage) {
                window.localStorage.setItem(key, value);
            }
        } catch (error) {
            // Appearance switching should still work in restricted browsers.
        }
    }

    function readStoredTheme() {
        return readStoredValue(themeKey);
    }

    function writeStoredTheme(enabled) {
        writeStoredValue(
            themeKey,
            enabled ? "1" : "0"
        );
    }

    function normalizeBubbleSkin(value) {
        const normalized = String(value || "")
            .trim()
            .toLowerCase();

        return validBubbleSkins.has(normalized)
            ? normalized
            : "";
    }

    function themeDefaultBubbleSkin(win95Enabled) {
        return win95Enabled ? "light" : "dark";
    }

    function getCurrentBubbleSkin() {
        const datasetSkin = normalizeBubbleSkin(
            document.body.dataset.jinBubbleSkin
        );

        if (datasetSkin) {
            return datasetSkin;
        }

        for (const [skin, className] of Object.entries(bubbleSkinClasses)) {
            if (document.body.classList.contains(className)) {
                return skin;
            }
        }

        return themeDefaultBubbleSkin(
            document.body.classList.contains(themeClass)
        );
    }

    function writeStoredBubbleSkinState(skin) {
        writeStoredValue(
            bubbleSkinKey,
            skin
        );
        writeStoredValue(
            bubbleSkinPinnedKey,
            bubbleSkinPinned ? "1" : "0"
        );
    }

    function applyBubbleSkin(
        skin,
        options = {}
    ) {
        const normalized = normalizeBubbleSkin(skin)
            || themeDefaultBubbleSkin(
                document.body.classList.contains(themeClass)
            );

        if (typeof options.pinned === "boolean") {
            bubbleSkinPinned = options.pinned;
        }

        Object.values(bubbleSkinClasses).forEach((className) => {
            document.body.classList.remove(className);
        });
        document.body.classList.add(
            bubbleSkinClasses[normalized]
        );
        document.body.dataset.jinBubbleSkin = normalized;
        const customBubble = normalized !== "dark" && normalized !== "light";
        document.body.classList.toggle("default-theme-bubble", !customBubble);
        document.body.classList.toggle("custom-theme-bubble", customBubble);

        if (options.persist !== false) {
            writeStoredBubbleSkinState(normalized);
        }

        if (options.emit !== false) {
            window.dispatchEvent(
                new CustomEvent(
                    "jin:bubble-skin-changed",
                    {
                        detail: {
                            skin: normalized,
                            pinned: bubbleSkinPinned,
                        },
                    }
                )
            );
        }

        return normalized;
    }

    function setBubbleSkinFromUser(skin) {
        const normalized = normalizeBubbleSkin(skin);

        if (!normalized) {
            return getCurrentBubbleSkin();
        }

        const themeDefault =
            themeDefaultBubbleSkin(
                document.body.classList.contains(themeClass)
            );

        return applyBubbleSkin(
            normalized,
            {
                pinned: normalized !== themeDefault,
            }
        );
    }

    function refreshPanelHeights() {
        if (
            window.JinPanels
            && typeof window.JinPanels.refreshCollapsedPanelHeights === "function"
        ) {
            window.requestAnimationFrame(
                window.JinPanels.refreshCollapsedPanelHeights
            );
        }
    }

    function applyWin95Theme(
        enabled,
        options = {}
    ) {
        document.body.classList.toggle(
            themeClass,
            enabled
        );

        if (options.persist !== false) {
            writeStoredTheme(enabled);
        }

        if (!bubbleSkinPinned) {
            applyBubbleSkin(
                themeDefaultBubbleSkin(enabled),
                {
                    pinned: false,
                    persist: options.persist !== false,
                }
            );
        }

        refreshPanelHeights();
    }

    function readStoredPinnedState(storedSkin, win95Enabled) {
        const storedPinned =
            readStoredValue(bubbleSkinPinnedKey);

        if (storedPinned === "1") {
            return true;
        }

        if (storedPinned === "0") {
            return false;
        }

        // Migration from the first skin-only storage shape: a mismatch already
        // means the user explicitly chose a skin that should stay pinned.
        return Boolean(
            storedSkin
            && storedSkin !== themeDefaultBubbleSkin(win95Enabled)
        );
    }

    function syncAppearanceFromStorage() {
        const win95Enabled =
            readStoredTheme() === "1";
        const storedSkin = normalizeBubbleSkin(
            readStoredValue(bubbleSkinKey)
        );
        const pinned = readStoredPinnedState(
            storedSkin,
            win95Enabled
        );
        const skin = pinned
            ? (storedSkin || themeDefaultBubbleSkin(win95Enabled))
            : themeDefaultBubbleSkin(win95Enabled);

        document.body.classList.toggle(
            themeClass,
            win95Enabled
        );
        applyBubbleSkin(
            skin,
            {
                pinned,
                persist: false,
            }
        );
        refreshPanelHeights();
    }

    const initialWin95Enabled =
        readStoredTheme() === "1";
    const initialStoredSkin =
        normalizeBubbleSkin(
            readStoredValue(bubbleSkinKey)
        );
    const initialPinned =
        readStoredPinnedState(
            initialStoredSkin,
            initialWin95Enabled
        );
    const initialSkin = initialPinned
        ? (initialStoredSkin || themeDefaultBubbleSkin(initialWin95Enabled))
        : themeDefaultBubbleSkin(initialWin95Enabled);

    document.body.classList.toggle(
        themeClass,
        initialWin95Enabled
    );

    applyBubbleSkin(
        initialSkin,
        {
            pinned: initialPinned,
            emit: false,
        }
    );

    window.JinAppearance = Object.freeze({
        bubbleSkins: Object.freeze([
            "dark",
            "light",
            "bamboo",
        ]),
        getBubbleSkin: getCurrentBubbleSkin,
        getThemeDefaultBubbleSkin: function () {
            return themeDefaultBubbleSkin(
                document.body.classList.contains(themeClass)
            );
        },
        isBubbleSkinPinned: function () {
            return bubbleSkinPinned;
        },
        isWin95Theme: function () {
            return document.body.classList.contains(themeClass);
        },
        setBubbleSkin: setBubbleSkinFromUser,
        setWin95Theme: function (enabled) {
            applyWin95Theme(Boolean(enabled));
        },
    });

    if (titleButton) {
        titleButton.addEventListener("click", function () {
            applyWin95Theme(
                !document.body.classList.contains(themeClass)
            );
        });
    }

    window.addEventListener("storage", function (event) {
        if (event.storageArea !== window.localStorage) {
            return;
        }

        if (
            event.key === themeKey
            || event.key === bubbleSkinKey
            || event.key === bubbleSkinPinnedKey
        ) {
            syncAppearanceFromStorage();
        }
    });
})();
