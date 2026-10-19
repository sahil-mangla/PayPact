import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ParticleMorphOrb, { AiThinkingOrb, AiThinkingCard } from '../components/ui/ParticleMorphOrb';

describe('ParticleMorphOrb & AI Thinking/Evaluating Components', () => {
  it('renders ParticleMorphOrb without crashing', () => {
    const { container } = render(<ParticleMorphOrb size={64} />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it('renders AiThinkingOrb with default thinking messages and pill structure', () => {
    render(<AiThinkingOrb />);
    expect(screen.getByText(/evaluating policy invariants/i)).toBeInTheDocument();
  });

  it('renders AiThinkingOrb with custom status text and subtext', () => {
    render(
      <AiThinkingOrb
        text="Custom Invariant Evaluation in Progress..."
        subtext="Verifying ₹5,000 budget ceiling"
      />
    );
    expect(screen.getByText('Custom Invariant Evaluation in Progress...')).toBeInTheDocument();
    expect(screen.getByText('Verifying ₹5,000 budget ceiling')).toBeInTheDocument();
  });

  it('renders AiThinkingCard with all 4 invariant stages and active state badge', () => {
    render(<AiThinkingCard currentStage={2} stageTitle="Evaluating Purchase Invariants" />);
    expect(screen.getByText('AI INVARIANT ENGINE ACTIVE')).toBeInTheDocument();
    expect(screen.getByText('Evaluating Purchase Invariants')).toBeInTheDocument();
    expect(screen.getByText('Natural Language Intent')).toBeInTheDocument();
    expect(screen.getByText('Policy Invariant Guard')).toBeInTheDocument();
    expect(screen.getByText('Catalogue SKU Verification')).toBeInTheDocument();
    expect(screen.getByText('SHA-256 Fingerprint')).toBeInTheDocument();
  });
});
