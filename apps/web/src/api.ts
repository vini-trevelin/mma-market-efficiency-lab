const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export type Health = {
  ok: boolean;
  warehouse_exists: boolean;
  warehouse_path: string;
  table_counts: Record<string, number>;
};

export type TableResponse = {
  name: string;
  exists?: boolean;
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

export function getAuditSummary() {
  return request<TableResponse>("/audit/summary");
}

export function getAuditChecks(filters: { status?: string; table_name?: string } = {}) {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.table_name) params.set("table_name", filters.table_name);
  return request<TableResponse>(`/audit/checks?${params.toString()}`);
}

export function getAuditCoverage(filters: { source?: string; promotion?: string } = {}) {
  const params = new URLSearchParams();
  if (filters.source) params.set("source", filters.source);
  if (filters.promotion) params.set("promotion", filters.promotion);
  return request<TableResponse>(`/audit/coverage?${params.toString()}`);
}

export function getAuditIdentity(filters: { source?: string; link_method?: string } = {}) {
  const params = new URLSearchParams();
  if (filters.source) params.set("source", filters.source);
  if (filters.link_method) params.set("link_method", filters.link_method);
  return request<TableResponse>(`/audit/identity?${params.toString()}`);
}

export function getAuditQuarantine(filters: { reason?: string; promotion?: string } = {}) {
  const params = new URLSearchParams();
  if (filters.reason) params.set("reason", filters.reason);
  if (filters.promotion) params.set("promotion", filters.promotion);
  return request<TableResponse>(`/audit/quarantine?${params.toString()}`);
}
