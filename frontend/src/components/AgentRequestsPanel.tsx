'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Bot, CheckCircle2, Copy } from 'lucide-react';

import { approveCheckout, listPolicyCheckouts, PolicyCheckout } from '../lib/api';
import { formatTimestamp, humanizeEvent } from '../lib/format';
import { ApprovalLinkButton } from './ApprovalLinkButton';

export const AGENT_REQUESTS_POLL_MS = 4000;
const RECENT_LIMIT = 5;

const visuallyHidden: React.CSSProperties = {
  position: 'absolute',
  width: '1px',
  height: '1px',
  margin: '-1px',
  padding: 0,
  overflow: 'hidden',
  clip: 'rect(0 0 0 0)',
  whiteSpace: 'nowrap',
  border: 0,
};

function money(amount: number, currency: string): string {
  const symbol = currency === 'USD' ? '$' : currency === 'INR' ? '₹' : `${currency} `;
  return `${symbol}${amount.toLocaleString('en-US')}`;
}

function describeItems(row: PolicyCheckout): string {
  const first = row.items?.[0]?.name || 'Purchase';
  const more = (row.items?.length || 0) - 1;
  return more > 0 ? `${first} and ${more} more` : first;
}

const STATE_LABELS: Record<string, string> = {
  AWAITING_APPROVAL: 'Needs your approval',
  AUTHORIZED: 'Approved, not paid yet',
  POLICY_REJECTED: 'Blocked by policy',
  PAID: 'Paid',
};

function stateBadge(state: string): { label: string; className: string } {
  const label = STATE_LABELS[state] || humanizeEvent(state);
  if (state === 'AWAITING_APPROVAL') return { label, className: 'badge-approval' };
  if (state === 'PAID' || state === 'AUTHORIZED') return { label, className: 'badge-allow' };
  if (state === 'POLICY_REJECTED' || state === 'FAILED') return { label, className: 'badge-reject' };
  return { label, className: 'badge-neutral' };
}

/**
 * The owner's inbox for a policy: purchases an agent has proposed, including ones proposed by an
 * outside agent over MCP, with the means to approve them. Polls while the tab is visible.
 */
export function AgentRequestsPanel({
  policyId,
  ownerToken,
  ownCheckoutIds,
  onApproved,
  pollMs = AGENT_REQUESTS_POLL_MS,
}: {
  policyId: string;
  ownerToken: string | null;
  /** Checkouts this page proposed itself; every other one came from an outside agent. */
  ownCheckoutIds: string[];
  onApproved?: (session: any) => void;
  pollMs?: number;
}) {
  const [rows, setRows] = useState<PolicyCheckout[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState('');
  const [copiedPolicy, setCopiedPolicy] = useState<'idle' | 'copied' | 'failed'>('idle');

  const inFlight = useRef(false);
  const mounted = useRef(true);
  const loadedOnce = useRef(false);
  const seenAwaiting = useRef<Set<string>>(new Set());
  const ownIds = useRef<string[]>(ownCheckoutIds);
  ownIds.current = ownCheckoutIds;

  const refresh = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const fetched = await listPolicyCheckouts(policyId, ownerToken);
      if (!mounted.current) return;
      const awaiting = fetched.filter((r) => r.state === 'AWAITING_APPROVAL');
      if (loadedOnce.current) {
        const fresh = awaiting.filter(
          (r) => !seenAwaiting.current.has(r.checkout_id) && !ownIds.current.includes(r.checkout_id),
        );
        if (fresh.length > 0) {
          const r = fresh[0];
          setAnnouncement(
            `New purchase request from ${r.agent_id || 'an agent'} needs your approval: ${describeItems(r)}, ${money(r.total_amount, r.currency)}.`,
          );
        }
      }
      awaiting.forEach((r) => seenAwaiting.current.add(r.checkout_id));
      loadedOnce.current = true;
      setRows(fetched);
      setLoaded(true);
      setLoadError(null);
    } catch (err: any) {
      if (!mounted.current) return;
      if (err?.status === 429) return; // rate limited: the next tick retries
      if (err?.status === 401 || err?.status === 403) {
        setLoadError('This browser’s owner token was not accepted, so agent requests cannot be shown.');
      } else {
        setLoadError('Could not refresh agent requests. Retrying.');
      }
    } finally {
      inFlight.current = false;
    }
  }, [policyId, ownerToken]);

  useEffect(() => {
    mounted.current = true;
    refresh();
    const tick = () => {
      if (document.visibilityState === 'visible') refresh();
    };
    const timer = setInterval(tick, pollMs);
    document.addEventListener('visibilitychange', tick);
    return () => {
      mounted.current = false;
      clearInterval(timer);
      document.removeEventListener('visibilitychange', tick);
    };
  }, [refresh, pollMs]);

  const handleApprove = async (row: PolicyCheckout) => {
    setApprovingId(row.checkout_id);
    setActionError(null);
    try {
      const session = await approveCheckout(row.checkout_id, ownerToken);
      if (!mounted.current) return;
      setRows((prev) => prev.map((r) => (r.checkout_id === row.checkout_id ? { ...r, state: session.state } : r)));
      onApproved?.(session);
      refresh();
    } catch (err: any) {
      if (mounted.current) setActionError(err?.message || 'Approval failed.');
    } finally {
      if (mounted.current) setApprovingId(null);
    }
  };

  const copyPolicyId = async () => {
    try {
      await navigator.clipboard.writeText(policyId);
      setCopiedPolicy('copied');
    } catch (_) {
      setCopiedPolicy('failed');
    }
    setTimeout(() => mounted.current && setCopiedPolicy('idle'), 2500);
  };

  const awaiting = rows.filter((r) => r.state === 'AWAITING_APPROVAL');
  const recent = rows.filter((r) => r.state !== 'AWAITING_APPROVAL').slice(0, RECENT_LIMIT);
  const origin = (r: PolicyCheckout) => (ownCheckoutIds.includes(r.checkout_id) ? 'This page' : 'Outside agent');

  return (
    <section
      aria-labelledby="agent-requests-heading"
      className="clean-card"
      style={{ padding: '12px 16px', borderLeft: `4px solid ${awaiting.length > 0 ? '#d97706' : '#0070ba'}` }}
    >
      <div className="wrap-sm" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Bot size={14} color="#0070ba" aria-hidden="true" />
          <h4 id="agent-requests-heading" style={{ fontSize: '0.86rem', fontWeight: 700, color: '#0f172a' }}>
            Agent requests
          </h4>
          {awaiting.length > 0 && (
            <span className="badge badge-approval" style={{ fontSize: '0.75rem', padding: '1px 6px' }}>
              {awaiting.length} waiting
            </span>
          )}
        </div>
      </div>

      <div
        style={{ background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '6px', padding: '7px 9px', marginBottom: '8px' }}
      >
        <div className="wrap-sm" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
          <div style={{ minWidth: 0 }}>
            <span style={{ color: '#526077', fontSize: '0.75rem', display: 'block' }}>Policy ID for an outside AI agent (MCP)</span>
            <code data-testid="policy-id" style={{ fontSize: '0.78rem', color: '#0f172a', wordBreak: 'break-all' }}>{policyId}</code>
          </div>
          <button
            type="button"
            onClick={copyPolicyId}
            className="btn btn-secondary"
            aria-label="Copy policy ID"
            style={{ padding: '4px 10px', fontSize: '0.75rem' }}
          >
            <Copy size={12} aria-hidden="true" /> {copiedPolicy === 'copied' ? 'Copied' : copiedPolicy === 'failed' ? 'Copy failed' : 'Copy'}
          </button>
        </div>
        <p style={{ fontSize: '0.72rem', color: '#64748b', marginTop: '3px' }}>
          An agent given this ID can propose and pay within your rules. Only you can approve here.
        </p>
      </div>

      {/* Announces a new request to screen readers without moving focus. */}
      <div role="status" aria-live="polite" style={visuallyHidden}>
        {announcement}
      </div>

      {loadError && (
        <p role="alert" style={{ fontSize: '0.75rem', color: '#b91c1c', marginBottom: '6px' }}>
          {loadError}
        </p>
      )}
      {actionError && (
        <p role="alert" style={{ fontSize: '0.75rem', color: '#b91c1c', marginBottom: '6px' }}>
          {actionError}
        </p>
      )}

      <h5 style={{ fontSize: '0.78rem', fontWeight: 700, color: '#0f172a', marginBottom: '4px' }}>Waiting for your approval</h5>
      {!loaded && !loadError ? (
        <p style={{ fontSize: '0.78rem', color: '#526077' }}>Loading requests…</p>
      ) : awaiting.length === 0 ? (
        <p style={{ fontSize: '0.78rem', color: '#526077' }}>
          Nothing is waiting. A request from an outside agent shows up here within a few seconds.
        </p>
      ) : (
        <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {awaiting.map((row) => {
            const label = `${describeItems(row)} for ${money(row.total_amount, row.currency)}`;
            return (
              <li
                key={row.checkout_id}
                style={{ border: '1px solid #fde68a', background: '#fffbeb', borderRadius: '6px', padding: '8px 10px' }}
              >
                <div className="wrap-sm" style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                  <strong style={{ fontSize: '0.82rem', color: '#0f172a', minWidth: 0, overflowWrap: 'anywhere' }}>{describeItems(row)}</strong>
                  <strong style={{ fontSize: '0.82rem', color: '#0070ba' }}>{money(row.total_amount, row.currency)}</strong>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', alignItems: 'center', margin: '3px 0 6px' }}>
                  <span className={`badge ${origin(row) === 'Outside agent' ? 'badge-blue' : 'badge-neutral'}`} style={{ fontSize: '0.72rem', padding: '1px 5px' }}>
                    {origin(row)}
                  </span>
                  {row.agent_id && (
                    <span className="badge badge-neutral" style={{ fontSize: '0.72rem', padding: '1px 5px' }}>{row.agent_id}</span>
                  )}
                  <span style={{ fontSize: '0.75rem', color: '#526077' }}>
                    {row.merchant}
                    {row.created_at ? ` · ${formatTimestamp(row.created_at)}` : ''}
                  </span>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'flex-start' }}>
                  <button
                    type="button"
                    onClick={() => handleApprove(row)}
                    disabled={approvingId !== null}
                    className="btn btn-primary"
                    aria-label={`Approve ${label}`}
                    style={{ padding: '6px 12px', fontSize: '0.78rem' }}
                  >
                    <CheckCircle2 size={13} aria-hidden="true" /> {approvingId === row.checkout_id ? 'Approving…' : 'Approve'}
                  </button>
                  <ApprovalLinkButton checkoutId={row.checkout_id} ownerToken={ownerToken} />
                </div>
              </li>
            );
          })}
        </ul>
      )}

      {recent.length > 0 && (
        <>
          <h5 style={{ fontSize: '0.78rem', fontWeight: 700, color: '#0f172a', margin: '10px 0 4px' }}>Recent requests</h5>
          <ul style={{ listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {recent.map((row) => {
              const badge = stateBadge(row.state);
              return (
                <li
                  key={row.checkout_id}
                  className="wrap-sm"
                  style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px', borderTop: '1px solid #f1f5f9', paddingTop: '4px' }}
                >
                  <div style={{ minWidth: 0 }}>
                    <span style={{ fontSize: '0.78rem', color: '#0f172a', overflowWrap: 'anywhere' }}>
                      {describeItems(row)} · {money(row.total_amount, row.currency)}
                    </span>
                    <span style={{ fontSize: '0.72rem', color: '#526077', display: 'block' }}>
                      {origin(row)}
                      {row.agent_id ? ` (${row.agent_id})` : ''}
                      {row.failure_reason ? ` · ${row.failure_reason}` : ''}
                    </span>
                  </div>
                  <span className={`badge ${badge.className}`} style={{ fontSize: '0.72rem', padding: '1px 6px' }}>{badge.label}</span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}
