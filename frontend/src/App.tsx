import { useCallback, useEffect, useState } from "react";
import { api, Project } from "./api";
import Sidebar from "./components/Sidebar";
import UploadVersion from "./components/UploadVersion";

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await api.listProjects();
      setProjects(list);
      setError(null);
      setSelectedId((current) => current ?? list[0]?.id ?? null);
    } catch (err) {
      setError(`Cannot reach the SpecGuard API: ${(err as Error).message}`);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function createProject(name: string) {
    try {
      const project = await api.createProject(name);
      await refresh();
      setSelectedId(project.id);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  const project = projects.find((p) => p.id === selectedId) ?? null;

  return (
    <div className="app">
      <header className="topbar">
        <h1>SpecGuard</h1>
        <span className="tagline">OpenAPI docs, breaking-change detection and generated tests</span>
      </header>
      <div className="layout">
        <Sidebar projects={projects} selectedId={selectedId} onSelect={setSelectedId} onCreate={createProject} />
        <main className="content">
          {error && <p className="error">{error}</p>}
          {!project && !error && <p className="muted">Create a project to get started.</p>}
          {project && (
            <>
              <h2>{project.name}</h2>
              <UploadVersion projectId={project.id} onUploaded={refresh} />
              <section className="panel">
                <h3>Versions</h3>
                {project.versions.length === 0 ? (
                  <p className="muted">No versions uploaded yet.</p>
                ) : (
                  <table>
                    <thead>
                      <tr><th>Label</th><th>Title</th><th>OpenAPI</th><th>Operations</th><th>Uploaded</th></tr>
                    </thead>
                    <tbody>
                      {project.versions.map((v) => (
                        <tr key={v.id}>
                          <td><strong>{v.label}</strong></td>
                          <td>{v.title}</td>
                          <td>{v.openapi}</td>
                          <td>{v.operation_count}</td>
                          <td>{new Date(v.created_at).toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </section>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
