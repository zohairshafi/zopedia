import { authFetch } from "@/features/auth";
import type { FullPeriodicConfig, PeriodicConfig, ResearchConfig, ResearchEvent } from "../types";

/**
 * Stream research events from the backend SSE endpoint.
 * Returns an AbortController for cancellation and an async generator of events.
 */
export function streamResearch(config: ResearchConfig, sessionId: string): {
  controller: AbortController;
  events: AsyncGenerator<ResearchEvent, void, unknown>;
} {
  const controller = new AbortController();

  async function* eventGenerator(): AsyncGenerator<ResearchEvent, void, unknown> {
    const response = await authFetch("/api/research/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...config, session_id: sessionId }),
      signal: controller.signal,
    });

    if (!response.ok) {
      const body = await response.text().catch(() => "");
      throw new Error(body || `Research stream failed (${response.status})`);
    }

    const reader = response.body?.getReader();
    if (!reader) throw new Error("No response body");

    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || !trimmed.startsWith("data: ")) continue;
          const data = trimmed.slice(6);
          if (data === "[DONE]") return;

          try {
            const event: ResearchEvent = JSON.parse(data);
            yield event;
          } catch {
            // Skip unparseable lines
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  }

  return { controller, events: eventGenerator() };
}

/**
 * Submit approved/rejected sources to resume the research stream.
 */
export async function approveSources(
  sessionId: string,
  approvedUrls: string[],
  rejectedUrls: string[] = [],
): Promise<void> {
  const response = await authFetch("/api/research/approve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      approved_urls: approvedUrls,
      rejected_urls: rejectedUrls,
    }),
  });

  if (!response.ok) {
    throw new Error(`Approval failed (${response.status})`);
  }
}

/**
 * Cancel a running research session.
 */
export async function cancelResearch(sessionId: string): Promise<void> {
  await authFetch("/api/research/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
}

/**
 * Create a periodic research config.
 */
export async function createPeriodicResearch(
  config: ResearchConfig,
): Promise<{ id: string; next_run_at: string }> {
  const res = await authFetch("/api/research/periodic", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!res.ok) {
    throw new Error(`Failed to create periodic research (${res.status})`);
  }
  return res.json();
}

/**
 * List all periodic configs for the current user.
 */
export async function listPeriodicResearch(): Promise<PeriodicConfig[]> {
  const res = await authFetch("/api/research/periodic");
  if (!res.ok) return [];
  const data = await res.json();
  return data.configs ?? [];
}

/**
 * Delete a periodic research config.
 */
export async function deletePeriodicResearch(id: string): Promise<void> {
  await authFetch(`/api/research/periodic/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

/**
 * Trigger immediate execution of a periodic config.
 */
export async function runPeriodicResearchNow(id: string): Promise<void> {
  await authFetch(`/api/research/periodic/${encodeURIComponent(id)}/run-now`, {
    method: "POST",
  });
}

/**
 * Get a single periodic config with full details for editing.
 */
export async function getPeriodicResearch(id: string): Promise<FullPeriodicConfig> {
  const res = await authFetch(`/api/research/periodic/${encodeURIComponent(id)}`);
  if (!res.ok) throw new Error(`Failed to get periodic research (${res.status})`);
  return res.json();
}

/**
 * Update an existing periodic research config.
 */
export async function updatePeriodicResearch(
  id: string,
  config: ResearchConfig,
): Promise<{ id: string; next_run_at: string }> {
  const res = await authFetch(`/api/research/periodic/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
  if (!res.ok) throw new Error(`Failed to update periodic research (${res.status})`);
  return res.json();
}

/**
 * Enable or disable a periodic research config.
 */
export async function togglePeriodicResearch(
  id: string,
  enabled: boolean,
): Promise<void> {
  await authFetch(`/api/research/periodic/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
}
