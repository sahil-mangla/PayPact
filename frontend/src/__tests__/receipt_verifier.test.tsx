import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import Home from '../app/page';

vi.mock('@paypal/react-paypal-js', () => ({
  PayPalScriptProvider: ({ children }: { children: React.ReactNode }) => <div data-testid="paypal-provider">{children}</div>,
  PayPalButtons: () => <button data-testid="paypal-button">PayPal Checkout</button>,
  usePayPalScriptReducer: () => [{ isPending: false }, vi.fn()],
}));

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

describe('Cryptographic Receipt Verifier Component', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockImplementation((url: string, options?: any) => {
      if (url.includes('/health')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'healthy', paypal_mode: 'mock' }),
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
        const isValid = body.signature === 'valid_hmac_hex_signature';
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            valid: isValid,
            receipt_id: body.receipt_id,
            checkout_id: body.checkout_id,
            algorithm: 'HMAC-SHA256',
            signer: 'APIL-Ledger-Authority-v1.0',
          }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve([]) });
    });
  });

  it('loads sample receipt and verifies valid signature successfully', async () => {
    render(<Home />);

    // Go to Audit Trail tab
    const auditTab = screen.getByText('Audit Trail');
    fireEvent.click(auditTab);

    // Click "Verify Authentic Receipt"
    const loadSampleBtn = await screen.findByText('Verify Authentic Receipt');
    fireEvent.click(loadSampleBtn);

    // Check verified status
    await waitFor(() => {
      expect(screen.getByText(/Authentic Signature Verified/i)).toBeInTheDocument();
    });
  });
});
