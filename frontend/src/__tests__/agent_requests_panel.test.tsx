import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AgentRequestsPanel } from '../components/AgentRequestsPanel';

const row = (over: Record<string, unknown>) => ({
  checkout_id: 'chk_1',
  state: 'AWAITING_APPROVAL',
  agent_id: 'agent_claude_desktop',
  merchant: 'Keychron India',
  items: [{ sku: 'KB', name: 'Keychron K2', quantity: 1, unit_price: 3899 }],
  total_amount: 3899,
  currency: 'INR',
  created_at: '2026-10-31T10:00:00+00:00',
  failure_reason: null,
  ...over,
});

function json(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }));
}

describe('AgentRequestsPanel', () => {
  let rows: any[];
  let calls: { url: string; init?: RequestInit }[];
  const writeText = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    rows = [
      row({}),
      row({ checkout_id: 'chk_2', state: 'PAID', agent_id: 'agent_hardware' }),
      row({ checkout_id: 'chk_3', state: 'POLICY_REJECTED', failure_reason: 'Over the budget ceiling.' }),
    ];
    calls = [];
    writeText.mockClear();
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    global.fetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      calls.push({ url, init });
      if (url.endsWith('/checkouts') && !init?.method) return json(200, rows);
      if (url.endsWith('/approve')) return json(200, { checkout_id: 'chk_1', state: 'AUTHORIZED' });
      if (url.endsWith('/approval-link'))
        return json(200, { approval_url: 'http://localhost:3000/approve/tok_xyz', expires_at: '2026-10-31T12:30:00+00:00' });
      return json(404, { detail: 'nope' });
    }) as unknown as typeof fetch;
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('lists waiting requests first and marks the outside agent', async () => {
    render(<AgentRequestsPanel policyId="pol_abc" ownerToken="otok" ownCheckoutIds={['chk_2']} />);

    expect(await screen.findByRole('heading', { name: 'Agent requests' })).toBeInTheDocument();
    expect(await screen.findByText('1 waiting')).toBeInTheDocument();
    const waiting = screen.getByRole('heading', { name: /waiting for your approval/i }).nextElementSibling as HTMLElement;
    expect(waiting.textContent).toContain('Outside agent');
    expect(waiting.textContent).toContain('agent_claude_desktop');
    expect(waiting.textContent).toContain('₹3,899');

    const recent = screen.getByRole('heading', { name: /recent requests/i }).nextElementSibling as HTMLElement;
    expect(recent.textContent).toContain('Paid');
    expect(recent.textContent).toContain('This page');
    expect(recent.textContent).toContain('Blocked by policy');
    expect(recent.textContent).toContain('Over the budget ceiling.');
  });

  it('sends the owner token when listing', async () => {
    render(<AgentRequestsPanel policyId="pol_abc" ownerToken="otok" ownCheckoutIds={[]} />);
    await screen.findByText('1 waiting');
    expect(calls[0].url).toBe('/api/authorizations/pol_abc/checkouts');
    expect((calls[0].init?.headers as Record<string, string>)['X-Owner-Token']).toBe('otok');
  });

  it('shows the policy id and copies it', async () => {
    render(<AgentRequestsPanel policyId="pol_abc" ownerToken="otok" ownCheckoutIds={[]} />);
    expect(screen.getByTestId('policy-id')).toHaveTextContent('pol_abc');
    fireEvent.click(screen.getByRole('button', { name: /copy policy id/i }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith('pol_abc'));
    expect(await screen.findByText('Copied')).toBeInTheDocument();
  });

  it('approves with the owner token header and reports it', async () => {
    const onApproved = vi.fn();
    render(<AgentRequestsPanel policyId="pol_abc" ownerToken="otok" ownCheckoutIds={[]} onApproved={onApproved} />);

    fireEvent.click(await screen.findByRole('button', { name: /approve keychron k2 for ₹3,899/i }));

    await waitFor(() => expect(onApproved).toHaveBeenCalled());
    const approve = calls.find((c) => c.url === '/api/checkouts/chk_1/approve');
    expect(approve?.init?.method).toBe('POST');
    expect((approve?.init?.headers as Record<string, string>)['X-Owner-Token']).toBe('otok');
  });

  it('shows the server reason when approval is refused', async () => {
    (global.fetch as any).mockImplementation((url: string, init?: RequestInit) =>
      url.endsWith('/approve') ? json(403, { detail: 'Invalid owner token for this policy.' }) : json(200, rows),
    );
    render(<AgentRequestsPanel policyId="pol_abc" ownerToken="wrong" ownCheckoutIds={[]} />);
    fireEvent.click(await screen.findByRole('button', { name: /approve keychron k2/i }));
    expect(await screen.findByText('Invalid owner token for this policy.')).toBeInTheDocument();
  });

  it('copies a one-time approval link', async () => {
    render(<AgentRequestsPanel policyId="pol_abc" ownerToken="otok" ownCheckoutIds={[]} />);
    fireEvent.click(await screen.findByRole('button', { name: /copy approval link for checkout chk_1/i }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith('http://localhost:3000/approve/tok_xyz'));
    expect(await screen.findByText(/approval link copied/i)).toBeInTheDocument();
    const mint = calls.find((c) => c.url === '/api/checkouts/chk_1/approval-link');
    expect(mint?.init?.method).toBe('POST');
    expect((mint?.init?.headers as Record<string, string>)['X-Owner-Token']).toBe('otok');
  });

  it('shows the link for manual copying when the clipboard is unavailable', async () => {
    writeText.mockRejectedValueOnce(new Error('denied'));
    render(<AgentRequestsPanel policyId="pol_abc" ownerToken="otok" ownCheckoutIds={[]} />);
    fireEvent.click(await screen.findByRole('button', { name: /copy approval link/i }));
    const input = (await screen.findByLabelText('Approval link')) as HTMLInputElement;
    expect(input.value).toBe('http://localhost:3000/approve/tok_xyz');
  });

  it('polls, and announces a request that arrives later', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    render(<AgentRequestsPanel policyId="pol_abc" ownerToken="otok" ownCheckoutIds={[]} pollMs={4000} />);
    await screen.findByText('1 waiting');
    const listCalls = () => calls.filter((c) => c.url.endsWith('/checkouts')).length;
    expect(listCalls()).toBe(1);
    // Nothing is announced for what was already there on first load.
    expect(screen.getAllByRole('status').every((el) => el.textContent === '')).toBe(true);

    rows = [row({ checkout_id: 'chk_new', agent_id: 'agent_gemini', total_amount: 1200 }), ...rows];
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4100);
    });

    expect(listCalls()).toBeGreaterThanOrEqual(2);
    expect(await screen.findByText('2 waiting')).toBeInTheDocument();
    const announcement = screen
      .getAllByRole('status')
      .map((el) => el.textContent)
      .find((t) => t && t.includes('New purchase request'));
    expect(announcement).toContain('agent_gemini');
    expect(announcement).toContain('₹1,200');
  });

  it('does not poll while the tab is hidden and refreshes when it returns', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const visibility = vi.spyOn(document, 'visibilityState', 'get').mockReturnValue('hidden');
    render(<AgentRequestsPanel policyId="pol_abc" ownerToken="otok" ownCheckoutIds={[]} pollMs={4000} />);
    await waitFor(() => expect(calls.length).toBe(1)); // the mount fetch
    const before = calls.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(13000);
    });
    expect(calls.length).toBe(before);

    visibility.mockReturnValue('visible');
    await act(async () => {
      document.dispatchEvent(new Event('visibilitychange'));
    });
    await waitFor(() => expect(calls.length).toBeGreaterThan(before));
  });

  it('says so when the owner token is not accepted', async () => {
    (global.fetch as any).mockImplementation(() => json(403, { detail: 'Invalid owner token for this policy.' }));
    render(<AgentRequestsPanel policyId="pol_abc" ownerToken="stale" ownCheckoutIds={[]} />);
    expect(await screen.findByText(/owner token was not accepted/i)).toBeInTheDocument();
  });
});
