// status.js

// -----------------------------------
// ELEMENTS
// -----------------------------------

const brainDot = document.querySelector("#brain-dot");
const brainLabel = document.querySelector("#brain-label");

const serviceDot = document.querySelector("#service-dot");
const serviceLabel = document.querySelector("#service-label");

// -----------------------------------
// UPDATE UI
// -----------------------------------

function setRuntimeState(dot, label, name, online) {

    if (online) {

        dot.className =
            "h-2 w-2 rounded-full bg-emerald-400 animate-pulse transition-all duration-300";

        label.textContent =
            `${name}: ONLINE`;

    } else {

        dot.className =
            "h-2 w-2 rounded-full bg-red-500 transition-all duration-300";

        label.textContent =
            `${name}: OFFLINE`;

    }

}

// -----------------------------------
// MAIN LOOP
// -----------------------------------

async function updateRuntime() {

    try {

        const response = await fetch("/api/status");
        const data = await response.json();

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

    } catch (err) {

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

    }
}

// FIRST RUN

updateRuntime();

// LOOP

setInterval(updateRuntime, 30000);
