import { afterEach, describe, expect, it, vi } from 'vitest';
import { generateIdempotencyKey } from './idempotency';

describe('generateIdempotencyKey', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it('uses crypto.randomUUID when available', () => {
    const randomUUID = vi.fn(() => 'generated-uuid');
    vi.stubGlobal('crypto', { randomUUID });

    expect(generateIdempotencyKey()).toBe('generated-uuid');
    expect(randomUUID).toHaveBeenCalledOnce();
  });

  it('falls back when crypto.randomUUID is unavailable', () => {
    vi.stubGlobal('crypto', {});
    vi.spyOn(Date, 'now').mockReturnValue(1234567890);
    vi.spyOn(Math, 'random').mockReturnValue(0.25);

    expect(generateIdempotencyKey()).toBe('1234567890-0.25');
  });
});
