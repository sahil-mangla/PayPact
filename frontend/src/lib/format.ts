// Display helpers for audit events.

// Events whose code reads badly when only de-capitalised.
const EVENT_LABELS: Record<string, string> = {
  APPROVAL_DENIED: 'Approval refused',
  APPROVAL_LINK_CREATED: 'Approval link created',
};

const APPROVAL_VIA: Record<string, string> = {
  owner_token: 'the owner token',
  approval_link: 'a one-time approval link',
};

/** Who or what a USER_APPROVED event says approved it, or null when it does not say. */
export function describeApprovalVia(via: unknown): string | null {
  return typeof via === 'string' && APPROVAL_VIA[via] ? `Approved using ${APPROVAL_VIA[via]}` : null;
}

/** PRE_EXECUTION_BLOCKED -> "Pre-execution blocked". */
export function humanizeEvent(eventType: string): string {
  if (EVENT_LABELS[eventType]) return EVENT_LABELS[eventType];
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
