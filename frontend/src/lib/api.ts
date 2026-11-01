// Backend URL resolution and fetch wrapper shared by the whole UI.

export const API_TIMEOUT_MS = 60_000;

const CONNECTION_ERROR = "Can't reach the server. Check that the backend is running, then try again.";
const TIMEOUT_ERROR =
  'The server took too long to respond. It may be waking up from sleep, so please try again in a few seconds.';

/** True for messages that mean "the request never completed", as opposed to a business refusal. */
export function isConnectionProblem(message: string | null | undefined): boolean {
  return !!message && (message.startsWith("Can't reach the server") || message.startsWith('The server took too long'));
}

export function getApiBaseUrl(): string {
  if (typeof window !== 'undefined') {
    // 1. A backend the user chose in the connection dialog
    try {
      const stored = localStorage.getItem('paypact_backend_url');
      if (stored && stored.trim()) {
        const clean = stored.trim().replace(/\/+$/, '');
        return clean.endsWith('/api') ? clean : `${clean}/api`;
      }
    } catch (_) {}

    // 2. NEXT_PUBLIC_API_URL
    const envUrl = process.env.NEXT_PUBLIC_API_URL;
    if (envUrl && envUrl.trim() && !envUrl.includes('localhost')) {
      const url =
        envUrl.trim().startsWith('http://') || envUrl.trim().startsWith('https://')
          ? envUrl.trim()
          : `https://${envUrl.trim()}`;
      return url.endsWith('/api') ? url : `${url.replace(/\/+$/, '')}/api`;
    }

    // 3. On Render, the backend service sits next to the frontend one
    const host = window.location.hostname;
    if (host.includes('.onrender.com') && host.includes('frontend')) {
      return `https://${host.replace('frontend', 'backend')}/api`;
    }

    // 4. Default: the Next.js rewrite proxies /api to the backend
    return '/api';
  }
  let url = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';
  if (url && !url.startsWith('http://') && !url.startsWith('https://')) {
    url = `https://${url}`;
  }
  if (url && !url.endsWith('/api')) {
    url = `${url.replace(/\/+$/, '')}/api`;
  }
  return url;
}

/**
 * fetch against the configured backend. It talks to one host only: if that host is down the
 * caller sees the failure (and the UI offers an explicit "connect" action) instead of the
 * request quietly going to a different server. A free-tier backend can take about a minute to
 * wake up, so the timeout is long and its message says so.
 */
export async function apiFetch(path: string, options?: RequestInit): Promise<Response> {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    return await fetch(`${getApiBaseUrl()}${normalizedPath}`, {
      ...options,
      signal: options?.signal ?? controller.signal,
    });
  } catch (err) {
    if (controller.signal.aborted) throw new Error(TIMEOUT_ERROR);
    // A failed network request surfaces as a bare TypeError ("Failed to fetch").
    if (err instanceof TypeError) throw new Error(CONNECTION_ERROR);
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/** The most useful message for a failed response: the server's reason, else `fallback`. */
export async function errorMessage(res: Response, fallback: string): Promise<string> {
  let detail: unknown;
  try {
    detail = (await res.json())?.detail;
  } catch (_) {
    return fallback;
  }
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d.msg === 'string' ? d.msg : null))
      .filter((m): m is string => !!m);
    if (msgs.length) return msgs.join('; ');
  }
  if (res.status === 429) return 'Too many requests. Please slow down and try again in a moment.';
  return fallback;
}

/** What a request asked for and the nearest catalogue item, sent with a "no match" refusal. */
export interface NoMatchInfo {
  requested: {
    kind?: string;
    origin?: string;
    destination?: string;
    travel_class?: string;
    quantity?: number;
    round_trip?: boolean;
    airline?: string;
  };
  closest: {
    sku: string;
    name: string;
    merchant: string;
    unit_price: number;
    currency: string;
    differences: string[];
  } | null;
}

/** An Error whose message is the server's reason; `noMatch` is set for a catalogue no-match. */
export class ApiError extends Error {
  noMatch?: NoMatchInfo;
}

function parseNoMatch(value: any): NoMatchInfo | undefined {
  if (!value || typeof value !== 'object' || !value.requested || typeof value.requested !== 'object') {
    return undefined;
  }
  const c = value.closest;
  const closest =
    c && typeof c === 'object' && typeof c.name === 'string'
      ? {
          sku: String(c.sku ?? ''),
          name: c.name,
          merchant: String(c.merchant ?? ''),
          unit_price: Number(c.unit_price) || 0,
          currency: String(c.currency ?? 'INR'),
          differences: Array.isArray(c.differences) ? c.differences.filter((d: unknown) => typeof d === 'string') : [],
        }
      : null;
  return { requested: value.requested, closest };
}

/** The Error for a failed /proposals call: the usual message, plus `noMatch` when the server sent one. */
export async function proposalError(res: Response, fallback: string): Promise<ApiError> {
  let noMatch: NoMatchInfo | undefined;
  try {
    const copy = typeof res.clone === 'function' ? res.clone() : res;
    noMatch = parseNoMatch((await copy.json())?.no_match);
  } catch (_) {
    noMatch = undefined;
  }
  const err = new ApiError(await errorMessage(res, fallback));
  if (noMatch) err.noMatch = noMatch;
  return err;
}

/**
 * A capture call can succeed over HTTP while the backend refuses the payment (for example the
 * policy was revoked while the PayPal window was open). Only a PAID session is a success.
 */
export function assertPaid(session: { state?: string; failure_reason?: string | null } | undefined) {
  if (session?.state === 'PAID') return;
  throw new Error(session?.failure_reason || 'The payment did not complete.');
}

// ---------------------------------------------------------------------------
// Owner token. Registering a policy returns it once; only the policy's owner may approve,
// revoke, mint approval links or list the policy's checkouts. The agent never sees it.
// ---------------------------------------------------------------------------

export const OWNER_TOKEN_HEADER = 'X-Owner-Token';

const OWNER_TOKEN_KEY = (policyId: string) => `paypact_owner_token:${policyId}`;

/** Remember the owner token for this tab's session so a refresh of the page state can find it. */
export function saveOwnerToken(policyId: string, token: string): void {
  try {
    sessionStorage.setItem(OWNER_TOKEN_KEY(policyId), token);
  } catch (_) {}
}

export function loadOwnerToken(policyId: string): string | null {
  try {
    return sessionStorage.getItem(OWNER_TOKEN_KEY(policyId));
  } catch (_) {
    return null;
  }
}

export function ownerHeaders(token: string | null | undefined, extra?: Record<string, string>): Record<string, string> {
  return token ? { ...extra, [OWNER_TOKEN_HEADER]: token } : { ...extra };
}

export const MISSING_OWNER_TOKEN =
  'This browser does not hold the owner token for this policy, so it cannot approve or revoke. Register the policy again from this page.';

/** Approve a checkout as the policy owner. Throws with the server's reason on refusal. */
export async function approveCheckout(checkoutId: string, ownerToken: string | null | undefined, userId = 'usr_shopper') {
  if (!ownerToken) throw new Error(MISSING_OWNER_TOKEN);
  const res = await apiFetch(`/checkouts/${checkoutId}/approve`, {
    method: 'POST',
    headers: ownerHeaders(ownerToken, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({ user_id: userId }),
  });
  if (!res.ok) throw new Error(await errorMessage(res, 'Approval failed.'));
  return res.json();
}

/** Revoke a policy as its owner. Throws with the server's reason on refusal. */
export async function revokePolicyRequest(policyId: string, ownerToken: string | null | undefined) {
  if (!ownerToken) throw new Error(MISSING_OWNER_TOKEN);
  const res = await apiFetch(`/authorizations/${policyId}/revoke`, {
    method: 'POST',
    headers: ownerHeaders(ownerToken),
  });
  if (!res.ok) throw new Error(await errorMessage(res, 'Could not revoke the policy.'));
  return res.json();
}

/** Mint a one-time approval link (30 minutes, bound to this exact proposal). */
export async function createApprovalLink(
  checkoutId: string,
  ownerToken: string | null | undefined,
): Promise<{ approval_url: string; expires_at: string }> {
  if (!ownerToken) throw new Error(MISSING_OWNER_TOKEN);
  const res = await apiFetch(`/checkouts/${checkoutId}/approval-link`, {
    method: 'POST',
    headers: ownerHeaders(ownerToken),
  });
  if (!res.ok) throw new Error(await errorMessage(res, 'Could not create an approval link.'));
  return res.json();
}

export interface PolicyCheckout {
  checkout_id: string;
  state: string;
  agent_id?: string | null;
  merchant: string;
  items: { sku: string; name: string; quantity: number; unit_price: number }[];
  total_amount: number;
  currency: string;
  created_at?: string | null;
  failure_reason?: string | null;
}

/** Every checkout under the policy, newest first (the owner's inbox of agent requests). */
export async function listPolicyCheckouts(
  policyId: string,
  ownerToken: string | null | undefined,
  signal?: AbortSignal,
): Promise<PolicyCheckout[]> {
  if (!ownerToken) throw new Error(MISSING_OWNER_TOKEN);
  const res = await apiFetch(`/authorizations/${policyId}/checkouts`, {
    headers: ownerHeaders(ownerToken),
    signal,
  });
  if (!res.ok) {
    const err = new Error(await errorMessage(res, 'Could not load agent requests.')) as Error & { status?: number };
    err.status = res.status;
    throw err;
  }
  return res.json();
}
