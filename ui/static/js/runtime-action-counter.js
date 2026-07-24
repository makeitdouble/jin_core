function formatRuntimeActionCountLabel(
  count
) {

  const normalizedCount = Math.max(
    0,
    Number.parseInt(
      count || 0,
      10
    ) || 0
  );

  return normalizedCount > 1
    ? `(count: ${normalizedCount})`
    : "";

}
