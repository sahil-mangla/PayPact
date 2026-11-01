'use client';

import React, { useState } from 'react';
import { Link2 } from 'lucide-react';

import { createApprovalLink } from '../lib/api';
import { formatTimestamp } from '../lib/format';

/**
 * Mints a one-time approval link for a checkout and copies it. The link lets the owner approve
 * from another device (it is not an agent credential), so it is shown in full if the clipboard
 * is unavailable.
 */
export function ApprovalLinkButton({
  checkoutId,
  ownerToken,
  disabled,
  style,
}: {
  checkoutId: string;
  ownerToken: string | null;
  disabled?: boolean;
  style?: React.CSSProperties;
}) {
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [fallbackUrl, setFallbackUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  const handleClick = async () => {
    setBusy(true);
    setStatus(null);
    setFallbackUrl(null);
    setFailed(false);
    try {
      const link = await createApprovalLink(checkoutId, ownerToken);
      const expiry = link.expires_at ? ` Expires ${formatTimestamp(link.expires_at)} and works once.` : ' Works once.';
      try {
        await navigator.clipboard.writeText(link.approval_url);
        setStatus(`Approval link copied.${expiry}`);
      } catch (_) {
        setFallbackUrl(link.approval_url);
        setStatus(`Could not copy automatically. Copy the link below.${expiry}`);
      }
    } catch (err: any) {
      setFailed(true);
      setStatus(err?.message || 'Could not create an approval link.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', minWidth: 0, ...style }}>
      <button
        type="button"
        onClick={handleClick}
        disabled={busy || disabled || !ownerToken}
        className="btn btn-secondary"
        aria-label={`Copy approval link for checkout ${checkoutId}`}
        style={{ padding: '6px 12px', fontSize: '0.78rem' }}
      >
        <Link2 size={13} aria-hidden="true" /> {busy ? 'Creating link…' : 'Copy approval link'}
      </button>
      <div role="status" aria-live="polite" style={{ fontSize: '0.75rem', color: failed ? '#b91c1c' : '#526077' }}>
        {status}
      </div>
      {fallbackUrl && (
        <input
          type="text"
          readOnly
          value={fallbackUrl}
          aria-label="Approval link"
          onFocus={(e) => e.currentTarget.select()}
          style={{
            width: '100%',
            fontSize: '0.75rem',
            fontFamily: 'JetBrains Mono, monospace',
            padding: '4px 6px',
            border: '1px solid #cbd5e1',
            borderRadius: '6px',
          }}
        />
      )}
    </div>
  );
}
