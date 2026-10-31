// Plain-English explanation of why a proposal was allowed, held for approval, or blocked.

export type DecisionTone = 'ok' | 'wait' | 'approved' | 'blocked';

function money(amount: number, currency: string): string {
  const symbol = currency === 'USD' ? '$' : currency === 'INR' ? '₹' : `${currency} `;
  return `${symbol}${amount.toLocaleString('en-US')}`;
}

export function decisionSummary(input: {
  state?: string;
  approvedByUser?: boolean;
  total: number;
  currency: string;
  autoLimit?: number;
  ceiling?: number;
  failureReason?: string | null;
}): { tone: DecisionTone; text: string } | null {
  const { state, approvedByUser, total, currency, autoLimit, ceiling, failureReason } = input;
  const amount = money(total, currency);

  if (state === 'POLICY_REJECTED') {
    return { tone: 'blocked', text: failureReason || 'This purchase breaks your policy, so it was blocked.' };
  }
  if (state === 'AWAITING_APPROVAL') {
    return {
      tone: 'wait',
      text:
        autoLimit !== undefined
          ? `${amount} is above your ${money(autoLimit, currency)} auto-buy limit, so a person must approve it before any payment.`
          : `${amount} needs a person's approval before any payment.`,
    };
  }
  if (state === 'AUTHORIZED' && approvedByUser) {
    return {
      tone: 'approved',
      text: `You approved this exact proposal (${amount}). It is checked again just before payment.`,
    };
  }
  if (state === 'AUTHORIZED') {
    const limits =
      autoLimit !== undefined && ceiling !== undefined
        ? ` is within your ${money(autoLimit, currency)} auto-buy limit and ${money(ceiling, currency)} ceiling, so it can proceed without asking.`
        : ' is within your limits, so it can proceed without asking.';
    return { tone: 'ok', text: `${amount}${limits}` };
  }
  return null;
}

/** One status label for the proposal card; a blocked purchase never also reads as approved. */
export function decisionBadge(input: {
  proposalState?: string;
  sessionState?: string;
  approvedByUser?: boolean;
}): string | null {
  const { proposalState, sessionState, approvedByUser } = input;
  if (proposalState === 'POLICY_REJECTED' || sessionState === 'POLICY_REJECTED') return 'Blocked';
  if (proposalState === 'AWAITING_APPROVAL') return 'Needs Approval';
  if (proposalState === 'AUTHORIZED') return approvedByUser ? 'Approved by you' : 'Auto-Approved';
  return null;
}
