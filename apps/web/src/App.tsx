import { Database, Play, RefreshCw, Table2, Terminal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { getCommand, getHealth, getTable, startCommand, type CommandStatus, type Health, type TableResponse } from "./api";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./components/ui/table";

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
];

type Tab = "health" | "tables" | "commands";

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
        <button className="icon-button" onClick={refreshHealth} aria-label="Refresh health">
          <RefreshCw size={18} />
        </button>
      </header>

      <nav className="tabs" aria-label="Primary">
        <TabButton active={tab === "health"} onClick={() => setTab("health")} icon={<Database size={16} />} label="Health" />
        <TabButton active={tab === "tables"} onClick={() => setTab("tables")} icon={<Table2 size={16} />} label="Tables" />
        <TabButton active={tab === "commands"} onClick={() => setTab("commands")} icon={<Terminal size={16} />} label="Commands" />
      </nav>

      {tab === "health" && <HealthPanel health={health} error={healthError} />}
      {tab === "tables" && <TablesPanel />}
      {tab === "commands" && <CommandsPanel onChange={refreshHealth} />}
    </main>
  );
}

function TabButton(props: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button className={props.active ? "tab active" : "tab"} onClick={props.onClick}>
      {props.icon}
      <span>{props.label}</span>
    </button>
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
        <button className="button" onClick={() => loadTable()}>
          <RefreshCw size={16} />
          Refresh
        </button>
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

  async function runCommand(name: string) {
    try {
      const started = await startCommand(name);
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
          <button className="button" key={command} onClick={() => runCommand(command)}>
            <Play size={16} />
            {command}
          </button>
        ))}
      </div>
      {error && <div className="error">{error}</div>}
      {runs.map((run) => (
        <article className="log" key={run.run_id}>
          <header>
            <strong>{run.name}</strong>
            <span>{run.status}</span>
          </header>
          <pre>{run.log || "No log output yet."}</pre>
        </article>
      ))}
    </section>
  );
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
