import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ApprovePage from '../app/approve/[token]/page';

const SUMMARY = {
  checkout_id: 'chk_link_01',
  state: 'AWAITING_APPROVAL',
  merchant: 'Keychron India',
  items: [{ sku: 'KB-K2', name: 'Keychron K2 Keyboard', quantity: 1, unit_price: 3899 }],
  item_subtotal: 3899,
  shipping_fee: 100,
  tax_fee: 0,
  total_amount: 3999,
  currency: 'INR',
  agent_id: 'agent_claude_desktop',
  decision: 'REQUIRE_APPROVAL',
  reasons: ['Total 3999 is above your 1000 auto-buy limit.'],
  expires_at: '2026-10-31T12:30:00+00:00',
};

function json(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

describe('approval link page', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    localStorage.clear();
    fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;
  });
  afterEach(() => vi.restoreAllMocks());

  it('shows what will be approved, then approves exactly once', async () => {
    fetchMock.mockImplementation((_url: string, init?: RequestInit) =>
      init?.method === 'POST' ? json(200, { ...SUMMARY, state: 'AUTHORIZED' }) : json(200, SUMMARY),
    );
    render(<ApprovePage params={{ token: 'tok_abc-123' }} />);

    expect(await screen.findByRole('heading', { level: 1, name: /approve this purchase/i })).toBeInTheDocument();
    expect(screen.getByText('Keychron India')).toBeInTheDocument();
    expect(screen.getByText(/Keychron K2 Keyboard/)).toBeInTheDocument();
    expect(screen.getByText(/above your 1000 auto-buy limit/)).toBeInTheDocument();
    expect(screen.getByText(/agent_claude_desktop/)).toBeInTheDocument();
    // The summary GET went through the same-origin /api proxy.
    expect(fetchMock.mock.calls[0][0]).toBe('/api/approvals/tok_abc-123');

    fireEvent.click(screen.getByRole('button', { name: /approve purchase of ₹3,999 at keychron india/i }));

    expect(await screen.findByRole('heading', { name: /purchase approved/i })).toBeInTheDocument();
    const post = fetchMock.mock.calls.find((c) => c[1]?.method === 'POST');
    expect(post?.[0]).toBe('/api/approvals/tok_abc-123');
    expect(screen.queryByRole('button', { name: /approve purchase of/i })).toBeNull();
  });

  it.each([
    [404, 'Unknown approval link.', /link is not valid/i],
    [410, 'This approval link has expired.', /can no longer be used/i],
    [409, 'The proposal changed after the link was created.', /purchase changed/i],
  ])('explains a %s response and offers no approve button', async (status, detail, heading) => {
    fetchMock.mockImplementation(() => json(status as number, { detail }));
    render(<ApprovePage params={{ token: 'tok_bad' }} />);

    expect(await screen.findByRole('heading', { name: heading })).toBeInTheDocument();
    expect(screen.getByText(detail as string)).toBeInTheDocument();
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /approve purchase/i })).toBeNull();
  });

  it('shows a used link as unusable when the approve call is refused', async () => {
    fetchMock.mockImplementation((_url: string, init?: RequestInit) =>
      init?.method === 'POST' ? json(410, { detail: 'This approval link has already been used.' }) : json(200, SUMMARY),
    );
    render(<ApprovePage params={{ token: 'tok_used' }} />);

    fireEvent.click(await screen.findByRole('button', { name: /approve purchase of/i }));

    expect(await screen.findByRole('heading', { name: /can no longer be used/i })).toBeInTheDocument();
    expect(screen.getByText(/already been used/)).toBeInTheDocument();
  });

  it('lets the owner retry after a network failure', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch')).mockImplementation(() => json(200, SUMMARY));
    render(<ApprovePage params={{ token: 'tok_net' }} />);

    expect(await screen.findByText(/can't reach the server/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));

    await waitFor(() => expect(screen.getByRole('heading', { name: /approve this purchase/i })).toBeInTheDocument());
  });
});
