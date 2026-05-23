const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

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

export type IdentityCandidate = {
  target_source_fighter_id: string;
  target_canonical_fighter_id: string;
  full_name: string;
  dob: string | null;
  url: string | null;
  candidate_reason: string;
  manual_decision: string | null;
  manual_note: string | null;
  fight_count: number | null;
  ufc_fight_count: number | null;
  sherdog_fight_count: number | null;
  first_fight_date: string | null;
  last_fight_date: string | null;
};

export type IdentityCandidateResponse = {
  source_fighter: Record<string, unknown>;
  review_row: Record<string, unknown>;
  suggestions: IdentityCandidate[];
  search_results: IdentityCandidate[];
  rejected_pairs: Record<string, unknown>[];
};

export type IdentityDecisionRequest = {
  source?: "sherdog";
  source_fighter_id: string;
  target_source?: "ufcstats";
  target_source_fighter_id?: string;
  decision: "approved" | "rejected" | "accepted_unresolved";
  note?: string;
  apply?: boolean;
};

export type IdentityDecisionResponse = {
  source: string;
  source_fighter_id: string;
  target_source: string;
  target_source_fighter_id: string;
  decision: string;
  note: string | null;
  apply_status: "started" | "blocked" | "skipped";
  run_id: string | null;
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
  filters: Record<string, string | undefined> = {},
) {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  for (const [key, value] of Object.entries(filters)) {
    if (value) params.set(key, value);
  }
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

export function getIdentityReview(
  filters: {
    source?: string;
    review_status?: string;
    has_candidate?: string;
    decision_status?: string;
  } = {},
) {
  const params = new URLSearchParams();
  if (filters.source) params.set("source", filters.source);
  if (filters.review_status) params.set("review_status", filters.review_status);
  if (filters.has_candidate) params.set("has_candidate", filters.has_candidate);
  if (filters.decision_status) params.set("decision_status", filters.decision_status);
  return request<TableResponse>(`/identity/review?${params.toString()}`);
}

export function getIdentityCandidates(sourceFighterId: string, q = "") {
  const params = new URLSearchParams({ source_fighter_id: sourceFighterId });
  if (q) params.set("q", q);
  return request<IdentityCandidateResponse>(`/identity/candidates?${params.toString()}`);
}

export function saveIdentityDecision(body: IdentityDecisionRequest) {
  return request<IdentityDecisionResponse>("/identity/decisions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function clearIdentityDecision(
  sourceFighterId: string,
  targetSourceFighterId?: string,
  apply = true,
) {
  const params = new URLSearchParams({
    source: "sherdog",
    source_fighter_id: sourceFighterId,
    target_source: "ufcstats",
    apply: String(apply),
  });
  if (targetSourceFighterId) {
    params.set("target_source_fighter_id", targetSourceFighterId);
  }
  return request<IdentityDecisionResponse>(`/identity/decisions?${params.toString()}`, {
    method: "DELETE",
  });
}
