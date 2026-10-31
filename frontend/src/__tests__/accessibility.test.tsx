import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import Home from '../app/page';
import { WordByWordText } from '../components/WordByWordText';

function mockMatchMedia(reduce: boolean) {
  Object.defineProperty(window, 'matchMedia', {
    writable: true,
    configurable: true,
    value: (query: string) => ({
      matches: reduce && query.includes('prefers-reduced-motion'),
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

describe('WordByWordText motion', () => {
  afterEach(() => vi.restoreAllMocks());

  it('animates words in by default', () => {
    mockMatchMedia(false);
    const { container } = render(<WordByWordText text="Matched to your request" />);
    const hidden = Array.from(container.querySelectorAll('span')).filter((s) =>
      (s.getAttribute('style') || '').includes('opacity: 0'),
    );
    expect(hidden.length).toBeGreaterThan(0);
  });
});

describe('Purchase form semantics', () => {
  beforeEach(() => {
    mockMatchMedia(false);
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) }) as any;
  });

  it('associates the purchase instructions label with its textarea', () => {
    render(<Home />);
    const field = screen.getByLabelText(/Purchase Instructions/i);
    expect(field.tagName).toBe('TEXTAREA');
    expect(field).toHaveAttribute('maxlength', '500');
  });
});


describe('First-run explanation', () => {
  beforeEach(() => {
    mockMatchMedia(false);
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) }) as any;
  });

  it('explains the PayPal flow before any proposal exists', () => {
    render(<Home />);
    const steps = screen.getByRole('list', { name: /how a purchase works/i });
    expect(steps.textContent).toMatch(/AI agent proposes/);
    expect(steps.textContent).toMatch(/You pay with PayPal/);
    expect(steps.textContent).toMatch(/signed receipt/);
  });
});

describe('Page structure for assistive technology', () => {
  beforeEach(() => {
    mockMatchMedia(false);
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve({}) }) as any;
  });

  it('has a page heading and an exposed tab list', () => {
    render(<Home />);
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('PayPact');
    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(3);
    expect(screen.getByRole('tab', { name: /Purchase Flow/i })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: /Audit Trail/i })).toHaveAttribute('aria-selected', 'false');
  });

  it('announces outcomes through a polite live region', () => {
    render(<Home />);
    expect(screen.getByRole('status')).toHaveAttribute('aria-live', 'polite');
  });
});


describe('Result visibility on a phone', () => {
  it('scrolls a new result into view on a narrow screen but not on a wide one', async () => {
    mockMatchMedia(false);
    const scroll = vi.fn();
    (Element.prototype as any).scrollIntoView = scroll;
    const proposal = { checkout_id: 'c1', state: 'AUTHORIZED', recommendation_explanation: 'ok', proposal: { items: [{ sku: 'S', name: 'N', quantity: 1, unit_price: 1 }], total_amount: 1, item_subtotal: 1, shipping_fee: 0, tax_fee: 0, currency: 'INR', merchant: 'M', proposal_fingerprint: 'f' } };
    global.fetch = vi.fn().mockImplementation((url: string) =>
      Promise.resolve({ ok: true, json: () => Promise.resolve(url.includes('/proposals') ? proposal : url.includes('/health') ? { paypal_mode: 'mock' } : { policy_id: 'p', maximum_total: 5, automatic_purchase_limit: 4, agent_quotas: {} }) }),
    ) as any;

    for (const [width, expected] of [[390, true], [1440, false]] as const) {
      scroll.mockClear();
      Object.defineProperty(window, 'innerWidth', { configurable: true, value: width });
      const { unmount } = render(<Home />);
      fireEvent.click(screen.getByText('Generate Proposal & Check Rules'));
      await waitFor(() => expect(screen.getByTestId('decision-note')).toBeInTheDocument());
      expect(scroll.mock.calls.length > 0).toBe(expected);
      unmount();
    }
  });
});
