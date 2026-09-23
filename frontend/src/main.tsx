import { cargoName } from "./departure";
import { ScheduleTimeline } from "./ScheduleRecovery";
import React, { useState, useEffect, useRef, useCallback } from "react";
import { createRoot } from "react-dom/client";
import {
  Anchor,
  Map,
  Layers3,
  GitPullRequest,
  FlaskConical,
  Network,
  Play,
  Pause,
  StepForward,
  MessageSquare,
  Search,
  X,
  ArrowUpRight,
  WifiOff,
  ChevronDown,
  BookOpen,
  ArrowRight,
} from "lucide-react";
import type {
  State,
  Event,
  Experiment,
  CommandResult,
  Source,
  InputRecord,
} from "./types";
import { clock } from "./types";
import { TerminalMap } from "./Map";
import {
  MetricStrip,
  Commitments,
  Inspector,
  JobTable,
  Badge,
} from "./components";
import { Recovery } from "./Recovery";
import { Evidence } from "./Evidence";
import { AssistantTraces } from "./AssistantTraces";
import { EvaluationPanel } from "./EvaluationPanel";
import { Scenarios } from "./Scenarios";
import { CaseWorkspace } from "./CaseWorkspace";
import { DataInputs } from "./DataInputs";
import { CaseContext, DepartureAttention, DiagnosisPanel } from "./Diagnosis";
import type { Diagnosis, Workspace } from "./Diagnosis";
import "./style.css";
import "./review.css";
import { ActionReceipt } from "./ActionReceipt";
import { ResourceCompetition } from "./ResourceCompetition";

type Page =
  | "Operations"
  | "Work & commitments"
  | "Recovery"
  | "Scenario lab"
  | "Evidence";
const pages = [
  { name: "Operations" as Page, icon: Map },
  { name: "Work & commitments" as Page, icon: Layers3 },
  { name: "Recovery" as Page, icon: GitPullRequest },
  { name: "Scenario lab" as Page, icon: FlaskConical },
  { name: "Evidence" as Page, icon: Network },
];
function App() {
  const [labView, setLabView] = useState("Disruption");
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [operationsView, setOperationsView] = useState("departure");
  const [departureId, setDepartureId] = useState(
    new URLSearchParams(window.location.search).get("departure") ||
      "NORTH-RAIL",
  );
  const [page, setPage] = useState<Page>(() => {
      const p = new URLSearchParams(location.search).get("page");
      return pages.some((x) => x.name === p) ? (p as Page) : "Operations";
    }),
    [run, setRun] = useState(
      new URLSearchParams(window.location.search).get("run") || "main",
    ),
    [runs, setRuns] = useState<{ id: string; name: string }[]>([]),
    [s, setS] = useState<State | null>(null),
    [stateRun, setStateRun] = useState<string | null>(null),
    [events, setEvents] = useState<Event[]>([]),
    [experiments, setExperiments] = useState<Experiment[]>([]),
    [commands, setCommands] = useState<CommandResult[]>([]),
    [sources, setSources] = useState<Source[]>([]),
    [inputs, setInputs] = useState<InputRecord[]>([]);
  const [selected, setSelected] = useState(
      new URLSearchParams(location.search).get("entity") || "",
    ),
    [flow, setFlow] = useState("all"),
    [search, setSearch] = useState(""),
    [status, setStatus] = useState("Connecting"),
    [updated, setUpdated] = useState(0),
    [age, setAge] = useState(0),
    [error, setError] = useState(""),
    [toast, setToast] = useState(""),
    [busy, setBusy] = useState(false),
    [role, setRole] = useState("operator"),
    [history, setHistory] = useState<{
      state: State;
      revision: number;
      events: Event[];
    } | null>(null),
    [workFilter, setWorkFilter] = useState("active"),
    [allWork, setAllWork] = useState(true),
    [assistantOpen, setAssistantOpen] = useState(false),
    [question, setQuestion] = useState(""),
    [answer, setAnswer] = useState<{
      answer: string;
      mode: string;
      fallback_reason?: string;
      trace_id: string;
      citations: Array<{ id: string; text: string; href: string }>;
      calls: unknown[];
      revision: number;
    } | null>(null),
    [asking, setAsking] = useState(false),
    [approval, setApproval] = useState<string | null>(null);
  useEffect(() => setInspectorOpen(false), [page, run]);
  const [caseCargo, setCaseCargo] = useState(
    new URLSearchParams(location.search).get("cargo") || "",
  );
  const [evaluationId, setEvaluationId] = useState("");
  useEffect(() => setEvaluationId(""), [run]);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [diagnosisError, setDiagnosisError] = useState("");
  const [diagnosisRetry, setDiagnosisRetry] = useState(0);
  const initialRevision = useRef(
    new URLSearchParams(location.search).get("revision"),
  );
  const [restoringHistory, setRestoringHistory] = useState(
    initialRevision.current !== null,
  );
  const previousRun = useRef(run);
  const previousPage = useRef(page);
  useEffect(() => {
    const restore = () => window.location.reload();
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);
  const csrf = useRef(""),
    currentRun = useRef(run);
  currentRun.current = run;
  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("run", run);
    url.searchParams.set("departure", departureId);
    url.searchParams.set("page", page);
    if (caseCargo) url.searchParams.set("cargo", caseCargo);
    else url.searchParams.delete("cargo");
    if (selected) url.searchParams.set("entity", selected);
    else url.searchParams.delete("entity");
    if (history) url.searchParams.set("revision", String(history.revision));
    else if (!restoringHistory) url.searchParams.delete("revision");
    if (previousPage.current !== page) window.history.pushState(null, "", url);
    else window.history.replaceState(null, "", url);
    previousPage.current = page;
  }, [run, departureId, caseCargo, page, selected, history, restoringHistory]);
  const api = useCallback(async (path: string, body?: unknown) => {
    const r = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers:
        body === undefined
          ? {}
          : {
              "Content-Type": "application/json",
              "X-CSRF-Token": csrf.current,
            },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data;
    try {
      data = await r.json();
    } catch {
      throw Error(
        await Promise.resolve(
          r.status === 403
            ? "Your local session expired. Refresh the page."
            : `Request failed (${r.status})`,
        ),
      );
    }
    if (!r.ok)
      throw Error(
        typeof data.detail === "string"
          ? data.detail
          : JSON.stringify(data.detail || data),
      );
    return data;
  }, []);
  const login = useCallback(
    async (code?: string) => {
      try {
        const result = await api("/api/session", code ? { code } : {});
        csrf.current = result.csrf;
        setRole(result.role);
        if (code) setToast("Scenario administrator controls unlocked");
      } catch (e) {
        setError(String(e));
        throw e;
      }
    },
    [api],
  );
  const refresh = useCallback(async () => {
    const target = run;
    try {
      const [state, ev, ex, cmd, rs] = await Promise.all(
        [
          "/api/state",
          "/api/events",
          "/api/experiments",
          "/api/commands",
          "/api/runs",
        ].map((p) => api(`${p}?run=${target}`)),
      );
      if (currentRun.current !== target) return;
      setS((old) => (old && old.revision > state.revision ? old : state));
      setStateRun(target);
      setEvents(ev);
      setExperiments(ex);
      setCommands(cmd);
      setRuns(rs);
      setStatus("Connected");
      setUpdated(Date.now());
    } catch (e) {
      setStatus("Offline");
      setError(String(e));
    }
  }, [api, run]);
  useEffect(() => {
    login().catch(() => {});
    api("/api/evidence")
      .then(setSources)
      .catch((e) => setError(String(e)));
  }, [login, api]);
  useEffect(() => {
    setS(null);
    setDiagnosis(null);
    if (previousRun.current !== run) {
      setSelected("");
      setCaseCargo("");
      setHistory(null);
      previousRun.current = run;
    }
    if (initialRevision.current !== null) {
      const target = run,
        revision = Number(initialRevision.current);
      initialRevision.current = null;
      api(`/api/history/${revision}?run=${encodeURIComponent(target)}`)
        .then((value) => {
          if (currentRun.current === target) {
            setHistory(value);
            setPage((p) =>
              p === "Recovery" || p === "Scenario lab" ? "Evidence" : p,
            );
          }
        })
        .catch((e) => setError(String(e)))
        .finally(() => setRestoringHistory(false));
    }
    refresh();
    const timer = setInterval(refresh, 4000);
    const stream = new EventSource(`/api/stream?run=${run}`);
    stream.onmessage = () => refresh();
    stream.onerror = () => setStatus("Polling fallback");
    return () => {
      clearInterval(timer);
      stream.close();
    };
  }, [run, refresh]);
  useEffect(() => {
    const t = setInterval(
      () => setAge(updated ? Math.floor((Date.now() - updated) / 1000) : 0),
      1000,
    );
    return () => clearInterval(t);
  }, [updated]);
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(""), 5000);
      return () => clearTimeout(t);
    }
  }, [toast]);
  const command = async (cmd: Record<string, unknown>) => {
    if (!s || busy) return;
    if (history) {
      setError("Return to current state before submitting a command.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api(`/api/commands?run=${run}`, {
        ...cmd,
        command_id: crypto.randomUUID(),
        expected_revision: s.revision,
      });
      setToast(
        String(cmd.action).startsWith("approve_")
          ? ""
          : `Command ${result.status}. Movement completion is tracked separately.`,
      );
      await refresh();
    } catch (e) {
      setError(String(e));
      await refresh();
    } finally {
      setBusy(false);
    }
  };
  const compare = async () => {
    try {
      await api(`/api/experiments?run=${run}`, { seeds: 5, horizon: 180 });
      setPage("Recovery");
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  };
  const cancel = async (id: string) => {
    try {
      await api(`/api/experiments/${id}/cancel`, {});
      refresh();
    } catch (e) {
      setError(String(e));
    }
  };
  const fork = async (fresh: boolean, profile: string) => {
    try {
      const result = await api(`/api/runs?run=${run}`, {
        name: `${fresh ? "Fresh" : "Forked"} shift · ${new Date().toLocaleTimeString()}`,
        fresh,
        profile,
      });
      setRuns((old) => [
        ...old,
        { id: result.id, name: `Freshly created shift · ${result.id}` },
      ]);
      setRun(result.id);
      setPage((current) =>
        current === "Scenario lab" ? "Scenario lab" : "Operations",
      );
      setToast("Independent shift created. The original is preserved.");
    } catch (e) {
      setError(String(e));
    }
  };
  const replay = async (revision: number | null) => {
    if (revision === null) {
      setHistory(null);
      return;
    }
    try {
      const result = await api(`/api/history/${revision}?run=${run}`);
      setHistory(result);
      setPage("Operations");
      setSelected("");
    } catch (e) {
      setError(String(e));
    }
  };
  const assistantEpoch = useRef(0);
  useEffect(() => {
    assistantEpoch.current++;
    setAnswer(null);
    setAsking(false);
  }, [run, selected, history?.revision, evaluationId]);
  const ask = async (q: string) => {
    const epoch = ++assistantEpoch.current;
    setAsking(true);
    setQuestion(q);
    setAnswer(null);
    try {
      const result = await api(
        `/api/assistant?run=${encodeURIComponent(run)}`,
        {
          question: q,
          evaluation_id: evaluationId || null,
          selected: selected || null,
          revision: history?.revision ?? null,
        },
      );
      if (epoch === assistantEpoch.current) setAnswer(result);
    } catch (e) {
      if (epoch === assistantEpoch.current) setError(String(e));
    } finally {
      if (epoch === assistantEpoch.current) setAsking(false);
    }
  };
  useEffect(() => {
    let cancelled = false;
    api(`/api/inputs?run=${run}`)
      .then((rows) => {
        if (!cancelled) setInputs(rows);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [run, api]);
  // Never issue a diagnosis for a new run using the previous run's revision.
  const display = stateRun === run ? history?.state || s : null;
  const currentDiagnosis =
    diagnosis?.run === run && diagnosis?.revision === display?.revision
      ? diagnosis
      : null;
  useEffect(() => {
    if (!display) return;
    let active = true;
    setDiagnosisError("");
    api(
      `/api/diagnosis?run=${encodeURIComponent(run)}&revision=${display.revision}`,
    )
      .then((value) => {
        if (active) setDiagnosis(value);
      })
      .catch((e) => {
        if (active) setDiagnosisError(String(e));
      });
    return () => {
      active = false;
    };
  }, [api, run, display?.revision, diagnosisRetry]);
  const cargoOptions =
    display?.containers.filter((c) => c.commitment_id === departureId) || [];
  const focusedCargo = cargoOptions.some((c) => c.id === caseCargo)
    ? caseCargo
    : cargoOptions[0]?.id || "";
  const visitDiagnosis = currentDiagnosis?.manifest.find(
    (r) => r.container_id === focusedCargo,
  );
  const chooseDeparture = (id: string) => {
    setDepartureId(id);
    const cargo =
      display?.containers.find((c) => c.commitment_id === id)?.id || "";
    setCaseCargo(cargo);
    setSelected(cargo);
  };
  const selectEntity = (id: string) => {
    setSelected(id);
    if (
      page === "Work & commitments" ||
      page === "Evidence" ||
      page === "Scenario lab"
    )
      setInspectorOpen(true);
    const cargoId = display?.jobs.find((j) => j.id === id)?.container_id || id;
    const cargo = display?.containers.find((c) => c.id === cargoId);
    if (cargo?.commitment_id) {
      setCaseCargo(cargo.id);
      setDepartureId(cargo.commitment_id);
    } else if (display?.commitments.some((c) => c.id === id))
      chooseDeparture(id);
  };
  const inspectCase = (id: string) => {
    selectEntity(id);
    setPage("Evidence");
  };
  const navigateCase = (target: Workspace) => {
    if (history && (target === "Recovery" || target === "Scenario lab")) return;
    setPage(target);
    if (target === "Operations") setOperationsView("departure");
    if (target === "Evidence") setSelected(focusedCargo);
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setPage("Operations");
          }}
        >
          <div>
            <Anchor size={23} />
          </div>
          <span>
            NORTHSTAR<small>TERMINAL RECOVERY LAB</small>
          </span>
        </a>
        <div className="nav-caption">WORKSPACES</div>
        <nav>
          {pages.map(({ name, icon: Icon }) => (
            <button
              key={name}
              className={page === name ? "active" : ""}
              aria-label={name}
              onClick={() => {
                setPage(name);
                if (name === "Evidence" && !selected) setSelected(focusedCargo);
                if (
                  name !== "Operations" &&
                  name !== "Work & commitments" &&
                  name !== "Evidence"
                )
                  setHistory(null);
              }}
            >
              <Icon size={18} />
              <span>{name}</span>
              {name === "Recovery" &&
                experiments.some((e) => e.status === "completed") && (
                  <i className="nav-dot" />
                )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="lab-label">
            <FlaskConical size={16} />
            <span>
              Synthetic environment<small>No live terminal connections</small>
            </span>
          </div>
          <button className="learn-link" onClick={() => setPage("Evidence")}>
            <BookOpen size={16} /> Inspect the model <ArrowUpRight size={14} />
          </button>
          <span className="version">V1.0 · LOCAL LEARNING EDITION</span>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">
            Northstar <span>/</span> {page}
          </div>
          <div className="top-controls">
            <select
              aria-label="Active shift"
              value={run}
              onChange={(e) => setRun(e.target.value)}
            >
              {runs.length ? (
                runs.map((r) => (
                  <option value={r.id} key={r.id}>
                    {r.name}
                  </option>
                ))
              ) : (
                <option value="main">Morning shift</option>
              )}
            </select>
            <span
              className={`connection ${age > 10 || status === "Offline" ? "offline" : ""}`}
              title={`Last successful database read ${age}s ago`}
            >
              <i />
              {status === "Connected" && age <= 10
                ? "Fresh state"
                : status === "Connected"
                  ? "Stale state"
                  : status}
            </span>
            <button
              className="assistant-trigger"
              onClick={() => setAssistantOpen(!assistantOpen)}
            >
              <MessageSquare size={17} />
              <span>Ask the terminal</span>
            </button>
          </div>
        </header>
        {error && (
          <div className="error-banner" role="alert">
            <span>{error}</span>
            <button aria-label="Dismiss error" onClick={() => setError("")}>
              <X size={16} />
            </button>
          </div>
        )}
        {toast && (
          <div className="toast" role="status">
            {toast}
          </div>
        )}
        {!display ? (
          <div className="loading">
            <Anchor size={36} />
            <h2>Connecting to Northstar</h2>
            <p>Loading the PostgreSQL-backed shift…</p>
            {status === "Offline" && (
              <button className="primary" onClick={refresh}>
                Retry connection
              </button>
            )}
          </div>
        ) : (
          <>
            <div className="clockbar">
              <div className="shift-title">
                <span className="eyebrow">SIMULATION CLOCK</span>
                <strong className="mono">{clock(display.minute)}</strong>
                <Badge
                  value={
                    history ? "historical" : s?.running ? "running" : "paused"
                  }
                />
                <span className="micro">
                  r{display.revision} · {display.policy}
                </span>
              </div>
              {history ? (
                <div className="input-row">
                  <b>Read-only snapshot · revision {history.revision}</b>
                  <button className="primary" onClick={() => setHistory(null)}>
                    Return to current state
                  </button>
                </div>
              ) : (
                <div className="clock-controls">
                  <select
                    aria-label="Simulation speed"
                    value={s?.speed || 1}
                    disabled={busy}
                    onChange={(e) =>
                      command({
                        action: "clock",
                        running: s?.running,
                        speed: Number(e.target.value),
                      })
                    }
                  >
                    <option value="1">1× speed</option>
                    <option value="2">2× speed</option>
                    <option value="5">5× speed</option>
                  </select>
                  <button
                    className="secondary"
                    disabled={busy || s?.running}
                    onClick={() => command({ action: "advance", minutes: 5 })}
                  >
                    <StepForward size={16} /> +5 min
                  </button>
                  <button
                    className="primary"
                    disabled={busy}
                    onClick={() =>
                      command({
                        action: s?.running ? "pause" : "clock",
                        running: !s?.running,
                        speed: s?.speed,
                      })
                    }
                  >
                    {s?.running ? <Pause size={16} /> : <Play size={16} />}{" "}
                    {s?.running ? "Pause" : "Run shift"}
                  </button>
                </div>
              )}
            </div>
            <div
              className={`workspace ${inspectorOpen && selected && !(page === "Operations" && operationsView === "departure") ? "with-inspector" : ""}`}
            >
              <main className="content">
                {!history && <ActionReceipt key={run} commands={commands} />}
                {!(page === "Operations" && operationsView === "departure") && (
                  <CaseContext
                    s={display}
                    report={currentDiagnosis}
                    departure={departureId}
                    cargo={focusedCargo}
                    chooseDeparture={chooseDeparture}
                    chooseCargo={selectEntity}
                    navigate={navigateCase}
                    page={page}
                    historical={!!history}
                  />
                )}
                {!currentDiagnosis && (
                  <div className="diagnosis-loading" role="status">
                    {diagnosisError
                      ? `Diagnosis unavailable: ${diagnosisError}`
                      : "Reading decision facts for this revision…"}
                    {diagnosisError && (
                      <button onClick={() => setDiagnosisRetry((x) => x + 1)}>
                        Retry diagnosis
                      </button>
                    )}
                  </div>
                )}
                {page === "Operations" &&
                  operationsView === "overview" &&
                  currentDiagnosis && (
                    <DepartureAttention
                      report={currentDiagnosis}
                      choose={chooseDeparture}
                    />
                  )}
                {page === "Work & commitments" && currentDiagnosis && (
                  <details className="panel">
                    <summary>Selected case diagnosis</summary>
                    <DiagnosisPanel
                      s={display}
                      report={currentDiagnosis}
                      row={visitDiagnosis}
                      navigate={navigateCase}
                      inspect={inspectCase}
                      historical={!!history}
                    />
                  </details>
                )}
                {page === "Recovery" && (
                  <p className="case-status">
                    Following{" "}
                    {focusedCargo ? cargoName(focusedCargo) : "this departure"}.
                    Recommendations include competing work across the terminal.
                  </p>
                )}

                {display.schedule &&
                  page !== "Recovery" &&
                  !(
                    page === "Operations" && operationsView === "departure"
                  ) && (
                    <section className="panel approved-schedule">
                      <div className="section-heading">
                        <h3>
                          {history
                            ? "Schedule at this revision"
                            : "Shared approved schedule"}{" "}
                          · {display.schedule.status}
                        </h3>
                        {!history && (
                          <button
                            className="text-button"
                            onClick={() => navigateCase("Recovery")}
                          >
                            Inspect bookings & outcomes
                          </button>
                        )}
                      </div>
                      <p>
                        {display.schedule.title} · approval basis r
                        {display.schedule.base_revision}.{" "}
                        {
                          display.schedule.rows.filter(
                            (r) =>
                              display.jobs.find((j) => j.id === r.job_id)
                                ?.status === "completed",
                          ).length
                        }{" "}
                        / {display.schedule.rows.length} booked moves completed.
                      </p>
                      {display.schedule.reason && (
                        <p>{display.schedule.reason}</p>
                      )}
                      <details>
                        <summary>
                          Inspect the approved equipment timeline
                        </summary>
                        <p className="micro">
                          Planned intervals from approval, not GPS observations.
                          Interrupted or withdrawn future bookings are released;
                          in-progress equipment remains occupied.
                        </p>
                        <ScheduleTimeline
                          s={display}
                          mode="approved"
                          rows={display.schedule.rows}
                          start={Math.min(
                            ...display.schedule.rows.map((r) => r.start),
                            display.minute,
                          )}
                          end={display.schedule.end_minute}
                          select={selectEntity}
                        />
                      </details>
                      {page === "Scenario lab" && (
                        <p className="micro">
                          A scenario branch inherits physical work in progress,
                          but does not inherit this run's resource bookings.
                          Compare and approve a new schedule in the branch.
                        </p>
                      )}
                    </section>
                  )}
                {page === "Scenario lab" && (
                  <nav className="review-tabs" aria-label="Scenario lab views">
                    {["Disruption", "Evaluation", "Input packs"].map((v) => (
                      <button
                        key={v}
                        aria-pressed={labView === v}
                        onClick={() => setLabView(v)}
                      >
                        {v}
                      </button>
                    ))}
                  </nav>
                )}
                {((page === "Scenario lab" && labView === "Evaluation") ||
                  page === "Evidence") &&
                  s &&
                  !history && (
                    <details className="panel" open={page === "Scenario lab"}>
                      <summary>Strategy evaluation</summary>
                      <EvaluationPanel
                        key={run}
                        run={run}
                        s={s}
                        api={api}
                        readOnly={!!history}
                        onReportSelect={setEvaluationId}
                      />
                    </details>
                  )}
                {((page === "Scenario lab" && labView === "Input packs") ||
                  page === "Evidence") && (
                  <details className="panel" open={page === "Scenario lab"}>
                    <summary>Input sources & reconciliation</summary>
                    <DataInputs
                      s={display}
                      run={run}
                      selected={selected}
                      request={api}
                      role={role}
                      historical={!!history}
                      allowImport={page === "Scenario lab"}
                      inspect={selectEntity}
                      activate={(id) => {
                        setRun(id);
                        setSelected("");
                        setHistory(null);
                        setToast(
                          "Input pack imported into a new paused shift. Step the clock to deliver test observations.",
                        );
                      }}
                    />
                  </details>
                )}
                {page === "Operations" && (
                  <div
                    className="operations-switch"
                    role="group"
                    aria-label="Operations view"
                  >
                    <button
                      className={operationsView === "departure" ? "active" : ""}
                      onClick={() => setOperationsView("departure")}
                    >
                      Departure workspace
                    </button>
                    <button
                      className={operationsView === "overview" ? "active" : ""}
                      onClick={() => setOperationsView("overview")}
                    >
                      Terminal overview
                    </button>
                  </div>
                )}
                {page === "Operations" && operationsView === "departure" && (
                  <CaseWorkspace
                    key={run}
                    s={display}
                    run={run}
                    departure={departureId}
                    cargoId={focusedCargo}
                    selected={selected}
                    chooseDeparture={chooseDeparture}
                    chooseCargo={selectEntity}
                    selectWork={setSelected}
                    request={api}
                    command={command}
                    historical={!!history}
                    stale={age > 10 || status === "Offline"}
                    diagnosis={currentDiagnosis}
                    inspect={inspectCase}
                    start={() => replay(0)}
                  />
                )}
                {page === "Operations" && operationsView === "overview" && (
                  <>
                    <div className="page-heading compact">
                      <div>
                        <div className="eyebrow">OPERATIONS OVERVIEW</div>
                        <h1>Terminal overview</h1>
                        <p>
                          Select a vessel, yard bay, container or crane to
                          follow its work.
                        </p>
                      </div>
                      <span className="outlined-label">
                        SCHEMATIC · SYNTHETIC DATA
                      </span>
                    </div>
                    <div className="notice">
                      <div>
                        <b>
                          {history
                            ? "Historical inspection"
                            : "Current saved shift"}{" "}
                          · {clock(display.minute)} · revision{" "}
                          {display.revision}
                        </b>
                        <p>
                          {
                            display.jobs.filter((j) => j.status === "completed")
                              .length
                          }{" "}
                          completed jobs are history. Click any ship to see
                          cargo aboard, expected arrivals and past handling.
                        </p>
                        <button
                          className="text-button"
                          onClick={() => replay(0)}
                        >
                          Explore starting state · 08:00
                        </button>
                      </div>
                    </div>
                    <MetricStrip s={display} />
                    <div className="map-toolbar">
                      <div className="segmented">
                        {["all", "import", "rail", "vessel"].map((f) => (
                          <button
                            key={f}
                            className={flow === f ? "active" : ""}
                            onClick={() => setFlow(f)}
                          >
                            {f === "all"
                              ? "All flows"
                              : f === "rail"
                                ? "Rail exports"
                                : f === "vessel"
                                  ? "Vessel exports"
                                  : "Imports"}
                          </button>
                        ))}
                      </div>
                      <div className="selection-hint">
                        {selected
                          ? `Tracing ${selected}`
                          : "Click the map to investigate"}
                      </div>
                    </div>
                    <TerminalMap
                      s={display}
                      selected={selected}
                      select={selectEntity}
                      flow={flow}
                    />
                    <div className="section-heading">
                      <h3>Outbound commitments</h3>
                      <button
                        className="text-button"
                        onClick={() => setPage("Work & commitments")}
                      >
                        View all work <ArrowRight size={15} />
                      </button>
                    </div>
                    <label className="case-status">
                      <input
                        type="checkbox"
                        checked={allWork}
                        onChange={(e) => setAllWork(e.target.checked)}
                      />{" "}
                      Show the whole terminal queue (otherwise this cargo's
                      required chain)
                    </label>
                    <div className="operation-footer">
                      <span>
                        <i className="live-dot" />
                        Positions and progress come from persisted transitions.
                      </span>
                      <span>
                        24 active cargo visits ·{" "}
                        {display.containers.length - 24} stored inventory
                      </span>
                    </div>
                  </>
                )}
                {page === "Work & commitments" && (
                  <>
                    <div className="page-heading">
                      <div>
                        <div className="eyebrow">FLOW & DEPENDENCIES</div>
                        <h1>Work & commitments</h1>
                        <p>
                          One work queue connects the quay, yard, road gate and
                          rail cutoffs.
                        </p>
                      </div>
                    </div>
                    <ResourceCompetition
                      s={display}
                      diagnosis={currentDiagnosis}
                      select={selectEntity}
                    />
                    <label className="case-status">
                      <input
                        type="checkbox"
                        checked={allWork}
                        onChange={(e) => setAllWork(e.target.checked)}
                      />{" "}
                      Show the whole terminal queue (otherwise this cargo's
                      required chain)
                    </label>
                    <div className="panel work-panel">
                      <div className="section-heading">
                        <div className="segmented">
                          {[
                            "active",
                            "all",
                            "queued",
                            "running",
                            "completed",
                          ].map((f) => (
                            <button
                              className={workFilter === f ? "active" : ""}
                              key={f}
                              onClick={() => setWorkFilter(f)}
                            >
                              {f}
                            </button>
                          ))}
                        </div>
                        <div className="search-input">
                          <Search size={15} />
                          <input
                            placeholder="Find cargo, move or equipment"
                            aria-label="Search handling moves"
                            value={search}
                            onChange={(e) => setSearch(e.target.value)}
                          />
                        </div>
                      </div>
                      <JobTable
                        jobs={display.jobs.filter(
                          (j) =>
                            (allWork ||
                              !!visitDiagnosis?.job_ids.includes(j.id)) &&
                            (workFilter === "all" ||
                              (workFilter === "active" &&
                                j.status !== "completed") ||
                              j.status === workFilter) &&
                            `${j.id} ${j.container_id} ${j.equipment_id} ${j.source_id} ${j.target_id} ${j.commitment_id} ${j.visit_id}`
                              .toLowerCase()
                              .includes(search.toLowerCase()),
                        )}
                        selected={selected}
                        select={selectEntity}
                      />
                    </div>
                    <p className="micro">
                      Blocked ≠ risky by probability. Cutoff, precedence,
                      physical accessibility, authority, resource reach and
                      capacity are distinct checks.
                    </p>
                  </>
                )}
                {page === "Recovery" && s && (
                  <Recovery
                    departure={departureId}
                    request={api}
                    command={command}
                    s={s}
                    experiments={experiments}
                    commands={commands}
                    compare={compare}
                    approve={setApproval}
                    select={selectEntity}
                    cancel={cancel}
                    run={run}
                    caseCargo={focusedCargo}
                  />
                )}
                {page === "Scenario lab" && labView === "Disruption" && s && (
                  <Scenarios
                    recover={() => navigateCase("Recovery")}
                    select={selectEntity}
                    inputs={inputs}
                    recordInput={async (body) => {
                      await api(`/api/inputs?run=${run}`, body);
                      setInputs(await api(`/api/inputs?run=${run}`));
                    }}
                    s={s}
                    role={role}
                    login={login}
                    command={command}
                    fork={fork}
                    experiments={experiments}
                    compare={compare}
                    cancel={cancel}
                  />
                )}
                {page === "Evidence" && s && !history && (
                  <AssistantTraces key={run} run={run} api={api} />
                )}
                {page === "Evidence" && s && (
                  <Evidence
                    inputs={inputs}
                    s={display!}
                    events={history?.events || events}
                    sources={sources}
                    selected={selected}
                    select={selectEntity}
                    replay={replay}
                  />
                )}
              </main>
              {inspectorOpen &&
                selected &&
                !(page === "Operations" && operationsView === "departure") && (
                  <Inspector
                    s={display}
                    id={selected}
                    select={selectEntity}
                    close={() => setInspectorOpen(false)}
                    command={command}
                    role={history ? "reader" : role}
                    onEvidence={() => {
                      setPage("Evidence");
                    }}
                  />
                )}
            </div>
          </>
        )}
      </div>
      {assistantOpen && (
        <aside className="assistant">
          <div className="section-heading">
            <h3>
              <MessageSquare size={19} /> Terminal assistant
            </h3>
            <button
              aria-label="Close assistant"
              onClick={() => setAssistantOpen(false)}
            >
              <X size={19} />
            </button>
          </div>
          <Badge value={answer?.mode || "evidence tools"} />
          <p className="micro">
            Cited facts come from bounded tools at one revision. OpenAI guidance
            is optional; local evidence tools work without a key. The assistant
            cannot approve or execute actions.
          </p>
          <div className="assistant-context">
            Context: <b>{selected || "whole terminal"}</b>
          </div>
          <div className="suggestions">
            {[
              "Explain the selected entity",
              "What needs attention?",
              "How is risk calculated?",
              "What did we know?",
              "What do evaluation results show?",
              "Compare saved plans",
              "What if YC-3 remains down?",
            ].map((q) => (
              <button key={q} onClick={() => ask(q)}>
                {q}
                <ArrowRight size={14} />
              </button>
            ))}
          </div>
          {asking && (
            <p role="status" className="micro">
              Retrieving revision-bound evidence… Equipment what-ifs can take
              about 20 seconds on this laptop.
            </p>
          )}
          {answer && (
            <div className="assistant-answer">
              <p>{answer.answer}</p>
              <small>
                Evidence at revision {answer.revision} · {answer.mode}
              </small>
              {answer.fallback_reason && (
                <p className="micro">
                  Local fallback: {answer.fallback_reason}
                </p>
              )}
              <div className="assistant-citations">
                {answer.citations?.map((c) => (
                  <a key={c.id} href={c.href} target="_blank" rel="noreferrer">
                    {c.id} · inspect supporting evidence
                  </a>
                ))}
              </div>
              <small>Trace {answer.trace_id}</small>
              <details>
                <summary>Inspect tool calls</summary>
                <pre>{JSON.stringify(answer.calls, null, 2)}</pre>
              </details>
            </div>
          )}
          <form
            className="assistant-form"
            onSubmit={(e) => {
              e.preventDefault();
              if (question.trim()) ask(question);
            }}
          >
            <input
              value={question}
              aria-label="Question for terminal assistant"
              placeholder="Ask about this state…"
              onChange={(e) => setQuestion(e.target.value)}
            />
            <button className="primary" disabled={asking || !question.trim()}>
              {asking ? "…" : "Ask"}
            </button>
          </form>
        </aside>
      )}
      {approval && (
        <div className="modal-backdrop">
          <section className="modal small">
            <div className="eyebrow">HUMAN APPROVAL</div>
            <h2>Apply this recovery policy?</h2>
            <p>
              This will change queued assignments and dispatch priority in the
              current simulated shift. In-flight moves, release holds and
              capacity constraints remain enforced. The server rechecks the
              plan’s revision before applying it.
            </p>
            <div className="input-row">
              <button className="secondary" onClick={() => setApproval(null)}>
                Cancel
              </button>
              <button
                className="primary"
                onClick={() => {
                  command({ action: "approve_plan", plan_id: approval });
                  setApproval(null);
                }}
              >
                Approve & submit
              </button>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
