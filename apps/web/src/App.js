import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { Database, Play, RefreshCw, Table2, Terminal } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { getCommand, getHealth, getTable, startCommand } from "./api";
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
export function App() {
    const [tab, setTab] = useState("health");
    const [health, setHealth] = useState(null);
    const [healthError, setHealthError] = useState(null);
    async function refreshHealth() {
        try {
            setHealth(await getHealth());
            setHealthError(null);
        }
        catch (error) {
            setHealthError(error instanceof Error ? error.message : String(error));
        }
    }
    useEffect(() => {
        void refreshHealth();
    }, []);
    return (_jsxs("main", { className: "shell", children: [_jsxs("header", { className: "topbar", children: [_jsxs("div", { children: [_jsx("h1", { children: "MMA Market Efficiency Lab" }), _jsx("p", { children: "Local UFCStats warehouse and point-in-time feature inspection." })] }), _jsx("button", { className: "icon-button", onClick: refreshHealth, "aria-label": "Refresh health", children: _jsx(RefreshCw, { size: 18 }) })] }), _jsxs("nav", { className: "tabs", "aria-label": "Primary", children: [_jsx(TabButton, { active: tab === "health", onClick: () => setTab("health"), icon: _jsx(Database, { size: 16 }), label: "Health" }), _jsx(TabButton, { active: tab === "tables", onClick: () => setTab("tables"), icon: _jsx(Table2, { size: 16 }), label: "Tables" }), _jsx(TabButton, { active: tab === "commands", onClick: () => setTab("commands"), icon: _jsx(Terminal, { size: 16 }), label: "Commands" })] }), tab === "health" && _jsx(HealthPanel, { health: health, error: healthError }), tab === "tables" && _jsx(TablesPanel, {}), tab === "commands" && _jsx(CommandsPanel, { onChange: refreshHealth })] }));
}
function TabButton(props) {
    return (_jsxs("button", { className: props.active ? "tab active" : "tab", onClick: props.onClick, children: [props.icon, _jsx("span", { children: props.label })] }));
}
function HealthPanel({ health, error }) {
    if (error)
        return _jsx("section", { className: "panel error", children: error });
    if (!health)
        return _jsx("section", { className: "panel", children: "Loading..." });
    const rows = Object.entries(health.table_counts);
    return (_jsxs("section", { className: "panel", children: [_jsxs("div", { className: "metric-grid", children: [_jsx(Metric, { label: "Warehouse", value: health.warehouse_exists ? "present" : "missing" }), _jsx(Metric, { label: "Path", value: health.warehouse_path })] }), _jsxs(Table, { children: [_jsx(TableHeader, { children: _jsxs(TableRow, { children: [_jsx(TableHead, { children: "Table" }), _jsx(TableHead, { children: "Rows" })] }) }), _jsx(TableBody, { children: rows.length === 0 ? (_jsx(TableRow, { children: _jsx(TableCell, { colSpan: 2, children: "No warehouse tables yet." }) })) : (rows.map(([name, count]) => (_jsxs(TableRow, { children: [_jsx(TableCell, { children: name }), _jsx(TableCell, { children: count })] }, name)))) })] })] }));
}
function Metric({ label, value }) {
    return (_jsxs("div", { className: "metric", children: [_jsx("span", { children: label }), _jsx("strong", { children: value })] }));
}
function TablesPanel() {
    const [name, setName] = useState(TABLES[0]);
    const [data, setData] = useState(null);
    const [error, setError] = useState(null);
    const columns = useMemo(() => (data?.rows[0] ? Object.keys(data.rows[0]) : []), [data]);
    async function loadTable(tableName = name) {
        try {
            setData(await getTable(tableName));
            setError(null);
        }
        catch (error) {
            setError(error instanceof Error ? error.message : String(error));
            setData(null);
        }
    }
    useEffect(() => {
        void loadTable(name);
    }, [name]);
    return (_jsxs("section", { className: "panel", children: [_jsxs("div", { className: "toolbar", children: [_jsx("select", { value: name, onChange: (event) => setName(event.target.value), "aria-label": "Table", children: TABLES.map((table) => (_jsx("option", { value: table, children: table }, table))) }), _jsxs("button", { className: "button", onClick: () => loadTable(), children: [_jsx(RefreshCw, { size: 16 }), "Refresh"] }), data && _jsxs("span", { className: "muted", children: [data.total, " rows"] })] }), error && _jsx("div", { className: "error", children: error }), data && (_jsxs(Table, { children: [_jsx(TableHeader, { children: _jsx(TableRow, { children: columns.map((column) => (_jsx(TableHead, { children: column }, column))) }) }), _jsx(TableBody, { children: data.rows.map((row, index) => (_jsx(TableRow, { children: columns.map((column) => (_jsx(TableCell, { children: formatValue(row[column]) }, column))) }, index))) })] }))] }));
}
function CommandsPanel({ onChange }) {
    const [runs, setRuns] = useState([]);
    const [error, setError] = useState(null);
    async function runCommand(name) {
        try {
            const started = await startCommand(name);
            setError(null);
            poll(started.run_id);
        }
        catch (error) {
            setError(error instanceof Error ? error.message : String(error));
        }
    }
    async function poll(runId) {
        const status = await getCommand(runId);
        setRuns((previous) => [status, ...previous.filter((run) => run.run_id !== runId)]);
        if (status.status === "running") {
            window.setTimeout(() => poll(runId), 1000);
        }
        else {
            onChange();
        }
    }
    return (_jsxs("section", { className: "panel", children: [_jsx("div", { className: "command-grid", children: COMMANDS.map((command) => (_jsxs("button", { className: "button", onClick: () => runCommand(command), children: [_jsx(Play, { size: 16 }), command] }, command))) }), error && _jsx("div", { className: "error", children: error }), runs.map((run) => (_jsxs("article", { className: "log", children: [_jsxs("header", { children: [_jsx("strong", { children: run.name }), _jsx("span", { children: run.status })] }), _jsx("pre", { children: run.log || "No log output yet." })] }, run.run_id)))] }));
}
function formatValue(value) {
    if (value === null || value === undefined)
        return "";
    if (typeof value === "object")
        return JSON.stringify(value);
    return String(value);
}
