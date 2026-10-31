import { describe, expect, it } from 'vitest';
import { decisionBadge, decisionSummary } from '../lib/decision';

const base = { total: 3899, currency: 'INR', autoLimit: 4000, ceiling: 5000 };

describe('decisionSummary', () => {
  it('explains an automatic approval with the numbers that justify it', () => {
    const d = decisionSummary({ ...base, state: 'AUTHORIZED' });
    expect(d?.tone).toBe('ok');
    expect(d?.text).toMatch(/3,899/);
    expect(d?.text).toMatch(/4,000/);
    expect(d?.text).toMatch(/5,000/);
  });

  it('explains why a person has to approve', () => {
    const d = decisionSummary({ ...base, total: 4699, state: 'AWAITING_APPROVAL' });
    expect(d?.tone).toBe('wait');
    expect(d?.text).toMatch(/4,699/);
    expect(d?.text).toMatch(/above your .*4,000/);
  });

  it('says the user approved it rather than calling it automatic', () => {
    const d = decisionSummary({ ...base, total: 4699, state: 'AUTHORIZED', approvedByUser: true });
    expect(d?.tone).toBe('approved');
    expect(d?.text).toMatch(/You approved/);
    expect(d?.text).not.toMatch(/automatically/i);
  });

  it('gives the refusal reason for a blocked purchase', () => {
    const d = decisionSummary({ ...base, state: 'POLICY_REJECTED', failureReason: 'Exceeds maximum authorized budget (4699.00 > 3000.00).' });
    expect(d?.tone).toBe('blocked');
    expect(d?.text).toContain('Exceeds maximum authorized budget');
  });

  it('uses the right currency symbol', () => {
    expect(decisionSummary({ ...base, currency: 'USD', state: 'AUTHORIZED' })?.text).toContain('$3,899');
  });
});

describe('decisionBadge', () => {
  it('shows exactly one status, and blocked always wins', () => {
    expect(decisionBadge({ proposalState: 'AUTHORIZED', sessionState: 'POLICY_REJECTED' })).toBe('Blocked');
    expect(decisionBadge({ proposalState: 'POLICY_REJECTED' })).toBe('Blocked');
  });

  it('distinguishes automatic approval from approval by the user', () => {
    expect(decisionBadge({ proposalState: 'AUTHORIZED' })).toBe('Auto-Approved');
    expect(decisionBadge({ proposalState: 'AUTHORIZED', approvedByUser: true })).toBe('Approved by you');
    expect(decisionBadge({ proposalState: 'AWAITING_APPROVAL' })).toBe('Needs Approval');
  });
});
