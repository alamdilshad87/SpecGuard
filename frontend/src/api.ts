const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface VersionSummary {
  id: number;
  label: string;
  title: string;
  openapi: string;
  operation_count: number;
  created_at: string;
}

export interface Project {
  id: number;
  name: string;
  created_at: string;
  versions: VersionSummary[];
}

export interface Change {
  severity: "breaking" | "warning" | "info";
  rule: string;
  operation: string;
  location: string;
  message: string;
}

export interface DiffResult {
  from_label?: string;
  to_label?: string;
  from_version: string;
  to_version: string;
  is_breaking: boolean;
  summary: Record<Change["severity"], number>;
  changes: Change[];
}

export interface TestCase {
  id: string;
  name: string;
  category: "positive" | "negative" | "edge";
  operation: string;
  method: string;
  path: string;
  query: Record<string, unknown>;
  body: unknown;
  expected_status: string[];
}

export interface TestResult {
  id: string;
  name: string;
  category: TestCase["category"];
  operation: string;
  expected_status: string[];
  status: number | null;
  passed: boolean;
  error?: string;
  duration_ms: number;
}

export interface TestRun {
  id: number;
  base_url: string;
  total: number;
  passed: number;
  created_at: string;
  results: TestResult[];
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* keep statusText */
    }
    throw new Error(detail);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  listProjects: () => request<Project[]>("/projects"),
  createProject: (name: string) => request<Project>("/projects", json({ name })),
  deleteProject: (id: number) => request<void>(`/projects/${id}`, { method: "DELETE" }),
  uploadVersion: (projectId: number, label: string, file: File) => {
    const form = new FormData();
    form.append("label", label);
    form.append("file", file);
    return request<VersionSummary>(`/projects/${projectId}/versions/upload`, { method: "POST", body: form });
  },
  addVersion: (projectId: number, label: string, content: string) =>
    request<VersionSummary>(`/projects/${projectId}/versions`, json({ label, content })),
  docs: (versionId: number) => request<{ content: string }>(`/versions/${versionId}/docs`),
  tests: (versionId: number) => request<TestCase[]>(`/versions/${versionId}/tests`),
  runTests: (versionId: number, baseUrl: string, categories?: string[]) =>
    request<TestRun>(`/versions/${versionId}/runs`, json({ base_url: baseUrl, categories })),
  runs: (versionId: number) => request<TestRun[]>(`/versions/${versionId}/runs`),
  diff: (fromId: number, toId: number) => request<DiffResult>(`/diff?from=${fromId}&to=${toId}`),
};
