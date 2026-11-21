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

export type RunStatus = "queued" | "running" | "succeeded" | "failed";

export interface TestRun {
  id: number;
  base_url: string;
  status: RunStatus;
  attempts: number;
  error: string | null;
  total: number;
  passed: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  results: TestResult[];
}

export interface LintIssue {
  level: "error" | "warning";
  location: string;
  message: string;
}

export interface LintReport {
  valid: boolean;
  summary: Record<LintIssue["level"], number>;
  issues: LintIssue[];
}

export interface CodeRoute {
  key: string;
  method: string;
  path: string;
  file: string;
  line: number;
  handler: string;
  doc: string;
}

export interface DriftReport {
  in_sync: boolean;
  summary: { matched: number; undocumented: number; unimplemented: number };
  matched: { operation: string; route: CodeRoute }[];
  undocumented_in_spec: CodeRoute[];
  not_implemented_in_code: { operation: string; operation_id: string }[];
  warnings?: string[];
}

export interface CodeScan {
  id: number;
  spec_version_id: number;
  files_scanned: number;
  in_sync: boolean;
  created_at: string;
  report: DriftReport;
}

export interface AskSource {
  id: string;
  title: string;
  source: "operation" | "code";
  score: number;
}

export interface AskResult {
  answer: string;
  mode: "llm" | "extractive" | "none";
  sources: AskSource[];
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
  run: (runId: number) => request<TestRun>(`/runs/${runId}`),
  diff: (fromId: number, toId: number) => request<DiffResult>(`/diff?from=${fromId}&to=${toId}`),
  lint: (versionId: number) => request<LintReport>(`/versions/${versionId}/lint`),
  scans: (versionId: number) => request<CodeScan[]>(`/versions/${versionId}/scans`),
  scan: (versionId: number, files: File[]) => {
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    return request<CodeScan>(`/versions/${versionId}/scans`, { method: "POST", body: form });
  },
  ask: (versionId: number, question: string, useLlm = true) =>
    request<AskResult>(`/versions/${versionId}/ask`, json({ question, use_llm: useLlm })),
};
