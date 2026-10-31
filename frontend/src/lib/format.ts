// Display helpers for audit events.

/** PRE_EXECUTION_BLOCKED -> "Pre-execution blocked". */
export function humanizeEvent(eventType: string): string {
  const words = eventType.toLowerCase().split('_').filter(Boolean);
  if (words.length === 0) return eventType;
  return words
    .join(' ')
    .replace('pre execution', 'pre-execution')
    .replace(/^./, (c) => c.toUpperCase());
}

/** An ISO timestamp as a short local date and time; unparseable input is returned unchanged. */
export function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}
