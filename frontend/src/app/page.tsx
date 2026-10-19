'use client';

import React, { useState, useEffect } from 'react';
import {
  Shield,
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  CreditCard,
  ShoppingBag,
  Sparkles,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  FileText,
  Lock,
  ArrowRight,
  Zap,
  Fingerprint,
  TrendingUp,
  Cpu,
  Layers,
  Activity,
  Copy,
  ChevronRight,
  ExternalLink,
} from 'lucide-react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';

const DEFAULT_SCENARIOS = [
  { scenario_id: 'SC-A', name: 'Happy Path Purchase', category: 'Nominal', description: 'Standard purchase within automatic limit and budget constraints.' },
  { scenario_id: 'SC-B', name: 'Price & Shipping Drift', category: 'Drift', description: 'Shipping fee added at checkout raises total above the automatic limit.' },
  { scenario_id: 'SC-C', name: 'Revoked Authorization', category: 'Lifecycle', description: 'User revokes spending policy while the agent\'s task is in-flight.' },
  { scenario_id: 'SC-D', name: 'Product Substitution', category: 'Integrity', description: 'Merchant substitutes a different product SKU after user approval.' },
  { scenario_id: 'SC-E', name: 'Duplicate Submission', category: 'Concurrency', description: 'Identical purchase request triggered twice concurrently.' },
  { scenario_id: 'SC-F', name: 'Prompt Injection in Item', category: 'Adversarial', description: 'Product description contains prompt injection attempting to force unauthorized purchase.' },
  { scenario_id: 'SC-G', name: 'Ambiguous Payment Timeout', category: 'Network', description: 'Network drops during capture. Ambiguous state without confirmation.' },
];

export default function Home() {
  const [activeTab, setActiveTab] = useState<'agent' | 'lab' | 'audit'>('agent');
  const [healthStatus, setHealthStatus] = useState<any>(null);

  // Agent State
  const [prompt, setPrompt] = useState('Find a wireless mechanical keyboard suitable for programming. Maximum budget ₹5,000, auto-buy under ₹4,000.');
  const [policy, setPolicy] = useState<any>(null);
  const [proposalRes, setProposalRes] = useState<any>(null);
  const [checkoutSession, setCheckoutSession] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Live Interactive Perturbations
  const [simulateDrift, setSimulateDrift] = useState<'none' | 'price_drift' | 'sku_substitution'>('none');

  // Lab Benchmark State
  const [labScenarios, setLabScenarios] = useState<any[]>([]);
  const [selectedSystem, setSelectedSystem] = useState<'PROPOSED_APIL' | 'BASELINE_A' | 'BASELINE_B'>('PROPOSED_APIL');
  const [benchmarkReport, setBenchmarkReport] = useState<any>(null);
  const [labRunning, setLabRunning] = useState(false);

  // Audit Ledger State
  const [auditData, setAuditData] = useState<any>(null);
  const [copiedHash, setCopiedHash] = useState<string | null>(null);

  // Initial Health & Scenarios Fetch
  useEffect(() => {
    fetchHealth();
    fetchScenarios();
  }, []);

  const fetchHealth = async () => {
    try {
      const res = await fetch(`${API_BASE}/health`);
      if (res.ok) {
        const data = await res.json();
        setHealthStatus(data);
      }
    } catch (e) {
      console.warn('API health check offline or connecting...', e);
    }
  };

  const fetchScenarios = async () => {
    try {
      const res = await fetch(`${API_BASE}/lab/scenarios`);
      if (res.ok) {
        const data = await res.json();
        setLabScenarios(data);
      }
    } catch (e) {
      console.warn('Failed to load lab scenarios', e);
    }
  };

  const fetchAuditEvents = async () => {
    try {
      const res = await fetch(`${API_BASE}/audit/events`);
      if (res.ok) {
        const data = await res.json();
        setAuditData(data);
      }
    } catch (e) {
      console.warn('Failed to fetch audit events', e);
    }
  };

  // Step 1: Parse and Confirm Intent Policy
  const handleParsePolicy = async () => {
    setLoading(true);
    setErrorMsg(null);
    setProposalRes(null);
    setCheckoutSession(null);
    try {
      const parseRes = await fetch(`${API_BASE}/authorizations/parse-intent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, user_id: 'usr_shopper' }),
      });
      if (!parseRes.ok) throw new Error('Failed to parse intent.');
      const parsedPolicy = await parseRes.json();

      // Register Policy
      const regRes = await fetch(`${API_BASE}/authorizations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(parsedPolicy),
      });
      if (!regRes.ok) throw new Error('Failed to register policy.');
      const savedPolicy = await regRes.json();
      setPolicy(savedPolicy);

      // Auto-generate proposal
      await handleGenerateProposal(savedPolicy.policy_id);
    } catch (err: any) {
      setErrorMsg(err.message || 'Error parsing intent');
    } finally {
      setLoading(false);
    }
  };

  // Step 2: Agent Generates Proposal
  const handleGenerateProposal = async (policyId: string) => {
    try {
      const propRes = await fetch(`${API_BASE}/proposals`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, policy_id: policyId }),
      });
      if (!propRes.ok) {
        const err = await propRes.json();
        throw new Error(err.detail || 'Failed to generate proposal');
      }
      const data = await propRes.json();
      setProposalRes(data);
    } catch (err: any) {
      setErrorMsg(err.message);
    }
  };

  // Step 3: Approve Proposal (if required)
  const handleApprove = async () => {
    if (!proposalRes?.checkout_id) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/checkouts/${proposalRes.checkout_id}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: 'usr_shopper' }),
      });
      if (!res.ok) throw new Error('Approval failed.');
      const updated = await res.json();
      setProposalRes((prev: any) => ({ ...prev, state: updated.state }));
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Step 4: Execute PayPal Checkout
  const handleExecutePayment = async () => {
    if (!proposalRes?.checkout_id) return;
    setLoading(true);
    setErrorMsg(null);
    try {
      const payload: any = {};
      if (simulateDrift !== 'none') {
        payload.simulate_drift_type = simulateDrift;
      }

      const res = await fetch(`${API_BASE}/checkouts/${proposalRes.checkout_id}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      setCheckoutSession(data);
      if (!res.ok) {
        setErrorMsg(data.detail || 'Execution blocked by policy engine');
      }
    } catch (err: any) {
      setErrorMsg(err.message);
    } finally {
      setLoading(false);
    }
  };

  // Revoke Policy
  const handleRevokePolicy = async () => {
    if (!policy?.policy_id) return;
    try {
      await fetch(`${API_BASE}/authorizations/${policy.policy_id}/revoke`, { method: 'POST' });
      setPolicy((prev: any) => ({ ...prev, is_revoked: true }));
    } catch (err: any) {
      setErrorMsg(err.message);
    }
  };

  // Run Benchmark in Lab
  const handleRunBenchmark = async () => {
    setLabRunning(true);
    try {
      const res = await fetch(`${API_BASE}/lab/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ system_type: selectedSystem }),
      });
      const data = await res.json();
      setBenchmarkReport(data.benchmark_report);
    } catch (err: any) {
      console.error(err);
    } finally {
      setLabRunning(false);
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedHash(text);
    setTimeout(() => setCopiedHash(null), 2000);
  };

  return (
    <main style={{ minHeight: '100vh', paddingBottom: '80px' }}>
      {/* Top Navbar */}
      <header
        style={{
          borderBottom: '1px solid var(--border-subtle)',
          background: 'rgba(6, 9, 19, 0.85)',
          backdropFilter: 'blur(12px)',
          position: 'sticky',
          top: 0,
          zIndex: 50,
          padding: '16px 32px',
        }}
      >
        <div style={{ maxWidth: '1280px', margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div
              style={{
                width: '40px',
                height: '40px',
                borderRadius: '10px',
                background: 'linear-gradient(135deg, #0070ba 0%, #06b6d4 100%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                boxShadow: '0 0 20px rgba(6, 182, 212, 0.4)',
              }}
            >
              <ShieldCheck size={22} color="#ffffff" />
            </div>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <h1 style={{ fontSize: '1.25rem', fontWeight: 800, color: '#fff' }}>APIL</h1>
                <span className="badge badge-neutral" style={{ fontSize: '0.65rem' }}>v1.0 Hackathon</span>
              </div>
              <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                Agent Payment Integrity Layer • PayPal Sandbox
              </p>
            </div>
          </div>

          {/* Mode Switcher */}
          <div style={{ display: 'flex', gap: '4px', background: 'rgba(255, 255, 255, 0.05)', padding: '4px', borderRadius: '12px', border: '1px solid var(--border-subtle)' }}>
            <button
              onClick={() => setActiveTab('agent')}
              className={`btn ${activeTab === 'agent' ? 'btn-primary' : 'btn-secondary'}`}
              style={{ padding: '8px 16px', fontSize: '0.8rem' }}
            >
              <ShoppingBag size={16} /> Purchase Agent
            </button>
            <button
              onClick={() => { setActiveTab('lab'); if (!benchmarkReport) handleRunBenchmark(); }}
              className={`btn ${activeTab === 'lab' ? 'btn-cyan' : 'btn-secondary'}`}
              style={{ padding: '8px 16px', fontSize: '0.8rem' }}
            >
              <Activity size={16} /> Integrity Lab
            </button>
            <button
              onClick={() => { setActiveTab('audit'); fetchAuditEvents(); }}
              className={`btn ${activeTab === 'audit' ? 'btn-primary' : 'btn-secondary'}`}
              style={{ padding: '8px 16px', fontSize: '0.8rem' }}
            >
              <FileText size={16} /> Audit Trail
            </button>
          </div>

          {/* Live Status Badge */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '6px 12px',
                borderRadius: '9999px',
                background: 'rgba(0, 112, 186, 0.15)',
                border: '1px solid rgba(0, 112, 186, 0.35)',
                fontSize: '0.75rem',
                color: '#60a5fa',
              }}
            >
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#38bdf8', display: 'inline-block', boxShadow: '0 0 8px #38bdf8' }} />
              PayPal Sandbox Connected
            </div>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <div style={{ maxWidth: '1280px', margin: '32px auto', padding: '0 24px' }}>
        {errorMsg && (
          <div
            className="animate-fade-in"
            style={{
              padding: '14px 20px',
              borderRadius: 'var(--radius-md)',
              background: 'var(--status-reject-bg)',
              border: '1px solid var(--status-reject-border)',
              color: 'var(--status-reject)',
              marginBottom: '24px',
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              fontSize: '0.875rem',
            }}
          >
            <AlertTriangle size={18} />
            <span>{errorMsg}</span>
          </div>
        )}

        {/* ============================================================== */}
        {/* VIEW 1: PURCHASE AGENT (Consumer Shopping Flow) */}
        {/* ============================================================== */}
        {activeTab === 'agent' && (
          <div className="animate-fade-in" style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '28px' }}>
            {/* Left Column: Input, Policy, and Execution */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              {/* Natural Language Prompt Composer */}
              <div className="glass-panel" style={{ padding: '24px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
                  <Sparkles size={20} color="var(--accent-cyan)" />
                  <h2 style={{ fontSize: '1.1rem', fontWeight: 700 }}>AI Purchase Goal</h2>
                </div>
                <textarea
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  rows={3}
                  style={{
                    width: '100%',
                    background: 'rgba(0, 0, 0, 0.35)',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-md)',
                    padding: '12px 16px',
                    color: '#fff',
                    fontSize: '0.9rem',
                    resize: 'none',
                    outline: 'none',
                    lineHeight: '1.5',
                  }}
                  placeholder="Describe what you want the agent to purchase and spending rules..."
                />

                {/* Preset Chips */}
                <div style={{ marginTop: '12px', display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', alignSelf: 'center' }}>Presets:</span>
                  <button
                    onClick={() => setPrompt('Find a wireless mechanical keyboard suitable for programming. Maximum budget ₹5,000, auto-buy under ₹4,000.')}
                    className="badge badge-neutral"
                    style={{ cursor: 'pointer', background: 'rgba(255,255,255,0.04)' }}
                  >
                    Nominal Under Limit (Auto-buy ₹4k)
                  </button>
                  <button
                    onClick={() => setPrompt('Find premium custom mechanical keyboard under ₹5,000. Require approval above ₹4,000.')}
                    className="badge badge-neutral"
                    style={{ cursor: 'pointer', background: 'rgba(255,255,255,0.04)' }}
                  >
                    Exceeds Auto Limit (Requires Approval)
                  </button>
                  <button
                    onClick={() => setPrompt('Search for custom brass keyboard. Budget ceiling ₹5,000.')}
                    className="badge badge-neutral"
                    style={{ cursor: 'pointer', background: 'rgba(255,255,255,0.04)' }}
                  >
                    Exceeds Max Budget (Ceiling Reject)
                  </button>
                </div>

                <div style={{ marginTop: '18px', display: 'flex', justifyContent: 'flex-end' }}>
                  <button
                    onClick={handleParsePolicy}
                    disabled={loading || !prompt.trim()}
                    className="btn btn-cyan"
                  >
                    {loading ? <RefreshCw className="animate-spin" size={16} /> : <Zap size={16} />}
                    Extract Constraints & Propose
                  </button>
                </div>
              </div>

              {/* Confirmed Authorization Policy Card */}
              {policy && (
                <div className="glass-panel animate-fade-in" style={{ padding: '24px', borderLeft: policy.is_revoked ? '4px solid var(--status-reject)' : '4px solid var(--accent-cyan)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <Lock size={18} color={policy.is_revoked ? 'var(--status-reject)' : 'var(--accent-cyan)'} />
                      <h3 style={{ fontSize: '1rem', fontWeight: 700 }}>Confirmed Authorization Policy</h3>
                      <span className="badge badge-neutral">v{policy.version}</span>
                    </div>
                    {policy.is_revoked ? (
                      <span className="badge badge-reject">Revoked by User</span>
                    ) : (
                      <button
                        onClick={handleRevokePolicy}
                        className="btn btn-danger"
                        style={{ padding: '4px 10px', fontSize: '0.75rem' }}
                      >
                        Revoke Policy
                      </button>
                    )}
                  </div>

                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', fontSize: '0.85rem' }}>
                    <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: '12px', borderRadius: 'var(--radius-sm)' }}>
                      <span style={{ color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Maximum Budget Ceiling</span>
                      <strong style={{ fontSize: '1.1rem', color: '#fff' }}>₹{policy.maximum_total.toLocaleString()}</strong>
                      <span style={{ color: 'var(--text-secondary)', display: 'block', fontSize: '0.75rem' }}>Hard invariant (Non-bypassable)</span>
                    </div>
                    <div style={{ background: 'rgba(255, 255, 255, 0.03)', padding: '12px', borderRadius: 'var(--radius-sm)' }}>
                      <span style={{ color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Automatic Purchase Limit</span>
                      <strong style={{ fontSize: '1.1rem', color: 'var(--accent-cyan)' }}>₹{policy.automatic_purchase_limit.toLocaleString()}</strong>
                      <span style={{ color: 'var(--text-secondary)', display: 'block', fontSize: '0.75rem' }}>Over limit requires explicit approval</span>
                    </div>
                  </div>

                  <div style={{ marginTop: '12px', fontSize: '0.75rem', color: 'var(--text-muted)', display: 'flex', justifyContent: 'space-between' }}>
                    <span>Category: <strong style={{ color: 'var(--text-primary)' }}>{policy.product_category}</strong></span>
                    <span>Allowed Merchants: <strong style={{ color: 'var(--text-primary)' }}>{policy.allowed_merchants?.join(', ')}</strong></span>
                  </div>
                </div>
              )}

              {/* Interactive Perturbation / Drift Injector (For Hackathon Demo) */}
              {proposalRes && (
                <div className="glass-panel animate-fade-in" style={{ padding: '20px', background: 'rgba(30, 41, 59, 0.4)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                    <TrendingUp size={18} color="var(--status-approval)" />
                    <h4 style={{ fontSize: '0.9rem', fontWeight: 700 }}>Interactive Drift Injection (Judge Simulation)</h4>
                  </div>
                  <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '12px' }}>
                    Test whether the pre-execution gate halts execution when real-world state shifts before PayPal capture:
                  </p>
                  <div style={{ display: 'flex', gap: '10px' }}>
                    <button
                      onClick={() => setSimulateDrift('none')}
                      className={`btn ${simulateDrift === 'none' ? 'btn-primary' : 'btn-secondary'}`}
                      style={{ padding: '6px 12px', fontSize: '0.75rem' }}
                    >
                      Nominal (No Drift)
                    </button>
                    <button
                      onClick={() => setSimulateDrift('price_drift')}
                      className={`btn ${simulateDrift === 'price_drift' ? 'btn-danger' : 'btn-secondary'}`}
                      style={{ padding: '6px 12px', fontSize: '0.75rem' }}
                    >
                      Inject +₹850 Shipping Drift
                    </button>
                    <button
                      onClick={() => setSimulateDrift('sku_substitution')}
                      className={`btn ${simulateDrift === 'sku_substitution' ? 'btn-danger' : 'btn-secondary'}`}
                      style={{ padding: '6px 12px', fontSize: '0.75rem' }}
                    >
                      Inject SKU Substitution
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* Right Column: AI Proposal, Fingerprint, and Payment Execution */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              {!proposalRes ? (
                <div
                  className="glass-panel"
                  style={{
                    padding: '60px 24px',
                    textAlign: 'center',
                    color: 'var(--text-muted)',
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <Cpu size={48} strokeWidth={1.2} style={{ marginBottom: '16px', opacity: 0.5 }} />
                  <h3 style={{ fontSize: '1.1rem', color: 'var(--text-secondary)', marginBottom: '8px' }}>
                    Awaiting Purchase Proposal
                  </h3>
                  <p style={{ fontSize: '0.85rem', maxWidth: '320px' }}>
                    Enter a purchase goal on the left. The agent will propose an item from the controlled catalogue.
                  </p>
                </div>
              ) : (
                <div className="glass-panel animate-fade-in" style={{ padding: '24px' }}>
                  {/* Proposal Header */}
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
                    <div>
                      <span style={{ fontSize: '0.75rem', color: 'var(--accent-cyan)', fontWeight: 600 }}>CANDIDATE PROPOSAL</span>
                      <h3 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#fff', marginTop: '2px' }}>
                        {proposalRes.proposal.items[0].name}
                      </h3>
                      <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                        Merchant: <strong>{proposalRes.proposal.merchant}</strong> • SKU: <code style={{ color: 'var(--accent-cyan)' }}>{proposalRes.proposal.items[0].sku}</code>
                      </p>
                    </div>

                    {/* Policy Gate Decision Badge */}
                    <div>
                      {proposalRes.state === 'AUTHORIZED' && (
                        <span className="badge badge-allow"><CheckCircle2 size={14} /> ALLOW (AUTO-BUY)</span>
                      )}
                      {proposalRes.state === 'AWAITING_APPROVAL' && (
                        <span className="badge badge-approval"><AlertTriangle size={14} /> REQUIRES APPROVAL</span>
                      )}
                      {proposalRes.state === 'POLICY_REJECTED' && (
                        <span className="badge badge-reject"><ShieldX size={14} /> REJECTED</span>
                      )}
                    </div>
                  </div>

                  {/* Recommendation Narrative */}
                  <div style={{ background: 'rgba(0, 0, 0, 0.25)', padding: '12px 16px', borderRadius: 'var(--radius-sm)', fontSize: '0.825rem', color: 'var(--text-secondary)', lineHeight: '1.5', marginBottom: '16px', borderLeft: '3px solid var(--accent-paypal)' }}>
                    {proposalRes.recommendation_explanation}
                  </div>

                  {/* Pricing Breakdown */}
                  <div style={{ background: 'rgba(255, 255, 255, 0.02)', padding: '16px', borderRadius: 'var(--radius-sm)', marginBottom: '18px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: '8px' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Line-item Subtotal</span>
                      <strong style={{ color: '#fff' }}>₹{proposalRes.proposal.item_subtotal.toLocaleString()}</strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: '8px' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>
                        Shipping Fee {simulateDrift === 'price_drift' && <span style={{ color: 'var(--status-reject)' }}>(+₹850 Injected)</span>}
                      </span>
                      <strong style={{ color: simulateDrift === 'price_drift' ? 'var(--status-reject)' : '#fff' }}>
                        ₹{(simulateDrift === 'price_drift' ? 850 : proposalRes.proposal.shipping_fee).toLocaleString()}
                      </strong>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.85rem', marginBottom: '12px' }}>
                      <span style={{ color: 'var(--text-secondary)' }}>Estimated Tax</span>
                      <strong style={{ color: '#fff' }}>₹{proposalRes.proposal.tax_fee.toLocaleString()}</strong>
                    </div>
                    <div style={{ height: '1px', background: 'var(--border-subtle)', marginBottom: '12px' }} />
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>Final Total Amount</span>
                      <strong style={{ fontSize: '1.25rem', color: simulateDrift === 'price_drift' ? 'var(--status-reject)' : 'var(--accent-cyan)' }}>
                        ₹{(simulateDrift === 'price_drift' ? proposalRes.proposal.item_subtotal + 850 : proposalRes.proposal.total_amount).toLocaleString()} {proposalRes.proposal.currency}
                      </strong>
                    </div>
                  </div>

                  {/* Cryptographic SHA-256 Fingerprint */}
                  <div style={{ background: 'rgba(6, 182, 212, 0.05)', border: '1px solid var(--accent-cyan-glow)', borderRadius: 'var(--radius-sm)', padding: '12px', marginBottom: '20px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                      <span style={{ fontSize: '0.75rem', color: 'var(--accent-cyan)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <Fingerprint size={14} /> CANONICAL PROPOSAL FINGERPRINT (SHA-256)
                      </span>
                      <button
                        onClick={() => copyToClipboard(proposalRes.proposal.proposal_fingerprint)}
                        style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.7rem' }}
                      >
                        {copiedHash ? 'Copied!' : <><Copy size={12} /> Copy</>}
                      </button>
                    </div>
                    <code style={{ fontSize: '0.75rem', color: '#94a3b8', wordBreak: 'break-all', display: 'block' }}>
                      {proposalRes.proposal.proposal_fingerprint}
                    </code>
                  </div>

                  {/* Execution Actions */}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {proposalRes.state === 'AWAITING_APPROVAL' && (
                      <button
                        onClick={handleApprove}
                        disabled={loading}
                        className="btn btn-cyan"
                        style={{ width: '100%' }}
                      >
                        <ShieldCheck size={18} /> Explicitly Approve Exact Proposal Fingerprint
                      </button>
                    )}

                    {proposalRes.state === 'AUTHORIZED' && (
                      <button
                        onClick={handleExecutePayment}
                        disabled={loading}
                        className="btn btn-primary"
                        style={{ width: '100%', padding: '14px', fontSize: '0.95rem' }}
                      >
                        {loading ? <RefreshCw className="animate-spin" size={18} /> : <CreditCard size={18} />}
                        Execute PayPal Sandbox Payment
                      </button>
                    )}

                    {proposalRes.state === 'POLICY_REJECTED' && (
                      <div style={{ textAlign: 'center', padding: '10px', color: 'var(--status-reject)', fontSize: '0.85rem' }}>
                        {proposalRes.failure_reason || 'Proposal rejected by Deterministic Policy Engine.'}
                      </div>
                    )}
                  </div>

                  {/* Payment Completed Verified Receipt */}
                  {checkoutSession?.state === 'PAID' && (
                    <div
                      className="animate-fade-in"
                      style={{
                        marginTop: '20px',
                        padding: '16px',
                        borderRadius: 'var(--radius-md)',
                        background: 'var(--status-allow-bg)',
                        border: '1px solid var(--status-allow-border)',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--status-allow)', marginBottom: '8px' }}>
                        <CheckCircle2 size={18} />
                        <strong style={{ fontSize: '0.9rem' }}>PayPal Sandbox Payment Verified & Settled</strong>
                      </div>
                      <div style={{ fontSize: '0.775rem', color: 'var(--text-secondary)', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
                        <div>Order ID: <code style={{ color: '#fff' }}>{checkoutSession.paypal_order_id}</code></div>
                        <div>Capture ID: <code style={{ color: '#fff' }}>{checkoutSession.paypal_capture_id}</code></div>
                        <div>Status: <strong style={{ color: 'var(--status-allow)' }}>COMPLETED</strong></div>
                        <div>Settled Total: <strong style={{ color: '#fff' }}>₹{proposalRes.proposal.total_amount.toLocaleString()}</strong></div>
                      </div>
                    </div>
                  )}

                  {/* Drift Caught Receipt */}
                  {checkoutSession?.state === 'POLICY_REJECTED' && (
                    <div
                      className="animate-fade-in"
                      style={{
                        marginTop: '20px',
                        padding: '16px',
                        borderRadius: 'var(--radius-md)',
                        background: 'var(--status-reject-bg)',
                        border: '1px solid var(--status-reject-border)',
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--status-reject)', marginBottom: '6px' }}>
                        <ShieldAlert size={18} />
                        <strong style={{ fontSize: '0.9rem' }}>Pre-Execution Gate Intercepted Drift!</strong>
                      </div>
                      <p style={{ fontSize: '0.8rem', color: '#fca5a5' }}>
                        {checkoutSession.failure_reason}
                      </p>
                      <span style={{ fontSize: '0.725rem', color: 'var(--text-muted)', display: 'block', marginTop: '6px' }}>
                        Zero payment request was sent to PayPal. Funds safely protected.
                      </span>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ============================================================== */}
        {/* VIEW 2: INTEGRITY LAB (Benchmark Matrix View) */}
        {/* ============================================================== */}
        {activeTab === 'lab' && (
          <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            {/* Lab Benchmark Header Bar */}
            <div className="glass-panel" style={{ padding: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <Layers size={22} color="var(--accent-cyan)" />
                  <h2 style={{ fontSize: '1.25rem', fontWeight: 800 }}>Integrity Lab Benchmark Runner</h2>
                </div>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
                  Compare the Proposed APIL against Unconstrained and Naive Baselines across all 7 transaction failure scenarios.
                </p>
              </div>

              <div style={{ display: 'flex', gap: '12px' }}>
                <select
                  value={selectedSystem}
                  onChange={(e: any) => setSelectedSystem(e.target.value)}
                  style={{
                    background: 'rgba(255, 255, 255, 0.05)',
                    color: '#fff',
                    border: '1px solid var(--border-subtle)',
                    borderRadius: 'var(--radius-md)',
                    padding: '8px 14px',
                    fontSize: '0.85rem',
                    outline: 'none',
                  }}
                >
                  <option value="PROPOSED_APIL">Proposed APIL (Lifecycle Gate)</option>
                  <option value="BASELINE_A">Baseline A (No Gate / Unconstrained)</option>
                  <option value="BASELINE_B">Baseline B (Naive Static Gate)</option>
                </select>

                <button
                  onClick={handleRunBenchmark}
                  disabled={labRunning}
                  className="btn btn-cyan"
                >
                  {labRunning ? <RefreshCw className="animate-spin" size={16} /> : <Zap size={16} />}
                  Run Full Evaluation Matrix
                </button>
              </div>
            </div>

            {/* Benchmark Summary Metrics Cards */}
            {benchmarkReport && (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '18px' }}>
                {Object.entries(benchmarkReport.summary_by_system).map(([sysKey, metrics]: any) => {
                  const isProposed = sysKey === 'PROPOSED_APIL';
                  return (
                    <div
                      key={sysKey}
                      className="glass-panel"
                      style={{
                        padding: '20px',
                        border: isProposed ? '2px solid var(--accent-cyan)' : '1px solid var(--border-subtle)',
                        boxShadow: isProposed ? '0 0 25px rgba(6, 182, 212, 0.15)' : 'none',
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                        <span style={{ fontSize: '0.85rem', fontWeight: 700, color: isProposed ? 'var(--accent-cyan)' : 'var(--text-secondary)' }}>
                          {sysKey === 'PROPOSED_APIL' ? 'Proposed APIL' : sysKey === 'BASELINE_A' ? 'Baseline A (No Gate)' : 'Baseline B (Static Gate)'}
                        </span>
                        {isProposed && <span className="badge badge-allow" style={{ fontSize: '0.65rem' }}>Protected</span>}
                      </div>

                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                        <div>
                          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Pass Rate</span>
                          <h4 style={{ fontSize: '1.5rem', fontWeight: 800, color: metrics.pass_rate_pct === 100 ? 'var(--status-allow)' : 'var(--status-reject)' }}>
                            {metrics.pass_rate_pct}%
                          </h4>
                        </div>
                        <div>
                          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Unauthorized Spends</span>
                          <h4 style={{ fontSize: '1.5rem', fontWeight: 800, color: metrics.unauthorized_spend_count === 0 ? 'var(--status-allow)' : 'var(--status-reject)' }}>
                            {metrics.unauthorized_spend_count}
                          </h4>
                        </div>
                      </div>

                      <div style={{ marginTop: '12px', fontSize: '0.75rem', color: 'var(--text-muted)', display: 'flex', justifyContent: 'space-between' }}>
                        <span>Avg Latency: <strong style={{ color: '#fff' }}>{metrics.avg_latency_ms} ms</strong></span>
                        <span>Scenarios: <strong>{metrics.total_scenarios}</strong></span>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {/* 7-Scenario Results Table */}
            <div className="glass-panel" style={{ padding: '24px' }}>
              <h3 style={{ fontSize: '1.1rem', fontWeight: 700, marginBottom: '16px' }}>Controlled Scenario Evaluation Matrix</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {(labScenarios.length ? labScenarios : DEFAULT_SCENARIOS).map((sc: any) => {
                  const result = benchmarkReport?.detailed_results?.find(
                    (r: any) => r.scenario_id === sc.scenario_id && r.system_configuration === selectedSystem
                  );

                  return (
                    <div
                      key={sc.scenario_id}
                      style={{
                        background: 'rgba(255, 255, 255, 0.02)',
                        border: '1px solid var(--border-subtle)',
                        borderRadius: 'var(--radius-md)',
                        padding: '16px 20px',
                        display: 'grid',
                        gridTemplateColumns: '80px 220px 1.5fr 160px',
                        alignItems: 'center',
                        gap: '16px',
                      }}
                    >
                      <div>
                        <span className="badge badge-neutral" style={{ fontSize: '0.7rem' }}>{sc.scenario_id}</span>
                      </div>
                      <div>
                        <strong style={{ fontSize: '0.9rem', color: '#fff' }}>{sc.name}</strong>
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block' }}>Category: {sc.category}</span>
                      </div>
                      <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                        <p>{sc.description}</p>
                        {result && (
                          <div style={{ marginTop: '4px', fontSize: '0.75rem', color: result.protection_successful ? '#34d399' : '#f87171' }}>
                            {result.primary_reason}
                          </div>
                        )}
                      </div>
                      <div style={{ textAlign: 'right' }}>
                        {result ? (
                          result.protection_successful ? (
                            <span className="badge badge-allow"><ShieldCheck size={14} /> Passed</span>
                          ) : (
                            <span className="badge badge-reject"><ShieldAlert size={14} /> Failed (Drift)</span>
                          )
                        ) : (
                          <span className="badge badge-neutral">Ready to run</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* ============================================================== */}
        {/* VIEW 3: AUDIT LEDGER (Cryptographic Provenance) */}
        {/* ============================================================== */}
        {activeTab === 'audit' && (
          <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <div className="glass-panel" style={{ padding: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <FileText size={22} color="var(--accent-paypal)" />
                  <h2 style={{ fontSize: '1.25rem', fontWeight: 800 }}>Append-Only Cryptographic Audit Ledger</h2>
                </div>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
                  Hash-chained event log recording every state transition, policy evaluation, and PayPal observation.
                </p>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                {auditData?.ledger_integrity_valid ? (
                  <span className="badge badge-allow" style={{ padding: '6px 14px' }}>
                    <CheckCircle2 size={14} /> Hash Chain Verified
                  </span>
                ) : (
                  <span className="badge badge-neutral">Verifying Ledger...</span>
                )}
                <button onClick={fetchAuditEvents} className="btn btn-secondary" style={{ padding: '8px 12px' }}>
                  <RefreshCw size={14} /> Refresh
                </button>
              </div>
            </div>

            {/* Audit Timeline */}
            <div className="glass-panel" style={{ padding: '24px' }}>
              {!auditData?.events?.length ? (
                <p style={{ textAlign: 'center', color: 'var(--text-muted)', padding: '40px 0' }}>
                  No audit events recorded yet. Run a purchase or lab scenario to populate the ledger.
                </p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  {auditData.events.slice().reverse().map((evt: any, idx: number) => (
                    <div
                      key={evt.event_id}
                      style={{
                        background: 'rgba(255, 255, 255, 0.02)',
                        border: '1px solid var(--border-subtle)',
                        borderRadius: 'var(--radius-md)',
                        padding: '16px 20px',
                        display: 'grid',
                        gridTemplateColumns: '180px 1fr 220px',
                        alignItems: 'center',
                        gap: '16px',
                      }}
                    >
                      <div>
                        <span className="badge badge-neutral" style={{ fontSize: '0.7rem', marginBottom: '4px' }}>
                          {evt.event_type}
                        </span>
                        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                          {new Date(evt.timestamp).toLocaleTimeString()}
                        </div>
                      </div>

                      <div>
                        <p style={{ fontSize: '0.85rem', color: '#fff' }}>{evt.reason || 'Event executed'}</p>
                        {evt.proposal_fingerprint && (
                          <span style={{ fontSize: '0.7rem', color: 'var(--accent-cyan)', fontFamily: 'monospace', display: 'block', marginTop: '4px' }}>
                            FP: {evt.proposal_fingerprint.slice(0, 24)}...
                          </span>
                        )}
                      </div>

                      <div style={{ textAlign: 'right', fontSize: '0.7rem' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Hash: </span>
                        <code style={{ color: '#94a3b8' }}>{evt.event_hash.slice(0, 12)}...</code>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
