import { useEffect, useState } from "react";
type Trace = {
  id: string;
  revision: number;
  mode: string;
  question: string;
  elapsed_ms: number;
  usage: { total_tokens?: number };
  answer: { answer: string; citations: Array<{ id: string; href: string }> };
};
export function AssistantTraces({
  run,
  api,
}: {
  run: string;
  api: (url: string, body?: unknown) => Promise<any>;
}) {
  const [rows, setRows] = useState<Trace[]>([]),
    [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    const refresh = () =>
      api(`/api/assistant/traces?run=${encodeURIComponent(run)}`)
        .then((r) => {
          if (live) {
            setRows(r);
            setError("");
          }
        })
        .catch((e) => {
          if (live) setError(String(e));
        });
    refresh();
    const t = setInterval(refresh, 4000);
    return () => {
      live = false;
      clearInterval(t);
    };
  }, [run, api]);
  return (
    <section className="panel evaluation-panel">
      <h2>Assistant evidence trail</h2>
      <p>
        Each answer retains its question, state revision, tool evidence,
        provider mode and measured latency. Token usage is recorded when OpenAI
        is enabled; no dollar cost is assumed.
      </p>
      {error && <p role="alert">{error}</p>}
      {!rows.length && (
        <p>
          No questions recorded for this run yet. Open the assistant to
          investigate a departure or evaluation.
        </p>
      )}
      {rows.map((r) => (
        <details key={r.id}>
          <summary>
            {r.question} · revision {r.revision} · {r.mode}
          </summary>
          <p style={{ whiteSpace: "pre-line" }}>{r.answer.answer}</p>
          <small>
            {r.elapsed_ms} ms · {r.usage.total_tokens ?? 0} provider tokens ·
            trace {r.id}
          </small>
          <div className="assistant-citations">
            {r.answer.citations.map((c) => (
              <a key={c.id} href={c.href} target="_blank" rel="noreferrer">
                {c.id} · evidence
              </a>
            ))}
          </div>
        </details>
      ))}
    </section>
  );
}
