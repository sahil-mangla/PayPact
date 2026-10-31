import { describe, expect, it } from 'vitest';
import { describeApprovalVia, formatTimestamp, humanizeEvent } from '../lib/format';

describe('humanizeEvent', () => {
  it('turns ledger codes into readable labels', () => {
    expect(humanizeEvent('PROPOSAL_CREATED')).toBe('Proposal created');
    expect(humanizeEvent('PRE_EXECUTION_BLOCKED')).toBe('Pre-execution blocked');
    expect(humanizeEvent('PAYMENT_COMPLETED')).toBe('Payment completed');
  });

  it('labels refused approvals and approval links in plain words', () => {
    expect(humanizeEvent('APPROVAL_DENIED')).toBe('Approval refused (not the owner)');
    expect(humanizeEvent('APPROVAL_LINK_CREATED')).toBe('Approval link created');
  });
});

describe('describeApprovalVia', () => {
  it('names how an approval was given', () => {
    expect(describeApprovalVia('owner_token')).toBe('Approved using the owner token');
    expect(describeApprovalVia('approval_link')).toBe('Approved using a one-time approval link');
    expect(describeApprovalVia(undefined)).toBeNull();
    expect(describeApprovalVia('something_else')).toBeNull();
  });
});

describe('formatTimestamp', () => {
  it('drops the microseconds and ISO punctuation', () => {
    const text = formatTimestamp('2026-10-31T09:46:11.071351+00:00');
    expect(text).not.toContain('T09');
    expect(text).not.toContain('071351');
  });

  it('leaves text it cannot parse alone', () => {
    expect(formatTimestamp('not a date')).toBe('not a date');
  });
});
