(function () {
    const themeKey = "jin_theme_win95";
    const themeClass = "theme-win95";
    const titleButton = document.getElementById("app-title");

    function applyWin95Theme(enabled) {
        document.body.classList.toggle(themeClass, enabled);
        localStorage.setItem(themeKey, enabled ? "1" : "0");
    }

    applyWin95Theme(localStorage.getItem(themeKey) === "1");

    if (titleButton) {
        titleButton.addEventListener("click", function () {
            applyWin95Theme(!document.body.classList.contains(themeClass));
        });
    }
})();
