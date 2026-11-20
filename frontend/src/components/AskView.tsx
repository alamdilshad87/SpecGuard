import { FormEvent, useEffect, useState } from "react";
import { api, AskResult } from "../api";

const SUGGESTIONS = ["How do I create a new item?", "Which query parameters can I filter by?", "Which operations can return 404?"];

interface Exchange {
  question: string;
  result: AskResult;
}

const MODE_LABEL: Record<AskResult["mode"], string> = {
  llm: "LLM answer",
  extractive: "Best-matching excerpt",
  none: "No match",
};

export default function AskView({ versionId }: { versionId: number }) {
  const [question, setQuestion] = useState("");
  const [useLlm, setUseLlm] = useState(true);
  const [history, setHistory] = useState<Exchange[]>([]);
  const [asking, setAsking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Answers belong to one spec version; start fresh when it changes.
  useEffect(() => {
    setHistory([]);
    setError(null);
  }, [versionId]);

  async function ask(text: string) {
    const q = text.trim();
    if (!q) return;
    setAsking(true);
    setError(null);
    try {
      const result = await api.ask(versionId, q, useLlm);
      setHistory((prev) => [{ question: q, result }, ...prev]);
      setQuestion("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setAsking(false);
    }
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    ask(question);
  }

  return (
    <div>
      <form className="row toolbar" onSubmit={submit}>
        <input className="grow" value={question} onChange={(e) => setQuestion(e.target.value)}
               placeholder="Ask about this API, e.g. which fields are required to create a book?" maxLength={1000} />
        <label className="check">
          <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} /> use LLM
        </label>
        <button disabled={asking || !question.trim()}>{asking ? "Thinking…" : "Ask"}</button>
      </form>
      <div className="row chips">
        {SUGGESTIONS.map((s) => (
          <button key={s} type="button" className="chip plain" disabled={asking} onClick={() => ask(s)}>{s}</button>
        ))}
      </div>
      <p className="muted small">
        Answers come from this spec version and docstrings from its latest code scan. Without an LLM configured
        on the server, the best-matching excerpt is shown instead.
      </p>
      {error && <p className="error">{error}</p>}

      {history.map(({ question: q, result }, i) => (
        <div key={history.length - i} className="panel inset">
          <h3>{q}</h3>
          <div className="muted small">{MODE_LABEL[result.mode]}</div>
          <div className="answer">{result.answer}</div>
          {result.sources.length > 0 && (
            <table>
              <thead><tr><th>Source</th><th>Chunk</th><th>Score</th></tr></thead>
              <tbody>
                {result.sources.map((s) => (
                  <tr key={s.id}>
                    <td><span className={`badge ${s.source === "code" ? "edge" : "positive"}`}>{s.source}</span></td>
                    <td><code>{s.id}</code><div className="muted small">{s.title}</div></td>
                    <td>{s.score.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ))}
    </div>
  );
}
