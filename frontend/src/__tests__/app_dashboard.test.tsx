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
  policy_id: 'pol_mock_test_01',
  version: 1,
  user_id: 'usr_shopper',
  product_category: 'travel',
  maximum_total: 5000,
  spent_total: 0,
  automatic_purchase_limit: 4000,
  allowed_currencies: ['INR', 'USD'],
  allowed_merchants: ['IndiGo Corporate', 'Keychron India'],
  is_revoked: false,
  agent_quotas: {
    agent_hardware: { agent_id: 'agent_hardware', agent_name: 'Hardware Agent', role: 'Hardware', allocated_budget: 5000, spent_budget: 0, is_active: true },
    agent_travel: { agent_id: 'agent_travel', agent_name: 'Travel Agent', role: 'Travel', allocated_budget: 5000, spent_budget: 0, is_active: true },
    agent_supplies: { agent_id: 'agent_supplies', agent_name: 'Supplies Agent', role: 'Supplies', allocated_budget: 2000, spent_budget: 0, is_active: true },
  },
};

describe('Dashboard Tab Switching & Integrity Lab', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockImplementation((url: string, options?: any) => {
      if (url.includes('/health')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            status: 'healthy',
            paypal_mode: 'mock',
            ollama: { available: true, model: 'qwen2.5-coder:7b', installed: true },
          }),
        });
      }
      if (url.includes('/lab/scenarios')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve([
            { scenario_id: 'SC-A', name: 'Happy Path Purchase', category: 'Nominal', expected_outcome: 'Pass' },
            { scenario_id: 'SC-B', name: 'Price & Shipping Drift', category: 'Drift', expected_outcome: 'Halt' },
            { scenario_id: 'SC-C', name: 'Revoked Authorization', category: 'Lifecycle', expected_outcome: 'Abort' },
          ]),
        });
      }
      if (url.includes('/audit/events')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            ledger_integrity_valid: true,
            event_count: 1,
            events: [
              {
                event_id: 'evt_001',
                timestamp: '2026-10-19T10:00:00Z',
                event_type: 'POLICY_REGISTERED',
                decision: 'ALLOW',
                reason: 'Policy registered',
                event_hash: 'hash_001',
                prev_event_hash: 'GENESIS_ROOT_HASH',
              },
            ],
          }),
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
          json: () => Promise.resolve({
            checkout_id: 'chk_mock_01',
            state: 'AUTHORIZED',
            recommendation_explanation: 'Mock proposal recommendation',
            proposal: {
              proposal_id: 'prop_01',
              policy_id: 'pol_mock_test_01',
              policy_version: 1,
              agent_id: 'agent_travel',
              merchant: 'IndiGo Corporate',
              items: [{ sku: 'TR-FLIGHT-BLR', name: 'Flight Ticket', quantity: 1, unit_price: 4299.0 }],
              item_subtotal: 4299.0,
              shipping_fee: 0,
              tax_fee: 0,
              total_amount: 4299.0,
              currency: 'INR',
              proposal_fingerprint: 'fp_mock_01',
            },
            product: { sku: 'TR-FLIGHT-BLR', name: 'Flight Ticket', unit_price: 4299.0, merchant: 'IndiGo Corporate', category: 'travel' },
          }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      });
    });
  });

  it('switches to Policy Test Lab tab when tab pill is clicked', async () => {
    render(<Home />);

    const labTab = screen.getByText('Policy Test Lab');
    fireEvent.click(labTab);

    await waitFor(() => {
      expect(screen.getByText(/Policy Enforcement Test Lab/i)).toBeInTheDocument();
    });
  });

  it('switches to Audit Trail tab when clicked and displays verified ledger badge', async () => {
    render(<Home />);

    const auditTab = screen.getByText('Audit Trail');
    fireEvent.click(auditTab);

    await waitFor(() => {
      expect(screen.getByText(/Audit Trail & Ledger/i)).toBeInTheDocument();
      expect(screen.getByText(/Ledger Valid & Tamper-Free/i)).toBeInTheDocument();
    });
  });

  it('switches agent persona to Travel Agent on button click and updates instruction prompt', async () => {
    render(<Home />);

    const travelAgentButton = screen.getByText('Travel Agent');
    fireEvent.click(travelAgentButton);

    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    expect(textarea.value).toContain('Bangalore');
  });

  it('switches agent persona to Supplies Agent on button click and updates instruction prompt', async () => {
    render(<Home />);

    const suppliesAgentButton = screen.getByText('Supplies Agent');
    fireEvent.click(suppliesAgentButton);

    const textarea = screen.getByRole('textbox') as HTMLTextAreaElement;
    expect(textarea.value).toContain('brass keyboard desk mat');
  });
});

describe('Integrity Lab failures are shown, not swallowed', () => {
  it('shows the server reason when the benchmark run fails', async () => {
    localStorage.clear();
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/lab/run')) {
        return Promise.resolve({
          ok: false,
          status: 500,
          json: () => Promise.resolve({ detail: 'Benchmark engine unavailable' }),
        });
      }
      if (url.includes('/health')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy', paypal_mode: 'mock', ollama: {} }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    }) as any;

    render(<Home />);
    fireEvent.click(screen.getByText('Policy Test Lab'));

    expect(await screen.findByText(/Benchmark engine unavailable/i)).toBeInTheDocument();
  });

  it('does not invent benchmark numbers when no run has succeeded', async () => {
    localStorage.clear();
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/lab/run')) {
        return Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({ detail: 'down' }) });
      }
      if (url.includes('/health')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy', paypal_mode: 'mock', ollama: {} }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    }) as any;

    render(<Home />);
    fireEvent.click(screen.getByText('Policy Test Lab'));
    await screen.findByText(/Policy Enforcement Test Lab/i);

    expect(screen.queryByText('100.0%')).not.toBeInTheDocument();
    expect(screen.queryByText('14.3%')).not.toBeInTheDocument();
    expect(screen.getByText('Policy Pass Rate').previousSibling?.textContent).toBe('—');
  });
});


describe('Integrity Lab figures come from the real report', () => {
  it('renders the summary and comparison table from /lab/run results', async () => {
    localStorage.clear();
    const summary = (pass: number, unauth: number, lat: number) => ({
      total_scenarios: 7,
      passed_scenarios: 0,
      pass_rate_pct: pass,
      unauthorized_spend_count: unauth,
      avg_latency_ms: lat,
    });
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/lab/run')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              benchmark_report: {
                summary_by_system: {
                  BASELINE_A: summary(11.1, 8, 0.31),
                  BASELINE_B: summary(66.6, 2, 0.32),
                  PROPOSED_APIL: summary(88.8, 1, 0.33),
                },
                detailed_results: [],
              },
            }),
        });
      }
      if (url.includes('/health')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ status: 'healthy', paypal_mode: 'mock', ollama: {} }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    }) as any;

    render(<Home />);
    fireEvent.click(screen.getByText('Policy Test Lab'));

    // Selected system defaults to PayPact: the cards and its table row use that run's numbers.
    expect(await screen.findAllByText('88.8%')).not.toHaveLength(0);
    expect(screen.getByText('11.1%')).toBeInTheDocument();
    expect(screen.getByText('66.6%')).toBeInTheDocument();
    expect(screen.getByText('0.31 ms')).toBeInTheDocument();
  });
});
