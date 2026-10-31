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
