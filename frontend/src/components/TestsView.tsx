import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, TestCase, TestRun } from "../api";

const CATEGORIES = ["positive", "negative", "edge"] as const;
const POLL_MS = 1000;
const isActive = (run?: TestRun) => run?.status === "queued" || run?.status === "running";

export default function TestsView({ versionId }: { versionId: number }) {
  const [cases, setCases] = useState<TestCase[]>([]);
  const [runs, setRuns] = useState<TestRun[]>([]);
  const [baseUrl, setBaseUrl] = useState("http://localhost:9000");
  const [selected, setSelected] = useState<string[]>([...CATEGORIES]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    api.tests(versionId).then(setCases).catch((e: Error) => setError(e.message));
    api.runs(versionId).then(setRuns).catch(() => setRuns([]));
  }, [versionId]);

  // Runs execute in a background worker: poll the newest run until it finishes.
  const latest = runs[0];
  useEffect(() => {
    if (!isActive(latest)) return;
    const timer = setTimeout(async () => {
      try {
        const fresh = await api.run(latest.id);
        setRuns((prev) => prev.map((r) => (r.id === fresh.id ? fresh : r)));
      } catch (err) {
        setError((err as Error).message);
      }
    }, POLL_MS);
    return () => clearTimeout(timer);
  }, [latest]);

  const counts = useMemo(
    () => Object.fromEntries(CATEGORIES.map((c) => [c, cases.filter((t) => t.category === c).length])),
    [cases],
  );

  async function run(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const queued = await api.runTests(versionId, baseUrl, selected);
      setRuns((prev) => [queued, ...prev]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  function toggle(category: string) {
    setSelected((prev) => (prev.includes(category) ? prev.filter((c) => c !== category) : [...prev, category]));
  }

  const busy = submitting || isActive(latest);

  return (
    <div>
      <form className="row toolbar" onSubmit={run}>
        <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="Base URL of the API under test" size={32} />
        {CATEGORIES.map((c) => (
          <label key={c} className="check">
            <input type="checkbox" checked={selected.includes(c)} onChange={() => toggle(c)} /> {c} ({counts[c] ?? 0})
          </label>
        ))}
        <button disabled={busy || selected.length === 0}>
          {latest?.status === "queued" ? "Queued…" : busy ? "Running…" : "Run tests"}
        </button>
      </form>
      {error && <p className="error">{error}</p>}

      {latest && isActive(latest) && (
        <div className="panel inset">
          <h3>
            <span className="badge info">{latest.status}</span>{" "}
            {latest.status === "queued"
              ? "Waiting for a worker to pick up this run…"
              : `Running against ${latest.base_url}${latest.attempts > 1 ? ` (attempt ${latest.attempts})` : ""}…`}
          </h3>
          <p className="muted small">Runs execute in the background; this updates automatically.</p>
        </div>
      )}

      {latest?.status === "failed" && (
        <div className="panel inset">
          <h3><span className="badge fail">failed</span> Run #{latest.id} could not complete</h3>
          <p className="error small">{latest.error}</p>
        </div>
      )}

      {latest?.status === "succeeded" && (
        <div className="panel inset">
          <h3>
            Latest run: {latest.passed}/{latest.total} passed
            ({latest.total ? Math.round((100 * latest.passed) / latest.total) : 0}%) against <code>{latest.base_url}</code>
          </h3>
          <table>
            <thead><tr><th>Result</th><th>Test</th><th>Operation</th><th>Expected</th><th>Got</th><th>ms</th></tr></thead>
            <tbody>
              {latest.results.map((r) => (
                <tr key={r.id}>
                  <td><span className={`badge ${r.passed ? "pass" : "fail"}`}>{r.passed ? "pass" : "fail"}</span></td>
                  <td>{r.name}</td>
                  <td><code>{r.operation}</code></td>
                  <td>{r.expected_status.join(", ")}</td>
                  <td>{r.status ?? <span className="error">{r.error}</span>}</td>
                  <td>{r.duration_ms}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3>Generated test cases ({cases.length})</h3>
      <table>
        <thead><tr><th>Type</th><th>Test</th><th>Request</th><th>Expect</th></tr></thead>
        <tbody>
          {cases.map((t) => (
            <tr key={t.id}>
              <td><span className={`badge ${t.category}`}>{t.category}</span></td>
              <td>{t.name}</td>
              <td>
                <code>{t.method} {t.path}{Object.keys(t.query).length ? "?" + new URLSearchParams(
                  Object.entries(t.query).map(([k, v]) => [k, String(v)])).toString() : ""}</code>
                {t.body !== null && t.body !== undefined && (
                  <details><summary className="muted small">body</summary><pre>{JSON.stringify(t.body, null, 2)}</pre></details>
                )}
              </td>
              <td>{t.expected_status.join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
