export function getApiErrorMessage(error, fallback = "Request failed.") {
  const envelope = error?.response?.data?.error;
  const message = envelope?.message || error?.response?.data?.message;
  if (typeof message === "string" && message.trim()) return message;
  if (typeof envelope === "string" && envelope.trim()) return envelope;
  if (typeof error?.message === "string" && error.message.trim()) return error.message;
  return fallback;
}
