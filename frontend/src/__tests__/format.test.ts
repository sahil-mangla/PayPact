import { describe, expect, it } from 'vitest';
import { formatTimestamp, humanizeEvent } from '../lib/format';

describe('humanizeEvent', () => {
  it('turns ledger codes into readable labels', () => {
    expect(humanizeEvent('PROPOSAL_CREATED')).toBe('Proposal created');
    expect(humanizeEvent('PRE_EXECUTION_BLOCKED')).toBe('Pre-execution blocked');
    expect(humanizeEvent('PAYMENT_COMPLETED')).toBe('Payment completed');
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
