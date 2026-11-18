import { useCallback, useEffect, useState } from "react";
import { api, Project } from "./api";
import DiffView from "./components/DiffView";
import DocsView from "./components/DocsView";
import Sidebar from "./components/Sidebar";
import TestsView from "./components/TestsView";
import UploadVersion from "./components/UploadVersion";

type Tab = "docs" | "tests" | "diff";

export default function App() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [versionId, setVersionId] = useState<number | null>(null);
  const [tab, setTab] = useState<Tab>("docs");
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

  const project = projects.find((p) => p.id === selectedId) ?? null;

  // Keep a valid version selected when the project or its versions change.
  useEffect(() => {
    if (!project) return setVersionId(null);
    if (!project.versions.some((v) => v.id === versionId)) {
      setVersionId(project.versions.at(-1)?.id ?? null);
    }
  }, [project, versionId]);

  async function createProject(name: string) {
    try {
      const created = await api.createProject(name);
      await refresh();
      setSelectedId(created.id);
    } catch (err) {
      setError((err as Error).message);
    }
  }

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
                        <tr key={v.id} className={`clickable ${v.id === versionId ? "selected" : ""}`}
                            onClick={() => setVersionId(v.id)}>
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

              {project.versions.length > 0 && (
                <section className="panel">
                  <nav className="tabs">
                    <button className={tab === "docs" ? "on" : ""} onClick={() => setTab("docs")}>Docs</button>
                    <button className={tab === "tests" ? "on" : ""} onClick={() => setTab("tests")}>Tests</button>
                    <button className={tab === "diff" ? "on" : ""} onClick={() => setTab("diff")}>Breaking changes</button>
                  </nav>
                  {tab === "docs" && versionId != null && <DocsView versionId={versionId} />}
                  {tab === "tests" && versionId != null && <TestsView versionId={versionId} />}
                  {tab === "diff" && <DiffView versions={project.versions} />}
                </section>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
