(function () {
    const themeKey = "jin_theme_win95";
    const themeClass = "theme-win95";
    const titleButton = document.getElementById("app-title");

    function readStoredTheme() {
        try {
            return window.localStorage
                ? window.localStorage.getItem(themeKey)
                : null;
        } catch (error) {
            return null;
        }
    }

    function writeStoredTheme(enabled) {
        try {
            if (window.localStorage) {
                window.localStorage.setItem(themeKey, enabled ? "1" : "0");
            }
        } catch (error) {
            // Theme switching should still work in restricted browser contexts.
        }
    }

    function applyWin95Theme(enabled) {
        document.body.classList.toggle(themeClass, enabled);
        writeStoredTheme(enabled);

        if (
            window.JinPanels
            && typeof window.JinPanels.refreshCollapsedPanelHeights === "function"
        ) {
            window.requestAnimationFrame(
                window.JinPanels.refreshCollapsedPanelHeights
            );
        }
    }

    applyWin95Theme(readStoredTheme() === "1");

    if (titleButton) {
        titleButton.addEventListener("click", function () {
            applyWin95Theme(!document.body.classList.contains(themeClass));
        });
    }
})();
