import {
  AlertTriangle,
  Database,
  Play,
  RefreshCw,
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
  getAuditQuarantine,
  getAuditSummary,
  getCommand,
  getHealth,
  getIdentityCandidates,
  getIdentityReview,
  getTable,
  saveIdentityDecision,
  clearIdentityDecision,
  startCommand,
  type CommandStatus,
  type Health,
  type IdentityCandidate,
  type IdentityCandidateResponse,
  type TableResponse,
} from "./api";
import { Button } from "./components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "./components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "./components/ui/tabs";

const TABLES = [
  "analysis_event_audit",
  "analysis_fight_audit",
  "analysis_fighter_audit",
  "analysis_identity_review",
  "analysis_pit_audit",
  "events",
  "fights",
  "fight_participants",
  "fighters",
  "fighter_fight_stats",
  "source_events",
  "source_fights",
  "source_fight_participants",
  "source_fighters",
  "fighter_identity_manual_overrides",
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
  "apply-identity-overrides",
  "repair-sherdog-major",
  "make-reports",
  "full-pipeline",
  "full-pipeline-sherdog-major",
];

type Tab =
  | "overview"
  | "events"
  | "fights"
  | "fighters"
  | "identity"
  | "quality"
  | "quarantine"
  | "tables"
  | "commands";

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
          <p>Local MMA warehouse audit, Sherdog repair, and point-in-time feature review.</p>
        </div>
        <Button variant="outline" size="icon" onClick={refreshHealth} aria-label="Refresh health">
          <RefreshCw size={18} />
        </Button>
      </header>

      <Tabs value={tab} onValueChange={changeTab}>
        <TabsList variant="line" aria-label="Primary">
          <TabTrigger value="overview" icon={<Database size={16} />} label="Overview" />
          <TabTrigger value="events" icon={<Database size={16} />} label="Events" />
          <TabTrigger value="fights" icon={<Table2 size={16} />} label="Fights" />
          <TabTrigger value="fighters" icon={<UserRound size={16} />} label="Fighters" />
          <TabTrigger value="identity" icon={<UserRound size={16} />} label="Identity" />
          <TabTrigger value="quality" icon={<ShieldCheck size={16} />} label="Quality" />
          <TabTrigger value="quarantine" icon={<AlertTriangle size={16} />} label="Quarantine" />
          <TabTrigger value="tables" icon={<Table2 size={16} />} label="Tables" />
          <TabTrigger value="commands" icon={<Terminal size={16} />} label="Commands" />
        </TabsList>
        <TabsContent value="overview">
          <OverviewPanel health={health} error={healthError} />
        </TabsContent>
        <TabsContent value="events">
          <EventsPanel onSelectFight={() => changeTab("fights")} />
        </TabsContent>
        <TabsContent value="fights">
          <FightsPanel onSelectFighter={() => changeTab("fighters")} />
        </TabsContent>
        <TabsContent value="fighters">
          <FightersPanel onSelectFight={() => changeTab("fights")} />
        </TabsContent>
        <TabsContent value="identity">
          <IdentityPanel />
        </TabsContent>
        <TabsContent value="quality">
          <QualityPanel />
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
  const summary = useAuditData(getAuditSummary, []);
  const coverage = useAuditData(getAuditCoverage, []);
  const counts = health?.table_counts ?? {};
  const summaryRows = summary.data?.rows ?? [];
  const warehouseBytes = summaryRows.find((row) => row.metric_name === "warehouse_file_bytes")?.metric_value;
  const sherdogBytes = summaryRows.find((row) => row.metric_name === "sherdog_bytes")?.metric_value;
  const ufcstatsBytes = summaryRows.find((row) => row.metric_name === "ufcstats_bytes")?.metric_value;

  if (error) return <section className="panel error">{error}</section>;
  if (!health) return <section className="panel">Loading...</section>;

  return (
    <section className="panel">
      <div className="metric-grid">
        <Metric label="Warehouse" value={health.warehouse_exists ? "present" : "missing"} />
        <Metric label="Warehouse size" value={formatBytes(warehouseBytes)} />
        <Metric label="Events" value={String(counts.events ?? 0)} />
        <Metric label="Fights" value={String(counts.fights ?? 0)} />
        <Metric label="Fighters" value={String(counts.fighters ?? 0)} />
        <Metric label="Sherdog raw size" value={formatBytes(sherdogBytes)} />
        <Metric label="UFCStats raw size" value={formatBytes(ufcstatsBytes)} />
        <Metric label="Audit" value={summary.data?.exists === false ? "not run" : "available"} />
      </div>
      <AuditEmpty data={summary.data} label="Run validate-warehouse to populate audit summary." />
      {summary.error && <div className="error">{summary.error}</div>}
      {summary.data && summary.data.rows.length > 0 && (
        <DataTable data={summary.data} emptyText="No summary rows." />
      )}
      <section className="subpanel">
        <h2>Coverage by source and promotion</h2>
        <AuditState audit={coverage} emptyText="Run validate-warehouse to populate coverage." />
      </section>
    </section>
  );
}

function EventsPanel({ onSelectFight }: { onSelectFight: () => void }) {
  const [source, setSource] = useUrlState("events_source", "");
  const [promotion, setPromotion] = useUrlState("events_promotion", "");
  const [hasAnomaly, setHasAnomaly] = useUrlState("events_has_anomaly", "");
  const [eventId, setEventId] = useUrlState("event_id", "");
  const events = useTableData("analysis_event_audit", {
    source,
    promotion,
    has_anomaly: hasAnomaly,
  });
  const fights = useTableData(
    "analysis_fight_audit",
    eventId ? { event_id: eventId } : {},
    200,
    0,
  );

  return (
    <section className="panel">
      <Toolbar>
        <SourceSelect value={source} onChange={setSource} />
        <input
          value={promotion}
          onChange={(event) => setPromotion(event.target.value)}
          placeholder="promotion filter"
          aria-label="Events promotion"
        />
        <BooleanSelect
          value={hasAnomaly}
          onChange={setHasAnomaly}
          label="Event anomalies"
          allLabel="all events"
          trueLabel="anomalies only"
          falseLabel="clean only"
        />
        <Button variant="outline" onClick={events.reload}>
          <RefreshCw size={16} />
          Refresh
        </Button>
        {events.data && <span className="muted">{events.data.total} rows</span>}
      </Toolbar>
      <DataState
        data={events.data}
        error={events.error}
        emptyText="No event rows match the current filters."
        onRowClick={(row) => setEventId(String(row.event_id ?? ""))}
      />
      <section className="subpanel">
        <Toolbar>
          <strong>Event drilldown</strong>
          <FilterChip label="event_id" value={eventId} onClear={() => setEventId("")} />
          {eventId && (
            <Button
              variant="outline"
              onClick={() => {
                const fightId = String(fights.data?.rows[0]?.fight_id ?? "");
                if (fightId) {
                  setUrlParam("fight_id", fightId);
                  onSelectFight();
                }
              }}
            >
              Open fights tab
            </Button>
          )}
        </Toolbar>
        <DataState
          data={fights.data}
          error={fights.error}
          emptyText="Select an event row to inspect its fights."
          onRowClick={(row) => {
            setUrlParam("fight_id", String(row.fight_id ?? ""));
            setUrlParam("event_id", String(row.event_id ?? ""));
            onSelectFight();
          }}
        />
      </section>
    </section>
  );
}

function FightsPanel({ onSelectFighter }: { onSelectFighter: () => void }) {
  const [source, setSource] = useUrlState("fights_source", "");
  const [promotion, setPromotion] = useUrlState("fights_promotion", "");
  const [eventId, setEventId] = useUrlState("event_id", "");
  const [fightId, setFightId] = useUrlState("fight_id", "");
  const [hasAnomaly, setHasAnomaly] = useUrlState("fights_has_anomaly", "");
  const fights = useTableData("analysis_fight_audit", {
    source,
    promotion,
    event_id: eventId,
    has_anomaly: hasAnomaly,
  });
  const participants = useTableData("fight_participants", fightId ? { fight_id: fightId } : {}, 20, 0);
  const matchup = useTableData("pit_matchup_features", fightId ? { fight_id: fightId } : {}, 20, 0);
  const pitAudit = useTableData("analysis_pit_audit", fightId ? { fight_id: fightId } : {}, 20, 0);

  return (
    <section className="panel">
      <Toolbar>
        <SourceSelect value={source} onChange={setSource} />
        <input
          value={promotion}
          onChange={(event) => setPromotion(event.target.value)}
          placeholder="promotion filter"
          aria-label="Fights promotion"
        />
        <input
          value={eventId}
          onChange={(event) => setEventId(event.target.value)}
          placeholder="event_id filter"
          aria-label="Fight event"
        />
        <BooleanSelect
          value={hasAnomaly}
          onChange={setHasAnomaly}
          label="Fight anomalies"
          allLabel="all fights"
          trueLabel="anomalies only"
          falseLabel="clean only"
        />
        <Button variant="outline" onClick={fights.reload}>
          <RefreshCw size={16} />
          Refresh
        </Button>
        {fights.data && <span className="muted">{fights.data.total} rows</span>}
      </Toolbar>
      <DataState
        data={fights.data}
        error={fights.error}
        emptyText="No fight rows match the current filters."
        onRowClick={(row) => setFightId(String(row.fight_id ?? ""))}
      />
      <section className="subpanel">
        <Toolbar>
          <strong>Fight drilldown</strong>
          <FilterChip label="fight_id" value={fightId} onClear={() => setFightId("")} />
        </Toolbar>
        <DataState
          data={participants.data}
          error={participants.error}
          emptyText="Select a fight row to inspect participants."
          onRowClick={(row) => {
            setUrlParam("fighter_id", String(row.fighter_id ?? ""));
            onSelectFighter();
          }}
        />
        <DataState
          data={matchup.data}
          error={matchup.error}
          emptyText="No matchup rows for the selected fight."
        />
        <DataState
          data={pitAudit.data}
          error={pitAudit.error}
          emptyText="No PIT audit rows for the selected fight."
          onRowClick={(row) => {
            setUrlParam("fighter_id", String(row.fighter_id ?? ""));
            onSelectFighter();
          }}
        />
      </section>
    </section>
  );
}

function FightersPanel({ onSelectFight }: { onSelectFight: () => void }) {
  const [source, setSource] = useUrlState("fighters_source", "");
  const [fighterId, setFighterId] = useUrlState("fighter_id", "");
  const [hasAnomaly, setHasAnomaly] = useUrlState("fighters_has_anomaly", "");
  const fighters = useTableData("analysis_fighter_audit", {
    source,
    has_anomaly: hasAnomaly,
    fighter_id: fighterId || undefined,
  });
  const history = useTableData("fight_participants", fighterId ? { fighter_id: fighterId } : {}, 200, 0);
  const pit = useTableData("analysis_pit_audit", fighterId ? { fighter_id: fighterId } : {}, 200, 0);

  return (
    <section className="panel">
      <Toolbar>
        <SourceSelect value={source} onChange={setSource} />
        <BooleanSelect
          value={hasAnomaly}
          onChange={setHasAnomaly}
          label="Fighter anomalies"
          allLabel="all fighters"
          trueLabel="incomplete only"
          falseLabel="complete only"
        />
        <input
          value={fighterId}
          onChange={(event) => setFighterId(event.target.value)}
          placeholder="fighter_id filter"
          aria-label="Fighter id"
        />
        <Button variant="outline" onClick={fighters.reload}>
          <RefreshCw size={16} />
          Refresh
        </Button>
        {fighters.data && <span className="muted">{fighters.data.total} rows</span>}
      </Toolbar>
      <DataState
        data={fighters.data}
        error={fighters.error}
        emptyText="No fighter rows match the current filters."
        onRowClick={(row) => setFighterId(String(row.fighter_id ?? ""))}
      />
      <section className="subpanel">
        <Toolbar>
          <strong>Fighter drilldown</strong>
          <FilterChip label="fighter_id" value={fighterId} onClear={() => setFighterId("")} />
        </Toolbar>
        <DataState
          data={history.data}
          error={history.error}
          emptyText="Select a fighter row to inspect fight history."
          onRowClick={(row) => {
            setUrlParam("fight_id", String(row.fight_id ?? ""));
            setUrlParam("event_id", String(row.event_id ?? ""));
            onSelectFight();
          }}
        />
        <DataState data={pit.data} error={pit.error} emptyText="No PIT rows for the selected fighter." />
      </section>
    </section>
  );
}

function IdentityPanel() {
  const [source, setSource] = useUrlState("identity_source", "sherdog");
  const [reviewStatus, setReviewStatus] = useUrlState("identity_review_status", "");
  const [decisionStatus, setDecisionStatus] = useUrlState("identity_decision_status", "");
  const [hasCandidate, setHasCandidate] = useUrlState("identity_has_candidate", "");
  const [selectedSourceFighterId, setSelectedSourceFighterId] = useUrlState(
    "identity_source_fighter_id",
    "",
  );
  const [candidateQuery, setCandidateQuery] = useUrlState("identity_query", "");
  const [note, setNote] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [applyRun, setApplyRun] = useState<CommandStatus | null>(null);
  const review = useAuditData(
    () =>
      getIdentityReview({
        source,
        review_status: reviewStatus,
        has_candidate: hasCandidate,
        decision_status: decisionStatus,
      }),
    [source, reviewStatus, hasCandidate, decisionStatus],
  );
  const candidates = useIdentityCandidates(selectedSourceFighterId, candidateQuery);
  const selectedRow = useMemo(
    () =>
      review.data?.rows.find(
        (row) => String(row.source_fighter_id ?? "") === selectedSourceFighterId,
      ) ?? null,
    [review.data, selectedSourceFighterId],
  );

  useEffect(() => {
    if (!selectedSourceFighterId && review.data?.rows[0]) {
      setSelectedSourceFighterId(String(review.data.rows[0].source_fighter_id ?? ""));
    }
  }, [review.data, selectedSourceFighterId, setSelectedSourceFighterId]);

  useEffect(() => {
    setNote(typeof selectedRow?.manual_note === "string" ? selectedRow.manual_note : "");
    setActionError(null);
    setActionMessage(null);
  }, [selectedSourceFighterId, selectedRow]);

  async function poll(runId: string) {
    const status = await getCommand(runId);
    setApplyRun(status);
    if (status.status === "running") {
      window.setTimeout(() => void poll(runId), 1000);
      return;
    }
    await review.reload();
    await candidates.reload();
  }

  async function submitDecision(
    targetSourceFighterId: string,
    decision: "approved" | "rejected" | "accepted_unresolved",
  ) {
    try {
      const response = await saveIdentityDecision({
        source_fighter_id: selectedSourceFighterId,
        target_source_fighter_id: targetSourceFighterId || undefined,
        decision,
        note,
        apply: true,
      });
      setActionError(null);
      setActionMessage(
        response.apply_status === "started"
          ? `${decision} saved, rebuild started`
          : response.apply_status === "blocked"
            ? `${decision} saved, rebuild blocked by another running command`
            : `${decision} saved`,
      );
      await review.reload();
      await candidates.reload();
      if (response.run_id) {
        storeRunId(response.run_id);
        setUrlParam("run", response.run_id);
        await poll(response.run_id);
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  }

  async function clearDecisionFor(targetSourceFighterId?: string) {
    try {
      const response = await clearIdentityDecision(
        selectedSourceFighterId,
        targetSourceFighterId,
        true,
      );
      setActionError(null);
      setActionMessage(
        response.apply_status === "started"
          ? "manual decision cleared, rebuild started"
          : response.apply_status === "blocked"
            ? "manual decision cleared, rebuild blocked by another running command"
            : "manual decision cleared",
      );
      await review.reload();
      await candidates.reload();
      if (response.run_id) {
        storeRunId(response.run_id);
        setUrlParam("run", response.run_id);
        await poll(response.run_id);
      }
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  }

  return (
    <section className="panel">
      <Toolbar>
        <SourceSelect value={source} onChange={setSource} />
        <select
          value={reviewStatus}
          onChange={(event) => setReviewStatus(event.target.value)}
          aria-label="Identity review status"
        >
          <option value="">all review statuses</option>
          <option value="accepted_unresolved">accepted_unresolved</option>
          <option value="linked_manual">linked_manual</option>
          <option value="linked_exact">linked_exact</option>
          <option value="linked_cleaned">linked_cleaned</option>
          <option value="candidate_review">candidate_review</option>
          <option value="unresolved">unresolved</option>
        </select>
        <select
          value={decisionStatus}
          onChange={(event) => setDecisionStatus(event.target.value)}
          aria-label="Identity decision status"
        >
          <option value="">all decision states</option>
          <option value="accepted_unresolved">accepted_unresolved</option>
          <option value="approved">approved override</option>
          <option value="none">no override</option>
        </select>
        <BooleanSelect
          value={hasCandidate}
          onChange={setHasCandidate}
          label="Identity candidates"
          allLabel="all candidate states"
          trueLabel="has candidates"
          falseLabel="no candidates"
        />
        <Button variant="outline" onClick={review.reload}>
          <RefreshCw size={16} />
          Refresh
        </Button>
        {review.data && <span className="muted">{review.data.total} rows</span>}
      </Toolbar>
      <DataState
        data={review.data}
        error={review.error}
        emptyText="No identity review rows."
        onRowClick={(row) => setSelectedSourceFighterId(String(row.source_fighter_id ?? ""))}
      />
      <section className="subpanel">
        <Toolbar>
          <strong>Identity review detail</strong>
          <FilterChip
            label="source_fighter_id"
            value={selectedSourceFighterId}
            onClear={() => setSelectedSourceFighterId("")}
          />
        </Toolbar>
        {!selectedSourceFighterId && <div className="empty">Select a Sherdog fighter row to review.</div>}
        {selectedSourceFighterId && (
          <>
            {actionError && <div className="error">{actionError}</div>}
            {actionMessage && <div className="empty">{actionMessage}</div>}
            {candidates.error && <div className="error">{candidates.error}</div>}
            {candidates.data && (
              <div className="identity-layout">
                <section className="identity-sidebar">
                  <IdentitySummary
                    sourceRow={candidates.data.source_fighter}
                    reviewRow={candidates.data.review_row}
                  />
                  <label className="stack-field">
                    <span className="muted">Review note</span>
                    <input
                      value={note}
                      onChange={(event) => setNote(event.target.value)}
                      placeholder="optional note"
                      aria-label="Review note"
                    />
                  </label>
                  <label className="stack-field">
                    <span className="muted">Manual UFC search</span>
                    <input
                      value={candidateQuery}
                      onChange={(event) => setCandidateQuery(event.target.value)}
                      placeholder="search UFC fighter name"
                      aria-label="Manual UFC search"
                    />
                  </label>
                  <div className="stack-actions">
                    <Button variant="outline" onClick={candidates.reload}>
                      <RefreshCw size={16} />
                      Refresh candidates
                    </Button>
                    <Button
                      variant="outline"
                      onClick={() => void submitDecision("", "accepted_unresolved")}
                    >
                      No candidates
                    </Button>
                    {selectedRow?.decision_status === "accepted_unresolved" && (
                      <Button variant="outline" onClick={() => void clearDecisionFor(undefined)}>
                        Clear no candidates
                      </Button>
                    )}
                  </div>
                </section>
                <section className="identity-main">
                  <IdentityCandidateTable
                    title="Suggested candidates"
                    candidates={candidates.data.suggestions}
                    emptyText="No deterministic candidates for this Sherdog fighter."
                    onApprove={(targetId) => void submitDecision(targetId, "approved")}
                    onReject={(targetId) => void submitDecision(targetId, "rejected")}
                    onClear={(targetId) => void clearDecisionFor(targetId)}
                  />
                  <IdentityCandidateTable
                    title="Manual search results"
                    candidates={candidates.data.search_results}
                    emptyText="Search UFC fighters by name to review manual targets."
                    onApprove={(targetId) => void submitDecision(targetId, "approved")}
                    onReject={(targetId) => void submitDecision(targetId, "rejected")}
                    onClear={(targetId) => void clearDecisionFor(targetId)}
                  />
                  <RejectedPairTable
                    rows={candidates.data.rejected_pairs}
                    onClear={(targetId) => void clearDecisionFor(targetId)}
                  />
                  {applyRun && <CommandLog run={applyRun} />}
                </section>
              </div>
            )}
          </>
        )}
      </section>
    </section>
  );
}

function IdentitySummary(props: {
  sourceRow: Record<string, unknown>;
  reviewRow: Record<string, unknown>;
}) {
  const sourceRow = props.sourceRow;
  const reviewRow = props.reviewRow;
  return (
    <div className="identity-summary">
      <div className="metric-grid">
        <Metric label="Sherdog fighter" value={formatValue(sourceRow.full_name)} />
        <Metric label="DOB" value={formatValue(sourceRow.dob)} />
        <Metric label="Current status" value={formatValue(reviewRow.review_status)} />
        <Metric label="Current link" value={formatValue(reviewRow.canonical_fighter_id)} />
        <Metric label="Current method" value={formatValue(reviewRow.link_method)} />
        <Metric label="Rejected pairs" value={formatValue(reviewRow.rejected_pair_count)} />
      </div>
      <div className="identity-meta">
        <div>
          <strong>Match reason</strong>
          <p>{formatValue(reviewRow.match_reason)}</p>
        </div>
        <div>
          <strong>History span</strong>
          <p>
            {formatValue(sourceRow.first_fight_date)} - {formatValue(sourceRow.last_fight_date)}
          </p>
        </div>
        <div>
          <strong>Fight counts</strong>
          <p>
            total {formatValue(sourceRow.fight_count)} | UFC {formatValue(sourceRow.ufc_fight_count)} | Sherdog{" "}
            {formatValue(sourceRow.sherdog_fight_count)}
          </p>
        </div>
      </div>
    </div>
  );
}

function IdentityCandidateTable(props: {
  title: string;
  candidates: IdentityCandidate[];
  emptyText: string;
  onApprove: (targetSourceFighterId: string) => void;
  onReject: (targetSourceFighterId: string) => void;
  onClear: (targetSourceFighterId: string) => void;
}) {
  return (
    <section className="subpanel">
      <h2>{props.title}</h2>
      {props.candidates.length === 0 ? (
        <div className="empty">{props.emptyText}</div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>target_source_fighter_id</TableHead>
              <TableHead>target_canonical_fighter_id</TableHead>
              <TableHead>full_name</TableHead>
              <TableHead>dob</TableHead>
              <TableHead>candidate_reason</TableHead>
              <TableHead>fight_count</TableHead>
              <TableHead>manual_decision</TableHead>
              <TableHead>actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {props.candidates.map((candidate) => (
              <TableRow key={candidate.target_source_fighter_id}>
                <TableCell>{candidate.target_source_fighter_id}</TableCell>
                <TableCell>{candidate.target_canonical_fighter_id}</TableCell>
                <TableCell>{candidate.full_name}</TableCell>
                <TableCell>{candidate.dob ?? ""}</TableCell>
                <TableCell>{candidate.candidate_reason}</TableCell>
                <TableCell>{formatValue(candidate.fight_count)}</TableCell>
                <TableCell>{formatValue(candidate.manual_decision)}</TableCell>
                <TableCell>
                  <div className="inline-actions">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => props.onApprove(candidate.target_source_fighter_id)}
                    >
                      Approve
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => props.onReject(candidate.target_source_fighter_id)}
                    >
                      Reject
                    </Button>
                    {candidate.manual_decision && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => props.onClear(candidate.target_source_fighter_id)}
                      >
                        Clear
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  );
}

function RejectedPairTable(props: {
  rows: Record<string, unknown>[];
  onClear: (targetSourceFighterId: string) => void;
}) {
  return (
    <section className="subpanel">
      <h2>Rejected pairs</h2>
      {props.rows.length === 0 ? (
        <div className="empty">No rejected pairs for this Sherdog fighter.</div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>target_source_fighter_id</TableHead>
              <TableHead>target_canonical_fighter_id</TableHead>
              <TableHead>full_name</TableHead>
              <TableHead>dob</TableHead>
              <TableHead>note</TableHead>
              <TableHead>actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {props.rows.map((row, index) => (
              <TableRow key={`${row.target_source_fighter_id}-${index}`}>
                <TableCell>{formatValue(row.target_source_fighter_id)}</TableCell>
                <TableCell>{formatValue(row.target_canonical_fighter_id)}</TableCell>
                <TableCell>{formatValue(row.full_name)}</TableCell>
                <TableCell>{formatValue(row.dob)}</TableCell>
                <TableCell>{formatValue(row.note)}</TableCell>
                <TableCell>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => props.onClear(String(row.target_source_fighter_id ?? ""))}
                  >
                    Clear
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
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
  const [eventId, setEventId] = useUrlState("table_event_id", "");
  const [fightId, setFightId] = useUrlState("table_fight_id", "");
  const [fighterId, setFighterId] = useUrlState("table_fighter_id", "");
  const [hasAnomaly, setHasAnomaly] = useUrlState("table_has_anomaly", "");
  const [limit, setLimit] = useUrlState("limit", "100");
  const [offset, setOffset] = useUrlState("offset", "0");
  const pageLimit = clampNumber(limit, 100, 1, 500);
  const pageOffset = clampNumber(offset, 0, 0, 1_000_000);
  const [data, setData] = useState<TableResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadTable(tableName = name) {
    try {
      setData(
        await getTable(tableName, pageLimit, pageOffset, {
          source,
          promotion,
          event_id: eventId,
          fight_id: fightId,
          fighter_id: fighterId,
          has_anomaly: hasAnomaly,
        }),
      );
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
      setData(null);
    }
  }

  useEffect(() => {
    void loadTable(name);
  }, [name, source, promotion, eventId, fightId, fighterId, hasAnomaly, pageLimit, pageOffset]);

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
          value={eventId}
          onChange={(event) => setEventId(event.target.value)}
          placeholder="event_id"
          aria-label="event_id"
        />
        <input
          value={fightId}
          onChange={(event) => setFightId(event.target.value)}
          placeholder="fight_id"
          aria-label="fight_id"
        />
        <input
          value={fighterId}
          onChange={(event) => setFighterId(event.target.value)}
          placeholder="fighter_id"
          aria-label="fighter_id"
        />
        <BooleanSelect
          value={hasAnomaly}
          onChange={setHasAnomaly}
          label="Anomaly"
          allLabel="all rows"
          trueLabel="anomalies only"
          falseLabel="clean only"
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
      void poll(started.run_id);
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
    }
  }

  async function poll(runId: string) {
    const status = await getCommand(runId);
    setRuns((previous) => [status, ...previous.filter((run) => run.run_id !== runId)]);
    if (status.status === "running") {
      window.setTimeout(() => void poll(runId), 1000);
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

function BooleanSelect(props: {
  value: string;
  onChange: (value: string) => void;
  label: string;
  allLabel: string;
  trueLabel: string;
  falseLabel: string;
}) {
  return (
    <select value={props.value} onChange={(event) => props.onChange(event.target.value)} aria-label={props.label}>
      <option value="">{props.allLabel}</option>
      <option value="true">{props.trueLabel}</option>
      <option value="false">{props.falseLabel}</option>
    </select>
  );
}

function FilterChip(props: { label: string; value: string; onClear: () => void }) {
  if (!props.value) return null;
  return (
    <button className="chip" onClick={props.onClear} type="button">
      {props.label}: {props.value}
    </button>
  );
}

function DataState(props: {
  data: TableResponse | null;
  error: string | null;
  emptyText: string;
  onRowClick?: (row: Record<string, unknown>) => void;
}) {
  if (props.error) return <div className="error">{props.error}</div>;
  if (!props.data) return <div className="muted">Loading...</div>;
  return <DataTable data={props.data} emptyText={props.emptyText} onRowClick={props.onRowClick} />;
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

function DataTable(props: {
  data: TableResponse;
  emptyText: string;
  onRowClick?: (row: Record<string, unknown>) => void;
}) {
  const columns = useMemo(() => (props.data.rows[0] ? Object.keys(props.data.rows[0]) : []), [props.data.rows]);
  if (props.data.rows.length === 0) return <div className="empty">{props.emptyText}</div>;
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
        {props.data.rows.map((row, index) => (
          <TableRow
            key={index}
            className={props.onRowClick ? "clickable-row" : undefined}
            onClick={props.onRowClick ? () => props.onRowClick?.(row) : undefined}
          >
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
  if ((column === "status" || column === "review_status") && typeof value === "string") {
    const badgeClass =
      value === "pass" ||
      value === "accepted_unresolved" ||
      value === "linked_manual" ||
      value === "linked_exact" ||
      value === "linked_cleaned"
        ? "pass"
        : value === "warn" || value === "candidate_review"
          ? "warn"
          : value === "fail" || value === "unresolved"
            ? "fail"
            : "";
    return <span className={`badge ${badgeClass}`}>{value}</span>;
  }
  if (column === "has_anomaly" && typeof value === "boolean") {
    return <span className={`badge ${value ? "fail" : "pass"}`}>{String(value)}</span>;
  }
  if (column === "url" && typeof value === "string" && value.startsWith("http")) {
    return (
      <a href={value} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>
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

function formatBytes(value: unknown): string {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes <= 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(size >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`;
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

function useIdentityCandidates(sourceFighterId: string, query: string) {
  const [data, setData] = useState<IdentityCandidateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reload() {
    if (!sourceFighterId) {
      setData(null);
      setError(null);
      return;
    }
    try {
      setData(await getIdentityCandidates(sourceFighterId, query));
      setError(null);
    } catch (error) {
      setError(error instanceof Error ? error.message : String(error));
      setData(null);
    }
  }

  useEffect(() => {
    void reload();
  }, [sourceFighterId, query]);

  return { data, error, reload };
}

function useTableData(
  name: string,
  filters: Record<string, string | undefined>,
  limit = 500,
  offset = 0,
) {
  return useAuditData(() => getTable(name, limit, offset, filters), [
    name,
    limit,
    offset,
    ...Object.entries(filters).flat(),
  ]);
}

function useUrlState(key: string, initialValue: string): [string, (value: string) => void] {
  const [value, setValue] = useState(() => getUrlParam(key) ?? initialValue);

  useEffect(() => {
    function handleUrlStateChange() {
      setValue(getUrlParam(key) ?? initialValue);
    }
    window.addEventListener("mma:urlstate", handleUrlStateChange as EventListener);
    return () => window.removeEventListener("mma:urlstate", handleUrlStateChange as EventListener);
  }, [key, initialValue]);

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
  window.dispatchEvent(new Event("mma:urlstate"));
}

function clampNumber(value: string, fallback: number, min: number, max: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, Math.trunc(parsed)));
}
