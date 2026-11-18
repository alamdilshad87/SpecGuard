import { FormEvent, useState } from "react";
import { Project } from "../api";

interface Props {
  projects: Project[];
  selectedId: number | null;
  onSelect: (id: number) => void;
  onCreate: (name: string) => Promise<void>;
}

export default function Sidebar({ projects, selectedId, onSelect, onCreate }: Props) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      await onCreate(name.trim());
      setName("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="sidebar">
      <h2>Projects</h2>
      <form onSubmit={submit} className="row">
        <input value={name} onChange={(e) => setName(e.target.value)} placeholder="New project name" />
        <button disabled={busy || !name.trim()}>Add</button>
      </form>
      <ul className="project-list">
        {projects.map((p) => (
          <li key={p.id}>
            <button className={p.id === selectedId ? "active" : ""} onClick={() => onSelect(p.id)}>
              <span>{p.name}</span>
              <small>{p.versions.length} version{p.versions.length === 1 ? "" : "s"}</small>
            </button>
          </li>
        ))}
        {projects.length === 0 && <li className="muted">No projects yet</li>}
      </ul>
    </aside>
  );
}
