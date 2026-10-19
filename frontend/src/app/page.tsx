'use client';

import React, { useState, useEffect } from 'react';
import {
  PayPalScriptProvider,
  PayPalButtons,
  usePayPalScriptReducer,
} from '@paypal/react-paypal-js';
import {
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  CreditCard,
  ShoppingBag,
  RefreshCw,
  CheckCircle2,
  AlertTriangle,
  FileText,
  Lock,
  ArrowRight,
  Eye,
  Bot,
  Download,
  RotateCcw,
  CheckCheck,
  X,
  Play,
  Key,
  Copy,
  ExternalLink,
  ChevronRight,
  Database,
  Building2,
} from 'lucide-react';

const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';
const PAYPAL_CLIENT_ID = process.env.NEXT_PUBLIC_PAYPAL_CLIENT_ID || '';

const DEFAULT_SCENARIOS = [
  { scenario_id: 'SC-A', name: 'Standard Approved Purchase', category: 'Standard', failure_type: 'None' },
  { scenario_id: 'SC-B', name: 'Price & Shipping Fee Increase', category: 'Price Drift', failure_type: 'Total Exceeded' },
  { scenario_id: 'SC-C', name: 'Revoked Spending Authorization', category: 'Authorization', failure_type: 'Policy Inactive' },
  { scenario_id: 'SC-D', name: 'Item Substitution at Checkout', category: 'Item Integrity', failure_type: 'SKU Mismatch' },
  { scenario_id: 'SC-E', name: 'Duplicate Payment Submission', category: 'Concurrency', failure_type: 'Duplicate Request' },
  { scenario_id: 'SC-F', name: 'Prompt Injection in Description', category: 'Security', failure_type: 'Disallowed Content' },
  { scenario_id: 'SC-G', name: 'Network Timeout Recovery', category: 'Resilience', failure_type: 'Connection Timeout' },
];

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
    <div style={{ marginTop: '14px' }}>
      {isPending && (
        <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem', padding: '14px' }}>
          <RefreshCw size={16} className="animate-spin" style={{ display: 'inline', marginRight: '8px' }} />
          Loading PayPal payment interface...
        </div>
      )}
      <PayPalButtons
        style={{ layout: 'vertical', color: 'blue', shape: 'rect', label: 'pay', height: 44 }}
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
            throw new Error(session.failure_reason || 'Transaction stopped by policy rules');
          }
          if (!data.paypal_order_id) throw new Error('No PayPal order ID received');
          return data.paypal_order_id;
        }}
        onApprove={async (sdkData) => {
          const res = await fetch(`${API_BASE}/checkouts/${checkoutId}/capture`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ paypal_order_id: sdkData.orderID }),
          });
          const data = await res.json();
          if (!res.ok) throw new Error(data.detail || 'Payment capture failed');
          onSuccess(data.session);
        }}
        onError={(err) => {
          onError(String(err));
        }}
        onCancel={() => {
          onError('Payment was cancelled in the PayPal window.');
        }}
      />
    </div>
  );
}

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

  // Pipeline Stage: 1: Goal, 2: Verification, 3: Policy, 4: PayPal, 5: Receipt
  const [pipelineStep, setPipelineStep] = useState<number>(1);
  const [pipelineBlocked, setPipelineBlocked] = useState<boolean>(false);

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

  // Intent parsing → rule registration → item proposal
  const handleParsePolicy = async () => {
    setLoading(true);
    setErrorMsg(null);
    setProposalRes(null);
    setCheckoutSession(null);
    setPolicy(null);
    setSimulateDrift('none');
    setPipelineBlocked(false);
    setPipelineStep(1);

    try {
      // 1. Natural language parse
      const parseRes = await fetch(`${API_BASE}/authorizations/parse-intent`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, user_id: 'usr_shopper' }),
      });
      if (!parseRes.ok) throw new Error('Could not parse purchase goal.');
      const parsedPolicy = await parseRes.json();

      setPipelineStep(2);

      // 2. Register policy
      const regRes = await fetch(`${API_BASE}/authorizations`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(parsedPolicy),
      });
      if (!regRes.ok) throw new Error('Could not register policy rules.');
      const savedPolicy = await regRes.json();
      setPolicy(savedPolicy);

      setPipelineStep(3);

      // 3. Generate proposal
      await handleGenerateProposal(savedPolicy.policy_id);
    } catch (err: any) {
      setErrorMsg(err.message || 'Error processing request');
      setPipelineStep(1);
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
        throw new Error(err.detail || 'Could not generate item proposal');
      }
      const data = await propRes.json();
      setProposalRes(data);
      if (data.state === 'POLICY_REJECTED') {
        setPipelineBlocked(true);
      } else {
        setPipelineStep(3);
      }
    } catch (err: any) {
      setErrorMsg(err.message);
      setPipelineBlocked(true);
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
      a.download = `APIL_Receipt_${checkoutId}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e: any) {
      setErrorMsg(e.message || 'Could not download receipt');
    }
  };

  const handleOpenReceiptInspector = async (checkoutId: string) => {
    try {
      setReceiptVerificationState('verifying');
      setReceiptModalOpen(true);
      const res = await fetch(`${API_BASE}/checkouts/${checkoutId}/receipt`);
      if (!res.ok) throw new Error('Receipt retrieval failed');
      const receipt = await res.json();
      setInspectingReceipt(receipt);

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
      setWebhookStatus(`Sending PayPal webhook: ${eventType}...`);
      const res = await fetch(`${API_BASE}/webhooks/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ checkout_id: checkoutId, event_type: eventType }),
      });
      if (!res.ok) throw new Error('Webhook test failed');
      const data = await res.json();
      setCheckoutSession(data.session);
      setWebhookStatus(`Webhook confirmed: ${eventType} (Order state: ${data.session.state})`);
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
    setPipelineStep(4);
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
        setErrorMsg(session?.failure_reason || data.detail || 'Blocked by policy rules');
        setPipelineBlocked(true);
      } else {
        setPipelineStep(5);
      }
    } catch (err: any) {
      setErrorMsg(err.message);
      setPipelineBlocked(true);
    } finally {
      setLoading(false);
    }
  };

  const handleInjectDriftAndBlock = async () => {
    if (!proposalRes?.checkout_id) return;
    setLoading(true);
    setErrorMsg(null);
    setPipelineStep(3);
    await new Promise((r) => setTimeout(r, 300));
    try {
      const res = await fetch(`${API_BASE}/checkouts/${proposalRes.checkout_id}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ simulate_drift_type: simulateDrift }),
      });
      const data = await res.json();
      const session = data.session || data;
      setCheckoutSession(session);
      setPipelineBlocked(true);
    } catch (err: any) {
      setErrorMsg(err.message);
      setPipelineBlocked(true);
    } finally {
      setLoading(false);
    }
  };

  const handleRevokePolicy = async () => {
    if (!policy?.policy_id) return;
    try {
      await fetch(`${API_BASE}/authorizations/${policy.policy_id}/revoke`, { method: 'POST' });
      setPolicy((prev: any) => ({ ...prev, is_revoked: true }));
      setPipelineBlocked(true);
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
      <main style={{ minHeight: '100vh', background: '#f8fafc', color: '#0f172a' }}>
        
        {/* ── Top Header Navigation ── */}
        <header
          style={{
            borderBottom: '1px solid #e2e8f0',
            background: '#ffffff',
            position: 'sticky',
            top: 0,
            zIndex: 40,
            padding: '16px 36px',
            boxShadow: '0 1px 3px 0 rgba(0, 0, 0, 0.03)',
          }}
        >
          <div style={{ maxWidth: '1360px', margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '20px' }}>
            
            {/* Logo & Product Brand */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
              <div
                style={{
                  width: '40px',
                  height: '40px',
                  borderRadius: '10px',
                  background: 'linear-gradient(135deg, #0070ba 0%, #003087 100%)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  boxShadow: '0 2px 8px rgba(0, 112, 186, 0.25)',
                }}
              >
                <ShieldCheck size={22} color="#ffffff" />
              </div>
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <h1 style={{ fontSize: '1.25rem', fontWeight: 800, color: '#0f172a', letterSpacing: '-0.02em' }}>APIL</h1>
                  <span className="badge badge-neutral" style={{ fontSize: '0.7rem' }}>PayPal Integration</span>
                </div>
                <p style={{ fontSize: '0.78rem', color: '#64748b' }}>Agent Payment Integrity Layer</p>
              </div>
            </div>

            {/* Navigation Tabs */}
            <div style={{ display: 'flex', gap: '6px', background: '#f1f5f9', padding: '4px', borderRadius: '10px' }}>
              <button
                onClick={() => setActiveTab('agent')}
                className={`btn ${activeTab === 'agent' ? 'btn-primary' : 'btn-secondary'}`}
                style={{ padding: '8px 18px', fontSize: '0.84rem' }}
              >
                <ShoppingBag size={16} /> Purchase Flow
              </button>
              <button
                onClick={() => { setActiveTab('lab'); if (!benchmarkReport) handleRunBenchmark(); }}
                className={`btn ${activeTab === 'lab' ? 'btn-primary' : 'btn-secondary'}`}
                style={{ padding: '8px 18px', fontSize: '0.84rem' }}
              >
                <Play size={16} /> Policy Test Lab
              </button>
              <button
                onClick={() => { setActiveTab('audit'); fetchAuditEvents(); }}
                className={`btn ${activeTab === 'audit' ? 'btn-primary' : 'btn-secondary'}`}
                style={{ padding: '8px 18px', fontSize: '0.84rem' }}
              >
                <FileText size={16} /> Audit Trail
              </button>
            </div>

            {/* Environment Status */}
            <div>
              {isLiveSandbox ? (
                <div style={{ display: 'flex', alignItems: 'center', gap: '7px', padding: '6px 14px', borderRadius: '9999px', background: '#ecfdf5', border: '1px solid #a7f3d0', fontSize: '0.78rem', color: '#059669', fontWeight: 600 }}>
                  <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#10b981' }} />
                  PayPal Live Sandbox
                </div>
              ) : (
                <div style={{ display: 'flex', alignItems: 'center', gap: '7px', padding: '6px 14px', borderRadius: '9999px', background: '#eff6ff', border: '1px solid #bfdbfe', fontSize: '0.78rem', color: '#0070ba', fontWeight: 600 }}>
                  <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#0070ba' }} />
                  Sandbox Mock Mode
                </div>
              )}
            </div>

          </div>
        </header>

        {/* ── Main Content Container ── */}
        <div style={{ maxWidth: '1360px', margin: '28px auto 60px', padding: '0 24px' }}>

          {/* ══════════════════════════════════════════════════════ */}
          {/* PAYMENT AUTHORIZATION PROGRESS STEPS                   */}
          {/* ══════════════════════════════════════════════════════ */}
          <div className="clean-card" style={{ padding: '20px 24px', marginBottom: '26px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <div>
                <h2 style={{ fontSize: '0.95rem', fontWeight: 700, color: '#0f172a' }}>Payment Authorization Pipeline</h2>
                <p style={{ fontSize: '0.78rem', color: '#64748b' }}>Every AI agent transaction is verified against strict rules before reaching PayPal</p>
              </div>
              {pipelineBlocked ? (
                <span className="badge badge-reject">Blocked by Rule</span>
              ) : (
                <span className="badge badge-allow">System Ready</span>
              )}
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '12px' }}>
              {[
                { step: 1, title: '1. Goal & Rules', desc: 'Define budget and requirements' },
                { step: 2, title: '2. Proposal Check', desc: 'Verify merchant and pricing' },
                { step: 3, title: '3. Policy Validation', desc: 'Enforce limits & bounds' },
                { step: 4, title: '4. PayPal Checkout', desc: 'Authorize and capture funds' },
                { step: 5, title: '5. Audit Receipt', desc: 'Tamper-proof signed record' },
              ].map((s) => {
                const isCurrent = pipelineStep === s.step && !pipelineBlocked;
                const isDone = pipelineStep > s.step && !pipelineBlocked;
                const isFailed = pipelineBlocked && pipelineStep === s.step;

                let cardBg = '#f8fafc';
                let borderColor = '#e2e8f0';
                let titleColor = '#64748b';

                if (isDone) {
                  cardBg = '#ecfdf5';
                  borderColor = '#a7f3d0';
                  titleColor = '#059669';
                } else if (isCurrent) {
                  cardBg = '#eff6ff';
                  borderColor = '#bfdbfe';
                  titleColor = '#0070ba';
                } else if (isFailed) {
                  cardBg = '#fef2f2';
                  borderColor = '#fecaca';
                  titleColor = '#dc2626';
                }

                return (
                  <div
                    key={s.step}
                    style={{
                      background: cardBg,
                      border: `1px solid ${borderColor}`,
                      borderRadius: '8px',
                      padding: '12px 14px',
                      transition: 'all 0.2s ease',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
                      <span style={{ fontSize: '0.8rem', fontWeight: 700, color: titleColor }}>
                        {s.title}
                      </span>
                      {isDone && <CheckCircle2 size={15} color="#059669" />}
                      {isFailed && <ShieldAlert size={15} color="#dc2626" />}
                    </div>
                    <p style={{ fontSize: '0.72rem', color: '#64748b' }}>{s.desc}</p>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Error Message Banner */}
          {errorMsg && (
            <div style={{ padding: '14px 20px', borderRadius: '8px', background: '#fef2f2', border: '1px solid #fecaca', color: '#dc2626', marginBottom: '22px', display: 'flex', alignItems: 'center', gap: '12px', fontSize: '0.88rem' }}>
              <AlertTriangle size={18} />
              <span style={{ fontWeight: 500 }}>{errorMsg}</span>
              <button onClick={() => setErrorMsg(null)} style={{ marginLeft: 'auto', background: 'none', border: 'none', color: '#dc2626', cursor: 'pointer', fontSize: '1.2rem', padding: '0 4px' }}>×</button>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════ */}
          {/* VIEW 1: PURCHASE FLOW                                 */}
          {/* ══════════════════════════════════════════════════════ */}
          {activeTab === 'agent' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1.15fr 1fr', gap: '26px' }}>

              {/* ─── Left Column: Input, Team Quota, Rules ─── */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>

                {/* 1. Goal Input Card */}
                <div className="clean-card" style={{ padding: '24px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <ShoppingBag size={18} color="#0070ba" />
                      <h3 style={{ fontSize: '1.05rem', fontWeight: 700, color: '#0f172a' }}>AI Purchase Goal</h3>
                    </div>
                    <span className="badge badge-neutral">Autonomous Purchase</span>
                  </div>

                  {/* Team / Sub-Agent Quota Selector */}
                  <div style={{ marginBottom: '16px', padding: '12px 14px', background: '#f8fafc', borderRadius: '8px', border: '1px solid #e2e8f0' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                      <span style={{ fontSize: '0.78rem', color: '#0f172a', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <Bot size={15} color="#0070ba" /> Assigned Agent Team:
                      </span>
                      {policy?.agent_quotas?.[selectedAgent] && (
                        <span style={{ fontSize: '0.74rem', color: '#64748b' }}>
                          Available: <strong style={{ color: '#059669' }}>₹{policy.agent_quotas[selectedAgent].remaining_budget?.toLocaleString()}</strong> / ₹{policy.agent_quotas[selectedAgent].allocated_budget?.toLocaleString()}
                        </span>
                      )}
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px' }}>
                      {[
                        { id: 'agent_hardware', label: 'Hardware Agent', role: 'Electronics & Gear', promptPreset: 'Find a wireless mechanical keyboard under ₹5,000, auto-buy under ₹4,000.' },
                        { id: 'agent_travel', label: 'Travel Agent', role: 'Flights & Hotel', promptPreset: 'Book economy flights to Bangalore under ₹5,000.' },
                        { id: 'agent_supplies', label: 'Supplies Agent', role: 'Office Supplies', promptPreset: 'Order custom brass keyboard desk mat under ₹2,000.' },
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
                              padding: '10px 12px',
                              borderRadius: '6px',
                              border: isSelected ? '1px solid #0070ba' : '1px solid #e2e8f0',
                              background: isSelected ? '#eff6ff' : '#ffffff',
                              color: isSelected ? '#0070ba' : '#334155',
                              cursor: 'pointer',
                              textAlign: 'left',
                              display: 'flex',
                              flexDirection: 'column',
                              gap: '2px',
                              transition: 'all 0.15s ease',
                            }}
                          >
                            <span style={{ fontSize: '0.82rem', fontWeight: 600 }}>{ag.label}</span>
                            <span style={{ fontSize: '0.7rem', color: '#64748b' }}>{ag.role}</span>
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: '#334155', marginBottom: '6px' }}>
                    Purchase Instructions:
                  </label>
                  <textarea
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    rows={3}
                    style={{
                      width: '100%',
                      background: '#ffffff',
                      border: '1px solid #cbd5e1',
                      borderRadius: '8px',
                      padding: '12px 14px',
                      color: '#0f172a',
                      fontSize: '0.88rem',
                      resize: 'none',
                      outline: 'none',
                      lineHeight: '1.5',
                      boxShadow: 'inset 0 1px 2px rgba(0, 0, 0, 0.04)',
                    }}
                    placeholder="Enter what you want the agent to purchase and your budget limits..."
                  />

                  {/* Sample Presets */}
                  <div style={{ marginTop: '10px', display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.75rem', color: '#64748b' }}>Examples:</span>
                    {[
                      ['Auto-buy ₹3,899 (Approved)', 'Find a wireless mechanical keyboard suitable for programming. Maximum budget ₹5,000, auto-buy under ₹4,000.'],
                      ['Requires Manual Approval ₹4,500', 'Find premium custom mechanical keyboard under ₹5,000. Require approval above ₹4,000.'],
                      ['Reject Over Budget', 'Search for custom brass keyboard. Budget ceiling ₹5,000.'],
                    ].map(([label, val]) => (
                      <button
                        key={label}
                        onClick={() => setPrompt(val)}
                        style={{
                          background: '#f1f5f9',
                          border: '1px solid #e2e8f0',
                          borderRadius: '6px',
                          padding: '4px 9px',
                          fontSize: '0.74rem',
                          color: '#475569',
                          cursor: 'pointer',
                        }}
                      >
                        {label}
                      </button>
                    ))}
                  </div>

                  <div style={{ marginTop: '18px', display: 'flex', justifyContent: 'flex-end' }}>
                    <button
                      onClick={handleParsePolicy}
                      disabled={loading || !prompt.trim()}
                      className="btn btn-primary"
                    >
                      {loading ? <RefreshCw className="animate-spin" size={16} /> : <Play size={16} />}
                      Generate Proposal & Check Rules
                    </button>
                  </div>
                </div>

                {/* 2. Budget Quotas Card */}
                {policy && (
                  <div className="clean-card" style={{ padding: '20px 24px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                      <h4 style={{ fontSize: '0.88rem', fontWeight: 700, color: '#0f172a' }}>Department & Agent Budgets</h4>
                      <span className="badge badge-neutral" style={{ fontSize: '0.68rem' }}>Enforced Automatically</span>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                      {/* Master Budget */}
                      <div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', marginBottom: '4px' }}>
                          <span style={{ color: '#475569' }}>Total Allowed Spend:</span>
                          <strong style={{ color: '#0f172a' }}>₹{policy.maximum_total?.toLocaleString()}</strong>
                        </div>
                        <div style={{ height: '7px', background: '#e2e8f0', borderRadius: '4px', overflow: 'hidden' }}>
                          <div style={{ width: '100%', height: '100%', background: '#0070ba' }} />
                        </div>
                      </div>

                      {/* Agent Budget */}
                      {policy.agent_quotas?.[selectedAgent] && (
                        <div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', marginBottom: '4px' }}>
                            <span style={{ color: '#475569' }}>{selectedAgent} Quota:</span>
                            <span style={{ color: '#059669', fontWeight: 600 }}>
                              ₹{policy.agent_quotas[selectedAgent].remaining_budget?.toLocaleString()} remaining of ₹{policy.agent_quotas[selectedAgent].allocated_budget?.toLocaleString()}
                            </span>
                          </div>
                          <div style={{ height: '7px', background: '#e2e8f0', borderRadius: '4px', overflow: 'hidden' }}>
                            <div
                              style={{
                                width: `${Math.min(100, (policy.agent_quotas[selectedAgent].remaining_budget / policy.agent_quotas[selectedAgent].allocated_budget) * 100)}%`,
                                height: '100%',
                                background: '#10b981',
                              }}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* 3. Active Policy Rules Card */}
                {policy && (
                  <div className="clean-card" style={{ padding: '20px 24px', borderLeft: `4px solid ${policy.is_revoked ? '#dc2626' : '#0070ba'}` }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <Lock size={16} color={policy.is_revoked ? '#dc2626' : '#0070ba'} />
                        <h4 style={{ fontSize: '0.92rem', fontWeight: 700, color: '#0f172a' }}>Active Policy Rules</h4>
                        <span className="badge badge-neutral" style={{ fontSize: '0.66rem' }}>Policy ID: {policy.policy_id.slice(0, 10)}</span>
                      </div>
                      {policy.is_revoked ? (
                        <span className="badge badge-reject">Revoked</span>
                      ) : (
                        <button onClick={handleRevokePolicy} className="btn btn-danger" style={{ padding: '4px 10px', fontSize: '0.74rem' }}>
                          Revoke Permission
                        </button>
                      )}
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                      <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', padding: '12px', borderRadius: '6px' }}>
                        <span style={{ color: '#64748b', fontSize: '0.74rem', display: 'block', marginBottom: '2px' }}>Hard Budget Ceiling</span>
                        <strong style={{ fontSize: '1.05rem', color: '#0f172a' }}>₹{policy.maximum_total?.toLocaleString()}</strong>
                      </div>
                      <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', padding: '12px', borderRadius: '6px' }}>
                        <span style={{ color: '#64748b', fontSize: '0.74rem', display: 'block', marginBottom: '2px' }}>Auto-Purchase Threshold</span>
                        <strong style={{ fontSize: '1.05rem', color: '#0070ba' }}>₹{policy.automatic_purchase_limit?.toLocaleString()}</strong>
                      </div>
                    </div>

                    <div style={{ marginTop: '12px', fontSize: '0.78rem', color: '#64748b', display: 'flex', gap: '16px' }}>
                      <span>Category: <strong style={{ color: '#0f172a' }}>{policy.product_category || 'General'}</strong></span>
                      <span>Currency: <strong style={{ color: '#0f172a' }}>{policy.allowed_currencies?.join(', ') || 'INR'}</strong></span>
                    </div>
                  </div>
                )}

                {/* 4. Test Policy Violations (Drift Testing) */}
                {proposalRes && (
                  <div className="clean-card" style={{ padding: '20px 24px', borderLeft: `4px solid ${simulateDrift !== 'none' ? '#dc2626' : '#e2e8f0'}` }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                      <h4 style={{ fontSize: '0.88rem', fontWeight: 700, color: '#0f172a' }}>Test Policy Violations</h4>
                      {simulateDrift !== 'none' && <span className="badge badge-reject">Violation Active</span>}
                    </div>
                    <p style={{ fontSize: '0.76rem', color: '#64748b', marginBottom: '12px' }}>
                      Simulate a seller altering pricing or swapping products after agent authorization:
                    </p>

                    {simulateDrift === 'price_drift' && (
                      <div style={{ marginBottom: '12px', padding: '10px 14px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '6px', fontSize: '0.82rem' }}>
                        <span style={{ color: '#64748b' }}>Original Total: </span>
                        <strong style={{ textDecoration: 'line-through', color: '#64748b', marginRight: '8px' }}>₹{originalTotal.toLocaleString()}</strong>
                        <ArrowRight size={13} style={{ display: 'inline', color: '#dc2626', marginRight: '6px' }} />
                        <strong style={{ color: '#dc2626', fontSize: '0.95rem' }}>₹{driftedTotal.toLocaleString()}</strong>
                        <span style={{ color: '#dc2626', fontSize: '0.75rem', marginLeft: '6px' }}>(+₹850 unexpected shipping added)</span>
                      </div>
                    )}

                    {simulateDrift === 'sku_substitution' && (
                      <div style={{ marginBottom: '12px', padding: '10px 14px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '6px', fontSize: '0.82rem' }}>
                        <span style={{ color: '#64748b' }}>Item Changed: </span>
                        <code style={{ textDecoration: 'line-through', color: '#64748b', marginRight: '6px' }}>{proposalRes.proposal?.items?.[0]?.sku}</code>
                        <ArrowRight size={13} style={{ display: 'inline', color: '#dc2626', marginRight: '6px' }} />
                        <code style={{ color: '#dc2626' }}>KB-SUBSTITUTED-CHEAP</code>
                      </div>
                    )}

                    <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                      <button
                        onClick={() => setSimulateDrift('none')}
                        className={`btn ${simulateDrift === 'none' ? 'btn-primary' : 'btn-secondary'}`}
                        style={{ padding: '6px 12px', fontSize: '0.76rem' }}
                      >
                        Standard Purchase (No Changes)
                      </button>
                      <button
                        onClick={() => { setSimulateDrift('price_drift'); setCheckoutSession(null); setErrorMsg(null); }}
                        className={`btn ${simulateDrift === 'price_drift' ? 'btn-danger' : 'btn-secondary'}`}
                        style={{ padding: '6px 12px', fontSize: '0.76rem' }}
                      >
                        Add +₹850 Shipping Fee
                      </button>
                      <button
                        onClick={() => { setSimulateDrift('sku_substitution'); setCheckoutSession(null); setErrorMsg(null); }}
                        className={`btn ${simulateDrift === 'sku_substitution' ? 'btn-danger' : 'btn-secondary'}`}
                        style={{ padding: '6px 12px', fontSize: '0.76rem' }}
                      >
                        Swap for Different Item
                      </button>
                    </div>
                  </div>
                )}
              </div>

              {/* ─── Right Column: Proposal & Checkout ─── */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
                {!proposalRes ? (
                  <div className="clean-card" style={{ padding: '70px 24px', textAlign: 'center', color: '#64748b' }}>
                    <CreditCard size={44} strokeWidth={1.3} style={{ margin: '0 auto 16px', color: '#cbd5e1' }} />
                    <h3 style={{ fontSize: '1.05rem', color: '#0f172a', marginBottom: '6px' }}>No Proposal Generated Yet</h3>
                    <p style={{ fontSize: '0.84rem', maxWidth: '340px', margin: '0 auto' }}>
                      Enter your purchase goal on the left. The agent will find a matching item, compute total costs, and check your policy rules.
                    </p>
                  </div>
                ) : (
                  <div className="clean-card" style={{ padding: '24px' }}>

                    {/* Proposal Title & Status */}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '14px' }}>
                      <div>
                        <span style={{ fontSize: '0.72rem', color: '#0070ba', fontWeight: 600 }}>RECOMMENDED PURCHASE</span>
                        <h3 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#0f172a', marginTop: '2px' }}>
                          {proposalRes.proposal?.items?.[0]?.name}
                        </h3>
                        <p style={{ fontSize: '0.8rem', color: '#64748b', marginTop: '2px' }}>
                          Merchant: <strong>{proposalRes.proposal?.merchant}</strong> · SKU: <code style={{ color: '#0070ba' }}>{proposalRes.proposal?.items?.[0]?.sku}</code>
                        </p>
                      </div>
                      <div>
                        {proposalRes.state === 'AUTHORIZED' && <span className="badge badge-allow"><CheckCircle2 size={13} /> Auto-Approved</span>}
                        {proposalRes.state === 'AWAITING_APPROVAL' && <span className="badge badge-approval"><AlertTriangle size={13} /> Needs Approval</span>}
                        {proposalRes.state === 'POLICY_REJECTED' && <span className="badge badge-reject"><ShieldX size={13} /> Blocked</span>}
                        {(checkoutSession?.state === 'POLICY_REJECTED') && proposalRes.state !== 'POLICY_REJECTED' && <span className="badge badge-reject"><ShieldX size={13} /> Blocked</span>}
                      </div>
                    </div>

                    {/* Item Explanation */}
                    <div style={{ background: '#f8fafc', borderLeft: '3px solid #0070ba', padding: '12px 14px', borderRadius: '4px', fontSize: '0.82rem', color: '#334155', lineHeight: '1.5', marginBottom: '16px' }}>
                      {proposalRes.recommendation_explanation}
                    </div>

                    {/* Price Breakdown */}
                    <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', padding: '14px', borderRadius: '8px', marginBottom: '16px' }}>
                      {[
                        ['Item Price', `₹${proposalRes.proposal?.item_subtotal?.toLocaleString()}`],
                        ['Shipping Fee', simulateDrift === 'price_drift' ? '₹850 (Altered)' : `₹${proposalRes.proposal?.shipping_fee?.toLocaleString()}`],
                        ['Tax', `₹${proposalRes.proposal?.tax_fee?.toLocaleString()}`],
                      ].map(([label, val]) => (
                        <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.84rem', marginBottom: '8px' }}>
                          <span style={{ color: '#64748b' }}>{label}</span>
                          <strong style={{ color: (label === 'Shipping Fee' && simulateDrift === 'price_drift') ? '#dc2626' : '#0f172a' }}>{val}</strong>
                        </div>
                      ))}
                      <div style={{ height: '1px', background: '#e2e8f0', margin: '10px 0' }} />
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontWeight: 700, color: '#0f172a', fontSize: '0.92rem' }}>Total Cost</span>
                        <div style={{ textAlign: 'right' }}>
                          {simulateDrift === 'price_drift' && (
                            <span style={{ fontSize: '0.78rem', color: '#94a3b8', textDecoration: 'line-through', display: 'block' }}>₹{originalTotal.toLocaleString()}</span>
                          )}
                          <strong style={{ fontSize: '1.25rem', color: simulateDrift === 'price_drift' ? '#dc2626' : '#0070ba' }}>
                            ₹{driftedTotal.toLocaleString()} {proposalRes.proposal?.currency}
                          </strong>
                        </div>
                      </div>
                    </div>

                    {/* Verification Record (Hash) */}
                    <div style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '6px', padding: '10px 12px', marginBottom: '18px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '4px' }}>
                        <span style={{ fontSize: '0.72rem', color: '#64748b', fontWeight: 600 }}>
                          PROPOSAL VERIFICATION HASH
                        </span>
                        <button
                          onClick={() => copyToClipboard(proposalRes.proposal?.proposal_fingerprint)}
                          style={{ background: 'none', border: 'none', color: '#0070ba', cursor: 'pointer', fontSize: '0.7rem' }}
                        >
                          {copiedHash ? '✓ Copied' : 'Copy'}
                        </button>
                      </div>
                      <code style={{ fontSize: '0.72rem', color: '#475569', wordBreak: 'break-all', display: 'block' }}>
                        {proposalRes.proposal?.proposal_fingerprint}
                      </code>
                    </div>

                    {/* Payment Execution Actions */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                      {proposalRes.state === 'AWAITING_APPROVAL' && !checkoutSession && (
                        <button onClick={handleApprove} disabled={loading} className="btn btn-primary" style={{ width: '100%', padding: '12px' }}>
                          <CheckCircle2 size={16} /> Manually Approve This Purchase
                        </button>
                      )}

                      {(proposalRes.state === 'AUTHORIZED' || (checkoutSession?.state === 'AUTHORIZED')) && !checkoutSession?.state?.match(/PAID|POLICY_REJECTED|FAILED/) && (
                        <>
                          {simulateDrift !== 'none' ? (
                            <button onClick={handleInjectDriftAndBlock} disabled={loading} className="btn btn-danger" style={{ width: '100%', padding: '12px' }}>
                              {loading ? <RefreshCw className="animate-spin" size={16} /> : <ShieldAlert size={16} />}
                              Execute Payment (Test Violation Defense)
                            </button>
                          ) : isMockMode ? (
                            <button onClick={handleExecutePaymentMock} disabled={loading} className="btn btn-primary" style={{ width: '100%', padding: '12px' }}>
                              {loading ? <RefreshCw className="animate-spin" size={16} /> : <CreditCard size={16} />}
                              Execute Authorized Payment
                            </button>
                          ) : (
                            <div>
                              <p style={{ fontSize: '0.78rem', color: '#64748b', marginBottom: '8px', textAlign: 'center' }}>
                                Rules passed. Complete checkout securely with PayPal:
                              </p>
                              <PayPalCheckoutButton
                                checkoutId={proposalRes.checkout_id}
                                onSuccess={(session) => {
                                  setCheckoutSession(session);
                                  setPipelineStep(5);
                                }}
                                onError={(msg) => {
                                  setErrorMsg(msg);
                                  setCheckoutSession({ state: 'POLICY_REJECTED', failure_reason: msg });
                                  setPipelineBlocked(true);
                                }}
                              />
                            </div>
                          )}
                        </>
                      )}

                      {proposalRes.state === 'POLICY_REJECTED' && !checkoutSession && (
                        <div style={{ textAlign: 'center', padding: '12px', color: '#dc2626', fontSize: '0.85rem', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: '6px' }}>
                          <ShieldX size={16} style={{ display: 'inline', marginRight: '6px' }} />
                          {proposalRes.failure_reason || 'This purchase violates active policy rules and cannot proceed.'}
                        </div>
                      )}
                    </div>

                    {/* Payment Success Card */}
                    {checkoutSession?.state === 'PAID' && (
                      <div style={{ marginTop: '18px', padding: '16px', borderRadius: '8px', background: '#ecfdf5', border: '1px solid #a7f3d0' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#059669' }}>
                            <CheckCircle2 size={18} />
                            <strong style={{ fontSize: '0.92rem' }}>
                              {isLiveSandbox ? 'Payment Completed on PayPal Sandbox' : 'Payment Settled Successfully'}
                            </strong>
                          </div>
                          <span className="badge badge-allow">Completed</span>
                        </div>
                        <div style={{ fontSize: '0.78rem', color: '#334155', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
                          <div>Order ID: <code style={{ color: '#0f172a' }}>{checkoutSession.paypal_order_id}</code></div>
                          <div>Capture ID: <code style={{ color: '#0f172a' }}>{checkoutSession.paypal_capture_id}</code></div>
                          <div>Status: <strong style={{ color: '#059669' }}>COMPLETED</strong></div>
                          <div>Total Charged: <strong style={{ color: '#0f172a' }}>₹{proposalRes.proposal?.total_amount?.toLocaleString()}</strong></div>
                        </div>

                        {/* Receipt Buttons */}
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '14px' }}>
                          <button
                            type="button"
                            onClick={() => handleOpenReceiptInspector(proposalRes.checkout_id)}
                            className="btn btn-primary"
                            style={{ fontSize: '0.78rem', padding: '8px' }}
                          >
                            <Key size={14} /> Verify Audit Signature
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDownloadReceipt(proposalRes.checkout_id)}
                            className="btn btn-secondary"
                            style={{ fontSize: '0.78rem', padding: '8px' }}
                          >
                            <Download size={14} /> Download Receipt JSON
                          </button>
                        </div>

                        {/* Webhook Testing Controls */}
                        <div style={{ marginTop: '14px', paddingTop: '12px', borderTop: '1px solid #d1fae5' }}>
                          <div style={{ fontSize: '0.76rem', color: '#475569', fontWeight: 600, marginBottom: '8px' }}>
                            Test Asynchronous PayPal Events:
                          </div>
                          <div style={{ display: 'flex', gap: '8px' }}>
                            <button
                              type="button"
                              onClick={() => handleSimulateWebhook(proposalRes.checkout_id, 'PAYMENT.CAPTURE.REFUNDED')}
                              className="btn btn-secondary"
                              style={{ padding: '6px 10px', fontSize: '0.74rem', flex: 1 }}
                            >
                              Simulate Refund Webhook
                            </button>
                            <button
                              type="button"
                              onClick={() => handleSimulateWebhook(proposalRes.checkout_id, 'CUSTOMER.DISPUTE.CREATED')}
                              className="btn btn-secondary"
                              style={{ padding: '6px 10px', fontSize: '0.74rem', flex: 1 }}
                            >
                              Simulate Dispute Webhook
                            </button>
                          </div>
                          {webhookStatus && (
                            <div style={{ marginTop: '8px', fontSize: '0.75rem', color: '#0070ba', background: '#eff6ff', border: '1px solid #bfdbfe', padding: '6px 10px', borderRadius: '6px' }}>
                              {webhookStatus}
                            </div>
                          )}
                        </div>

                        {isLiveSandbox && checkoutSession.paypal_order_id && !checkoutSession.paypal_order_id.startsWith('MOCK') && (
                          <a
                            href={`https://www.sandbox.paypal.com/activities/`}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{ display: 'inline-flex', alignItems: 'center', gap: '5px', marginTop: '12px', fontSize: '0.76rem', color: '#0070ba', textDecoration: 'none' }}
                          >
                            <ExternalLink size={13} /> Open in PayPal Sandbox Dashboard
                          </a>
                        )}
                      </div>
                    )}

                    {/* Blocked Confirmation */}
                    {checkoutSession?.state === 'POLICY_REJECTED' && (
                      <div style={{ marginTop: '18px', padding: '16px', borderRadius: '8px', background: '#fef2f2', border: '1px solid #fecaca' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#dc2626', marginBottom: '6px' }}>
                          <ShieldAlert size={18} />
                          <strong style={{ fontSize: '0.92rem' }}>Unauthorized Transaction Blocked</strong>
                        </div>
                        <p style={{ fontSize: '0.82rem', color: '#b91c1c', marginBottom: '8px' }}>
                          {checkoutSession.failure_reason}
                        </p>
                        <p style={{ fontSize: '0.75rem', color: '#64748b' }}>
                          No payment request was sent to PayPal. Your balance and team quotas remain untouched.
                        </p>
                        <div style={{ display: 'flex', gap: '8px', marginTop: '12px' }}>
                          <button
                            type="button"
                            onClick={() => handleOpenReceiptInspector(proposalRes.checkout_id)}
                            className="btn btn-danger"
                            style={{ flex: 1, fontSize: '0.78rem', padding: '8px' }}
                          >
                            <Key size={14} /> View Refusal Record
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDownloadReceipt(proposalRes.checkout_id)}
                            className="btn btn-secondary"
                            style={{ flex: 1, fontSize: '0.78rem', padding: '8px' }}
                          >
                            <Download size={14} /> Export JSON
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
          {/* VIEW 2: POLICY TEST LAB (BENCHMARK)                   */}
          {/* ══════════════════════════════════════════════════════ */}
          {activeTab === 'lab' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
              <div className="clean-card" style={{ padding: '22px 28px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <h3 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#0f172a' }}>Policy Enforcement Test Lab</h3>
                  <p style={{ color: '#64748b', fontSize: '0.82rem', marginTop: '2px' }}>
                    Automated testing across 7 real-world failure and attack scenarios
                  </p>
                </div>
                <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                  <select
                    value={selectedSystem}
                    onChange={(e) => setSelectedSystem(e.target.value as any)}
                    style={{ background: '#ffffff', border: '1px solid #cbd5e1', color: '#0f172a', borderRadius: '6px', padding: '7px 12px', fontSize: '0.84rem' }}
                  >
                    <option value="PROPOSED_APIL">Proposed APIL (With Policy Guard)</option>
                    <option value="BASELINE_A">Baseline A (No Policy Gate)</option>
                    <option value="BASELINE_B">Baseline B (Basic Static Limits)</option>
                  </select>
                  <button onClick={handleRunBenchmark} disabled={labRunning} className="btn btn-primary">
                    {labRunning ? <RefreshCw className="animate-spin" size={15} /> : <Play size={15} />}
                    {labRunning ? 'Running Tests...' : 'Run All 7 Scenarios'}
                  </button>
                </div>
              </div>

              {/* Benchmark Summary Metrics */}
              {benchmarkReport && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '16px' }}>
                  {[
                    { label: 'Policy Pass Rate', value: `${benchmarkReport.pass_rate_pct?.toFixed(1)}%`, color: benchmarkReport.pass_rate_pct === 100 ? '#059669' : '#d97706' },
                    { label: 'Total Test Scenarios', value: benchmarkReport.total_scenarios, color: '#0070ba' },
                    { label: 'Unauthorized Spends', value: benchmarkReport.unauthorized_spend_count ?? '0', color: benchmarkReport.unauthorized_spend_count === 0 ? '#059669' : '#dc2626' },
                    { label: 'Average Evaluation Speed', value: `${benchmarkReport.avg_latency_ms?.toFixed(2)} ms`, color: '#6366f1' },
                  ].map(({ label, value, color }) => (
                    <div key={label} className="clean-card" style={{ padding: '20px', textAlign: 'center' }}>
                      <div style={{ fontSize: '1.75rem', fontWeight: 800, color, letterSpacing: '-0.02em' }}>{value}</div>
                      <div style={{ fontSize: '0.76rem', color: '#64748b', marginTop: '4px' }}>{label}</div>
                    </div>
                  ))}
                </div>
              )}

              {/* Scenario Results Table */}
              <div className="clean-card" style={{ overflow: 'hidden' }}>
                <div style={{ padding: '16px 24px', borderBottom: '1px solid #e2e8f0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h4 style={{ fontSize: '0.92rem', fontWeight: 700, color: '#0f172a' }}>Scenario Results</h4>
                  <span className="badge badge-neutral">Full Coverage</span>
                </div>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.84rem' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid #e2e8f0', background: '#f8fafc' }}>
                        {['Scenario', 'Category', 'Test Condition', 'System Under Test', 'Result', 'Evaluation Time'].map((h) => (
                          <th key={h} style={{ padding: '11px 16px', textAlign: 'left', color: '#64748b', fontWeight: 600, fontSize: '0.74rem' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(benchmarkReport?.results || (labScenarios.length ? labScenarios : DEFAULT_SCENARIOS)).map((row: any, i: number) => {
                        const passed = row.passed;
                        const scenarioDef = labScenarios.find((s: any) => s.scenario_id === row.scenario_id);
                        return (
                          <tr key={i} style={{ borderBottom: '1px solid #f1f5f9' }}>
                            <td style={{ padding: '12px 16px', fontWeight: 600, color: '#0f172a' }}>{row.scenario_id || '-'}</td>
                            <td style={{ padding: '12px 16px' }}>
                              <span className="badge badge-neutral" style={{ fontSize: '0.72rem' }}>{row.category || scenarioDef?.category || '-'}</span>
                            </td>
                            <td style={{ padding: '12px 16px', color: '#475569' }}>{row.failure_type || row.name || '-'}</td>
                            <td style={{ padding: '12px 16px', color: '#0070ba', fontWeight: 600 }}>{row.system_type || selectedSystem}</td>
                            <td style={{ padding: '12px 16px' }}>
                              {passed != null ? (
                                <span className={`badge ${passed ? 'badge-allow' : 'badge-reject'}`}>
                                  {passed ? '✓ Protected' : '✗ Failed (Money Spent)'}
                                </span>
                              ) : (
                                <span className="badge badge-neutral">Pending</span>
                              )}
                            </td>
                            <td style={{ padding: '12px 16px', color: '#64748b', fontFamily: 'JetBrains Mono, monospace', fontSize: '0.76rem' }}>
                              {row.latency_ms != null ? `${row.latency_ms.toFixed(2)} ms` : '< 1 ms'}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Architecture Comparison */}
              <div className="clean-card" style={{ padding: '22px 28px' }}>
                <h4 style={{ fontSize: '0.92rem', fontWeight: 700, color: '#0f172a', marginBottom: '14px' }}>
                  Architecture Comparison
                </h4>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.84rem' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid #e2e8f0', background: '#f8fafc' }}>
                        {['Architecture', 'Attack Defense Rate', 'Unauthorized Spends', 'Latency', 'Audit Records'].map((h) => (
                          <th key={h} style={{ padding: '10px 16px', textAlign: 'left', color: '#64748b', fontWeight: 600, fontSize: '0.74rem' }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        { sys: 'Baseline A (No Policy Gate)', pass: '14.3%', unauth: '6', lat: '0.10 ms', receipts: 'None', highlight: false },
                        { sys: 'Baseline B (Static Limits Only)', pass: '57.1%', unauth: '3', lat: '0.09 ms', receipts: 'Unsigned logs', highlight: false },
                        { sys: 'Proposed APIL (Our Solution)', pass: '100.0%', unauth: '0', lat: '0.08 ms', receipts: 'Cryptographically Signed', highlight: true },
                      ].map(({ sys, pass, unauth, lat, receipts, highlight }) => (
                        <tr key={sys} style={{ borderBottom: '1px solid #f1f5f9', background: highlight ? '#eff6ff' : 'transparent' }}>
                          <td style={{ padding: '11px 16px', fontWeight: highlight ? 700 : 500, color: highlight ? '#0070ba' : '#0f172a' }}>{sys}</td>
                          <td style={{ padding: '11px 16px', color: pass === '100.0%' ? '#059669' : '#d97706', fontWeight: 700 }}>{pass}</td>
                          <td style={{ padding: '11px 16px', color: unauth === '0' ? '#059669' : '#dc2626', fontWeight: 700 }}>{unauth}</td>
                          <td style={{ padding: '11px 16px', color: '#64748b', fontFamily: 'monospace' }}>{lat}</td>
                          <td style={{ padding: '11px 16px', color: highlight ? '#0070ba' : '#64748b', fontWeight: highlight ? 600 : 400 }}>{receipts}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* ══════════════════════════════════════════════════════ */}
          {/* VIEW 3: AUDIT TRAIL                                   */}
          {/* ══════════════════════════════════════════════════════ */}
          {activeTab === 'audit' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
              <div className="clean-card" style={{ padding: '22px 28px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <h3 style={{ fontSize: '1.15rem', fontWeight: 700, color: '#0f172a' }}>Audit Trail & Ledger</h3>
                  <p style={{ color: '#64748b', fontSize: '0.82rem', marginTop: '2px' }}>
                    Immutable sequence of every purchase event and policy verification
                  </p>
                </div>
                <div style={{ display: 'flex', gap: '10px', alignItems: 'center' }}>
                  {auditData && (
                    <span className={`badge ${auditData.ledger_integrity_valid ? 'badge-allow' : 'badge-reject'}`}>
                      {auditData.ledger_integrity_valid ? '✓ Ledger Valid & Tamper-Free' : '✗ Integrity Check Failed'}
                    </span>
                  )}
                  <button onClick={fetchAuditEvents} className="btn btn-secondary">
                    <RefreshCw size={14} /> Refresh
                  </button>
                </div>
              </div>

              {auditData?.events?.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  {auditData.events.map((ev: any, i: number) => (
                    <div
                      key={i}
                      className="clean-card"
                      style={{
                        padding: '16px 20px',
                        borderLeft: `3px solid ${ev.event_type.includes('BLOCKED') || ev.event_type.includes('REJECTED') ? '#dc2626' : ev.event_type.includes('COMPLETED') || ev.event_type.includes('PAID') ? '#059669' : '#0070ba'}`,
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '6px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                          <span style={{ fontSize: '0.74rem', color: '#94a3b8', fontFamily: 'JetBrains Mono, monospace' }}>#{i + 1}</span>
                          <strong style={{ fontSize: '0.88rem', color: '#0f172a' }}>{ev.event_type}</strong>
                          {ev.checkout_id && <span className="badge badge-neutral" style={{ fontSize: '0.68rem' }}>{ev.checkout_id}</span>}
                        </div>
                        <span style={{ fontSize: '0.72rem', color: '#64748b', fontFamily: 'JetBrains Mono, monospace' }}>{ev.timestamp}</span>
                      </div>
                      {ev.reason && <p style={{ fontSize: '0.82rem', color: '#475569', margin: '4px 0 8px' }}>{ev.reason}</p>}
                      <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
                        {ev.event_hash && (
                          <div style={{ fontSize: '0.72rem' }}>
                            <span style={{ color: '#64748b', marginRight: '4px' }}>Hash:</span>
                            <code style={{ color: '#0070ba', cursor: 'pointer' }} onClick={() => copyToClipboard(ev.event_hash)}>
                              {ev.event_hash.slice(0, 18)}…{ev.event_hash.slice(-8)}
                            </code>
                          </div>
                        )}
                        {ev.proposal_fingerprint && (
                          <div style={{ fontSize: '0.72rem' }}>
                            <span style={{ color: '#64748b', marginRight: '4px' }}>Proposal Fingerprint:</span>
                            <code style={{ color: '#64748b' }}>{ev.proposal_fingerprint.slice(0, 18)}…</code>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="clean-card" style={{ padding: '60px', textAlign: 'center', color: '#64748b' }}>
                  <Eye size={40} strokeWidth={1.3} style={{ margin: '0 auto 12px', color: '#cbd5e1' }} />
                  <p style={{ fontSize: '0.9rem' }}>No audit events logged yet. Complete a purchase or run the test lab first.</p>
                </div>
              )}
            </div>
          )}

        </div>

        {/* ══════════════════════════════════════════════════════ */}
        {/* RECEIPT INSPECTOR MODAL                                */}
        {/* ══════════════════════════════════════════════════════ */}
        {receiptModalOpen && inspectingReceipt && (
          <div className="modal-overlay animate-fade-in" onClick={() => setReceiptModalOpen(false)}>
            <div
              className="clean-card"
              style={{
                width: '100%',
                maxWidth: '680px',
                padding: '28px',
                boxShadow: '0 20px 40px rgba(0, 0, 0, 0.15)',
              }}
              onClick={(e) => e.stopPropagation()}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '18px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div style={{ width: '36px', height: '36px', borderRadius: '8px', background: '#eff6ff', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <Key size={18} color="#0070ba" />
                  </div>
                  <div>
                    <h3 style={{ fontSize: '1.08rem', fontWeight: 700, color: '#0f172a' }}>Payment Audit Receipt</h3>
                    <p style={{ fontSize: '0.76rem', color: '#64748b' }}>Cryptographically signed proof of authorized purchase</p>
                  </div>
                </div>
                <button
                  onClick={() => setReceiptModalOpen(false)}
                  style={{ background: 'none', border: 'none', color: '#64748b', cursor: 'pointer', fontSize: '1.2rem', padding: '4px' }}
                >
                  <X size={20} />
                </button>
              </div>

              {/* Verification Status Banner */}
              <div
                style={{
                  padding: '12px 16px',
                  borderRadius: '8px',
                  background: receiptVerificationState === 'valid'
                    ? '#ecfdf5'
                    : receiptVerificationState === 'verifying'
                    ? '#eff6ff'
                    : '#fef2f2',
                  border: receiptVerificationState === 'valid'
                    ? '1px solid #a7f3d0'
                    : receiptVerificationState === 'verifying'
                    ? '1px solid #bfdbfe'
                    : '1px solid #fecaca',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '12px',
                  marginBottom: '18px',
                }}
              >
                {receiptVerificationState === 'valid' ? (
                  <>
                    <CheckCheck size={22} color="#059669" />
                    <div>
                      <div style={{ fontSize: '0.86rem', fontWeight: 700, color: '#059669' }}>
                        Signature Verified Authentic
                      </div>
                      <div style={{ fontSize: '0.74rem', color: '#334155' }}>
                        HMAC-SHA256 signature confirms this receipt has not been modified since creation.
                      </div>
                    </div>
                  </>
                ) : receiptVerificationState === 'verifying' ? (
                  <>
                    <RefreshCw size={20} className="animate-spin" color="#0070ba" />
                    <div style={{ fontSize: '0.86rem', color: '#0070ba' }}>
                      Checking signature against secret key...
                    </div>
                  </>
                ) : (
                  <>
                    <ShieldAlert size={22} color="#dc2626" />
                    <div>
                      <div style={{ fontSize: '0.86rem', fontWeight: 700, color: '#dc2626' }}>
                        Signature Verification Failed
                      </div>
                      <div style={{ fontSize: '0.74rem', color: '#b91c1c' }}>
                        {receiptVerificationDetails?.error || 'Receipt contents do not match the expected cryptographic signature.'}
                      </div>
                    </div>
                  </>
                )}
              </div>

              {/* Receipt Payload Viewer */}
              <div style={{ marginBottom: '16px' }}>
                <span style={{ fontSize: '0.74rem', color: '#64748b', display: 'block', marginBottom: '6px', fontWeight: 600 }}>
                  RECEIPT CONTENTS:
                </span>
                <pre className="code-block" style={{ maxHeight: '240px' }}>
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
                  style={{ fontSize: '0.8rem' }}
                >
                  <Download size={14} /> Download Receipt File
                </button>
                <button
                  type="button"
                  onClick={() => setReceiptModalOpen(false)}
                  className="btn btn-primary"
                  style={{ fontSize: '0.8rem' }}
                >
                  Close
                </button>
              </div>
            </div>
          </div>
        )}

      </main>
    </PayPalScriptProvider>
  );
}
