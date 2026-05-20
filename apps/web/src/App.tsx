import {
  AlertTriangle,
  Database,
  Play,
  RefreshCw,
  Search,
  ShieldCheck,
  Table2,
  Terminal,
  UserRound,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  getAuditChecks,
  getAuditCoverage,
  getAuditIdentity,
  getAuditQuarantine,
  getAuditSummary,
  getCommand,
  getHealth,
  getTable,
  startCommand,
  type CommandStatus,
  type Health,
  type TableResponse,
} from "./api";
import { Button } from "./components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";

const TABLES = [
  "events",
  "fights",
  "fight_participants",
  "fighters",
  "fighter_fight_stats",
  "source_events",
  "source_fights",
  "source_fight_participants",
  "source_fighters",
  "fighter_identity_links",
  "parse_quarantine",
  "pit_fighter_features",
  "pit_matchup_features",
  "warehouse_quality",
  "audit_summary",
  "audit_checks",
  "audit_coverage",
  "audit_missingness",
  "audit_identity",
  "audit_pit",
];

const COMMANDS = [
  "download-ufcstats",
  "download-sherdog",
  "parse-ufcstats",
  "parse-sherdog",
  "build-warehouse",
  "build-features",
  "validate-warehouse",
  "make-reports",
  "full-pipeline",
  "full-pipeline-sherdog-major",
];

type Tab = "overview" | "coverage" | "quality" | "identity" | "quarantine" | "tables" | "commands";
const RUN_IDS_KEY = "mma_eff_lab_command_run_ids";

export function App() {
  const [tab, setTab] = useState<Tab>(() => (getUrlParam("tab") as Tab) || "overview");
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  async function refreshHealth() {
    try {
      setHealth(await getHealth());
      setHealthError(null);
    } catch (error) {
      setHealthError(error instanceof Error ? error.message : String(error));
    }
  }

  function changeTab(value: string) {
    const next = value as Tab;
    setTab(next);
    setUrlParam("tab", next);
  }

  useEffect(() => {
    void refreshHealth();
  }, []);

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <h1>MMA Market Efficiency Lab</h1>
          <p>Local MMA warehouse audit and point-in-time feature inspection.</p>
        </div>
        <Button variant="outline" size="icon" onClick={refreshHealth} aria-label="Refresh health">
          <RefreshCw size={18} />
        </Button>
      </header>

      <Tabs value={tab} onValueChange={changeTab}>
        <TabsList variant="line" aria-label="Primary">
          <TabTrigger value="overview" icon={<Database size={16} />} label="Overview" />
          <TabTrigger value="coverage" icon={<Search size={16} />} label="Coverage" />
          <TabTrigger value="quality" icon={<ShieldCheck size={16} />} label="Quality" />
          <TabTrigger value="identity" icon={<UserRound size={16} />} label="Identity" />
          <TabTrigger value="quarantine" icon={<AlertTriangle size={16} />} label="Quarantine" />
          <TabTrigger value="tables" icon={<Table2 size={16} />} label="Tables" />
          <TabTrigger value="commands" icon={<Terminal size={16} />} label="Commands" />
        </TabsList>
        <TabsContent value="overview">
          <OverviewPanel health={health} error={healthError} />
        </TabsContent>
        <TabsContent value="coverage">
          <CoveragePanel />
        </TabsContent>
        <TabsContent value="quality">
          <QualityPanel />
        </TabsContent>
        <TabsContent value="identity">
          <IdentityPanel />
        </TabsContent>
        <TabsContent value="quarantine">
          <QuarantinePanel />
        </TabsContent>
        <TabsContent value="tables">
          <TablesPanel />
        </TabsContent>
        <TabsContent value="commands">
          <CommandsPanel onChange={refreshHealth} />
        </TabsContent>
      </Tabs>
    </main>
  );
}

function TabTrigger(props: { value: Tab; icon: ReactNode; label: string }) {
  return (
    <TabsTrigger value={props.value}>
      {props.icon}
      <span>{props.label}</span>
    </TabsTrigger>
  );
}

function OverviewPanel({ health, error }: { health: Health | null; error: string | null }) {
  const audit = useAuditData(getAuditSummary, []);
  const counts = health?.table_counts ?? {};
  const checkCounts = audit.data?.rows.reduce<Record<string, string>>((acc, row) => {
    if (row.section === "row_counts" && typeof row.metric_name === "string") {
      acc[row.metric_name] = formatValue(row.metric_value);
    }
    return acc;
  }, {});

  if (error) return <section className="panel error">{error}</section>;
  if (!health) return <section className="panel">Loading...</section>;
  return (
    <section className="panel">
      <div className="metric-grid">
        <Metric label="Warehouse" value={health.warehouse_exists ? "present" : "missing"} />
        <Metric label="Events" value={String(counts.events ?? checkCounts?.events ?? 0)} />
        <Metric label="Fights" value={String(counts.fights ?? checkCounts?.fights ?? 0)} />
        <Metric label="Fighters" value={String(counts.fighters ?? checkCounts?.fighters ?? 0)} />
        <Metric label="Quarantine" value={String(counts.parse_quarantine ?? 0)} />
        <Metric label="Audit" value={audit.data?.exists === false ? "not run" : "available"} />
      </div>
      <AuditEmpty data={audit.data} label="Run validate-warehouse to populate audit summary." />
      {audit.error && <div className="error">{audit.error}</div>}
      {audit.data && audit.data.rows.length > 0 && (
        <DataTable data={audit.data} emptyText="No summary rows." />
      )}
    </section>
  );
}

function CoveragePanel() {
  const [source, setSource] = useUrlState("coverage_source", "");
  const [promotion, setPromotion] = useUrlState("coverage_promotion", "");
  const audit = useAuditData(() => getAuditCoverage({ source, promotion }), [source, promotion]);
  return (
    <section className="panel">
      <Toolbar>
        <SourceSelect value={source} onChange={setSource} />
        <input
          value={promotion}
          onChange={(event) => setPromotion(event.target.value)}
          placeholder="promotion filter"
          aria-label="Coverage promotion"
        />
        <Button variant="outline" onClick={audit.reload}>
          <RefreshCw size={16} />
          Refresh
        </Button>
        {audit.data && <span className="muted">{audit.data.total} rows</span>}
      </Toolbar>
      <AuditState audit={audit} emptyText="Run validate-warehouse to populate coverage." />
    </section>
  );
}

function QualityPanel() {
  const [status, setStatus] = useUrlState("check_status", "");
  const [tableName, setTableName] = useUrlState("check_table", "");
  const audit = useAuditData(
    () => getAuditChecks({ status, table_name: tableName }),
    [status, tableName],
  );
  return (
    <section className="panel">
      <Toolbar>
        <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Status">
          <option value="">all statuses</option>
          <option value="fail">fail</option>
          <option value="warn">warn</option>
          <option value="pass">pass</option>
        </select>
        <input
          value={tableName}
          onChange={(event) => setTableName(event.target.value)}
          placeholder="table filter"
          aria-label="Check table"
        />
        <Button variant="outline" onClick={audit.reload}>
          <RefreshCw size={16} />
          Refresh
        </Button>
        {audit.data && <span className="muted">{audit.data.total} rows</span>}
      </Toolbar>
      <AuditState audit={audit} emptyText="Run validate-warehouse to populate quality checks." />
    </section>
  );
}

function IdentityPanel() {
  const [source, setSource] = useUrlState("identity_source", "");
  const [linkMethod, setLinkMethod] = useUrlState("identity_method", "");
  const audit = useAuditData(
    () => getAuditIdentity({ source, link_method: linkMethod }),
    [source, linkMethod],
  );
  return (
    <section className="panel">
      <Toolbar>
        <SourceSelect value={source} onChange={setSource} />
        <select
          value={linkMethod}
          onChange={(event) => setLinkMethod(event.target.value)}
          aria-label="Identity link method"
        >
          <option value="">all link methods</option>
          <option value="source_self">source_self</option>
          <option value="exact_name_dob">exact_name_dob</option>
        </select>
        <Button variant="outline" onClick={audit.reload}>
          <RefreshCw size={16} />
          Refresh
        </Button>
        {audit.data && <span className="muted">{audit.data.total} rows</span>}
      </Toolbar>
      <AuditState audit={audit} emptyText="Run validate-warehouse to populate identity audit." />
    </section>
  );
}

function QuarantinePanel() {
  const [reason, setReason] = useUrlState("quarantine_reason", "");
  const [promotion, setPromotion] = useUrlState("quarantine_promotion", "");
  const audit = useAuditData(
    () => getAuditQuarantine({ reason, promotion }),
    [reason, promotion],
  );
  return (
    <section className="panel">
      <Toolbar>
        <input
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="reason filter"
          aria-label="Quarantine reason"
        />
        <input
          value={promotion}
          onChange={(event) => setPromotion(event.target.value)}
          placeholder="promotion filter"
          aria-label="Quarantine promotion"
        />
        <Button variant="outline" onClick={audit.reload}>
          <RefreshCw size={16} />
          Refresh
        </Button>
        {audit.data && <span className="muted">{audit.data.total} rows</span>}
      </Toolbar>
      <AuditState audit={audit} emptyText="No quarantine rows." />
    </section>
  );
}

function TablesPanel() {
  const [name, setName] = useUrlState("table", TABLES[0]);
  const [source, setSource] = useUrlState("source", "");
  const [promotion, setPromotion] = useUrlState("promotion", "");
  const [limit, setLimit] = useUrlState("limit", "100");
  const [offset, setOffset] = useUrlState("offset", "0");
  const pageLimit = clampNumber(limit, 100, 1, 500);
  const pageOffset = clampNumber(offset, 0, 0, 1_000_000);
  const [data, setData] = useState<TableResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadTable(tableName = name) {
    try {
      setData(await getTable(tableName, pageLimit, pageOffset, { source, promotion }));
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
      setData(null);
    }
  }

  useEffect(() => {
    void loadTable(name);
  }, [name, source, promotion, pageLimit, pageOffset]);

  function page(delta: number) {
    const next = Math.max(0, pageOffset + delta * pageLimit);
    setOffset(String(next));
  }

  return (
    <section className="panel">
      <Toolbar>
        <select value={name} onChange={(event) => setName(event.target.value)} aria-label="Table">
          {TABLES.map((table) => (
            <option key={table} value={table}>
              {table}
            </option>
          ))}
        </select>
        <SourceSelect value={source} onChange={setSource} />
        <input
          value={promotion}
          onChange={(event) => setPromotion(event.target.value)}
          placeholder="promotion filter"
          aria-label="Promotion"
        />
        <input
          value={limit}
          onChange={(event) => setLimit(event.target.value)}
          placeholder="limit"
          aria-label="Limit"
        />
        <Button variant="outline" onClick={() => loadTable()}>
          <RefreshCw size={16} />
          Refresh
        </Button>
        {data && <span className="muted">{data.total} rows</span>}
      </Toolbar>
      <Toolbar>
        <Button variant="outline" onClick={() => page(-1)} disabled={pageOffset === 0}>
          Previous
        </Button>
        <span className="muted">
          offset {pageOffset} / limit {pageLimit}
        </span>
        <Button
          variant="outline"
          onClick={() => page(1)}
          disabled={!data || pageOffset + pageLimit >= data.total}
        >
          Next
        </Button>
      </Toolbar>
      {error && <div className="error">{error}</div>}
      {data && <DataTable data={data} emptyText="No rows match the current filters." />}
    </section>
  );
}

function CommandsPanel({ onChange }: { onChange: () => void }) {
  const [runs, setRuns] = useState<CommandStatus[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const runId = new URLSearchParams(window.location.search).get("run");
    if (runId) {
      void poll(runId);
    }
    for (const runId of getStoredRunIds()) {
      void poll(runId);
    }
  }, []);

  async function runCommand(name: string) {
    try {
      const started = await startCommand(name);
      storeRunId(started.run_id);
      setUrlParam("run", started.run_id);
      setError(null);
      poll(started.run_id);
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    }
  }

  async function poll(runId: string) {
    const status = await getCommand(runId);
    setRuns((previous) => [status, ...previous.filter((run) => run.run_id !== runId)]);
    if (status.status === "running") {
      window.setTimeout(() => poll(runId), 1000);
    } else {
      onChange();
    }
  }

  return (
    <section className="panel">
      <div className="command-grid">
        {COMMANDS.map((command) => (
          <Button variant="outline" key={command} onClick={() => runCommand(command)}>
            <Play size={16} />
            {command}
          </Button>
        ))}
      </div>
      {error && <div className="error">{error}</div>}
      {runs.map((run) => (
        <CommandLog run={run} key={run.run_id} />
      ))}
    </section>
  );
}

function Toolbar({ children }: { children: ReactNode }) {
  return <div className="toolbar">{children}</div>;
}

function SourceSelect(props: { value: string; onChange: (value: string) => void }) {
  return (
    <select value={props.value} onChange={(event) => props.onChange(event.target.value)} aria-label="Source">
      <option value="">all sources</option>
      <option value="ufcstats">ufcstats</option>
      <option value="sherdog">sherdog</option>
    </select>
  );
}

function AuditState(props: {
  audit: ReturnType<typeof useAuditData>;
  emptyText: string;
}) {
  if (props.audit.error) return <div className="error">{props.audit.error}</div>;
  if (!props.audit.data) return <div className="muted">Loading...</div>;
  return (
    <>
      <AuditEmpty data={props.audit.data} label={props.emptyText} />
      <DataTable data={props.audit.data} emptyText={props.emptyText} />
    </>
  );
}

function AuditEmpty({ data, label }: { data: TableResponse | null; label: string }) {
  if (!data || data.exists !== false) return null;
  return <div className="empty">{label}</div>;
}

function DataTable({ data, emptyText }: { data: TableResponse; emptyText: string }) {
  const columns = useMemo(() => (data.rows[0] ? Object.keys(data.rows[0]) : []), [data.rows]);
  if (data.rows.length === 0) return <div className="empty">{emptyText}</div>;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          {columns.map((column) => (
            <TableHead key={column}>{column}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.rows.map((row, index) => (
          <TableRow key={index}>
            {columns.map((column) => (
              <TableCell key={column}>{formatCell(column, row[column])}</TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function CommandLog({ run }: { run: CommandStatus }) {
  const preRef = useRef<HTMLPreElement | null>(null);
  const progress = summarizeProgress(run);

  useEffect(() => {
    if (preRef.current) {
      preRef.current.scrollTop = preRef.current.scrollHeight;
    }
  }, [run.log]);

  return (
    <article className="log">
      <header>
        <div>
          <strong>{run.name}</strong>
          {progress && <span className="progress">{progress}</span>}
        </div>
        <span className={`badge ${run.status}`}>{run.status}</span>
      </header>
      <pre ref={preRef}>{run.log || "No log output yet."}</pre>
    </article>
  );
}

function formatCell(column: string, value: unknown): ReactNode {
  if (column === "status" && typeof value === "string") {
    return <span className={`badge ${value}`}>{value}</span>;
  }
  if (column === "url" && typeof value === "string" && value.startsWith("http")) {
    return (
      <a href={value} target="_blank" rel="noreferrer">
        {value}
      </a>
    );
  }
  return formatValue(value);
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function summarizeProgress(run: CommandStatus): string | null {
  const matches = [...run.log.matchAll(/\[(?:sherdog )?event (\d+)\/(\d+)(?: done)?\]/g)];
  const latest = matches.at(-1);
  if (!latest) return null;
  const current = Number(latest[1]);
  const total = Number(latest[2]);
  if (!current || !total) return null;
  const started = Date.parse(run.started_at_utc);
  if (!Number.isFinite(started)) return `event ${current}/${total}`;
  const elapsedMs = Date.now() - started;
  const eventRate = current / Math.max(elapsedMs / 1000, 1);
  const remainingSeconds = Math.max((total - current) / Math.max(eventRate, 0.0001), 0);
  const percent = ((current / total) * 100).toFixed(1);
  return `event ${current}/${total} (${percent}%) - ETA ${formatDuration(remainingSeconds)}`;
}

function formatDuration(seconds: number): string {
  const rounded = Math.round(seconds);
  const hours = Math.floor(rounded / 3600);
  const minutes = Math.floor((rounded % 3600) / 60);
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function useAuditData(fetcher: () => Promise<TableResponse>, deps: unknown[]) {
  const [data, setData] = useState<TableResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    try {
      setData(await fetcher());
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
      setData(null);
    }
  }

  useEffect(() => {
    void reload();
  }, deps);

  return { data, error, reload };
}

function useUrlState(key: string, initialValue: string): [string, (value: string) => void] {
  const [value, setValue] = useState(() => getUrlParam(key) ?? initialValue);
  function update(next: string) {
    setValue(next);
    setUrlParam(key, next);
  }
  return [value, update];
}

function getStoredRunIds(): string[] {
  try {
    const value = window.localStorage.getItem(RUN_IDS_KEY);
    return value ? (JSON.parse(value) as string[]) : [];
  } catch {
    return [];
  }
}

function storeRunId(runId: string): void {
  const runIds = [runId, ...getStoredRunIds().filter((existing) => existing !== runId)].slice(0, 5);
  window.localStorage.setItem(RUN_IDS_KEY, JSON.stringify(runIds));
}

function getUrlParam(key: string): string | null {
  return new URLSearchParams(window.location.search).get(key);
}

function setUrlParam(key: string, value: string): void {
  const params = new URLSearchParams(window.location.search);
  if (value) {
    params.set(key, value);
  } else {
    params.delete(key);
  }
  const query = params.toString();
  window.history.replaceState(null, "", query ? `?${query}` : window.location.pathname);
}

function clampNumber(value: string, fallback: number, min: number, max: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, Math.trunc(parsed)));
}
