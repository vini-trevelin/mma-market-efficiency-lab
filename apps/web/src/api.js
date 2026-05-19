const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";
async function request(path, init) {
    const response = await fetch(`${API_BASE}${path}`, init);
    if (!response.ok) {
        const detail = await response.text();
        throw new Error(`${response.status} ${detail}`);
    }
    return response.json();
}
export function getHealth() {
    return request("/health");
}
export function getTable(name, limit = 100, offset = 0) {
    return request(`/tables/${name}?limit=${limit}&offset=${offset}`);
}
export function startCommand(name) {
    return request(`/commands/${name}`, { method: "POST" });
}
export function getCommand(runId) {
    return request(`/commands/${runId}`);
}
