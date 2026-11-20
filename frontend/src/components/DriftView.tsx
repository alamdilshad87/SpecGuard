import { FormEvent, useEffect, useRef, useState } from "react";
import { api, CodeRoute, CodeScan } from "../api";

const ACCEPT = ".py,.js,.ts,.mjs,.cjs,.cs,.zip";

function Location({ route }: { route: CodeRoute }) {
  return (
    <>
      <code>{route.file}:{route.line}</code>
      {route.handler && <div className="muted small">{route.handler}</div>}
    </>
  );
}

export default function DriftView({ versionId }: { versionId: number }) {
  const [scans, setScans] = useState<CodeScan[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setError(null);
    setScans([]);
    setSelectedId(null);
    api.scans(versionId).then((list) => {
      setScans(list);
      setSelectedId(list[0]?.id ?? null);
    }).catch((e: Error) => setError(e.message));
  }, [versionId]);

  async function scan(e: FormEvent) {
    e.preventDefault();
    if (files.length === 0) return;
    setScanning(true);
    setError(null);
    try {
      const result = await api.scan(versionId, files);
      setScans((prev) => [result, ...prev]);
      setSelectedId(result.id);
      setFiles([]);
      if (input.current) input.current.value = "";
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setScanning(false);
    }
  }

  const current = scans.find((s) => s.id === selectedId) ?? null;
  const report = current?.report;

  return (
    <div>
      <form className="row toolbar" onSubmit={scan}>
        <input ref={input} type="file" multiple accept={ACCEPT}
               onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
        <button disabled={scanning || files.length === 0}>{scanning ? "Scanning…" : "Scan code"}</button>
        {scans.length > 1 && (
          <select value={selectedId ?? ""} onChange={(e) => setSelectedId(Number(e.target.value))}>
            {scans.map((s) => (
              <option key={s.id} value={s.id}>
                {new Date(s.created_at).toLocaleString()} · {s.files_scanned} file{s.files_scanned === 1 ? "" : "s"}
              </option>
            ))}
          </select>
        )}
      </form>
      <p className="muted small">
        Upload source files or a .zip: FastAPI/Flask (.py), Express (.js/.ts) or ASP.NET Core (.cs).
        Routes are matched to spec operations by path shape, so <code>/books/{"{book_id}"}</code> matches <code>/books/{"{bookId}"}</code>.
      </p>
      {error && <p className="error">{error}</p>}
      {!current && !error && <p className="muted">No scans yet for this version.</p>}

      {current && report && (
        <>
          <div className={`verdict ${report.in_sync ? "good" : "bad"}`}>
            {report.in_sync
              ? `Code and spec are in sync: all ${report.summary.matched} operations implemented`
              : `Drift found: ${report.summary.undocumented} undocumented route${report.summary.undocumented === 1 ? "" : "s"}, `
                + `${report.summary.unimplemented} unimplemented operation${report.summary.unimplemented === 1 ? "" : "s"}`}
          </div>
          {report.warnings?.map((w) => <p key={w} className="warn-text small">⚠ {w}</p>)}

          {report.undocumented_in_spec.length > 0 && (
            <div className="panel inset">
              <h3>In code, missing from the spec ({report.undocumented_in_spec.length})</h3>
              <table>
                <thead><tr><th>Route</th><th>Where</th></tr></thead>
                <tbody>
                  {report.undocumented_in_spec.map((r) => (
                    <tr key={r.key + r.file + r.line}>
                      <td><span className="badge breaking">undocumented</span> <code>{r.key}</code></td>
                      <td><Location route={r} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {report.not_implemented_in_code.length > 0 && (
            <div className="panel inset">
              <h3>In the spec, not found in code ({report.not_implemented_in_code.length})</h3>
              <table>
                <thead><tr><th>Operation</th><th>operationId</th></tr></thead>
                <tbody>
                  {report.not_implemented_in_code.map((o) => (
                    <tr key={o.operation}>
                      <td><span className="badge warning">unimplemented</span> <code>{o.operation}</code></td>
                      <td><code>{o.operation_id}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h3>Matched ({report.matched.length})</h3>
          <table>
            <thead><tr><th>Spec operation</th><th>Implemented by</th></tr></thead>
            <tbody>
              {report.matched.map((m) => (
                <tr key={m.operation}>
                  <td><span className="badge pass">matched</span> <code>{m.operation}</code></td>
                  <td><Location route={m.route} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
