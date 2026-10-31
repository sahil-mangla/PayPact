import React from 'react';
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';

// framer-motion reads the preference once per module graph, so this lives in its own file
// and the preference is set before the component is loaded.
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  configurable: true,
  value: (query: string) => ({
    matches: query.includes('prefers-reduced-motion'),
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  }),
});

describe('WordByWordText with reduced motion', () => {
  it('shows the full text and provider tag at once, with nothing hidden for animation', async () => {
    const { WordByWordText } = await import('../components/WordByWordText');
    const { container } = render(
      <WordByWordText text="Matched to your request. [Powered by Gemini 2.5 Flash]" />,
    );
    expect(container.textContent).toContain('Matched to your request.');
    expect(container.textContent).toContain('Powered by Gemini 2.5 Flash');
    const hidden = Array.from(container.querySelectorAll('*')).filter((el) =>
      (el.getAttribute('style') || '').includes('opacity: 0'),
    );
    expect(hidden).toHaveLength(0);
  });
});
