import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import Home from '../app/page';

vi.mock('@paypal/react-paypal-js', () => ({
  PayPalScriptProvider: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="paypal-provider">{children}</div>
  ),
  PayPalButtons: () => <div data-testid="paypal-buttons" />,
  usePayPalScriptReducer: () => [{ isPending: false }, vi.fn()],
}));

function mockHealth(mode: 'mock' | 'live_sandbox') {
  global.fetch = vi.fn().mockImplementation((url: string) =>
    Promise.resolve({
      ok: true,
      json: () =>
        Promise.resolve(url.includes('/health') ? { status: 'healthy', paypal_mode: mode, ollama: {} } : []),
    }),
  ) as any;
}

describe('PayPal mode is shown honestly', () => {
  beforeEach(() => localStorage.clear());

  it('says demo mode, and never loads the PayPal SDK, when the backend is simulating PayPal', async () => {
    mockHealth('mock');
    render(<Home />);
    expect(await screen.findByText(/Demo mode/i)).toBeInTheDocument();
    expect(screen.queryByText('PayPal Sandbox')).not.toBeInTheDocument();
    expect(screen.queryByTestId('paypal-provider')).not.toBeInTheDocument();
  });

  it('says PayPal Sandbox when the backend talks to the real sandbox', async () => {
    mockHealth('live_sandbox');
    render(<Home />);
    expect(await screen.findByText('PayPal Sandbox')).toBeInTheDocument();
    expect(screen.queryByText(/Demo mode/i)).not.toBeInTheDocument();
  });

  it('does not claim either mode before the backend has answered', async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch')) as any;
    render(<Home />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(screen.queryByText('PayPal Sandbox')).not.toBeInTheDocument();
    expect(screen.queryByText(/Demo mode/i)).not.toBeInTheDocument();
  });
});
