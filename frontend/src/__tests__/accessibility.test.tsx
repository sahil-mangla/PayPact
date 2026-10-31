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
