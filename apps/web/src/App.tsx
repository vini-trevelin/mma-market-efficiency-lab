import { Database, Play, RefreshCw, Table2, Terminal } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
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
  "pit_fighter_features",
  "pit_matchup_features",
  "warehouse_quality",
];

const COMMANDS = [
  "download-ufcstats",
  "parse-ufcstats",
  "build-warehouse",
  "build-features",
  "make-reports",
  "full-pipeline",
];

type Tab = "health" | "tables" | "commands";
const RUN_IDS_KEY = "mma_eff_lab_command_run_ids";

export function App() {
  const [tab, setTab] = useState<Tab>("health");
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

  useEffect(() => {
    void refreshHealth();
  }, []);

  return (
    <main className="shell">
      <header className="topbar">
        <div>
          <h1>MMA Market Efficiency Lab</h1>
          <p>Local UFCStats warehouse and point-in-time feature inspection.</p>
        </div>
        <Button variant="outline" size="icon" onClick={refreshHealth} aria-label="Refresh health">
          <RefreshCw size={18} />
        </Button>
      </header>

      <Tabs value={tab} onValueChange={(value) => setTab(value as Tab)}>
        <TabsList variant="line" aria-label="Primary">
          <TabTrigger value="health" icon={<Database size={16} />} label="Health" />
          <TabTrigger value="tables" icon={<Table2 size={16} />} label="Tables" />
          <TabTrigger value="commands" icon={<Terminal size={16} />} label="Commands" />
        </TabsList>
        <TabsContent value="health">
          <HealthPanel health={health} error={healthError} />
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

function HealthPanel({ health, error }: { health: Health | null; error: string | null }) {
  if (error) return <section className="panel error">{error}</section>;
  if (!health) return <section className="panel">Loading...</section>;
  const rows = Object.entries(health.table_counts);
  return (
    <section className="panel">
      <div className="metric-grid">
        <Metric label="Warehouse" value={health.warehouse_exists ? "present" : "missing"} />
        <Metric label="Path" value={health.warehouse_path} />
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Table</TableHead>
            <TableHead>Rows</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={2}>No warehouse tables yet.</TableCell>
            </TableRow>
          ) : (
            rows.map(([name, count]) => (
              <TableRow key={name}>
                <TableCell>{name}</TableCell>
                <TableCell>{count}</TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
    </section>
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

function TablesPanel() {
  const [name, setName] = useState(TABLES[0]);
  const [data, setData] = useState<TableResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const columns = useMemo(() => (data?.rows[0] ? Object.keys(data.rows[0]) : []), [data]);

  async function loadTable(tableName = name) {
    try {
      setData(await getTable(tableName));
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
      setData(null);
    }
  }

  useEffect(() => {
    void loadTable(name);
  }, [name]);

  return (
    <section className="panel">
      <div className="toolbar">
        <select value={name} onChange={(event) => setName(event.target.value)} aria-label="Table">
          {TABLES.map((table) => (
            <option key={table} value={table}>
              {table}
            </option>
          ))}
        </select>
        <Button variant="outline" onClick={() => loadTable()}>
          <RefreshCw size={16} />
          Refresh
        </Button>
        {data && <span className="muted">{data.total} rows</span>}
      </div>
      {error && <div className="error">{error}</div>}
      {data && (
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
                  <TableCell key={column}>{formatValue(row[column])}</TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
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
      window.history.replaceState(null, "", `?run=${started.run_id}`);
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
        <span>{run.status}</span>
      </header>
      <pre ref={preRef}>{run.log || "No log output yet."}</pre>
    </article>
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function summarizeProgress(run: CommandStatus): string | null {
  const matches = [...run.log.matchAll(/\[event (\d+)\/(\d+)(?: done)?\]/g)];
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
