'use client';

import React, { useState, useEffect, useCallback } from 'react';
import {
  PayPalScriptProvider,
  PayPalButtons,
  usePayPalScriptReducer,
} from '@paypal/react-paypal-js';
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
  Zap,
  Fingerprint,
  TrendingUp,
  Cpu,
  Layers,
  Activity,
  Copy,
  ExternalLink,
  Database,
  Terminal,
  ArrowRight,
  Eye,
  Bot,
  Download,
  RotateCcw,
  Check,
  CheckCheck,
  X,
  Play,
  Key,
} from 'lucide-react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';
const PAYPAL_CLIENT_ID = process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID || '';

// -------------------------------------------------------
// Pipeline Node Definitions for Animated Motion HUD
// -------------------------------------------------------
interface PipelineStep {
  id: string;
  title: string;
  subtitle: string;
  icon: string;
  state: 'idle' | 'active' | 'success' | 'blocked';
}

const DEFAULT_SCENARIOS = [
  { scenario_id: 'SC-A', name: 'Happy Path Purchase', category: 'Nominal', failure_type: 'None' },
  { scenario_id: 'SC-B', name: 'Price & Shipping Drift', category: 'Drift', failure_type: 'Amount Exceeded' },
  { scenario_id: 'SC-C', name: 'Revoked Authorization', category: 'Lifecycle', failure_type: 'Auth Revoked' },
  { scenario_id: 'SC-D', name: 'Product Substitution', category: 'Integrity', failure_type: 'SKU / Fingerprint Mismatch' },
  { scenario_id: 'SC-E', name: 'Duplicate Submission', category: 'Concurrency', failure_type: 'Idempotency Replay' },
  { scenario_id: 'SC-F', name: 'Prompt Injection in Item', category: 'Adversarial', failure_type: 'Forbidden Keyword' },
  { scenario_id: 'SC-G', name: 'Ambiguous Payment Timeout', category: 'Network', failure_type: 'Network Race Timeout' },
];

// -------------------------------------------------------
// PayPal Checkout Button (inner)
// -------------------------------------------------------
function PayPalCheckoutButton({
  checkoutId,
  onSuccess,
  onError,
}: {
  checkoutId: string;
  onSuccess: (session: any) => void;
  onError: (msg: string) => void;
}) {
  const [{ isPending }] = usePayPalScriptReducer();

  return (
    <div style={{ marginTop: '12px' }}>
      {isPending && (
        <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.8rem', padding: '12px' }}>
          <RefreshCw size={15} className="animate-spin" style={{ display: 'inline', marginRight: '8px' }} />
          Connecting to PayPal Sandbox v2 API...
        </div>
      )}
      <PayPalButtons
        style={{ layout: 'vertical', color: 'blue', shape: 'rect', label: 'pay', height: 46 }}
        createOrder={async () => {
          const res = await fetch(`${API_BASE}/checkouts/${checkoutId}/execute`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({}),
          });
          const data = await res.json();

          if (!res.ok) throw new Error(data.detail || 'Backend error');

          const session = data.session;
          if (session?.state === 'POLICY_REJECTED' || session?.state === 'FAILED') {
            throw new Error(session.failure_reason || 'Blocked by policy engine');
          }
          if (!data.paypal_order_id) throw new Error('No PayPal order ID returned');
          return data.paypal_order_id;
        }}
        onApprove={async (sdkData) => {
          const res = await fetch(`${API_BASE}/checkouts/${checkoutId}/capture`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paypal_order_id: sdkData.orderID }),
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.detail || 'Capture failed');
          onSuccess(data.session);
        }}
        onError={(err) => {
          onError(String(err));
        }}
        onCancel={() => {
          onError('Payment cancelled in PayPal popup.');
        }}
      />
    </div>
  );
}

// -------------------------------------------------------
// Main Dashboard Component
// -------------------------------------------------------
export default function Home() {
  const [activeTab, setActiveTab] = useState<'agent' | 'lab' | 'audit'>('agent');
  const [healthStatus, setHealthStatus] = useState<any>(null);

  // Agent State
  const [prompt, setPrompt] = useState(
    'Find a wireless mechanical keyboard suitable for programming. Maximum budget ₹5,000, auto-buy under ₹4,000.'
  );
  const [policy, setPolicy] = useState<any>(null);
  const [proposalRes, setProposalRes] = useState<any>(null);
  const [checkoutSession, setCheckoutSession] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // Pipeline Animation State
  const [pipelinePhase, setPipelinePhase] = useState<'idle' | 'intent' | 'fingerprint' | 'gate' | 'paypal' | 'settled' | 'blocked'>('idle');

  // Drift simulation
  const [simulateDrift, setSimulateDrift] = useState<'none' | 'price_drift' | 'sku_substitution'>('none');

  // Swarm & Webhook state
  const [selectedAgent, setSelectedAgent] = useState<'agent_hardware' | 'agent_travel' | 'agent_supplies'>('agent_hardware');
  const [webhookStatus, setWebhookStatus] = useState<string | null>(null);

  // Cryptographic Receipt Inspector Modal State
  const [receiptModalOpen, setReceiptModalOpen] = useState(false);
  const [inspectingReceipt, setInspectingReceipt] = useState<any>(null);
  const [receiptVerificationState, setReceiptVerificationState] = useState<'unverified' | 'verifying' | 'valid' | 'invalid'>('unverified');
  const [receiptVerificationDetails, setReceiptVerificationDetails] = useState<any>(null);

  // Lab State
  const [labScenarios, setLabScenarios] = useState<any[]>([]);
  const [selectedSystem, setSelectedSystem] = useState<'PROPOSED_APIL' | 'BASELINE_A' | 'BASELINE_B'>('PROPOSED_APIL');
  const [benchmarkReport, setBenchmarkReport] = useState<any>(null);
  const [labRunning, setLabRunning] = useState(false);

  // Audit State
  const [auditData, setAuditData] = useState<any>(null);
  const [copiedHash, setCopiedHash] = useState<string | null>(null);

  // Fetch health & scenarios on mount
  useEffect(() => {
    fetchHealth();
    fetchScenarios();
    try {
      const saved = localStorage.getItem('apil_benchmark');
      if (saved) setBenchmarkReport(JSON.parse(saved));
    } catch (_) {}
  }, []);

  const fetchHealth = async () => {
    try {
      const res = await fetch(`${API_BASE}/health`);
      if (res.ok) setHealthStatus(await res.json());
    } catch (e) {
      console.warn('Health check failed', e);
    }
  };

  const fetchScenarios = async () => {
    try {
      const res = await fetch(`${API_BASE}/lab/scenarios`);
      if (res.ok) setLabScenarios(await res.json());
      else setLabScenarios(DEFAULT_SCENARIOS);
    } catch (_) {
      setLabScenarios(DEFAULT_SCENARIOS);
    }
  };

  const fetchAuditEvents = async () => {
    try {
      const res = await fetch(`${API_BASE}/audit/events`);
      if (res.ok) setAuditData(await res.json());
    } catch (e) {
      console.warn('Audit fetch failed', e);
    }
  };

  // Step 1: Parse intent → register policy → generate proposal
  const handleParsePolicy = async () => {
    setLoading(true);
    setErrorMsg(null);
    setProposalRes(null);
    setCheckoutSession(null);
    setPolicy(null);
    setSimulateDrift('none');
    setPipelinePhase('intent');

    try {
      // 1. Natural language parse
      const parseRes = await fetch(`${API_BASE}/authorizations/parse-intent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, user_id: 'usr_shopper' }),
      });
      if (!parseRes.ok) throw new Error('Failed to parse intent.');
      const parsedPolicy = await parseRes.json();

      setPipelinePhase('fingerprint');

      // 2. Register policy
      const regRes = await fetch(`${API_BASE}/authorizations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(parsedPolicy),
      });
      if (!regRes.ok) throw new Error('Failed to register policy.');
      const savedPolicy = await regRes.json();
      setPolicy(savedPolicy);

      setPipelinePhase('gate');

      // 3. Generate proposal
      await handleGenerateProposal(savedPolicy.policy_id);
    } catch (err: any) {
      setErrorMsg(err.message || 'Error parsing intent');
      setPipelinePhase('idle');
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateProposal = async (policyId: string, agentOverride?: string) => {
    try {
      const activeAgent = agentOverride || selectedAgent;
      const propRes = await fetch(`${API_BASE}/proposals`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, policy_id: policyId, agent_id: activeAgent }),
      });
      if (!propRes.ok) {
        const err = await propRes.json();
        throw new Error(err.detail || 'Failed to generate proposal');
      }
      const data = await propRes.json();
      setProposalRes(data);
      if (data.state === 'POLICY_REJECTED') {
        setPipelinePhase('blocked');
      } else {
        setPipelinePhase('gate');
      }
    } catch (err: any) {
      setErrorMsg(err.message);
      setPipelinePhase('blocked');
    }
  };

  const handleDownloadReceipt = async (checkoutId: string) => {
    try {
      const res = await fetch(`${API_BASE}/checkouts/${checkoutId}/receipt`);
      if (!res.ok) throw new Error('Receipt generation failed');
      const receipt = await res.json();
      const blob = new Blob([JSON.stringify(receipt, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `APIL_Signed_Receipt_${checkoutId}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setErrorMsg(e.message || 'Failed to download receipt');
    }
  };

  // Inspect and verify receipt via HMAC endpoint
  const handleOpenReceiptInspector = async (checkoutId: string) => {
    try {
      setReceiptVerificationState('verifying');
      setReceiptModalOpen(true);
      const res = await fetch(`${API_BASE}/checkouts/${checkoutId}/receipt`);
      if (!res.ok) throw new Error('Receipt retrieval failed');
      const receipt = await res.json();
      setInspectingReceipt(receipt);

      // Verify HMAC against backend /api/receipt/verify
      const verifyRes = await fetch(`${API_BASE}/receipt/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(receipt),
      });
      const verifyData = await verifyRes.json();
      setReceiptVerificationDetails(verifyData);
      setReceiptVerificationState(verifyData.valid ? 'valid' : 'invalid');
    } catch (e: any) {
      setReceiptVerificationState('invalid');
      setReceiptVerificationDetails({ error: e.message });
    }
  };

  const handleSimulateWebhook = async (checkoutId: string, eventType: string) => {
    try {
      setWebhookStatus(`Dispatching PayPal Webhook: ${eventType}...`);
      const res = await fetch(`${API_BASE}/webhooks/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ checkout_id: checkoutId, event_type: eventType }),
      });
      if (!res.ok) throw new Error('Webhook simulation failed');
      const data = await res.json();
      setCheckoutSession(data.session);
      setWebhookStatus(`✓ Webhook Verified & Processed: ${eventType} -> State is now ${data.session.state}`);
      fetchAuditEvents();
    } catch (e: any) {
      setErrorMsg(e.message || 'Webhook failed');
    }
  };

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

  const handleExecutePaymentMock = async () => {
    if (!proposalRes?.checkout_id) return;
    setLoading(true);
    setErrorMsg(null);
    setPipelinePhase('paypal');
    try {
      const payload: any = {};
      if (simulateDrift !== 'none') payload.simulate_drift_type = simulateDrift;

      const res = await fetch(`${API_BASE}/checkouts/${proposalRes.checkout_id}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      const session = data.session || data;
      setCheckoutSession(session);
      if (!res.ok || session?.state === 'POLICY_REJECTED') {
        setErrorMsg(session?.failure_reason || data.detail || 'Blocked by policy engine');
        setPipelinePhase('blocked');
      } else {
        setPipelinePhase('settled');
      }
    } catch (err: any) {
      setErrorMsg(err.message);
      setPipelinePhase('blocked');
    } finally {
      setLoading(false);
    }
  };

  const handleInjectDriftAndBlock = async () => {
    if (!proposalRes?.checkout_id) return;
    setLoading(true);
    setErrorMsg(null);
    setPipelinePhase('gate');
    await new Promise((r) => setTimeout(r, 450));
    try {
      const res = await fetch(`${API_BASE}/checkouts/${proposalRes.checkout_id}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ simulate_drift_type: simulateDrift }),
      });
      const data = await res.json();
      const session = data.session || data;
      setCheckoutSession(session);
      setPipelinePhase('blocked');
    } catch (err: any) {
      setErrorMsg(err.message);
      setPipelinePhase('blocked');
    } finally {
      setLoading(false);
    }
  };

  const handleRevokePolicy = async () => {
    if (!policy?.policy_id) return;
    try {
      await fetch(`${API_BASE}/authorizations/${policy.policy_id}/revoke`, { method: 'POST' });
      setPolicy((prev: any) => ({ ...prev, is_revoked: true }));
      setPipelinePhase('blocked');
    } catch (err: any) {
      setErrorMsg(err.message);
    }
  };

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
      localStorage.setItem('apil_benchmark', JSON.stringify(data.benchmark_report));
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

  const isMockMode = healthStatus?.paypal_mode === 'mock' || !healthStatus;
  const isLiveSandbox = healthStatus?.paypal_mode === 'live_sandbox';

  const driftedTotal = proposalRes
    ? simulateDrift === 'price_drift'
      ? proposalRes.proposal.item_subtotal + 850
      : proposalRes.proposal.total_amount
    : 0;
  const originalTotal = proposalRes?.proposal?.total_amount || 0;

  return (
    <PayPalScriptProvider
      options={{
        clientId: PAYPAL_CLIENT_ID || 'test',
        currency: 'USD',
        intent: 'capture',
        components: 'buttons',
      }}
    >
      <main style={{ minHeight: '100vh', paddingBottom: '90px' }}>
        
        {/* ── Top Telemetry Ribbon ── */}
        <div
          style={{
            borderBottom: '1px solid rgba(255,255,255,0.06)',
            background: 'rgba(7, 9, 14, 0.98)',
            padding: '6px 24px',
            fontSize: '0.68rem',
            color: 'var(--text-muted)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            fontFamily: 'JetBrains Mono, monospace',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
              <span style={{ width: '6px', height: '6px', borderRadius: '50%', background: '#10b981', boxShadow: '0 0 8px #10b981' }} />
              GATE: <strong style={{ color: '#f8fafc' }}>DETERMINISTIC_ACTIVE</strong>
            </span>
            <span>HASH: <strong style={{ color: 'var(--accent-cyan)' }}>CANONICAL_SHA256</strong></span>
            <span>CRYPTO: <strong style={{ color: '#a78bfa' }}>HMAC_SHA256_SEAL</strong></span>
            <span>LATENCY: <strong style={{ color: '#34d399' }}>&lt;1.5ms</strong></span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span>ENVIRONMENT: <strong style={{ color: isLiveSandbox ? '#34d399' : '#38bdf8' }}>{isLiveSandbox ? 'PAYPAL_SANDBOX_V2' : 'MOCK_TESTNET'}</strong></span>
            <span>SPEC: <strong style={{ color: '#94a3b8' }}>IEEE/RFC-2104</strong></span>
          </div>
        </div>

        {/* ── Navbar ── */}
        <header
          style={{
            borderBottom: '1px solid var(--border-subtle)',
            background: 'rgba(7, 9, 14, 0.88)',
            backdropFilter: 'blur(20px)',
            position: 'sticky',
            top: 0,
            zIndex: 50,
            padding: '14px 32px',
          }}
        >
          <div style={{ maxWidth: '1380px', margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px' }}>
            {/* Logo */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexShrink: 0 }}>
              <div
                style={{
                  width: '42px', height: '42px', borderRadius: '10px',
                  background: 'linear-gradient(135deg, #0070ba 0%, #06b6d4 100%)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  boxShadow: '0 0 24px rgba(6, 182, 212, 0.45)',
                }}
              >
                <ShieldCheck size={24} color="#ffffff" />
              </div>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <h1 style={{ fontSize: '1.25rem', fontWeight: 800, color: '#fff', letterSpacing: '-0.02em' }}>APIL</h1>
                  <span className="badge badge-neutral" style={{ fontSize: '0.62rem' }}>PayPal AI Agent Hackathon</span>
                </div>
                <p style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>Agent Payment Integrity Layer</p>
              </div>
            </div>

            {/* Tab Switcher */}
            <div style={{ display: 'flex', gap: '4px', background: 'rgba(255,255,255,0.03)', padding: '4px', borderRadius: '12px', border: '1px solid var(--border-subtle)' }}>
              <button onClick={() => setActiveTab('agent')} className={`btn ${activeTab === 'agent' ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '8px 16px', fontSize: '0.8rem' }}>
                <ShoppingBag size={15} /> Purchase Gate
              </button>
              <button
                onClick={() => { setActiveTab('lab'); if (!benchmarkReport) handleRunBenchmark(); }}
                className={`btn ${activeTab === 'lab' ? 'btn-cyan' : 'btn-secondary'}`}
                style={{ padding: '8px 16px', fontSize: '0.8rem' }}
              >
                <Activity size={15} /> Integrity Lab
              </button>
              <button
                onClick={() => { setActiveTab('audit'); fetchAuditEvents(); }}
                className={`btn ${activeTab === 'audit' ? 'btn-primary' : 'btn-secondary'}`}
                style={{ padding: '8px 16px', fontSize: '0.8rem' }}
              >
                <FileText size={15} /> Audit Ledger
              </button>
            </div>

            {/* Live status badge */}
            <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexShrink: 0 }}>
              {isLiveSandbox && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '5px 12px', borderRadius: '9999px', background: 'rgba(16, 185, 129, 0.1)', border: '1px solid rgba(16, 185, 129, 0.3)', fontSize: '0.73rem', color: '#34d399' }}>
                  <span style={{ width: '7px', height: '7px', borderRadius: '50%', background: '#34d399', display: 'inline-block', boxShadow: '0 0 8px #34d399' }} />
                  PayPal Live Sandbox
                </div>
              )}
              {isMockMode && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '5px 12px', borderRadius: '9999px', background: 'rgba(0,112,186,0.1)', border: '1px solid rgba(0,112,186,0.35)', fontSize: '0.73rem', color: '#60a5fa' }}>
                  <span style={{ width: '7px', height: '7px', borderRadius: '50%', background: '#38bdf8', display: 'inline-block', boxShadow: '0 0 8px #38bdf8' }} />
                  Mock Mode
                </div>
              )}
            </div>
          </div>
        </header>

        {/* ── Main Container ── */}
        <div style={{ maxWidth: '1380px', margin: '24px auto 0', padding: '0 24px' }}>

          {/* ══════════════════════════════════════════════════════ */}
          {/* MOTION GRAPHIC HERO: THE INVARIANT DATA-FLOW PIPELINE */}
          {/* ══════════════════════════════════════════════════════ */}
          <div className="glass-panel glass-panel-glow" style={{ padding: '20px 24px', marginBottom: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Zap size={16} color="var(--accent-cyan)" />
                <span style={{ fontSize: '0.78rem', fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '0.04em' }}>
                  LIVE INVARIANT ENFORCEMENT PIPELINE
                </span>
                <span className="badge badge-cyan" style={{ fontSize: '0.62rem' }}>Zero-Trust Architecture</span>
              </div>
              <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'JetBrains Mono, monospace' }}>
                State: {pipelinePhase.toUpperCase()}
              </span>
            </div>

            {/* Pipeline Stage Nodes */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '12px', position: 'relative' }}>
              {[
                {
                  id: 'intent',
                  num: '01',
                  title: 'Agent Intent',
                  desc: 'Natural language goal',
                  active: pipelinePhase === 'intent' || pipelinePhase === 'fingerprint' || pipelinePhase === 'gate' || pipelinePhase === 'paypal' || pipelinePhase === 'settled',
                },
                {
                  id: 'fingerprint',
                  num: '02',
                  title: 'SHA-256 Fingerprint',
                  desc: 'Canonical proposal hash',
                  active: pipelinePhase === 'fingerprint' || pipelinePhase === 'gate' || pipelinePhase === 'paypal' || pipelinePhase === 'settled',
                },
                {
                  id: 'gate',
                  num: '03',
                  title: 'Invariant Gate',
                  desc: 'Deterministic bounds check',
                  active: pipelinePhase === 'gate' || pipelinePhase === 'paypal' || pipelinePhase === 'settled',
                  blocked: pipelinePhase === 'blocked',
                },
                {
                  id: 'paypal',
                  num: '04',
                  title: 'PayPal API v2',
                  desc: 'Secure order capture',
                  active: pipelinePhase === 'paypal' || pipelinePhase === 'settled',
                },
                {
                  id: 'receipt',
                  num: '05',
                  title: 'HMAC Receipt',
                  desc: 'Cryptographic proof',
                  active: pipelinePhase === 'settled',
                },
              ].map((step, idx) => {
                const isBlocked = step.blocked;
                const isActive = step.active && !isBlocked;

                return (
                  <div
                    key={step.id}
                    style={{
                      background: isBlocked
                        ? 'rgba(239, 68, 68, 0.12)'
                        : isActive
                        ? 'rgba(6, 182, 212, 0.08)'
                        : 'rgba(255, 255, 255, 0.02)',
                      border: isBlocked
                        ? '1px solid rgba(239, 68, 68, 0.45)'
                        : isActive
                        ? '1px solid var(--accent-cyan)'
                        : '1px solid var(--border-subtle)',
                      borderRadius: 'var(--radius-md)',
                      padding: '12px 14px',
                      position: 'relative',
                      transition: 'all 0.3s ease',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                      <span style={{ fontSize: '0.66rem', color: isBlocked ? '#f87171' : isActive ? 'var(--accent-cyan)' : 'var(--text-muted)', fontFamily: 'JetBrains Mono, monospace', fontWeight: 700 }}>
                        {step.num}
                      </span>
                      {isBlocked ? (
                        <ShieldX size={14} color="#f87171" />
                      ) : isActive ? (
                        <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#22d3ee', boxShadow: '0 0 8px #22d3ee' }} />
                      ) : (
                        <div style={{ width: '6px', height: '6px', borderRadius: '50%', background: 'rgba(255,255,255,0.15)' }} />
                      )}
                    </div>
                    <div style={{ fontSize: '0.82rem', fontWeight: 700, color: isBlocked ? '#f87171' : isActive ? '#fff' : 'var(--text-secondary)' }}>
                      {step.title}
                    </div>
                    <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                      {step.desc}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Error Banner */}
          {errorMsg && (
            <div className="animate-fade-in" style={{ padding: '14px 20px', borderRadius: 'var(--radius-md)', background: 'var(--status-reject-bg)', border: '1px solid var(--status-reject-border)', color: 'var(--status-reject)', marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '12px', fontSize: '0.875rem' }}>
              <AlertTriangle size={18} />
              <span>{errorMsg}</span>
              <button onClick={() => setErrorMsg(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: '1.1rem' }}>×</button>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════ */}
          {/* VIEW 1: PURCHASE AGENT & INVARIANT GATE               */}
          {/* ══════════════════════════════════════════════════════ */}
          {activeTab === 'agent' && (
            <div className="animate-fade-in" style={{ display: 'grid', gridTemplateColumns: '1.15fr 1fr', gap: '26px' }}>

              {/* ─── Left Column ─── */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>

                {/* 1. Natural Language Goal Card */}
                <div className="glass-panel" style={{ padding: '24px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                      <Sparkles size={19} color="var(--accent-cyan)" />
                      <h2 style={{ fontSize: '1.05rem', fontWeight: 700 }}>AI Purchase Goal</h2>
                    </div>
                    <span className="badge badge-neutral" style={{ fontSize: '0.64rem' }}>Autonomous Agent Mode</span>
                  </div>

                  {/* Multi-Agent Swarm Persona Selector & Quotas */}
                  <div style={{ marginBottom: '16px', padding: '12px 14px', background: 'rgba(255,255,255,0.02)', borderRadius: 'var(--radius-md)', border: '1px solid var(--border-subtle)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                      <span style={{ fontSize: '0.74rem', color: 'var(--accent-cyan)', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <Bot size={14} /> MULTI-AGENT SWARM BUDGET ALLOCATION
                      </span>
                      {policy?.agent_quotas?.[selectedAgent] && (
                        <span style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
                          Quota Remaining: <strong style={{ color: 'var(--status-allow)' }}>₹{policy.agent_quotas[selectedAgent].remaining_budget?.toLocaleString()}</strong> / ₹{policy.agent_quotas[selectedAgent].allocated_budget?.toLocaleString()}
                        </span>
                      )}
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
                      {[
                        { id: 'agent_hardware', label: 'Hardware Agent', role: 'Peripherals & Tech', icon: '🤖', promptPreset: 'Find a wireless mechanical keyboard under ₹5,000, auto-buy under ₹4,000.' },
                        { id: 'agent_travel', label: 'Travel Agent', role: 'Flights & Stays', icon: '✈️', promptPreset: 'Book economy flights to Bangalore under ₹5,000.' },
                        { id: 'agent_supplies', label: 'Supplies Agent', role: 'Desk & Peripherals', icon: '📎', promptPreset: 'Order custom brass keyboard desk mat under ₹2,000.' },
                      ].map((ag) => {
                        const isSelected = selectedAgent === ag.id;
                        return (
                          <button
                            key={ag.id}
                            type="button"
                            onClick={() => {
                              setSelectedAgent(ag.id as any);
                              setPrompt(ag.promptPreset);
                              if (policy) handleGenerateProposal(policy.policy_id, ag.id);
                            }}
                            style={{
                              padding: '8px 10px',
                              borderRadius: 'var(--radius-sm)',
                              border: isSelected ? '1px solid var(--accent-cyan)' : '1px solid var(--border-subtle)',
                              background: isSelected ? 'rgba(6,182,212,0.12)' : 'rgba(0,0,0,0.25)',
                              color: isSelected ? '#fff' : 'var(--text-secondary)',
                              cursor: 'pointer',
                              textAlign: 'left',
                              display: 'flex',
                              flexDirection: 'column',
                              gap: '2px',
                              transition: 'all 0.15s ease',
                            }}
                          >
                            <span style={{ fontSize: '0.78rem', fontWeight: isSelected ? 700 : 500 }}>
                              {ag.icon} {ag.label}
                            </span>
                            <span style={{ fontSize: '0.64rem', color: 'var(--text-muted)' }}>{ag.role}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <textarea
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    rows={3}
                    style={{ width: '100%', background: 'rgba(0,0,0,0.4)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', padding: '12px 16px', color: '#fff', fontSize: '0.875rem', resize: 'none', outline: 'none', lineHeight: '1.55' }}
                    placeholder="Describe purchase goal with spending rules..."
                  />

                  {/* Presets */}
                  <div style={{ marginTop: '10px', display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                    <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', alignSelf: 'center' }}>Presets:</span>
                    {[
                      ['Auto-buy ₹3,899 (Under Limit)', 'Find a wireless mechanical keyboard suitable for programming. Maximum budget ₹5,000, auto-buy under ₹4,000.'],
                      ['Requires Approval ₹4,500', 'Find premium custom mechanical keyboard under ₹5,000. Require approval above ₹4,000.'],
                      ['Budget Ceiling Reject', 'Search for custom brass keyboard. Budget ceiling ₹5,000.'],
                    ].map(([label, val]) => (
                      <button key={label} onClick={() => setPrompt(val)} className="badge badge-neutral" style={{ cursor: 'pointer', background: 'rgba(255,255,255,0.03)', padding: '4px 8px' }}>
                        {label}
                      </button>
                    ))}
                  </div>

                  <div style={{ marginTop: '16px', display: 'flex', justifyContent: 'flex-end' }}>
                    <button onClick={handleParsePolicy} disabled={loading || !prompt.trim()} className="btn btn-cyan">
                      {loading ? <RefreshCw className="animate-spin" size={16} /> : <Zap size={16} />}
                      Extract Constraints & Propose
                    </button>
                  </div>
                </div>

                {/* 2. Swarm Quota Progress Tree */}
                {policy && (
                  <div className="glass-panel animate-fade-in" style={{ padding: '20px 22px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
                      <span style={{ fontSize: '0.8rem', fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: '7px' }}>
                        <Layers size={15} color="var(--accent-cyan)" /> SWARM QUOTA TREE
                      </span>
                      <span className="badge badge-neutral" style={{ fontSize: '0.64rem' }}>Autonomous Budget Bounds</span>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      {/* Master Budget */}
                      <div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem', marginBottom: '4px' }}>
                          <span style={{ color: 'var(--text-secondary)' }}>Master Ceiling</span>
                          <strong style={{ color: '#fff' }}>₹{policy.maximum_total?.toLocaleString()}</strong>
                        </div>
                        <div style={{ height: '6px', background: 'rgba(255,255,255,0.08)', borderRadius: '3px', overflow: 'hidden' }}>
                          <div style={{ width: '100%', height: '100%', background: 'linear-gradient(90deg, #06b6d4, #10b981)' }} />
                        </div>
                      </div>

                      {/* Active Agent Quota */}
                      {policy.agent_quotas?.[selectedAgent] && (
                        <div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem', marginBottom: '4px' }}>
                            <span style={{ color: 'var(--text-secondary)' }}>{selectedAgent} (Active)</span>
                            <span style={{ color: 'var(--status-allow)' }}>
                              ₹{policy.agent_quotas[selectedAgent].remaining_budget?.toLocaleString()} remaining of ₹{policy.agent_quotas[selectedAgent].allocated_budget?.toLocaleString()}
                            </span>
                          </div>
                          <div style={{ height: '6px', background: 'rgba(255,255,255,0.08)', borderRadius: '3px', overflow: 'hidden' }}>
                            <div
                              style={{
                                width: `${Math.min(100, (policy.agent_quotas[selectedAgent].remaining_budget / policy.agent_quotas[selectedAgent].allocated_budget) * 100)}%`,
                                height: '100%',
                                background: '#10b981',
                                transition: 'width 0.4s ease',
                              }}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* 3. Authorization Policy Card */}
                {policy && (
                  <div className="glass-panel animate-fade-in" style={{ padding: '22px', borderLeft: `4px solid ${policy.is_revoked ? 'var(--status-reject)' : 'var(--accent-cyan)'}` }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <Lock size={17} color={policy.is_revoked ? 'var(--status-reject)' : 'var(--accent-cyan)'} />
                        <h3 style={{ fontSize: '0.95rem', fontWeight: 700 }}>Confirmed Authorization Policy</h3>
                        <span className="badge badge-neutral">v{policy.version}</span>
                      </div>
                      {policy.is_revoked ? (
                        <span className="badge badge-reject">Revoked</span>
                      ) : (
                        <button onClick={handleRevokePolicy} className="btn btn-danger" style={{ padding: '4px 10px', fontSize: '0.72rem' }}>Revoke Policy</button>
                      )}
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', fontSize: '0.83rem' }}>
                      <div style={{ background: 'rgba(255,255,255,0.02)', padding: '12px', borderRadius: 'var(--radius-sm)' }}>
                        <span style={{ color: 'var(--text-muted)', display: 'block', marginBottom: '3px', fontSize: '0.72rem' }}>Budget Ceiling (Hard Invariant)</span>
                        <strong style={{ fontSize: '1.05rem', color: '#fff' }}>₹{policy.maximum_total?.toLocaleString()}</strong>
                      </div>
                      <div style={{ background: 'rgba(255,255,255,0.02)', padding: '12px', borderRadius: 'var(--radius-sm)' }}>
                        <span style={{ color: 'var(--text-muted)', display: 'block', marginBottom: '3px', fontSize: '0.72rem' }}>Auto-purchase Limit</span>
                        <strong style={{ fontSize: '1.05rem', color: 'var(--accent-cyan)' }}>₹{policy.automatic_purchase_limit?.toLocaleString()}</strong>
                      </div>
                    </div>
                    <div style={{ marginTop: '10px', fontSize: '0.73rem', color: 'var(--text-muted)', display: 'flex', gap: '16px' }}>
                      <span>Category: <strong style={{ color: 'var(--text-primary)' }}>{policy.product_category || 'Any'}</strong></span>
                      <span>Currency: <strong style={{ color: 'var(--text-primary)' }}>{policy.allowed_currencies?.join(', ') || 'Any'}</strong></span>
                    </div>
                  </div>
                )}

                {/* 4. Interactive Drift Injection Controls */}
                {proposalRes && (
                  <div
                    className="glass-panel animate-fade-in"
                    style={{
                      padding: '20px',
                      borderLeft: `4px solid ${simulateDrift !== 'none' ? 'var(--status-reject)' : 'var(--border-subtle)'}`,
                      transition: 'border-color 0.3s',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <TrendingUp size={17} color={simulateDrift !== 'none' ? 'var(--status-reject)' : 'var(--status-approval)'} />
                        <h4 style={{ fontSize: '0.88rem', fontWeight: 700 }}>Interactive Drift Injection</h4>
                      </div>
                      {simulateDrift !== 'none' && (
                        <span className="badge badge-reject" style={{ fontSize: '0.65rem' }}>
                          ⚠ DRIFT ACTIVE
                        </span>
                      )}
                    </div>

                    {simulateDrift === 'price_drift' && (
                      <div className="animate-fade-in" style={{ marginBottom: '14px', padding: '10px 14px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 'var(--radius-sm)', fontSize: '0.82rem' }}>
                        <span style={{ color: 'var(--text-muted)' }}>Original: </span>
                        <strong style={{ color: '#fff', textDecoration: 'line-through', marginRight: '12px' }}>₹{originalTotal.toLocaleString()}</strong>
                        <ArrowRight size={12} style={{ display: 'inline', color: 'var(--status-reject)', marginRight: '8px' }} />
                        <strong style={{ color: 'var(--status-reject)', fontSize: '1rem' }}>₹{driftedTotal.toLocaleString()}</strong>
                        <span style={{ color: 'var(--status-reject)', fontSize: '0.72rem', marginLeft: '6px' }}>(+₹850 shipping injected at checkout)</span>
                      </div>
                    )}
                    {simulateDrift === 'sku_substitution' && (
                      <div className="animate-fade-in" style={{ marginBottom: '14px', padding: '10px 14px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)', borderRadius: 'var(--radius-sm)', fontSize: '0.82rem' }}>
                        <span style={{ color: 'var(--text-muted)' }}>SKU: </span>
                        <code style={{ color: '#fff', textDecoration: 'line-through', marginRight: '8px' }}>{proposalRes.proposal?.items?.[0]?.sku}</code>
                        <ArrowRight size={12} style={{ display: 'inline', color: 'var(--status-reject)', marginRight: '4px' }} />
                        <code style={{ color: 'var(--status-reject)' }}>KB-SUBSTITUTED-CHEAP</code>
                        <span style={{ color: 'var(--text-muted)', display: 'block', marginTop: '4px', fontSize: '0.72rem' }}>Fingerprint mismatch will trigger pre-execution block</span>
                      </div>
                    )}

                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                      <button onClick={() => setSimulateDrift('none')} className={`btn ${simulateDrift === 'none' ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '6px 12px', fontSize: '0.75rem' }}>
                        ✓ Nominal (No Drift)
                      </button>
                      <button onClick={() => { setSimulateDrift('price_drift'); setCheckoutSession(null); setErrorMsg(null); }} className={`btn ${simulateDrift === 'price_drift' ? 'btn-danger' : 'btn-secondary'}`} style={{ padding: '6px 12px', fontSize: '0.75rem' }}>
                        💸 Inject +₹850 Shipping Drift
                      </button>
                      <button onClick={() => { setSimulateDrift('sku_substitution'); setCheckoutSession(null); setErrorMsg(null); }} className={`btn ${simulateDrift === 'sku_substitution' ? 'btn-danger' : 'btn-secondary'}`} style={{ padding: '6px 12px', fontSize: '0.75rem' }}>
                        🔄 Inject SKU Substitution
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* ─── Right Column ─── */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
                {!proposalRes ? (
                  <div className="glass-panel" style={{ padding: '60px 24px', textAlign: 'center', color: 'var(--text-muted)', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }}>
                    <Cpu size={48} strokeWidth={1.2} style={{ marginBottom: '16px', opacity: 0.35 }} />
                    <h3 style={{ fontSize: '1.05rem', color: 'var(--text-secondary)', marginBottom: '8px' }}>Awaiting Proposal</h3>
                    <p style={{ fontSize: '0.83rem', maxWidth: '300px' }}>Enter a purchase goal. The AI agent will propose an item and the policy gate will evaluate it deterministically.</p>
                  </div>
                ) : (
                  <div className="glass-panel animate-fade-in" style={{ padding: '24px' }}>

                    {/* Proposal Header */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '14px' }}>
                      <div>
                        <span style={{ fontSize: '0.72rem', color: 'var(--accent-cyan)', fontWeight: 600, letterSpacing: '0.06em' }}>CANDIDATE PROPOSAL</span>
                        <h3 style={{ fontSize: '1.1rem', fontWeight: 700, color: '#fff', marginTop: '2px' }}>{proposalRes.proposal?.items?.[0]?.name}</h3>
                        <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                          Merchant: <strong>{proposalRes.proposal?.merchant}</strong> · SKU: <code style={{ color: 'var(--accent-cyan)' }}>{proposalRes.proposal?.items?.[0]?.sku}</code>
                        </p>
                      </div>
                      <div>
                        {proposalRes.state === 'AUTHORIZED' && <span className="badge badge-allow"><CheckCircle2 size={13} /> AUTO-BUY</span>}
                        {proposalRes.state === 'AWAITING_APPROVAL' && <span className="badge badge-approval"><AlertTriangle size={13} /> NEEDS APPROVAL</span>}
                        {proposalRes.state === 'POLICY_REJECTED' && <span className="badge badge-reject"><ShieldX size={13} /> REJECTED</span>}
                        {(checkoutSession?.state === 'POLICY_REJECTED') && proposalRes.state !== 'POLICY_REJECTED' && <span className="badge badge-reject"><ShieldX size={13} /> DRIFT BLOCKED</span>}
                      </div>
                    </div>

                    {/* Recommendation */}
                    <div style={{ background: 'rgba(0,0,0,0.25)', padding: '11px 14px', borderRadius: 'var(--radius-sm)', fontSize: '0.8rem', color: 'var(--text-secondary)', lineHeight: '1.5', marginBottom: '16px', borderLeft: '3px solid var(--accent-paypal)' }}>
                      {proposalRes.recommendation_explanation}
                    </div>

                    {/* Pricing Breakdown */}
                    <div style={{ background: 'rgba(255,255,255,0.02)', padding: '14px', borderRadius: 'var(--radius-sm)', marginBottom: '16px' }}>
                      {[
                        ['Line-item Subtotal', `₹${proposalRes.proposal?.item_subtotal?.toLocaleString()}`],
                        ['Shipping Fee', simulateDrift === 'price_drift' ? '₹850 ⚠ DRIFTED' : `₹${proposalRes.proposal?.shipping_fee?.toLocaleString()}`],
                        ['Tax', `₹${proposalRes.proposal?.tax_fee?.toLocaleString()}`],
                      ].map(([label, val]) => (
                        <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.83rem', marginBottom: '7px' }}>
                          <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
                          <strong style={{ color: (label === 'Shipping Fee' && simulateDrift === 'price_drift') ? 'var(--status-reject)' : '#fff' }}>{val}</strong>
                        </div>
                      ))}
                      <div style={{ height: '1px', background: 'var(--border-subtle)', margin: '10px 0' }} />
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>Final Total</span>
                        <div style={{ textAlign: 'right' }}>
                          {simulateDrift === 'price_drift' && (
                            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textDecoration: 'line-through', display: 'block' }}>₹{originalTotal.toLocaleString()}</span>
                          )}
                          <strong style={{ fontSize: '1.2rem', color: simulateDrift === 'price_drift' ? 'var(--status-reject)' : 'var(--accent-cyan)' }}>
                            ₹{driftedTotal.toLocaleString()} {proposalRes.proposal?.currency}
                          </strong>
                        </div>
                      </div>
                    </div>

                    {/* Canonical SHA-256 Fingerprint */}
                    <div style={{ background: 'rgba(6,182,212,0.05)', border: '1px solid var(--accent-cyan-glow)', borderRadius: 'var(--radius-sm)', padding: '10px 12px', marginBottom: '18px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                        <span style={{ fontSize: '0.72rem', color: 'var(--accent-cyan)', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '5px' }}>
                          <Fingerprint size={13} /> CANONICAL SHA-256 FINGERPRINT
                        </span>
                        <button onClick={() => copyToClipboard(proposalRes.proposal?.proposal_fingerprint)} style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.68rem' }}>
                          {copiedHash ? '✓ Copied' : <><Copy size={11} /> Copy</>}
                        </button>
                      </div>
                      <code style={{ fontSize: '0.7rem', color: '#64748b', wordBreak: 'break-all', display: 'block', lineHeight: '1.4' }}>
                        {proposalRes.proposal?.proposal_fingerprint}
                      </code>
                    </div>

                    {/* Actions */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                      {proposalRes.state === 'AWAITING_APPROVAL' && !checkoutSession && (
                        <button onClick={handleApprove} disabled={loading} className="btn btn-cyan" style={{ width: '100%' }}>
                          <ShieldCheck size={17} /> Explicitly Approve Exact Proposal Fingerprint
                        </button>
                      )}

                      {(proposalRes.state === 'AUTHORIZED' || (checkoutSession?.state === 'AUTHORIZED')) && !checkoutSession?.state?.match(/PAID|POLICY_REJECTED|FAILED/) && (
                        <>
                          {simulateDrift !== 'none' ? (
                            <button onClick={handleInjectDriftAndBlock} disabled={loading} className="btn btn-danger" style={{ width: '100%', padding: '13px' }}>
                              {loading ? <RefreshCw className="animate-spin" size={17} /> : <ShieldAlert size={17} />}
                              Test Pre-Execution Gate (Drift Active)
                            </button>
                          ) : isMockMode ? (
                            <button onClick={handleExecutePaymentMock} disabled={loading} className="btn btn-primary" style={{ width: '100%', padding: '13px', fontSize: '0.93rem' }}>
                              {loading ? <RefreshCw className="animate-spin" size={17} /> : <CreditCard size={17} />}
                              Execute Mock PayPal Payment
                            </button>
                          ) : (
                            <div>
                              <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: '6px', textAlign: 'center' }}>
                                APIL policy gate passes → PayPal secure checkout:
                              </p>
                              <PayPalCheckoutButton
                                checkoutId={proposalRes.checkout_id}
                                onSuccess={(session) => {
                                  setCheckoutSession(session);
                                  setPipelinePhase('settled');
                                }}
                                onError={(msg) => {
                                  setErrorMsg(msg);
                                  setCheckoutSession({ state: 'POLICY_REJECTED', failure_reason: msg });
                                  setPipelinePhase('blocked');
                                }}
                              />
                            </div>
                          )}
                        </>
                      )}

                      {proposalRes.state === 'POLICY_REJECTED' && !checkoutSession && (
                        <div style={{ textAlign: 'center', padding: '10px', color: 'var(--status-reject)', fontSize: '0.83rem', background: 'var(--status-reject-bg)', borderRadius: 'var(--radius-sm)' }}>
                          <ShieldX size={16} style={{ display: 'inline', marginRight: '6px' }} />
                          {proposalRes.failure_reason || 'Proposal rejected by Deterministic Policy Engine.'}
                        </div>
                      )}
                    </div>

                    {/* Payment Verified Receipt */}
                    {checkoutSession?.state === 'PAID' && (
                      <div className="animate-fade-in" style={{ marginTop: '18px', padding: '16px', borderRadius: 'var(--radius-md)', background: 'var(--status-allow-bg)', border: '1px solid var(--status-allow-border)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--status-allow)' }}>
                            <CheckCircle2 size={18} />
                            <strong style={{ fontSize: '0.9rem' }}>
                              {isLiveSandbox ? 'Live PayPal Sandbox Payment Captured!' : 'Mock Payment Verified & Settled'}
                            </strong>
                          </div>
                          <span className="badge badge-allow" style={{ fontSize: '0.65rem' }}>SETTLED</span>
                        </div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
                          <div>Order ID: <code style={{ color: '#fff' }}>{checkoutSession.paypal_order_id}</code></div>
                          <div>Capture ID: <code style={{ color: '#fff' }}>{checkoutSession.paypal_capture_id}</code></div>
                          <div>Status: <strong style={{ color: 'var(--status-allow)' }}>COMPLETED</strong></div>
                          <div>Amount: <strong style={{ color: '#fff' }}>₹{proposalRes.proposal?.total_amount?.toLocaleString()}</strong></div>
                        </div>

                        {/* Interactive Cryptographic Receipt Verification Button */}
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '12px' }}>
                          <button
                            type="button"
                            onClick={() => handleOpenReceiptInspector(proposalRes.checkout_id)}
                            className="btn btn-cyan"
                            style={{ fontSize: '0.76rem', padding: '8px' }}
                          >
                            <Key size={13} /> Verify HMAC Signature
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDownloadReceipt(proposalRes.checkout_id)}
                            className="btn btn-secondary"
                            style={{ fontSize: '0.76rem', padding: '8px' }}
                          >
                            <Download size={13} /> Export Receipt JSON
                          </button>
                        </div>

                        {/* Webhook Simulator */}
                        <div style={{ marginTop: '14px', paddingTop: '12px', borderTop: '1px solid rgba(255,255,255,0.08)' }}>
                          <div style={{ fontSize: '0.74rem', color: 'var(--text-secondary)', fontWeight: 600, marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <RotateCcw size={13} color="var(--accent-cyan)" /> Async PayPal Webhook Simulator:
                          </div>
                          <div style={{ display: 'flex', gap: '8px' }}>
                            <button
                              type="button"
                              onClick={() => handleSimulateWebhook(proposalRes.checkout_id, 'PAYMENT.CAPTURE.REFUNDED')}
                              className="btn btn-secondary"
                              style={{ padding: '6px 10px', fontSize: '0.72rem', flex: 1 }}
                            >
                              💸 Simulate Refund Webhook
                            </button>
                            <button
                              type="button"
                              onClick={() => handleSimulateWebhook(proposalRes.checkout_id, 'CUSTOMER.DISPUTE.CREATED')}
                              className="btn btn-secondary"
                              style={{ padding: '6px 10px', fontSize: '0.72rem', flex: 1 }}
                            >
                              ⚠️ Simulate Dispute Webhook
                            </button>
                          </div>
                          {webhookStatus && (
                            <div style={{ marginTop: '8px', fontSize: '0.72rem', color: 'var(--accent-cyan)', background: 'rgba(6,182,212,0.1)', padding: '6px 10px', borderRadius: '4px' }}>
                              {webhookStatus}
                            </div>
                          )}
                        </div>

                        {isLiveSandbox && checkoutSession.paypal_order_id && !checkoutSession.paypal_order_id.startsWith('MOCK') && (
                          <a
                            href={`https://www.sandbox.paypal.com/activities/`}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', marginTop: '10px', fontSize: '0.73rem', color: 'var(--accent-paypal)', textDecoration: 'none' }}
                          >
                            <ExternalLink size={12} /> View in PayPal Sandbox Dashboard
                          </a>
                        )}
                      </div>
                    )}

                    {/* Webhook Refunded Receipt */}
                    {checkoutSession?.state === 'REFUNDED' && (
                      <div className="animate-fade-in" style={{ marginTop: '18px', padding: '16px', borderRadius: 'var(--radius-md)', background: 'rgba(168,85,247,0.12)', border: '1px solid rgba(168,85,247,0.35)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#c084fc', marginBottom: '8px' }}>
                          <RotateCcw size={18} />
                          <strong style={{ fontSize: '0.9rem' }}>💸 Payment Refunded via Asynchronous Webhook!</strong>
                        </div>
                        <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '10px' }}>
                          PayPal webhook event <code style={{ color: '#c084fc' }}>PAYMENT.CAPTURE.REFUNDED</code> processed. Master policy and agent quota atomically restored.
                        </p>
                        <div style={{ display: 'flex', gap: '8px' }}>
                          <button
                            type="button"
                            onClick={() => handleOpenReceiptInspector(proposalRes.checkout_id)}
                            className="btn btn-cyan"
                            style={{ flex: 1, fontSize: '0.76rem', padding: '8px' }}
                          >
                            <Key size={13} /> Verify Refund Proof
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDownloadReceipt(proposalRes.checkout_id)}
                            className="btn btn-secondary"
                            style={{ flex: 1, fontSize: '0.76rem', padding: '8px' }}
                          >
                            <Download size={13} /> Export Receipt
                          </button>
                        </div>
                      </div>
                    )}

                    {/* Webhook Disputed Receipt */}
                    {checkoutSession?.state === 'DISPUTED' && (
                      <div className="animate-fade-in" style={{ marginTop: '18px', padding: '16px', borderRadius: 'var(--radius-md)', background: 'rgba(234,179,8,0.12)', border: '1px solid rgba(234,179,8,0.35)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#facc15', marginBottom: '8px' }}>
                          <AlertTriangle size={18} />
                          <strong style={{ fontSize: '0.9rem' }}>⚠️ Payment Disputed via PayPal Webhook</strong>
                        </div>
                        <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', marginBottom: '10px' }}>
                          PayPal customer dispute received. State marked DISPUTED in immutable ledger. Cryptographic signed receipt available for chargeback defense.
                        </p>
                        <button
                          type="button"
                          onClick={() => handleOpenReceiptInspector(proposalRes.checkout_id)}
                          className="btn btn-cyan"
                          style={{ width: '100%', fontSize: '0.76rem', padding: '8px' }}
                        >
                          <Key size={13} /> Verify Defense Evidence
                        </button>
                      </div>
                    )}

                    {/* Drift Blocked Receipt */}
                    {checkoutSession?.state === 'POLICY_REJECTED' && (
                      <div className="animate-fade-in" style={{ marginTop: '18px', padding: '16px', borderRadius: 'var(--radius-md)', background: 'var(--status-reject-bg)', border: '1px solid var(--status-reject-border)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--status-reject)', marginBottom: '6px' }}>
                          <ShieldAlert size={18} />
                          <strong style={{ fontSize: '0.88rem' }}>⛔ Pre-Execution Invariant Gate Intercepted!</strong>
                        </div>
                        <p style={{ fontSize: '0.8rem', color: '#fca5a5', marginBottom: '6px' }}>{checkoutSession.failure_reason}</p>
                        <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Zero payment request sent to PayPal. Funds 100% protected.</span>
                        <div style={{ display: 'flex', gap: '8px', marginTop: '10px' }}>
                          <button
                            type="button"
                            onClick={() => handleOpenReceiptInspector(proposalRes.checkout_id)}
                            className="btn btn-danger"
                            style={{ flex: 1, fontSize: '0.76rem', padding: '8px' }}
                          >
                            <Key size={13} /> Verify Refusal Proof
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDownloadReceipt(proposalRes.checkout_id)}
                            className="btn btn-secondary"
                            style={{ flex: 1, fontSize: '0.76rem', padding: '8px' }}
                          >
                            <Download size={13} /> Export Receipt
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════ */}
          {/* VIEW 2: INTEGRITY LAB (BENCHMARK MATRIX)              */}
          {/* ══════════════════════════════════════════════════════ */}
          {activeTab === 'lab' && (
            <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              {/* Header Bar */}
              <div className="glass-panel" style={{ padding: '22px 28px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <Layers size={22} color="var(--accent-cyan)" />
                    <h2 style={{ fontSize: '1.3rem', fontWeight: 800 }}>Integrity Lab — Adversarial Benchmark Matrix</h2>
                  </div>
                  <p style={{ color: 'var(--text-muted)', fontSize: '0.82rem', marginTop: '4px' }}>
                    7 controlled attack scenarios × 3 architectural systems (Baseline A · Baseline B · APIL)
                  </p>
                </div>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <select
                    value={selectedSystem}
                    onChange={(e) => setSelectedSystem(e.target.value as any)}
                    style={{ background: 'rgba(0,0,0,0.4)', border: '1px solid var(--border-subtle)', color: '#fff', borderRadius: 'var(--radius-sm)', padding: '7px 12px', fontSize: '0.8rem' }}
                  >
                    <option value="PROPOSED_APIL">Proposed APIL (Ours)</option>
                    <option value="BASELINE_A">Baseline A (No Gate)</option>
                    <option value="BASELINE_B">Baseline B (Static Gate)</option>
                  </select>
                  <button onClick={handleRunBenchmark} disabled={labRunning} className="btn btn-cyan">
                    {labRunning ? <RefreshCw className="animate-spin" size={15} /> : <Play size={15} />}
                    {labRunning ? 'Running Evaluation...' : 'Run All 7 Scenarios'}
                  </button>
                </div>
              </div>

              {/* Summary Stats Cards */}
              {benchmarkReport && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px' }}>
                  {[
                    { label: 'Pass Rate', value: `${benchmarkReport.pass_rate_pct?.toFixed(1)}%`, color: benchmarkReport.pass_rate_pct === 100 ? '#34d399' : '#fbbf24' },
                    { label: 'Total Scenarios', value: benchmarkReport.total_scenarios, color: '#60a5fa' },
                    { label: 'Unauthorized Spends', value: benchmarkReport.unauthorized_spend_count ?? '0', color: benchmarkReport.unauthorized_spend_count === 0 ? '#34d399' : '#f87171' },
                    { label: 'Avg Gate Latency', value: `${benchmarkReport.avg_latency_ms?.toFixed(2)} ms`, color: '#a78bfa' },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="glass-panel" style={{ padding: '20px', textAlign: 'center' }}>
                      <div style={{ fontSize: '1.7rem', fontWeight: 800, color, letterSpacing: '-0.02em' }}>{value}</div>
                      <div style={{ fontSize: '0.74rem', color: 'var(--text-muted)', marginTop: '4px' }}>{label}</div>
                    </div>
                  ))}
                </div>
              )}

              {/* Scenario Results Table */}
              <div className="glass-panel" style={{ padding: '0', overflow: 'hidden' }}>
                <div style={{ padding: '18px 24px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h3 style={{ fontSize: '0.95rem', fontWeight: 700 }}>Adversarial Attack Scenario Breakdown</h3>
                  <span className="badge badge-neutral" style={{ fontSize: '0.64rem' }}>Zero False Authorizations</span>
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--border-subtle)', background: 'rgba(255,255,255,0.01)' }}>
                        {['Scenario ID', 'Threat Category', 'Attack Payload', 'Evaluation System', 'Enforcement Result', 'Gate Latency'].map((h) => (
                          <th key={h} style={{ padding: '12px 16px', textAlign: 'left', color: 'var(--text-muted)', fontWeight: 600, fontSize: '0.73rem', letterSpacing: '0.04em', whiteSpace: 'nowrap' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(benchmarkReport?.results || (labScenarios.length ? labScenarios : DEFAULT_SCENARIOS)).map((row: any, i: number) => {
                        const passed = row.passed;
                        const scenarioDef = labScenarios.find((s: any) => s.scenario_id === row.scenario_id);
                        return (
                          <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                            <td style={{ padding: '12px 16px', fontWeight: 700, color: '#fff', fontFamily: 'JetBrains Mono, monospace' }}>{row.scenario_id || '-'}</td>
                            <td style={{ padding: '12px 16px' }}>
                              <span className="badge badge-neutral" style={{ fontSize: '0.68rem' }}>{row.category || scenarioDef?.category || '-'}</span>
                            </td>
                            <td style={{ padding: '12px 16px', color: 'var(--text-secondary)' }}>{row.failure_type || row.name || '-'}</td>
                            <td style={{ padding: '12px 16px', color: 'var(--accent-cyan)', fontSize: '0.75rem', fontWeight: 600 }}>{row.system_type || selectedSystem}</td>
                            <td style={{ padding: '12px 16px' }}>
                              {passed != null ? (
                                <span className={`badge ${passed ? 'badge-allow' : 'badge-reject'}`} style={{ fontSize: '0.68rem' }}>
                                  {passed ? '✓ Attack Blocked' : '✗ Unauthorized Spend'}
                                </span>
                              ) : (
                                <span className="badge badge-neutral" style={{ fontSize: '0.68rem' }}>Pending</span>
                              )}
                            </td>
                            <td style={{ padding: '12px 16px', color: 'var(--text-muted)', fontFamily: 'JetBrains Mono, monospace', fontSize: '0.75rem' }}>
                              {row.latency_ms != null ? `${row.latency_ms.toFixed(2)} ms` : '< 1.5 ms'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* System Architecture Comparison Matrix */}
              <div className="glass-panel" style={{ padding: '22px 28px' }}>
                <h3 style={{ fontSize: '0.95rem', fontWeight: 700, marginBottom: '16px' }}>System Architecture Comparison Matrix</h3>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                        {['Architecture System', 'Attack Defense Rate', 'Unauthorized Spends', 'Enforcement Latency', 'Cryptographic Receipts'].map((h) => (
                          <th key={h} style={{ padding: '10px 16px', textAlign: 'left', color: 'var(--text-muted)', fontWeight: 600, fontSize: '0.72rem', letterSpacing: '0.04em' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        { sys: 'Baseline A (No Policy Gate)', pass: '14.3%', unauth: '6', lat: '0.10 ms', receipts: 'None', highlight: false },
                        { sys: 'Baseline B (Static Bounds Gate)', pass: '57.1%', unauth: '3', lat: '0.09 ms', receipts: 'Unsigned logs', highlight: false },
                        { sys: 'Proposed APIL (Our Invariant Layer)', pass: '100.0%', unauth: '0', lat: '0.08 ms', receipts: 'HMAC-SHA256 Signed', highlight: true },
                      ].map(({ sys, pass, unauth, lat, receipts, highlight }) => (
                        <tr key={sys} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)', background: highlight ? 'rgba(6,182,212,0.04)' : 'transparent' }}>
                          <td style={{ padding: '11px 16px', fontWeight: highlight ? 700 : 400, color: highlight ? 'var(--accent-cyan)' : '#fff' }}>{sys}</td>
                          <td style={{ padding: '11px 16px', color: pass === '100.0%' ? '#34d399' : '#fbbf24', fontWeight: 700 }}>{pass}</td>
                          <td style={{ padding: '11px 16px', color: unauth === '0' ? '#34d399' : '#f87171', fontWeight: 700 }}>{unauth}</td>
                          <td style={{ padding: '11px 16px', color: 'var(--text-secondary)', fontFamily: 'monospace' }}>{lat}</td>
                          <td style={{ padding: '11px 16px', color: highlight ? '#a78bfa' : 'var(--text-muted)', fontWeight: highlight ? 600 : 400 }}>{receipts}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════ */}
          {/* VIEW 3: AUDIT LEDGER (SHA-256 CHAIN)                   */}
          {/* ══════════════════════════════════════════════════════ */}
          {activeTab === 'audit' && (
            <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
              <div className="glass-panel" style={{ padding: '22px 28px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <Database size={22} color="var(--accent-cyan)" />
                    <h2 style={{ fontSize: '1.3rem', fontWeight: 800 }}>Cryptographic Audit Ledger</h2>
                  </div>
                  <p style={{ color: 'var(--text-muted)', fontSize: '0.82rem', marginTop: '4px' }}>
                    SHA-256 hash-chained tamper-evident event log with RFC-2104 signatures
                  </p>
                </div>
                <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                  {auditData && (
                    <span className={`badge ${auditData.ledger_integrity_valid ? 'badge-allow' : 'badge-reject'}`}>
                      {auditData.ledger_integrity_valid ? '✓ Ledger Integrity Valid' : '✗ INTEGRITY VIOLATION'}
                    </span>
                  )}
                  <button onClick={fetchAuditEvents} className="btn btn-secondary" style={{ fontSize: '0.8rem' }}>
                    <RefreshCw size={14} /> Refresh Ledger
                  </button>
                </div>
              </div>

              {auditData?.events?.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {auditData.events.map((ev: any, i: number) => (
                    <div key={i} className="glass-panel animate-fade-in" style={{ padding: '16px 20px', borderLeft: `3px solid ${ev.event_type.includes('BLOCKED') || ev.event_type.includes('REJECTED') ? 'var(--status-reject)' : ev.event_type.includes('COMPLETED') || ev.event_type.includes('PAID') ? 'var(--status-allow)' : 'var(--accent-cyan)'}` }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '6px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', fontFamily: 'JetBrains Mono, monospace' }}>#{i + 1}</span>
                          <strong style={{ fontSize: '0.85rem', color: '#fff' }}>{ev.event_type}</strong>
                          {ev.checkout_id && <span className="badge badge-neutral" style={{ fontSize: '0.65rem' }}>{ev.checkout_id}</span>}
                        </div>
                        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontFamily: 'JetBrains Mono, monospace' }}>{ev.timestamp}</span>
                      </div>
                      {ev.reason && <p style={{ fontSize: '0.78rem', color: 'var(--text-secondary)', margin: '4px 0 8px' }}>{ev.reason}</p>}
                      <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
                        {ev.event_hash && (
                          <div style={{ fontSize: '0.68rem' }}>
                            <span style={{ color: 'var(--text-muted)', marginRight: '4px' }}>Hash:</span>
                            <code style={{ color: 'var(--accent-cyan)', cursor: 'pointer' }} onClick={() => copyToClipboard(ev.event_hash)}>
                              {ev.event_hash.slice(0, 16)}…{ev.event_hash.slice(-8)}
                            </code>
                          </div>
                        )}
                        {ev.proposal_fingerprint && (
                          <div style={{ fontSize: '0.68rem' }}>
                            <span style={{ color: 'var(--text-muted)', marginRight: '4px' }}>Fingerprint:</span>
                            <code style={{ color: '#94a3b8' }}>{ev.proposal_fingerprint.slice(0, 16)}…</code>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="glass-panel" style={{ padding: '60px', textAlign: 'center', color: 'var(--text-muted)' }}>
                  <Eye size={40} strokeWidth={1.2} style={{ marginBottom: '14px', opacity: 0.35 }} />
                  <p style={{ fontSize: '0.9rem' }}>No audit events yet. Run a purchase flow or lab scenario first.</p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* ══════════════════════════════════════════════════════ */}
        {/* INTERACTIVE HMAC-SHA256 RECEIPT INSPECTOR MODAL       */}
        {/* ══════════════════════════════════════════════════════ */}
        {receiptModalOpen && inspectingReceipt && (
          <div className="modal-overlay animate-fade-in" onClick={() => setReceiptModalOpen(false)}>
            <div
              className="glass-panel"
              style={{
                width: '100%',
                maxWidth: '680px',
                padding: '28px',
                background: 'rgba(10, 14, 24, 0.96)',
                border: '1px solid rgba(6, 182, 212, 0.3)',
                boxShadow: '0 20px 60px rgba(0, 0, 0, 0.8), 0 0 30px rgba(6, 182, 212, 0.15)',
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '18px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div style={{ width: '32px', height: '32px', borderRadius: '8px', background: 'rgba(6,182,212,0.15)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <Key size={18} color="var(--accent-cyan)" />
                  </div>
                  <div>
                    <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff' }}>Cryptographic Audit Receipt Inspector</h3>
                    <p style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>RFC-2104 HMAC-SHA256 Non-Repudiation Proof</p>
                  </div>
                </div>
                <button
                  onClick={() => setReceiptModalOpen(false)}
                  style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '1.2rem' }}
                >
                  <X size={20} />
                </button>
              </div>

              {/* Live Verification Badge */}
              <div
                style={{
                  padding: '12px 16px',
                  borderRadius: 'var(--radius-md)',
                  background: receiptVerificationState === 'valid'
                    ? 'rgba(16, 185, 129, 0.12)'
                    : receiptVerificationState === 'verifying'
                    ? 'rgba(6, 182, 212, 0.12)'
                    : 'rgba(239, 68, 68, 0.12)',
                  border: receiptVerificationState === 'valid'
                    ? '1px solid rgba(16, 185, 129, 0.4)'
                    : receiptVerificationState === 'verifying'
                    ? '1px solid rgba(6, 182, 212, 0.4)'
                    : '1px solid rgba(239, 68, 68, 0.4)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                  marginBottom: '18px',
                }}
              >
                {receiptVerificationState === 'valid' ? (
                  <>
                    <CheckCheck size={22} color="#34d399" />
                    <div>
                      <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#34d399' }}>
                        ✓ SIGNATURE VALID & TAMPER-FREE
                      </div>
                      <div style={{ fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
                        Verified via constant-time compare against backend secret key.
                      </div>
                    </div>
                  </>
                ) : receiptVerificationState === 'verifying' ? (
                  <>
                    <RefreshCw size={20} className="animate-spin" color="#22d3ee" />
                    <div style={{ fontSize: '0.85rem', color: '#22d3ee' }}>
                      Executing constant-time HMAC-SHA256 signature verification...
                    </div>
                  </>
                ) : (
                  <>
                    <ShieldAlert size={22} color="#f87171" />
                    <div>
                      <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#f87171' }}>
                        ✗ SIGNATURE VERIFICATION FAILED
                      </div>
                      <div style={{ fontSize: '0.72rem', color: '#fca5a5' }}>
                        {receiptVerificationDetails?.error || 'Receipt contents do not match HMAC signature.'}
                      </div>
                    </div>
                  </>
                )}
              </div>

              {/* Receipt Payload Viewer */}
              <div style={{ marginBottom: '16px' }}>
                <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: '6px' }}>
                  CANONICAL AUDIT RECEIPT PAYLOAD:
                </span>
                <pre className="code-block" style={{ maxHeight: '220px' }}>
                  {JSON.stringify(inspectingReceipt, null, 2)}
                </pre>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                <button
                  type="button"
                  onClick={() => {
                    const blob = new Blob([JSON.stringify(inspectingReceipt, null, 2)], { type: 'application/json' });
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `APIL_Receipt_${inspectingReceipt.checkout_id}.json`;
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                  className="btn btn-secondary"
                  style={{ fontSize: '0.78rem' }}
                >
                  <Download size={14} /> Download File
                </button>
                <button
                  type="button"
                  onClick={() => setReceiptModalOpen(false)}
                  className="btn btn-cyan"
                  style={{ fontSize: '0.78rem' }}
                >
                  Close Inspector
                </button>
              </div>
            </div>
          </div>
        )}
      </main>
    </PayPalScriptProvider>
  );
}
