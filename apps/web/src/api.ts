const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export type Health = {
  ok: boolean;
  warehouse_exists: boolean;
  warehouse_path: string;
  table_counts: Record<string, number>;
};

export type TableResponse = {
  name: string;
  total: number;
  limit: number;
  offset: number;
  rows: Record<string, unknown>[];
};

export type CommandStatus = {
  run_id: string;
  name: string;
  status: "running" | "succeeded" | "failed";
  started_at_utc: string;
  finished_at_utc: string | null;
  returncode: number | null;
  log_path: string;
  log: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status} ${detail}`);
  }
  return response.json() as Promise<T>;
}

export function getHealth() {
  return request<Health>("/health");
}

export function getTable(
  name: string,
  limit = 100,
  offset = 0,
  filters: { source?: string; promotion?: string } = {},
) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (filters.source) params.set("source", filters.source);
  if (filters.promotion) params.set("promotion", filters.promotion);
  return request<TableResponse>(`/tables/${name}?${params.toString()}`);
}

export function startCommand(name: string) {
  return request<{ run_id: string; status: string }>(`/commands/${name}`, { method: "POST" });
}

export function getCommand(runId: string) {
  return request<CommandStatus>(`/commands/${runId}`);
}
