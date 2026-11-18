import { FormEvent, useState } from "react";
import { api } from "../api";

interface Props {
  projectId: number;
  onUploaded: () => void;
}

export default function UploadVersion({ projectId, onUploaded }: Props) {
  const [label, setLabel] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file || !label.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.uploadVersion(projectId, label.trim(), file);
      setLabel("");
      setFile(null);
      (e.target as HTMLFormElement).reset();
      onUploaded();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="panel upload" onSubmit={submit}>
      <h3>Upload a spec version</h3>
      <div className="row">
        <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Label, e.g. v1 or 2.0.0" />
        <input type="file" accept=".yaml,.yml,.json" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <button disabled={busy || !file || !label.trim()}>{busy ? "Uploading…" : "Upload"}</button>
      </div>
      <p className="muted small">OpenAPI 3.x in YAML or JSON. The spec is validated before it is saved.</p>
      {error && <p className="error">{error}</p>}
    </form>
  );
}
