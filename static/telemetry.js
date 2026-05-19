window.handleTelemetryMessage = function (data) {

  if (data.type !== "telemetry") {
    return;
  }

  const runtimeStates =
    Object.values(
      data.runtime || {}
    );

  const serviceRuntime =
    runtimeStates.find(
      runtime =>
        runtime.label === "service"
    );

  const brainRuntime =
    runtimeStates.find(
      runtime =>
        runtime.label === "brain"
    ) || serviceRuntime;

  const brainModelElement =
    document.getElementById(
      "brain-model"
    );

  const serviceModelElement =
    document.getElementById(
      "service-model"
    );

  const brainContextElement =
    document.getElementById(
      "brain-context"
    );

  const serviceContextElement =
    document.getElementById(
      "service-context"
    );

  // -----------------------------------
  // BRAIN
  // -----------------------------------

  if (
    brainRuntime &&
    brainModelElement
  ) {

    brainModelElement.textContent =
      `BRAIN: ${brainRuntime.model}`;

  }

  if (
    brainRuntime &&
    brainContextElement
  ) {

    brainContextElement.textContent =
      `${brainRuntime.used_tokens} / `
      + `${brainRuntime.max_tokens} ctx`;

  }

  // -----------------------------------
  // SERVICE
  // -----------------------------------

  if (
    serviceRuntime &&
    serviceModelElement
  ) {

    serviceModelElement.textContent =
      `SERVICE: ${serviceRuntime.model}`;

  }

  if (
    serviceRuntime &&
    serviceContextElement
  ) {

    serviceContextElement.textContent =
      `${serviceRuntime.used_tokens} / `
      + `${serviceRuntime.max_tokens} ctx`;

  }

};
