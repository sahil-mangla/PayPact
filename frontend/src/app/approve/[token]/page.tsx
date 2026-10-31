'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { CheckCircle2, ShieldAlert, ShieldCheck } from 'lucide-react';

import { apiFetch, errorMessage, isConnectionProblem } from '../../../lib/api';
import { formatTimestamp } from '../../../lib/format';

interface ApprovalSummary {
  checkout_id: string;
  state: string;
  merchant: string;
  items: { sku: string; name: string; quantity: number; unit_price: number }[];
  item_subtotal: number;
  shipping_fee: number;
  tax_fee: number;
  total_amount: number;
  currency: string;
  agent_id?: string | null;
  decision: string;
  reasons: string[];
  expires_at: string;
}

type View =
  | { kind: 'loading' }
  | { kind: 'ready'; summary: ApprovalSummary }
  | { kind: 'approving'; summary: ApprovalSummary }
  | { kind: 'approved'; summary: ApprovalSummary }
  | { kind: 'problem'; title: string; message: string; retry?: boolean };

function money(amount: number, currency: string): string {
  const symbol = currency === 'USD' ? '$' : currency === 'INR' ? '₹' : `${currency} `;
  return `${symbol}${amount.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 })}`;
}

/** Turn a failed response into a plain-words problem the owner can act on. */
async function problemFrom(res: Response): Promise<View> {
  const detail = await errorMessage(res, '');
  if (res.status === 404) {
    return {
      kind: 'problem',
      title: 'This link is not valid',
      message: detail || 'We do not recognise this approval link. Check that you copied all of it, or ask for a new one.',
    };
  }
  if (res.status === 410) {
    return {
      kind: 'problem',
      title: 'This link can no longer be used',
      message: detail || 'It has expired, has already been used, or the purchase no longer needs approval. Create a new link from the dashboard if you still want to approve.',
    };
  }
  if (res.status === 409) {
    return {
      kind: 'problem',
      title: 'The purchase changed',
      message: detail || 'The purchase no longer matches what this link was created for, so it was not approved. Review the new request in the dashboard.',
    };
  }
  if (res.status === 429) {
    return { kind: 'problem', title: 'Too many attempts', message: detail || 'Please wait a moment and try again.', retry: true };
  }
  return { kind: 'problem', title: 'Something went wrong', message: detail || 'The server could not handle this request. Please try again.', retry: true };
}

export default function ApprovePage({ params }: { params: { token: string } }) {
  const token = params.token;
  const [view, setView] = useState<View>({ kind: 'loading' });
  const headingRef = useRef<HTMLHeadingElement | null>(null);

  const path = `/approvals/${encodeURIComponent(token)}`;

  const load = useCallback(async () => {
    setView({ kind: 'loading' });
    try {
      const res = await apiFetch(path);
      if (!res.ok) {
        setView(await problemFrom(res));
        return;
      }
      setView({ kind: 'ready', summary: await res.json() });
    } catch (err: any) {
      setView({
        kind: 'problem',
        title: isConnectionProblem(err?.message) ? 'Cannot reach PayPact' : 'Something went wrong',
        message: err?.message || 'Please try again.',
        retry: true,
      });
    }
  }, [path]);

  useEffect(() => {
    load();
  }, [load]);

  // After the view changes to a result, bring the heading into focus so screen readers read it.
  useEffect(() => {
    if (view.kind === 'approved' || view.kind === 'problem') headingRef.current?.focus();
  }, [view.kind]);

  const approve = async () => {
    if (view.kind !== 'ready') return;
    const summary = view.summary;
    setView({ kind: 'approving', summary });
    try {
      const res = await apiFetch(path, { method: 'POST' });
      if (!res.ok) {
        setView(await problemFrom(res));
        return;
      }
      setView({ kind: 'approved', summary });
    } catch (err: any) {
      setView({ kind: 'problem', title: 'Approval did not go through', message: err?.message || 'Please try again.', retry: true });
    }
  };

  const summary = view.kind === 'ready' || view.kind === 'approving' || view.kind === 'approved' ? view.summary : null;

  return (
    <main style={{ maxWidth: '560px', margin: '0 auto', padding: '24px 16px 48px' }}>
      <p style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.85rem', fontWeight: 700, color: '#003087', marginBottom: '12px' }}>
        <ShieldCheck size={16} aria-hidden="true" /> PayPact
      </p>

      <div className="clean-card" style={{ padding: '18px 18px 20px' }}>
        {/* Status messages are announced as they change. */}
        <div role="status" aria-live="polite" style={{ minHeight: view.kind === 'loading' ? '1.5em' : 0 }}>
          {view.kind === 'loading' && <span style={{ fontSize: '0.85rem', color: '#526077' }}>Loading the purchase…</span>}
          {view.kind === 'approving' && <span style={{ fontSize: '0.85rem', color: '#526077' }}>Approving…</span>}
        </div>

        {view.kind === 'problem' && (
          <div role="alert">
            <h1
              ref={headingRef}
              tabIndex={-1}
              style={{ fontSize: '1.15rem', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}
            >
              <ShieldAlert size={20} color="#b91c1c" aria-hidden="true" /> {view.title}
            </h1>
            <p style={{ fontSize: '0.88rem', color: '#475569' }}>{view.message}</p>
            {view.retry && (
              <button type="button" onClick={load} className="btn btn-secondary" style={{ marginTop: '12px' }}>
                Try again
              </button>
            )}
          </div>
        )}

        {view.kind === 'approved' && (
          <div>
            <h1
              ref={headingRef}
              tabIndex={-1}
              style={{ fontSize: '1.15rem', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}
            >
              <CheckCircle2 size={20} color="#059669" aria-hidden="true" /> Purchase approved
            </h1>
            <p style={{ fontSize: '0.88rem', color: '#475569' }}>
              You approved {money(view.summary.total_amount, view.summary.currency)} at {view.summary.merchant}. This link cannot be used
              again. The payment is checked once more against exactly what you approved before any money moves.
            </p>
          </div>
        )}

        {summary && view.kind !== 'approved' && (
          <div>
            <h1 style={{ fontSize: '1.15rem', marginBottom: '4px' }}>Approve this purchase?</h1>
            <p style={{ fontSize: '0.85rem', color: '#526077', marginBottom: '14px' }}>
              {summary.agent_id ? `The agent ${summary.agent_id} asked` : 'An agent asked'} to buy from <strong>{summary.merchant}</strong>.
            </p>

            <h2 style={{ fontSize: '0.85rem', marginBottom: '6px' }}>Items</h2>
            <ul style={{ listStyle: 'none', marginBottom: '10px' }}>
              {summary.items.map((item) => (
                <li
                  key={item.sku}
                  style={{ display: 'flex', justifyContent: 'space-between', gap: '12px', fontSize: '0.88rem', padding: '4px 0', borderTop: '1px solid #f1f5f9' }}
                >
                  <span style={{ minWidth: 0, overflowWrap: 'anywhere' }}>
                    {item.name} <span style={{ color: '#526077' }}>× {item.quantity}</span>
                  </span>
                  <span>{money(item.unit_price * item.quantity, summary.currency)}</span>
                </li>
              ))}
            </ul>

            <dl style={{ fontSize: '0.85rem', display: 'grid', gridTemplateColumns: '1fr auto', gap: '3px 0', marginBottom: '8px' }}>
              <dt style={{ color: '#526077' }}>Subtotal</dt>
              <dd style={{ textAlign: 'right', paddingLeft: '12px' }}>{money(summary.item_subtotal, summary.currency)}</dd>
              <dt style={{ color: '#526077' }}>Shipping</dt>
              <dd style={{ textAlign: 'right', paddingLeft: '12px' }}>{money(summary.shipping_fee, summary.currency)}</dd>
              <dt style={{ color: '#526077' }}>Tax</dt>
              <dd style={{ textAlign: 'right', paddingLeft: '12px' }}>{money(summary.tax_fee, summary.currency)}</dd>
              <dt style={{ fontWeight: 700, borderTop: '1px solid #e2e8f0', paddingTop: '6px' }}>Total</dt>
              <dd style={{ textAlign: 'right', paddingLeft: '12px', fontWeight: 700, fontSize: '1.05rem', color: '#0070ba', borderTop: '1px solid #e2e8f0', paddingTop: '6px' }}>
                {money(summary.total_amount, summary.currency)} {summary.currency}
              </dd>
            </dl>

            {summary.reasons.length > 0 && (
              <div style={{ background: '#fffbeb', border: '1px solid #fde68a', borderRadius: '6px', padding: '8px 10px', marginBottom: '12px' }}>
                <h2 style={{ fontSize: '0.8rem', marginBottom: '3px' }}>Why your approval is needed</h2>
                <ul style={{ fontSize: '0.82rem', color: '#475569', paddingLeft: '18px' }}>
                  {summary.reasons.map((reason, i) => (
                    <li key={i}>{reason}</li>
                  ))}
                </ul>
              </div>
            )}

            <p style={{ fontSize: '0.78rem', color: '#526077', marginBottom: '12px' }}>
              This link expires {formatTimestamp(summary.expires_at)} and works once. Approve only if you recognise this purchase.
            </p>

            <button
              type="button"
              onClick={approve}
              disabled={view.kind === 'approving'}
              className="btn btn-primary"
              aria-label={`Approve purchase of ${money(summary.total_amount, summary.currency)} at ${summary.merchant}`}
              style={{ width: '100%', padding: '11px 18px' }}
            >
              <CheckCircle2 size={16} aria-hidden="true" /> {view.kind === 'approving' ? 'Approving…' : 'Approve purchase'}
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
