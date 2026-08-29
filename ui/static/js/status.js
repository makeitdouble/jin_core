// status.js

// -----------------------------------
// ELEMENTS
// -----------------------------------

const brainDot = document.querySelector("#brain-dot");
const brainLabel = document.querySelector("#brain-label");
const brainStatusButton = document.querySelector("#brain-status");

const serviceDot = document.querySelector("#service-dot");
const serviceLabel = document.querySelector("#service-label");
const serviceStatusButton = document.querySelector("#service-status");

const STATUS_REFRESH_COOLDOWN_MS = 1000;

let runtimeStatusRequestInFlight = false;
let lastRuntimeStatusStartedAt = 0;
let runtimeStatusModal = null;
let runtimeStatusModalTitle = null;
let runtimeStatusModalContent = null;
let activeRuntimeStatusRole = "";
let activeRuntimeStatusModelPicker = null;

function formatRuntimeStatusBytes(value) {
    const bytes = Number(value || 0);

    if (!Number.isFinite(bytes) || bytes <= 0) {
        return "";
    }

    const units = ["B", "KB", "MB", "GB", "TB"];
    let amount = bytes;
    let unitIndex = 0;

    while (amount >= 1024 && unitIndex < units.length - 1) {
        amount /= 1024;
        unitIndex += 1;
    }

    const precision = amount >= 100 || unitIndex === 0 ? 0 : 1;
    return `${amount.toFixed(precision)} ${units[unitIndex]}`;
}

function formatRuntimeStatusQuantization(value) {
    if (value === null || value === undefined || value === "") {
        return "";
    }

    if (typeof value !== "object" || Array.isArray(value)) {
        return String(value);
    }

    const name = findRuntimeStatusValue(
        value,
        "name",
        "quantization_level",
        "quant"
    );

    if (name !== null && name !== undefined && name !== "") {
        return String(name);
    }

    const bitsPerWeight = Number(
        findRuntimeStatusValue(
            value,
            "bits_per_weight",
            "bits"
        )
    );

    if (Number.isFinite(bitsPerWeight) && bitsPerWeight > 0) {
        return `${bitsPerWeight} bpw`;
    }

    return "";
}

function formatRuntimeStatusValue(value) {
    if (value === null || value === undefined || value === "") {
        return "";
    }

    if (Array.isArray(value)) {
        return value
            .map(item => String(item || "").trim())
            .filter(Boolean)
            .join(", ");
    }

    if (typeof value === "boolean") {
        return value ? "yes" : "no";
    }

    return String(value);
}

function appendRuntimeStatusField(container, labelText, value) {
    const hasNodeValue = (
        typeof Node !== "undefined"
        && value instanceof Node
    );
    const text = hasNodeValue
        ? ""
        : formatRuntimeStatusValue(value).trim();

    if (!container || (!hasNodeValue && !text)) {
        return false;
    }

    const field = document.createElement("div");
    field.className = "delayed-memory-modal-field";

    const label = document.createElement("div");
    label.className = "delayed-memory-modal-label";
    label.textContent = String(labelText || "");

    const content = document.createElement("div");
    content.className = "delayed-memory-modal-value break-words";

    if (hasNodeValue) {
        content.appendChild(value);
    } else {
        content.textContent = text;
    }

    field.append(label, content);
    container.appendChild(field);
    return true;
}

function appendRuntimeStatusCard(container, titleText, fields) {
    if (!container) {
        return;
    }

    const card = document.createElement("div");
    card.className = "jin-context-card jin-context-card-plain delayed-memory-modal-card";

    const header = document.createElement("div");
    header.className = "jin-context-card-header delayed-memory-modal-card-header";
    header.title = "Click to collapse / expand";
    header.tabIndex = 0;
    header.setAttribute("role", "button");
    header.setAttribute("aria-expanded", "true");

    const heading = document.createElement("div");
    heading.className = "jin-context-card-heading";

    const title = document.createElement("div");
    title.className = "jin-context-card-title delayed-memory-modal-card-title";
    title.textContent = `[ ${String(titleText || "").trim()} ]`;
    heading.appendChild(title);
    header.appendChild(heading);

    const toggle = () => {
        const collapsed = !card.classList.contains("is-collapsed");
        card.classList.toggle("is-collapsed", collapsed);
        header.setAttribute("aria-expanded", collapsed ? "false" : "true");
    };

    header.addEventListener("click", toggle);
    header.addEventListener("keydown", (event) => {
        if (event.target !== header) {
            return;
        }

        if (event.key !== "Enter" && event.key !== " ") {
            return;
        }

        event.preventDefault();
        toggle();
    });

    const body = document.createElement("div");
    body.className = "jin-context-card-body delayed-memory-modal-card-body";

    const fieldList = document.createElement("div");
    fieldList.className = "delayed-memory-modal-fields";

    let appended = false;
    fields.forEach(([label, value]) => {
        appended = appendRuntimeStatusField(fieldList, label, value) || appended;
    });

    if (!appended) {
        appendRuntimeStatusField(fieldList, "status", "metadata unavailable");
    }

    body.appendChild(fieldList);
    card.append(header, body);
    container.appendChild(card);
}

function getRuntimeStatusModelId(model) {
    return String(
        (
            model
            && typeof model === "object"
            && (
                model.id
                || model.key
                || model.model
                || model.name
            )
        )
        || ""
    ).trim();
}

function getRuntimeStatusModelName(model) {
    return String(
        (
            model
            && typeof model === "object"
            && (
                model.display_name
                || model.name
                || model.label
                || getRuntimeStatusModelId(model)
            )
        )
        || ""
    ).trim();
}

function getRuntimeStatusModelOptions(lmStudio, configuredModel) {
    const options = [];
    const seen = new Set();

    function addOption(modelId, modelName) {
        const id = String(modelId || "").trim();

        if (!id || seen.has(id)) {
            return;
        }

        options.push({
            id,
            name: String(modelName || id).trim() || id,
        });
        seen.add(id);
    }

    (lmStudio.available_models || []).forEach((model) => {
        if (!model || typeof model !== "object") {
            return;
        }

        addOption(
            model.id,
            model.name
        );
    });

    addOption(
        configuredModel,
        configuredModel
    );

    return options;
}

function closeRuntimeStatusModelPicker(options = {}) {
    if (
        !activeRuntimeStatusModelPicker
        || typeof activeRuntimeStatusModelPicker.close !== "function"
    ) {
        return;
    }

    activeRuntimeStatusModelPicker.close(options);
}

function runtimeStatusModelPickerContains(target) {
    if (
        !target
        || !activeRuntimeStatusModelPicker
        || !activeRuntimeStatusModelPicker.container
    ) {
        return false;
    }

    return activeRuntimeStatusModelPicker.container.contains(target);
}

async function saveRuntimeStatusConfig(role, updates) {
    const response = await fetch(
        "/api/runtime-config",
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                role,
                ...updates,
            }),
        }
    );

    if (!response.ok) {
        throw new Error(
            `HTTP ${response.status}`
        );
    }

    applyRuntimeStatusSnapshot(
        await response.json()
    );
}

function createRuntimeStatusModelValue(
    role,
    value,
    lmStudio,
    online
) {
    const container = document.createElement("span");
    container.textContent = value;

    if (!online) {
        return container;
    }

    const options = getRuntimeStatusModelOptions(
        lmStudio,
        value
    );

    if (!options.length) {
        return container;
    }

    container.tabIndex = 0;
    container.setAttribute("role", "button");
    container.setAttribute("aria-label", "Select runtime model");
    container.classList.add("cursor-pointer");

    const picker = document.createElement("span");
    picker.className = "delayed-memory-modal-fact-picker hidden";

    const input = document.createElement("input");
    input.type = "text";
    input.className = "delayed-memory-modal-fact-input";
    input.setAttribute("aria-label", "Search models");
    input.setAttribute("autocomplete", "off");
    input.setAttribute("spellcheck", "false");

    const dropdown = document.createElement("span");
    dropdown.className = "delayed-memory-modal-fact-dropdown";

    function closePicker(options = {}) {
        picker.classList.add("hidden");
        input.value = "";
        dropdown.innerHTML = "";

        if (options.blur !== false) {
            input.blur();
        }

        if (
            activeRuntimeStatusModelPicker
            && activeRuntimeStatusModelPicker.close === closePicker
        ) {
            activeRuntimeStatusModelPicker = null;
        }
    }

    function renderOptions() {
        const query = String(input.value || "").trim().toLowerCase();
        const filteredOptions = options.filter((option) => {
            return (
                !query
                || option.id.toLowerCase().includes(query)
                || option.name.toLowerCase().includes(query)
            );
        });

        dropdown.innerHTML = "";

        if (!filteredOptions.length) {
            const empty = document.createElement("span");
            empty.className = "delayed-memory-modal-fact-empty";
            empty.textContent = "no models";
            dropdown.appendChild(empty);
            return;
        }

        filteredOptions.forEach((option, index) => {
            const optionButton = document.createElement("button");
            const id = document.createElement("span");
            const separator = document.createElement("span");
            const text = document.createElement("span");

            optionButton.type = "button";
            optionButton.className = "delayed-memory-modal-fact-option";
            optionButton.title = option.id;

            id.className = "delayed-memory-modal-fact-option-id";
            id.textContent = String(index + 1);

            separator.className =
                "delayed-memory-modal-fact-option-separator";
            separator.textContent = ".";

            text.className = "delayed-memory-modal-fact-option-text";
            text.textContent = option.name || option.id;

            optionButton.append(id, separator, text);
            optionButton.addEventListener("click", (event) => {
                event.preventDefault();
                event.stopPropagation();
                closePicker();

                if (option.id === value) {
                    return;
                }

                void saveRuntimeStatusConfig(
                    role,
                    {
                        model: option.id,
                    }
                );
            });

            dropdown.appendChild(optionButton);
        });
    }

    function openPicker() {
        if (!online) {
            return;
        }

        if (
            activeRuntimeStatusModelPicker
            && activeRuntimeStatusModelPicker.close !== closePicker
        ) {
            closeRuntimeStatusModelPicker();
        }

        activeRuntimeStatusModelPicker = {
            close: closePicker,
            container,
        };
        picker.classList.remove("hidden");
        renderOptions();
        input.focus({
            preventScroll: true,
        });
    }

    container.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        openPicker();
    });

    container.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") {
            return;
        }

        event.preventDefault();
        openPicker();
    });

    input.addEventListener("click", (event) => {
        event.stopPropagation();
    });

    input.addEventListener("input", renderOptions);
    input.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            closePicker();
            container.focus({
                preventScroll: true,
            });
            return;
        }

        if (event.key !== "Enter") {
            return;
        }

        event.preventDefault();

        const query = String(input.value || "").trim().toLowerCase();
        const nextOption = options.find((option) => {
            return (
                option.id.toLowerCase() === query
                || option.name.toLowerCase() === query
            );
        }) || options.find((option) => {
            return (
                !query
                || option.id.toLowerCase().includes(query)
                || option.name.toLowerCase().includes(query)
            );
        });

        if (!nextOption) {
            return;
        }

        closePicker();

        if (nextOption.id !== value) {
            void saveRuntimeStatusConfig(
                role,
                {
                    model: nextOption.id,
                }
            );
        }
    });

    picker.append(input, dropdown);
    container.appendChild(picker);

    return container;
}

function createRuntimeStatusConfiguredValue(role, value) {
    const editor = document.createElement("span");
    const normalizedValue = Number(value || 0);
    let savedValue = (
        Number.isFinite(normalizedValue)
        && normalizedValue > 0
    )
        ? String(Math.trunc(normalizedValue))
        : "";
    let saveTimer = null;

    editor.textContent = savedValue;
    editor.setAttribute("contenteditable", "plaintext-only");
    editor.setAttribute("spellcheck", "false");
    editor.setAttribute("role", "textbox");
    editor.setAttribute("aria-label", "Configured context");
    editor.classList.add("delayed-memory-modal-editable");

    function readNextValue() {
        return String(editor.textContent || "")
            .replace(/[^\d]/g, "")
            .trim();
    }

    function restoreSavedValue() {
        editor.textContent = savedValue;
    }

    function persistValue() {
        const nextValue = readNextValue();
        const nextNumber = Number(nextValue || 0);

        if (
            !nextValue
            || !Number.isFinite(nextNumber)
            || nextNumber <= 0
        ) {
            restoreSavedValue();
            return;
        }

        const nextText = String(Math.trunc(nextNumber));

        if (nextText === savedValue) {
            editor.textContent = savedValue;
            return;
        }

        savedValue = nextText;
        editor.textContent = savedValue;

        void saveRuntimeStatusConfig(
            role,
            {
                configured_context_window: Number(savedValue),
            }
        );
    }

    function schedulePersistValue() {
        window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(
            persistValue,
            350
        );
    }

    editor.addEventListener("input", schedulePersistValue);
    editor.addEventListener("blur", () => {
        window.clearTimeout(saveTimer);
        persistValue();
    });
    editor.addEventListener("keydown", (event) => {
        if (event.key !== "Enter") {
            return;
        }

        event.preventDefault();
        editor.blur();
    });

    return editor;
}

function closeRuntimeStatusModal() {
    if (!runtimeStatusModal) {
        return;
    }

    closeRuntimeStatusModelPicker();
    runtimeStatusModal.classList.add("hidden");
    runtimeStatusModal.classList.remove("flex");
    activeRuntimeStatusRole = "";
}

function ensureRuntimeStatusModal() {
    if (runtimeStatusModal) {
        return runtimeStatusModal;
    }

    runtimeStatusModal = document.createElement("div");
    runtimeStatusModal.id = "jin-runtime-status-modal";
    runtimeStatusModal.className =
        "delayed-memory-report-modal fixed inset-0 z-50 hidden items-center justify-center bg-black/70 p-4";

    const panel = document.createElement("div");
    panel.className =
        "delayed-memory-modal-panel w-full max-w-2xl max-h-[86vh] rounded border border-zinc-700 bg-zinc-950 shadow-2xl flex flex-col";

    const header = document.createElement("div");
    header.className =
        "h-11 shrink-0 border-b border-zinc-800 px-4 flex items-center justify-between gap-4";

    runtimeStatusModalTitle = document.createElement("div");
    runtimeStatusModalTitle.className =
        "min-w-0 truncate text-xs uppercase tracking-widest text-zinc-300";

    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className =
        "delayed-memory-modal-icon-button delayed-memory-modal-close";
    closeButton.textContent = "×";
    closeButton.setAttribute("aria-label", "Close");
    closeButton.addEventListener("click", closeRuntimeStatusModal);

    runtimeStatusModalContent = document.createElement("div");
    runtimeStatusModalContent.className =
        "delayed-memory-modal-content min-h-0 flex-1 overflow-auto p-4 text-[12px] leading-relaxed text-zinc-200 space-y-3";

    header.append(runtimeStatusModalTitle, closeButton);
    panel.append(header, runtimeStatusModalContent);
    runtimeStatusModal.appendChild(panel);
    document.body.appendChild(runtimeStatusModal);

    runtimeStatusModal.addEventListener("click", (event) => {
        if (event.target === runtimeStatusModal) {
            closeRuntimeStatusModal();
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && activeRuntimeStatusRole) {
            closeRuntimeStatusModal();
        }
    });

    document.addEventListener("click", (event) => {
        if (
            !activeRuntimeStatusRole
            || !activeRuntimeStatusModelPicker
            || runtimeStatusModelPickerContains(event.target)
        ) {
            return;
        }

        closeRuntimeStatusModelPicker();
    });

    return runtimeStatusModal;
}

function findRuntimeStatusValue(value, ...keys) {
    const wanted = new Set(
        keys
            .map(key => String(key || "").trim().toLowerCase())
            .filter(Boolean)
    );
    const queue = [value];

    while (queue.length) {
        const current = queue.shift();

        if (Array.isArray(current)) {
            current.forEach(item => {
                if (item && typeof item === "object") {
                    queue.push(item);
                }
            });
            continue;
        }

        if (!current || typeof current !== "object") {
            continue;
        }

        for (const [key, child] of Object.entries(current)) {
            if (
                wanted.has(String(key).toLowerCase())
                && child !== null
                && child !== undefined
                && child !== ""
            ) {
                return child;
            }
        }

        Object.values(current).forEach(child => {
            if (child && typeof child === "object") {
                queue.push(child);
            }
        });
    }

    return "";
}

function formatRuntimeStatusCapabilities(value) {
    if (Array.isArray(value)) {
        return value;
    }

    if (value && typeof value === "object") {
        return Object.entries(value)
            .filter(([, enabled]) => Boolean(enabled))
            .map(([key]) => key);
    }

    return value;
}

function renderRuntimeStatusModal(role) {
    const normalizedRole = String(role || "").trim().toLowerCase();
    const status = window.jinLatestStatus || {};
    const runtimeConfig = status.runtime_config || {};
    const roleConfig = runtimeConfig[normalizedRole] || {};
    const lmStudio = roleConfig.lm_studio || {};
    const model = lmStudio.model || {};
    const loadedModel = lmStudio.loaded_model || {};
    const online = Boolean(status[normalizedRole]);
    const configuredModel = (
        roleConfig.model
        || getRuntimeStatusModelId(model)
        || getRuntimeStatusModelName(model)
    );

    ensureRuntimeStatusModal();
    activeRuntimeStatusRole = normalizedRole;
    runtimeStatusModalTitle.textContent = `[ ${normalizedRole.toUpperCase()} ]`;
    closeRuntimeStatusModelPicker({
        blur: false,
    });
    runtimeStatusModalContent.replaceChildren();

    const contextLength = Number(
        findRuntimeStatusValue(
            loadedModel,
            "loaded_context_length",
            "context_length",
            "context_window",
            "n_ctx",
            "num_ctx"
        ) || 0
    );
    const maxContextLength = Number(
        findRuntimeStatusValue(
            model,
            "max_context_length",
            "max_context_window",
            "max_position_embeddings"
        ) || 0
    );

    appendRuntimeStatusCard(
        runtimeStatusModalContent,
        "runtime",
        [
            ["url", lmStudio.url],
            ["status", online ? "online" : "offline"],
            [
                "model",
                createRuntimeStatusModelValue(
                    normalizedRole,
                    configuredModel,
                    lmStudio,
                    online
                )
            ],
            [
                "route",
                normalizedRole === "brain"
                    ? "primary runtime"
                    : "dedicated worker",
            ],
        ]
    );

    appendRuntimeStatusCard(
        runtimeStatusModalContent,
        "context",
        [
            [
                "configured",
                createRuntimeStatusConfiguredValue(
                    normalizedRole,
                    roleConfig.max_tokens
                ),
            ],
            ["loaded", contextLength > 0 ? contextLength : "unknown"],
            ["maximum", maxContextLength > 0 ? maxContextLength : "unknown"],
        ]
    );

    appendRuntimeStatusCard(
        runtimeStatusModalContent,
        "lm studio",
        [
            ["loaded", lmStudio.loaded],
            ["name", findRuntimeStatusValue(model, "display_name", "name", "key", "id")],
            ["state", findRuntimeStatusValue(loadedModel, "state", "status")],
            ["instance", findRuntimeStatusValue(loadedModel, "id", "key", "model")],
            ["architecture", findRuntimeStatusValue(model, "architecture", "arch", "family")],
            [
                "quantization",
                formatRuntimeStatusQuantization(
                    findRuntimeStatusValue(
                        model,
                        "quantization",
                        "quantization_level",
                        "quant"
                    )
                )
            ],
            [
                "capabilities",
                formatRuntimeStatusCapabilities(
                    findRuntimeStatusValue(model, "capabilities", "supported_features")
                )
            ],
            ["publisher", findRuntimeStatusValue(model, "publisher", "author", "organization")],
            ["type", findRuntimeStatusValue(model, "type", "model_type")],
            ["format", findRuntimeStatusValue(model, "compatibility_type", "format")],
            [
                "size",
                formatRuntimeStatusBytes(
                    findRuntimeStatusValue(model, "size_bytes", "file_size_bytes")
                )
            ],
            [
                "metadata",
                lmStudio.source === "native"
                    ? "LM Studio native API"
                    : lmStudio.source === "openai"
                        ? "OpenAI-compatible API"
                        : "",
            ],
        ]
    );
}

async function openRuntimeStatusModal(role) {
    const normalizedRole = String(role || "").trim().toLowerCase();

    if (!runtimeStatusRoleIsOnline(normalizedRole)) {
        return;
    }

    const modal = ensureRuntimeStatusModal();

    modal.classList.remove("hidden");
    modal.classList.add("flex");
    renderRuntimeStatusModal(normalizedRole);

    await updateRuntime();

    if (activeRuntimeStatusRole === normalizedRole) {
        renderRuntimeStatusModal(normalizedRole);
    }
}

async function loadBehaviorContract() {

    try {

        const response = await fetch(
            "/api/behavior-contract",
            {
                cache: "no-store",
            }
        );

        if (!response.ok) {
            throw new Error(
                `HTTP ${response.status}`
            );
        }

        window.JIN_BEHAVIOR_CONTRACT =
            await response.json();

    } catch (err) {

        console.warn(
            "[behavior_contract] failed to load",
            err
        );

    }
}

// -----------------------------------
// UPDATE UI
// -----------------------------------

function setRuntimeButtonInteractivity(button, enabled) {
    if (!button) {
        return;
    }

    button.disabled = !enabled;
    button.setAttribute(
        "aria-disabled",
        enabled ? "false" : "true"
    );
    button.classList.toggle("cursor-pointer", enabled);
    button.classList.toggle("hover:text-zinc-200", enabled);
    button.classList.toggle("cursor-default", !enabled);
}

function setRuntimeChecking(dot, label, button, name) {

    dot.className =
        "h-2 w-2 rounded-full bg-slate-500 animate-pulse transition-all duration-300";

    label.textContent =
        name;

    setRuntimeButtonInteractivity(
        button,
        false
    );

}


function setRuntimeState(dot, label, button, name, online, configured = true) {

    if (!configured) {

        dot.className =
            "h-2 w-2 rounded-full bg-slate-600 transition-all duration-300";

        label.textContent =
            name;

        setRuntimeButtonInteractivity(
            button,
            false
        );

        return;
    }

    if (online) {

        dot.className =
            "h-2 w-2 rounded-full bg-emerald-400 animate-pulse transition-all duration-300";

        label.textContent =
            name;

    } else {

        dot.className =
            "h-2 w-2 rounded-full bg-red-500 transition-all duration-300";

        label.textContent =
            name;

    }

    setRuntimeButtonInteractivity(
        button,
        Boolean(online)
    );

}

function applyRuntimeStatusSnapshot(data) {
    window.jinLatestStatus =
        data;

    setRuntimeState(
      brainDot,
      brainLabel,
      brainStatusButton,
      "BRAIN",
      data.brain,
      true
    );

    setRuntimeState(
      serviceDot,
      serviceLabel,
      serviceStatusButton,
      "SERVICE",
      data.service,
      Boolean(data.service_configured)
    );

    window.jinRuntimeConfig = {
        serviceConfigured:
            Boolean(data.service_configured),
        formatResponse:
            data.format_response !== false,
        runtimeStatus: {
            brain: Boolean(data.brain),
            service: Boolean(data.service),
        },
        runtimeConfig:
            data.runtime_config || {}
    };

    if (window.updateRuntimePanelFromStatus) {
        window.updateRuntimePanelFromStatus(
            data
        );
    }

    if (activeRuntimeStatusRole) {
        renderRuntimeStatusModal(
            activeRuntimeStatusRole
        );
    }
}

// -----------------------------------
// MAIN LOOP
// -----------------------------------

async function updateRuntime(options = {}) {

    if (runtimeStatusRequestInFlight) {
        return;
    }

    runtimeStatusRequestInFlight = true;
    lastRuntimeStatusStartedAt = Date.now();

    const showChecking =
        Boolean(options.showChecking);

    if (showChecking) {

        setRuntimeChecking(
          brainDot,
          brainLabel,
          brainStatusButton,
          "BRAIN"
        );

        if (
            window.jinRuntimeConfig
            && window.jinRuntimeConfig.serviceConfigured
        ) {
            setRuntimeChecking(
              serviceDot,
              serviceLabel,
              serviceStatusButton,
              "SERVICE"
            );
        }

    }

    try {

        const response = await fetch(
            "/api/status",
            {
                cache: "no-store",
            }
        );

        const data = await response.json();

        applyRuntimeStatusSnapshot(
            data
        );

    } catch (err) {

        const offlineStatus = {
            brain: false,
            service: false,
            service_configured: Boolean(
                window.jinRuntimeConfig
                && window.jinRuntimeConfig.serviceConfigured
            ),
            format_response: (
                window.jinRuntimeConfig
                && window.jinRuntimeConfig.formatResponse
            ) !== false,
            runtime_config: (
                window.jinRuntimeConfig
                && window.jinRuntimeConfig.runtimeConfig
            ) || {},
        };

        applyRuntimeStatusSnapshot(
            offlineStatus
        );

    } finally {

        runtimeStatusRequestInFlight = false;

    }
}


function runtimeStatusIsHealthy() {

    const runtimeConfig =
        window.jinRuntimeConfig;

    if (
        !runtimeConfig
        || !runtimeConfig.runtimeStatus
    ) {
        return false;
    }

    return Boolean(
        runtimeConfig.runtimeStatus.brain
    );

}

function runtimeStatusRoleIsOnline(role) {
    const normalizedRole =
        String(role || "").trim().toLowerCase();
    const latestStatus =
        window.jinLatestStatus || {};
    const runtimeConfig =
        window.jinRuntimeConfig || {};
    const runtimeStatus =
        runtimeConfig.runtimeStatus || {};

    if (
        Object.prototype.hasOwnProperty.call(
            latestStatus,
            normalizedRole
        )
    ) {
        return Boolean(
            latestStatus[normalizedRole]
        );
    }

    return Boolean(
        runtimeStatus[normalizedRole]
    );
}

function refreshRuntimeStatus() {

    // Focus/visibility changes are not a polling loop. If the WebSocket is
    // already connected and the latest model status is healthy, there is
    // nothing to probe and /api/status would only hit LM Studio again.
    if (
        window.jinWebSocketConnected === true
        && runtimeStatusIsHealthy()
    ) {
        return;
    }

    if (
        Date.now() - lastRuntimeStatusStartedAt
        < STATUS_REFRESH_COOLDOWN_MS
    ) {
        return;
    }

    void updateRuntime();

}

serviceStatusButton?.addEventListener(
    "click",
    () => {
        if (!runtimeStatusRoleIsOnline("service")) {
            return;
        }

        void openRuntimeStatusModal(
            "service"
        );
    }
);

brainStatusButton?.addEventListener(
    "click",
    () => {
        if (!runtimeStatusRoleIsOnline("brain")) {
            return;
        }

        void openRuntimeStatusModal(
            "brain"
        );
    }
);

// FIRST RUN

void loadBehaviorContract();

void updateRuntime();

window.addEventListener(
    "focus",
    refreshRuntimeStatus
);

document.addEventListener(
    "visibilitychange",
    function () {

        if (!document.hidden) {
            refreshRuntimeStatus();
        }

    }
);
