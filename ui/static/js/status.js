// status.js

// -----------------------------------
// ELEMENTS
// -----------------------------------

const brainDot = document.querySelector("#brain-dot");
const brainLabel = document.querySelector("#brain-label");

const serviceDot = document.querySelector("#service-dot");
const serviceLabel = document.querySelector("#service-label");

const STATUS_REFRESH_COOLDOWN_MS = 1000;

let runtimeStatusRequestInFlight = false;
let lastRuntimeStatusStartedAt = 0;

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

    } catch (err) {

        const offlineStatus = {
            brain: false,
            service: false,
            translator: false,
            use_service_as_brain: false,
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

    } finally {

        runtimeStatusRequestInFlight = false;

    }
}


function refreshRuntimeStatus() {

    if (
        Date.now() - lastRuntimeStatusStartedAt
        < STATUS_REFRESH_COOLDOWN_MS
    ) {
        return;
    }

    void updateRuntime();

}

// FIRST RUN

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
