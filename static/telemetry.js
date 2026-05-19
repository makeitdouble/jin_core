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

    const usingServiceAsBrain =
      data.brain.model === data.service.model;

    // SERVICE AS BRAIN MODE

    if (usingServiceAsBrain) {

        if (brainModelElement) {
            brainModelElement.textContent =
              `BRAIN: ${data.brain.model}`;
        }

        if (serviceModelElement) {
            serviceModelElement.textContent =
              `SERVICE: ${data.brain.model}`;
        }

        if (brainContextElement) {
            brainContextElement.textContent =
              brainText;
        }

        if (serviceContextElement) {
            serviceContextElement.textContent =
              "BYPASSED";
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
        brainContextElement.textContent =
          brainText;
    }

    if (serviceContextElement) {
        serviceContextElement.textContent =
          serviceText;
    }
};
