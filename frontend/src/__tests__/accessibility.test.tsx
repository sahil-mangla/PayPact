import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
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
