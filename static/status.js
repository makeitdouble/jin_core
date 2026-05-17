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

function setNodeState(dot, label, name, online) {

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

async function updateStatuses() {

    try {

        const response = await fetch("/api/status");
        const data = await response.json();

        setNodeState(
          brainDot,
          brainLabel,
          "BRAIN",
          data.brain
        );

        setNodeState(
          serviceDot,
          serviceLabel,
          "SERVICE",
          data.service
        );

    } catch (err) {

        setNodeState(
          brainDot,
          brainLabel,
          "BRAIN",
          false
        );

        setNodeState(
          serviceDot,
          serviceLabel,
          "SERVICE",
          false
        );

    }
}

// FIRST RUN

updateStatuses();

// LOOP

setInterval(updateStatuses, 30000);
