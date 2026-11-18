import { useEffect, useState } from "react";
import { api, Change, DiffResult, VersionSummary } from "../api";

const SEVERITIES: Change["severity"][] = ["breaking", "warning", "info"];

export default function DiffView({ versions }: { versions: VersionSummary[] }) {
  const [fromId, setFromId] = useState<number | null>(null);
  const [toId, setToId] = useState<number | null>(null);
  const [result, setResult] = useState<DiffResult | null>(null);
  const [filter, setFilter] = useState<Change["severity"] | "all">("all");
  const [error, setError] = useState<string | null>(null);

  // Default to comparing the two most recent versions.
  useEffect(() => {
    if (versions.length >= 2) {
      setFromId(versions[versions.length - 2].id);
      setToId(versions[versions.length - 1].id);
    }
    setResult(null);
  }, [versions]);

  async function run() {
    if (fromId == null || toId == null) return;
    setError(null);
    try {
      setResult(await api.diff(fromId, toId));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (versions.length < 2) {
    return <p className="muted">Upload at least two versions to compare them.</p>;
  }

  const shown = result?.changes.filter((c) => filter === "all" || c.severity === filter) ?? [];

  return (
    <div>
      <div className="row toolbar">
        <label>From</label>
        <select value={fromId ?? ""} onChange={(e) => setFromId(Number(e.target.value))}>
          {versions.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
        </select>
        <label>To</label>
        <select value={toId ?? ""} onChange={(e) => setToId(Number(e.target.value))}>
          {versions.map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}
        </select>
        <button onClick={run} disabled={fromId === toId}>Compare</button>
      </div>
      {error && <p className="error">{error}</p>}
      {result && (
        <>
          <div className={`verdict ${result.is_breaking ? "bad" : "good"}`}>
            {result.is_breaking
              ? `${result.summary.breaking} breaking change${result.summary.breaking === 1 ? "" : "s"}: clients of ${result.from_label} may break on ${result.to_label}`
              : `No breaking changes from ${result.from_label} to ${result.to_label}`}
          </div>
          <div className="row chips">
            <button className={`chip ${filter === "all" ? "on" : ""}`} onClick={() => setFilter("all")}>
              All {result.changes.length}
            </button>
            {SEVERITIES.map((s) => (
              <button key={s} className={`chip ${s} ${filter === s ? "on" : ""}`} onClick={() => setFilter(s)}>
                {s} {result.summary[s]}
              </button>
            ))}
          </div>
          <table>
            <thead><tr><th>Severity</th><th>Operation</th><th>Location</th><th>Change</th></tr></thead>
            <tbody>
              {shown.map((c, i) => (
                <tr key={i}>
                  <td><span className={`badge ${c.severity}`}>{c.severity}</span></td>
                  <td><code>{c.operation}</code></td>
                  <td><code>{c.location}</code></td>
                  <td>{c.message}<div className="muted small">{c.rule}</div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
