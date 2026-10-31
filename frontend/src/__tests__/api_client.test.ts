import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { apiFetch, API_TIMEOUT_MS, getApiBaseUrl } from '../lib/api';

describe('apiFetch', () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('never silently retries a different host after a network error', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    global.fetch = fetchMock as unknown as typeof fetch;

    await expect(apiFetch('/health')).rejects.toThrow('Failed to fetch');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).not.toContain('onrender.com');
    expect(localStorage.getItem('paypact_backend_url')).toBeNull();
  });

  it('returns a 5xx response as is instead of rerouting the request', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('down', { status: 503 }));
    global.fetch = fetchMock as unknown as typeof fetch;

    const res = await apiFetch('/proposals', { method: 'POST' });

    expect(res.status).toBe(503);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(localStorage.getItem('paypact_backend_url')).toBeNull();
  });

  it('gives up after the timeout with a message that explains a cold start', async () => {
    vi.useFakeTimers();
    global.fetch = vi.fn().mockImplementation(
      (_url: string, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () =>
            reject(new DOMException('aborted', 'AbortError')),
          );
        }),
    ) as unknown as typeof fetch;

    const pending = apiFetch('/health');
    const assertion = expect(pending).rejects.toThrow(/waking up|too long/i);
    await vi.advanceTimersByTimeAsync(API_TIMEOUT_MS + 10);
    await assertion;
  });

  it('honours a backend URL the user configured', () => {
    localStorage.setItem('paypact_backend_url', 'https://my-backend.example.com/');
    expect(getApiBaseUrl()).toBe('https://my-backend.example.com/api');
  });
});

import { errorMessage, assertPaid } from '../lib/api';

describe('errorMessage', () => {
  it('uses the server-provided reason', async () => {
    const res = new Response(JSON.stringify({ detail: 'No catalogue item matches this request.' }), {
      status: 400,
    });
    expect(await errorMessage(res, 'fallback')).toBe('No catalogue item matches this request.');
  });

  it('flattens validation errors instead of printing [object Object]', async () => {
    const res = new Response(
      JSON.stringify({ detail: [{ loc: ['body', 'prompt'], msg: 'String should have at most 500 characters' }] }),
      { status: 422 },
    );
    const msg = await errorMessage(res, 'fallback');
    expect(msg).toContain('at most 500 characters');
    expect(msg).not.toContain('[object');
  });

  it('explains rate limiting in plain words', async () => {
    const res = new Response('{"detail":"Too many requests."}', { status: 429 });
    expect(await errorMessage(res, 'fallback')).toMatch(/too many requests|slow down/i);
  });

  it('falls back when the body is not JSON (e.g. a proxy error page)', async () => {
    const res = new Response('<html>Bad gateway</html>', { status: 502 });
    expect(await errorMessage(res, 'Could not parse purchase goal.')).toBe(
      'Could not parse purchase goal.',
    );
  });
});

describe('assertPaid', () => {
  it('accepts a paid session', () => {
    expect(() => assertPaid({ state: 'PAID' })).not.toThrow();
  });

  it('turns a capture the backend refused into an error with its reason', () => {
    expect(() =>
      assertPaid({ state: 'POLICY_REJECTED', failure_reason: 'Policy is revoked.' }),
    ).toThrow('Policy is revoked.');
    expect(() => assertPaid({ state: 'FAILED' })).toThrow(/did not complete/i);
  });
});
