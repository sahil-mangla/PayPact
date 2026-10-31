import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import Home from '../app/page';

vi.mock('@paypal/react-paypal-js', () => ({
  PayPalScriptProvider: ({ children }: { children: React.ReactNode }) => <div data-testid="paypal-provider">{children}</div>,
  PayPalButtons: () => <button data-testid="paypal-button">PayPal Checkout</button>,
  usePayPalScriptReducer: () => [{ isPending: false }, vi.fn()],
}));

const MOCK_POLICY = {
  policy_id: 'pol_unit_flow_01',
  version: 1,
  user_id: 'usr_shopper',
  product_category: 'hardware',
  maximum_total: 5000,
  spent_total: 0,
  automatic_purchase_limit: 4000,
  allowed_currencies: ['INR', 'USD'],
  allowed_merchants: ['Keychron India'],
  is_revoked: false,
  agent_quotas: {
    agent_hardware: { agent_id: 'agent_hardware', agent_name: 'Hardware Agent', role: 'Hardware', allocated_budget: 5000, spent_budget: 0, is_active: true },
    agent_travel: { agent_id: 'agent_travel', agent_name: 'Travel Agent', role: 'Travel', allocated_budget: 5000, spent_budget: 0, is_active: true },
    agent_supplies: { agent_id: 'agent_supplies', agent_name: 'Supplies Agent', role: 'Supplies', allocated_budget: 2000, spent_budget: 0, is_active: true },
  },
};

const MOCK_PROPOSAL_RES = {
  checkout_id: 'chk_flow_test_01',
  state: 'AUTHORIZED',
  recommendation_explanation: 'Agent found Keychron K2 Wireless within INR 5,000 threshold.',
  proposal: {
    proposal_id: 'prop_flow_01',
    policy_id: 'pol_unit_flow_01',
    policy_version: 1,
    agent_id: 'agent_hardware',
    merchant: 'Keychron India',
    items: [{ sku: 'KB-K2-BRN', name: 'Keychron K2 Mechanical Keyboard', quantity: 1, unit_price: 3899.0 }],
    item_subtotal: 3899.0,
    shipping_fee: 0,
    tax_fee: 0,
    total_amount: 3899.0,
    currency: 'INR',
    proposal_fingerprint: 'a1b2c3d4e5f6',
  },
  product: { sku: 'KB-K2-BRN', name: 'Keychron K2 Mechanical Keyboard', unit_price: 3899.0, merchant: 'Keychron India', category: 'hardware' },
};

const SAMPLE_RECEIPT = {
  receipt_id: 'rcpt_sample_test_01',
  checkout_id: 'chk_sample_test_01',
  timestamp: '2026-10-19T10:00:00Z',
  decision: 'ALLOW',
  status: 'PAID',
  policy_id: 'pol_sample_01',
  policy_version: 1,
  proposal_fingerprint: 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
  total_amount: 3899.00,
  currency: 'INR',
  merchant: 'Keychron India',
  items_count: 1,
  agent_id: 'agent_hardware',
  paypal_order_id: 'ORDER-12345',
  paypal_capture_id: 'CAP-67890',
  signature_algorithm: 'HMAC-SHA256',
  signer_identity: 'APIL-Ledger-Authority-v1.0',
  signature: 'valid_hmac_hex_signature',
  raw_canonical_digest: 'valid_digest',
};

describe('End-to-End User Actions & Flow Test', () => {
  beforeEach(() => {
    localStorage.clear();
    global.fetch = vi.fn().mockImplementation((url: string, options?: any) => {
      if (url.includes('/health')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'healthy', paypal_mode: 'mock', ollama: { available: true } }),
        });
      }
      if (url.includes('/lab/scenarios')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([]),
        });
      }
      if (url.includes('/authorizations/parse-intent') || (url.includes('/authorizations') && options?.method === 'POST')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(MOCK_POLICY),
        });
      }
      if (url.includes('/proposals')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(MOCK_PROPOSAL_RES),
        });
      }
      if (url.includes('/audit/events')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ ledger_integrity_valid: true, event_count: 0, events: [] }),
        });
      }
      if (url.includes('/receipt/sample')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve(SAMPLE_RECEIPT),
        });
      }
      if (url.includes('/receipt/verify')) {
        const body = JSON.parse(options?.body || '{}');
        const isValid = body.total_amount === 3899.0;
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            valid: isValid,
            receipt_id: body.receipt_id || 'rcpt_sim_01',
            checkout_id: body.checkout_id || 'chk_sim_01',
            algorithm: 'HMAC-SHA256',
            signer: 'APIL-Ledger-Authority-v1.0',
            tamper_reason: isValid ? null : 'Digest mismatch: canonical payload tampered',
          }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });
  });

  it('submits intent and generates proposal and policy rule cards', async () => {
    render(<Home />);

    const runAgentBtn = screen.getByText('Generate Proposal & Check Rules');
    fireEvent.click(runAgentBtn);

    await waitFor(() => {
      expect(screen.getByText('Hard Budget Ceiling')).toBeInTheDocument();
      expect(screen.getByText('Auto-Purchase Threshold')).toBeInTheDocument();
      expect(screen.getByText('Test Policy Violations')).toBeInTheDocument();
    });
  });

  it('detects tampering when price is altered in receipt verifier', async () => {
    render(<Home />);

    const auditTab = screen.getByText('Audit Trail');
    fireEvent.click(auditTab);

    const tamperBtn = await screen.findByText(/Tamper Price/i);
    fireEvent.click(tamperBtn);

    await waitFor(() => {
      expect(screen.getByText(/TAMPER DETECTED: Cryptographic Signature Mismatch/i)).toBeInTheDocument();
    });
  });
});

describe('Attack simulator chips run in one click', () => {
  const calls: Array<{ url: string; body: any }> = [];

  beforeEach(() => {
    calls.length = 0;
    localStorage.clear();
    global.fetch = vi.fn().mockImplementation((url: string, options?: any) => {
      const body = options?.body ? JSON.parse(options.body) : undefined;
      calls.push({ url, body });
      if (url.includes('/health')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy', paypal_mode: 'mock', ollama: {} }) });
      }
      if (url.includes('/authorizations')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_POLICY) });
      }
      if (url.includes('/proposals')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(MOCK_PROPOSAL_RES) });
      }
      if (url.includes('/execute')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              session: { checkout_id: 'chk_flow_test_01', state: 'POLICY_REJECTED', failure_reason: 'Proposal details drifted after user approval was granted.', proposal: MOCK_PROPOSAL_RES.proposal },
            }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });
  });

  it('a prompt-injection chip submits the request without a second click', async () => {
    render(<Home />);
    fireEvent.click(screen.getByText('Prompt Injection Bypass'));

    await waitFor(() => {
      const parse = calls.find((c) => c.url.includes('/authorizations/parse-intent'));
      expect(parse?.body.prompt).toContain('Rolex');
      expect(calls.some((c) => c.url.includes('/proposals'))).toBe(true);
    });
  });

  it('a drift chip also fires the drifted execution so the block is shown', async () => {
    render(<Home />);
    fireEvent.click(screen.getByText('Stealth Shipping Drift (+₹850)'));

    await waitFor(() => {
      const exec = calls.find((c) => c.url.includes('/execute'));
      expect(exec?.body.simulate_drift_type).toBe('price_drift');
    });
  });
});

describe('After payment: refunds, disputes and the quota panel', () => {
  const calls: string[] = [];

  beforeEach(() => {
    calls.length = 0;
    localStorage.clear();
    let policy = { ...MOCK_POLICY };
    global.fetch = vi.fn().mockImplementation((url: string, options?: any) => {
      calls.push(`${options?.method || 'GET'} ${url}`);
      const json = (body: any) => Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
      if (url.includes('/health')) return json({ status: 'healthy', paypal_mode: 'mock', ollama: {} });
      if (url.includes('/authorizations/parse-intent') || (url.includes('/authorizations') && options?.method === 'POST')) {
        return json(policy);
      }
      if (url.match(/\/authorizations\/[^/]+$/)) return json({ ...policy, spent_total: 3899 });
      if (url.includes('/proposals')) return json(MOCK_PROPOSAL_RES);
      if (url.includes('/execute')) {
        return json({ session: { checkout_id: 'chk_flow_test_01', state: 'PAID', paypal_order_id: 'MOCK-ORD-1', paypal_capture_id: 'MOCK-CAP-1', proposal: MOCK_PROPOSAL_RES.proposal } });
      }
      if (url.includes('/webhooks/simulate')) {
        const type = JSON.parse(options.body).event_type;
        return json({ session: { checkout_id: 'chk_flow_test_01', state: type.includes('DISPUTE') ? 'DISPUTED' : 'REFUNDED', paypal_order_id: 'MOCK-ORD-1', paypal_capture_id: 'MOCK-CAP-1', proposal: MOCK_PROPOSAL_RES.proposal } });
      }
      return json([]);
    });
  });

  async function payThenSimulate(label: string) {
    render(<Home />);
    fireEvent.click(screen.getByText('Generate Proposal & Check Rules'));
    fireEvent.click(await screen.findByText('Execute Authorized Payment'));
    fireEvent.click(await screen.findByText(label));
  }

  it('keeps the settled card and shows Refunded instead of offering to pay again', async () => {
    await payThenSimulate('Simulate Refund Webhook');
    expect(await screen.findByText('Payment Refunded')).toBeInTheDocument();
    expect(screen.queryByText('Execute Authorized Payment')).not.toBeInTheDocument();
    expect(screen.getByText(/Webhook confirmed/i)).toBeInTheDocument();
  });

  it('keeps the settled card and shows Disputed for a dispute', async () => {
    await payThenSimulate('Simulate Dispute Webhook');
    expect(await screen.findByText('Payment Disputed')).toBeInTheDocument();
    expect(screen.queryByText('Execute Authorized Payment')).not.toBeInTheDocument();
  });

  it('reloads the policy after a payment so the quota panel is not stale', async () => {
    render(<Home />);
    fireEvent.click(screen.getByText('Generate Proposal & Check Rules'));
    fireEvent.click(await screen.findByText('Execute Authorized Payment'));
    await screen.findByText('Payment Settled Successfully');
    await waitFor(() => {
      expect(calls.some((c) => /^GET .*\/authorizations\/pol_/.test(c))).toBe(true);
    });
  });
});
