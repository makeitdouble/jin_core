window.handleTelemetryMessage = function (data) {

    if (data.type !== "telemetry") {
        return;
    }

    const brainModelElement =
      document.getElementById("brain-model");

    const serviceModelElement =
      document.getElementById("service-model");

    const brainContextElement =
      document.getElementById("brain-context");

    const serviceContextElement =
      document.getElementById("service-context");

    const brainText =
      `${data.brain.used_tokens} / ${data.brain.max_tokens} ctx`;

    const serviceText =
      `${data.service.used_tokens} / ${data.service.max_tokens} ctx`;

    // BYPASS MODE
    if (data.service.max_tokens === 0) {

        if (brainModelElement) {
            brainModelElement.textContent =
              "BRAIN: BYPASSED";
        }

        if (serviceModelElement) {
            serviceModelElement.textContent =
              `SERVICE: ${data.brain.model}`;
        }

        if (brainContextElement) {
            brainContextElement.textContent = "BYPASSED";
        }

        if (serviceContextElement) {
            serviceContextElement.textContent = brainText;
        }

        return;
    }

    // NORMAL MODE
    if (brainModelElement) {
        brainModelElement.textContent =
          `BRAIN: ${data.brain.model}`;
    }

    if (serviceModelElement) {
        serviceModelElement.textContent =
          `SERVICE: ${data.service.model}`;
    }

    if (brainContextElement) {
        brainContextElement.textContent = brainText;
    }

    if (serviceContextElement) {
        serviceContextElement.textContent = serviceText;
    }
};
