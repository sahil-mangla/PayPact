import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import Home from '../app/page';

vi.mock('@paypal/react-paypal-js', () => ({
  PayPalScriptProvider: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  PayPalButtons: () => <button>PayPal Checkout</button>,
  usePayPalScriptReducer: () => [{ isPending: false }, vi.fn()],
}));

const POLICY = {
  policy_id: 'pol_owner_01',
  version: 1,
  user_id: 'usr_shopper',
  product_category: 'hardware',
  maximum_total: 5000,
  spent_total: 0,
  automatic_purchase_limit: 1000,
  allowed_currencies: ['INR'],
  allowed_merchants: ['Keychron India'],
  is_revoked: false,
  agent_quotas: {
    agent_hardware: { agent_id: 'agent_hardware', agent_name: 'Hardware Agent', role: 'Hardware', allocated_budget: 5000, spent_budget: 0, remaining_budget: 5000, is_active: true },
  },
};

const PROPOSAL = {
  checkout_id: 'chk_owner_01',
  state: 'AWAITING_APPROVAL',
  recommendation_explanation: 'Keychron K2 fits.',
  proposal: {
    proposal_id: 'prop_1',
    policy_id: 'pol_owner_01',
    policy_version: 1,
    agent_id: 'agent_hardware',
    merchant: 'Keychron India',
    items: [{ sku: 'KB-K2', name: 'Keychron K2 Keyboard', quantity: 1, unit_price: 3899 }],
    item_subtotal: 3899,
    shipping_fee: 0,
    tax_fee: 0,
    total_amount: 3899,
    currency: 'INR',
    proposal_fingerprint: 'abc123',
  },
  product: { sku: 'KB-K2', name: 'Keychron K2 Keyboard', unit_price: 3899, merchant: 'Keychron India', category: 'hardware' },
};

const j = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));

describe('owner token in the dashboard', () => {
  let calls: { url: string; init?: any }[];
  const writeText = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    calls = [];
    localStorage.clear();
    sessionStorage.clear();
    writeText.mockClear();
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    global.fetch = vi.fn().mockImplementation((url: string, init?: any) => {
      calls.push({ url, init });
      if (url.includes('/health')) return j({ status: 'healthy', paypal_mode: 'mock', ollama: {} });
      if (url.includes('/lab/scenarios')) return j([]);
      if (url.includes('/authorizations/parse-intent')) return j(POLICY);
      if (url.endsWith('/authorizations') && init?.method === 'POST') return j({ ...POLICY, owner_token: 'otok_secret' });
      if (url.endsWith('/checkouts') && !init?.method) return j([]);
      if (url.includes('/proposals')) return j(PROPOSAL);
      if (url.endsWith('/approve')) return j({ checkout_id: 'chk_owner_01', state: 'AUTHORIZED' });
      if (url.endsWith('/approval-link'))
        return j({ approval_url: 'http://localhost:3000/approve/tok_1', expires_at: '2026-10-31T12:30:00+00:00' });
      if (url.endsWith('/revoke')) return j({ status: 'revoked' });
      return j({});
    });
  });

  const startFlow = async () => {
    render(<Home />);
    fireEvent.click(screen.getByText('Generate Proposal & Check Rules'));
    await screen.findByText(/Manually Approve This Purchase/);
  };
  const headerOf = (suffix: string) =>
    calls.find((c) => c.url.endsWith(suffix))?.init?.headers?.['X-Owner-Token'];

  it('keeps the token from registration and sends it on approve', async () => {
    await startFlow();
    expect(sessionStorage.getItem('paypact_owner_token:pol_owner_01')).toBe('otok_secret');

    fireEvent.click(screen.getByText(/Manually Approve This Purchase/));

    await waitFor(() => expect(headerOf('/checkouts/chk_owner_01/approve')).toBe('otok_secret'));
  });

  it('sends the token on revoke', async () => {
    await startFlow();
    fireEvent.click(screen.getByText('Revoke Permission'));
    await waitFor(() => expect(headerOf('/authorizations/pol_owner_01/revoke')).toBe('otok_secret'));
    expect(await screen.findByText('Revoked')).toBeInTheDocument();
  });

  it('does not mark the policy revoked when the server refuses the revoke', async () => {
    await startFlow();
    (global.fetch as any).mockImplementation((url: string, init?: any) =>
      url.endsWith('/revoke') ? j({ detail: 'Invalid owner token for this policy.' }, 403) : j([]),
    );
    fireEvent.click(screen.getByText('Revoke Permission'));
    expect(await screen.findByText('Invalid owner token for this policy.')).toBeInTheDocument();
    expect(screen.queryByText('Revoked')).toBeNull();
  });

  it('copies an approval link for the proposal that needs approval', async () => {
    await startFlow();
    const buttons = screen.getAllByRole('button', { name: /copy approval link for checkout chk_owner_01/i });
    fireEvent.click(buttons[0]);

    await waitFor(() => expect(writeText).toHaveBeenCalledWith('http://localhost:3000/approve/tok_1'));
    expect(headerOf('/checkouts/chk_owner_01/approval-link')).toBe('otok_secret');
  });

  it('shows the agent requests panel with the policy id once a policy is active', async () => {
    await startFlow();
    expect(screen.getByRole('heading', { name: 'Agent requests' })).toBeInTheDocument();
    expect(screen.getByTestId('policy-id')).toHaveTextContent('pol_owner_01');
    await waitFor(() => expect(headerOf('/authorizations/pol_owner_01/checkouts')).toBe('otok_secret'));
  });
});
