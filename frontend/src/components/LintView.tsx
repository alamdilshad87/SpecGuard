import { useEffect, useState } from "react";
import { api, LintIssue, LintReport } from "../api";

const LEVELS: LintIssue["level"][] = ["error", "warning"];

export default function LintView({ versionId }: { versionId: number }) {
  const [report, setReport] = useState<LintReport | null>(null);
  const [filter, setFilter] = useState<LintIssue["level"] | "all">("all");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setReport(null);
    setError(null);
    api.lint(versionId).then(setReport).catch((e: Error) => setError(e.message));
  }, [versionId]);

  if (error) return <p className="error">{error}</p>;
  if (!report) return <p className="muted">Linting…</p>;

  const { error: errors, warning: warnings } = report.summary;
  const shown = report.issues.filter((i) => filter === "all" || i.level === filter);

  return (
    <div>
      <div className={`verdict ${report.valid ? (warnings ? "warn" : "good") : "bad"}`}>
        {report.valid
          ? warnings
            ? `No errors, ${warnings} warning${warnings === 1 ? "" : "s"}`
            : "No problems found"
          : `${errors} error${errors === 1 ? "" : "s"} and ${warnings} warning${warnings === 1 ? "" : "s"}`}
      </div>

      {report.issues.length > 0 && (
        <>
          <div className="row chips">
            <button className={`chip ${filter === "all" ? "on" : ""}`} onClick={() => setFilter("all")}>
              All {report.issues.length}
            </button>
            {LEVELS.map((level) => (
              <button key={level} className={`chip ${filter === level ? "on" : ""}`} onClick={() => setFilter(level)}>
                {level} {report.summary[level]}
              </button>
            ))}
          </div>
          <table>
            <thead><tr><th>Level</th><th>Location</th><th>Problem</th></tr></thead>
            <tbody>
              {shown.map((issue, i) => (
                <tr key={i}>
                  <td><span className={`badge ${issue.level}`}>{issue.level}</span></td>
                  <td><code>{issue.location}</code></td>
                  <td>{issue.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
