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
    const text = formatRuntimeStatusValue(value).trim();

    if (!container || !text) {
        return false;
    }

    const field = document.createElement("div");
    field.className = "delayed-memory-modal-field";

    const label = document.createElement("div");
    label.className = "delayed-memory-modal-label";
    label.textContent = String(labelText || "");

    const content = document.createElement("div");
    content.className = "delayed-memory-modal-value break-words";
    content.textContent = text;

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

function closeRuntimeStatusModal() {
    if (!runtimeStatusModal) {
        return;
    }

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

    ensureRuntimeStatusModal();
    activeRuntimeStatusRole = normalizedRole;
    runtimeStatusModalTitle.textContent = `[ ${normalizedRole.toUpperCase()} ]`;
    runtimeStatusModalContent.replaceChildren();

    appendRuntimeStatusCard(
        runtimeStatusModalContent,
        "runtime",
        [
            ["status", online ? "online" : "offline"],
            [
                "model",
                roleConfig.model
                || findRuntimeStatusValue(model, "display_name", "name", "key", "id")
            ],
            ["context", roleConfig.max_tokens ? `${roleConfig.max_tokens} configured` : ""],
            [
                "route",
                normalizedRole === "brain" && status.use_service_as_brain
                    ? "service runtime"
                    : "dedicated runtime",
            ],
        ]
    );

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
    const contextText = contextLength > 0
        ? (
            maxContextLength > 0 && maxContextLength !== contextLength
                ? `${contextLength} loaded / ${maxContextLength} max`
                : `${contextLength}`
        )
        : (maxContextLength > 0 ? `${maxContextLength} max` : "");

    appendRuntimeStatusCard(
        runtimeStatusModalContent,
        "lm studio",
        [
            ["loaded", lmStudio.loaded],
            ["name", findRuntimeStatusValue(model, "display_name", "name", "key", "id")],
            ["state", findRuntimeStatusValue(loadedModel, "state", "status")],
            ["instance", findRuntimeStatusValue(loadedModel, "id", "key", "model")],
            ["context", contextText],
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
    const modal = ensureRuntimeStatusModal();
    const normalizedRole = String(role || "").trim().toLowerCase();

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

function setRuntimeChecking(dot, label, name) {

    dot.className =
        "h-2 w-2 rounded-full bg-slate-500 animate-pulse transition-all duration-300";

    label.textContent =
        name;

}


function setRuntimeState(dot, label, name, online) {

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
          "BRAIN"
        );

        setRuntimeChecking(
          serviceDot,
          serviceLabel,
          "SERVICE"
        );

    }

    try {

        const response = await fetch(
            "/api/status",
            {
                cache: "no-store",
            }
        );

        const data = await response.json();

        window.jinLatestStatus =
            data;

        setRuntimeState(
          brainDot,
          brainLabel,
          "BRAIN",
          data.brain
        );

        setRuntimeState(
          serviceDot,
          serviceLabel,
          "SERVICE",
          data.service
        );

        window.jinRuntimeConfig = {
            useServiceAsBrain:
                Boolean(
                    data.use_service_as_brain
                ),
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

    } catch (err) {

        const offlineStatus = {
            brain: false,
            service: false,
            use_service_as_brain: false,
            format_response: (
                window.jinRuntimeConfig
                && window.jinRuntimeConfig.formatResponse
            ) !== false,
            runtime_config: (
                window.jinRuntimeConfig
                && window.jinRuntimeConfig.runtimeConfig
            ) || {},
        };

        window.jinLatestStatus =
            offlineStatus;

        setRuntimeState(
          brainDot,
          brainLabel,
          "BRAIN",
          false
        );

        setRuntimeState(
          serviceDot,
          serviceLabel,
          "SERVICE",
          false
        );

        if (window.updateRuntimePanelFromStatus) {
            window.updateRuntimePanelFromStatus(
                offlineStatus
            );
        }

        if (activeRuntimeStatusRole) {
            renderRuntimeStatusModal(
                activeRuntimeStatusRole
            );
        }

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

    const status =
        runtimeConfig.runtimeStatus;

    return Boolean(
        status.service
        && (
            runtimeConfig.useServiceAsBrain
            || status.brain
        )
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
        void openRuntimeStatusModal(
            "service"
        );
    }
);

brainStatusButton?.addEventListener(
    "click",
    () => {
        void openRuntimeStatusModal(
            "brain"
        );
    }
);

// FIRST RUN

void loadBehaviorContract();

void updateRuntime({
    showChecking: !(
        window.jinRuntimeConfig
        && window.jinRuntimeConfig.runtimeStatus
    ),
});

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
