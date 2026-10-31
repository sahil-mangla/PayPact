// Backend URL resolution and fetch wrapper shared by the whole UI.

export const API_TIMEOUT_MS = 60_000;

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
    if (controller.signal.aborted) {
      throw new Error(
        'The server took too long to respond. It may be waking up from sleep, so please try again in a few seconds.',
      );
    }
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

/**
 * A capture call can succeed over HTTP while the backend refuses the payment (for example the
 * policy was revoked while the PayPal window was open). Only a PAID session is a success.
 */
export function assertPaid(session: { state?: string; failure_reason?: string | null } | undefined) {
  if (session?.state === 'PAID') return;
  throw new Error(session?.failure_reason || 'The payment did not complete.');
}
