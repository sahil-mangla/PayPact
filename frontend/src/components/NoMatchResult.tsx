'use client';

import React from 'react';
import { SearchX } from 'lucide-react';

import type { NoMatchInfo } from '../lib/api';
import { money } from '../lib/decision';

const cap = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** One short chip per thing the request asked for; nothing for what it did not say. */
export function requestedChips(r: NoMatchInfo['requested']): string[] {
  const chips: string[] = [];
  if (r.travel_class) chips.push(cap(r.travel_class));
  if (r.kind) chips.push(cap(r.kind));
  if (r.origin && r.destination) chips.push(`${r.origin} to ${r.destination}`);
  else if (r.destination) chips.push(`${r.kind === 'flight' ? 'To' : 'In'} ${r.destination}`);
  else if (r.origin) chips.push(`From ${r.origin}`);
  if (r.quantity) chips.push(`Quantity ${r.quantity}`);
  if (r.round_trip) chips.push('Round trip');
  if (r.airline) chips.push(r.airline);
  return chips;
}

/**
 * The right-panel result when nothing in the catalogue matches the request. It is one
 * status region so a screen reader announces it once; the closest item is shown for
 * context only and is deliberately not offered as something to buy.
 */
export function NoMatchResult({ info }: { info: NoMatchInfo }) {
  const chips = requestedChips(info.requested);
  const closest = info.closest;
  const label: React.CSSProperties = { fontSize: '0.72rem', fontWeight: 700, color: '#526077', margin: '0 0 6px' };

  return (
    <div
      role="status"
      data-testid="no-match-result"
      className="clean-card"
      style={{ padding: '22px 18px', minHeight: '380px', color: '#334155', overflowWrap: 'anywhere' }}
    >
      <div style={{ textAlign: 'center', marginBottom: '14px' }}>
        <SearchX size={34} strokeWidth={1.3} aria-hidden="true" style={{ margin: '0 auto 8px', color: '#94a3b8' }} />
        <h3 style={{ fontSize: '0.96rem', color: '#0f172a', marginBottom: '4px' }}>No matching item</h3>
        <p style={{ fontSize: '0.77rem', margin: 0 }}>Nothing was proposed and nothing was charged.</p>
      </div>

      {chips.length > 0 && (
        <div style={{ marginBottom: '14px' }}>
          <h4 style={label}>You asked for</h4>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
            {chips.map((chip) => (
              <li key={chip} style={{ fontSize: '0.74rem', fontWeight: 600, color: '#0369a1', background: '#e0f2fe', borderRadius: '999px', padding: '3px 10px' }}>
                {chip}
              </li>
            ))}
          </ul>
        </div>
      )}

      {closest && (
        <div style={{ marginBottom: '14px' }}>
          <h4 style={label}>Closest in the catalogue</h4>
          <div style={{ border: '1px solid #e2e8f0', borderRadius: '10px', padding: '10px 12px', background: '#f8fafc' }}>
            <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#0f172a' }}>{closest.name}</div>
            <div style={{ fontSize: '0.74rem', color: '#526077', marginTop: '2px' }}>
              {closest.merchant} · {money(closest.unit_price, closest.currency)}
            </div>
            {closest.differences.length > 0 && (
              <div style={{ marginTop: '8px' }}>
                <div style={{ ...label, margin: '0 0 3px' }}>What differs</div>
                <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '0.76rem' }}>
                  {closest.differences.map((d) => (
                    <li key={d}>{d}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
          <p style={{ fontSize: '0.72rem', color: '#526077', margin: '6px 0 0' }}>
            This is the nearest item, shown for comparison. It does not meet your request.
          </p>
        </div>
      )}

      <p style={{ fontSize: '0.77rem', margin: 0 }}>
        Change the request (for example the destination) or switch the agent, then generate again.
      </p>
    </div>
  );
}
