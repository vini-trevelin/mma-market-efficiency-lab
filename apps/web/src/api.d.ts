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
export declare function getHealth(): Promise<Health>;
export declare function getTable(name: string, limit?: number, offset?: number): Promise<TableResponse>;
export declare function startCommand(name: string): Promise<{
    run_id: string;
    status: string;
}>;
export declare function getCommand(runId: string): Promise<CommandStatus>;
