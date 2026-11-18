import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, TestCase, TestRun } from "../api";

const CATEGORIES = ["positive", "negative", "edge"] as const;

export default function TestsView({ versionId }: { versionId: number }) {
  const [cases, setCases] = useState<TestCase[]>([]);
  const [runs, setRuns] = useState<TestRun[]>([]);
  const [baseUrl, setBaseUrl] = useState("http://localhost:9000");
  const [selected, setSelected] = useState<string[]>([...CATEGORIES]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    api.tests(versionId).then(setCases).catch((e: Error) => setError(e.message));
    api.runs(versionId).then(setRuns).catch(() => setRuns([]));
  }, [versionId]);

  const counts = useMemo(
    () => Object.fromEntries(CATEGORIES.map((c) => [c, cases.filter((t) => t.category === c).length])),
    [cases],
  );

  async function run(e: FormEvent) {
    e.preventDefault();
    setRunning(true);
    setError(null);
    try {
      const result = await api.runTests(versionId, baseUrl, selected);
      setRuns((prev) => [result, ...prev]);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setRunning(false);
    }
  }

  function toggle(category: string) {
    setSelected((prev) => (prev.includes(category) ? prev.filter((c) => c !== category) : [...prev, category]));
  }

  const latest = runs[0];

  return (
    <div>
      <form className="row toolbar" onSubmit={run}>
        <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder="Base URL of the API under test" size={32} />
        {CATEGORIES.map((c) => (
          <label key={c} className="check">
            <input type="checkbox" checked={selected.includes(c)} onChange={() => toggle(c)} /> {c} ({counts[c] ?? 0})
          </label>
        ))}
        <button disabled={running || selected.length === 0}>{running ? "Running…" : "Run tests"}</button>
      </form>
      {error && <p className="error">{error}</p>}

      {latest && (
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
