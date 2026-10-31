import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  apiFetch,
  API_TIMEOUT_MS,
  approveCheckout,
  createApprovalLink,
  getApiBaseUrl,
  isConnectionProblem,
  listPolicyCheckouts,
  loadOwnerToken,
  MISSING_OWNER_TOKEN,
  ownerHeaders,
  revokePolicyRequest,
  saveOwnerToken,
} from '../lib/api';

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

    await expect(apiFetch('/health')).rejects.toThrow(/can't reach the server/i);

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


describe('isConnectionProblem', () => {
  it('recognises network and timeout failures but not business refusals', () => {
    expect(isConnectionProblem("Can't reach the server. Check that the backend is running.")).toBe(true);
    expect(isConnectionProblem('The server took too long to respond. It may be waking up.')).toBe(true);
    expect(isConnectionProblem('Exceeds maximum authorized budget (4699.00 > 3000.00).')).toBe(false);
  });
});


describe('owner token', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  const okJson = (body: unknown) =>
    new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });

  it('sends X-Owner-Token when approving', async () => {
    const fetchMock = vi.fn().mockResolvedValue(okJson({ state: 'AUTHORIZED' }));
    global.fetch = fetchMock as unknown as typeof fetch;

    await approveCheckout('chk_1', 'otok');

    expect(String(fetchMock.mock.calls[0][0])).toContain('/checkouts/chk_1/approve');
    const headers = fetchMock.mock.calls[0][1].headers;
    expect(headers['X-Owner-Token']).toBe('otok');
    expect(headers['Content-Type']).toBe('application/json');
  });

  it('sends X-Owner-Token when revoking and minting a link', async () => {
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(okJson({ approval_url: 'u', expires_at: 'e', status: 'revoked' })));
    global.fetch = fetchMock as unknown as typeof fetch;

    await revokePolicyRequest('pol_1', 'otok');
    await createApprovalLink('chk_1', 'otok');
    await listPolicyCheckouts('pol_1', 'otok');

    const urls = fetchMock.mock.calls.map((c) => String(c[0]));
    expect(urls[0]).toContain('/authorizations/pol_1/revoke');
    expect(urls[1]).toContain('/checkouts/chk_1/approval-link');
    expect(urls[2]).toContain('/authorizations/pol_1/checkouts');
    for (const call of fetchMock.mock.calls) {
      expect(call[1].headers['X-Owner-Token']).toBe('otok');
    }
  });

  it('refuses to call the server at all without a token', async () => {
    const fetchMock = vi.fn();
    global.fetch = fetchMock as unknown as typeof fetch;

    await expect(approveCheckout('chk_1', null)).rejects.toThrow(MISSING_OWNER_TOKEN);
    await expect(revokePolicyRequest('pol_1', undefined)).rejects.toThrow(MISSING_OWNER_TOKEN);
    await expect(createApprovalLink('chk_1', '')).rejects.toThrow(MISSING_OWNER_TOKEN);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('surfaces the server reason when the token is refused', async () => {
    global.fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ detail: 'Invalid owner token for this policy.' }), { status: 403 }),
      ) as unknown as typeof fetch;
    await expect(approveCheckout('chk_1', 'bad')).rejects.toThrow('Invalid owner token for this policy.');
  });

  it('tags a failed list with its status so the UI can tell 403 from a network blip', async () => {
    global.fetch = vi.fn().mockResolvedValue(new Response('{}', { status: 403 })) as unknown as typeof fetch;
    await expect(listPolicyCheckouts('pol_1', 'bad')).rejects.toMatchObject({ status: 403 });
  });

  it('keeps the token in sessionStorage and survives storage that throws', () => {
    sessionStorage.clear();
    saveOwnerToken('pol_1', 'otok');
    expect(loadOwnerToken('pol_1')).toBe('otok');
    expect(loadOwnerToken('pol_other')).toBeNull();

    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(() => saveOwnerToken('pol_2', 'x')).not.toThrow();
    expect(loadOwnerToken('pol_2')).toBeNull();
  });

  it('ownerHeaders leaves the header off when there is no token', () => {
    expect(ownerHeaders(null)).toEqual({});
    expect(ownerHeaders('t', { A: 'b' })).toEqual({ A: 'b', 'X-Owner-Token': 't' });
  });
});
