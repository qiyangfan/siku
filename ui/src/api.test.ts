import { afterEach, describe, expect, it, vi } from "vitest";
import { checkHealth } from "./api";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("健康检查 API", () => {
  it("健康请求超时后会中止网络请求", async () => {
    vi.useFakeTimers();
    const fetchStub = vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener(
          "abort",
          () => reject(new DOMException("Request timed out", "AbortError")),
          { once: true },
        );
      }),
    );
    vi.stubGlobal("fetch", fetchStub);

    const request = checkHealth();
    const rejection = expect(request).rejects.toMatchObject({ name: "AbortError" });
    await vi.advanceTimersByTimeAsync(3_000);

    await rejection;
    expect(fetchStub).toHaveBeenCalledWith(
      "/api/health",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(vi.getTimerCount()).toBe(0);
  });
});
