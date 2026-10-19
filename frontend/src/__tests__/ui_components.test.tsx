import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import Home from '../app/page';
import { WordByWordText } from '../components/WordByWordText';

// Mock PayPal React SDK components to avoid network dependencies during tests
vi.mock('@paypal/react-paypal-js', () => ({
  PayPalScriptProvider: ({ children }: { children: React.ReactNode }) => <div data-testid="paypal-provider">{children}</div>,
  PayPalButtons: () => <button data-testid="paypal-button">PayPal Checkout</button>,
  usePayPalScriptReducer: () => [{ isPending: false }, vi.fn()],
}));

describe('WordByWordText Component', () => {
  it('renders all words in a phrase correctly with animation spans', () => {
    const text = 'Autonomous Agent Payment Layer';
    const { container } = render(<WordByWordText text={text} />);
    
    expect(container.textContent).toContain('Autonomous');
    expect(container.textContent).toContain('Agent');
    expect(container.textContent).toContain('Payment');
    expect(container.textContent).toContain('Layer');
    
    const spans = container.querySelectorAll('span > span');
    expect(spans.length).toBe(4);
  });

  it('handles single word strings smoothly', () => {
    const { container } = render(<WordByWordText text="APIL" />);
    expect(container.textContent).toBe('APIL');
  });
});

describe('Main Dashboard Layout & Navigation', () => {
  beforeEach(() => {
    // Provide basic fetch mock for initial load
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes('/health')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            status: 'healthy',
            service: 'Agent Payment Integrity Layer (APIL)',
            paypal_mode: 'mock',
            ollama: { available: true, model: 'qwen2.5-coder:7b', installed: true },
          }),
        });
      }
      if (url.includes('/agent/model-status')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            available: true,
            model: 'qwen2.5-coder:7b',
            installed: true,
          }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve([]),
      });
    });
  });

  it('renders the Aceternity-style floating pill navigation with all 3 core tabs', () => {
    render(<Home />);
    
    expect(screen.getByText('PayPact')).toBeInTheDocument();
    expect(screen.getByText('Purchase Flow')).toBeInTheDocument();
    expect(screen.getByText('Policy Test Lab')).toBeInTheDocument();
    expect(screen.getByText('Audit Trail')).toBeInTheDocument();
  });

  it('renders the 3 Swarm Agent personas in the selector card', () => {
    render(<Home />);

    expect(screen.getByText('Hardware Agent')).toBeInTheDocument();
    expect(screen.getByText('Travel Agent')).toBeInTheDocument();
    expect(screen.getByText('Supplies Agent')).toBeInTheDocument();
  });

  it('renders the default instructions textarea and generate button', () => {
    render(<Home />);

    const textarea = screen.getByRole('textbox');
    expect(textarea).toBeInTheDocument();
    expect((textarea as HTMLTextAreaElement).value).toContain('mechanical keyboard');

    const generateButton = screen.getByText('Generate Proposal & Check Rules');
    expect(generateButton).toBeInTheDocument();
  });
});
