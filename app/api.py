import os, secrets, logging, threading, time, uuid
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Literal
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ConfigDict, model_validator
from .store import Store, ROOT
from . import runtime
from .domain import RuleError, enrich, seed_state
from .planning import enqueue_experiment, work_experiment
from .tools import inspect_entity
from .assistant import assistant, configured
from psycopg.types.json import Jsonb

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
LOG = logging.getLogger("terminal.api")
store = Store()
stop = threading.Event()
sessions = {}
LOCAL = Path(os.getenv("TERMINAL_STATE_DIR", str(ROOT / ".local")))
LOCAL.mkdir(parents=True, exist_ok=True)
code_path = LOCAL / "admin-code"
if not code_path.exists():
    code_path.write_text(secrets.token_urlsafe(12))
    code_path.chmod(0o600)
ADMIN_CODE = code_path.read_text().strip()


def worker(exit_event):
    last = time.monotonic()
    while not exit_event.is_set():
        try:
            runtime.mark("commands", "working")
            processed = store.process_one()
            if time.monotonic() - last >= 1:
                store.auto_tick()
                last = time.monotonic()
            runtime.mark("commands")
            if not processed:
                exit_event.wait(0.15)
        except Exception:
            runtime.mark("commands", "failed")
            LOG.exception("worker_cycle_failed")
            exit_event.wait(2)


def planner(exit_event):
    while not exit_event.is_set():
        try:
            runtime.mark("planner", "working")
            from .schedule_store import work as work_schedule

            from .evaluation_store import work as work_evaluation

            if (
                not work_schedule(store)
                and not work_evaluation(store)
                and not work_experiment(store)
            ):
                runtime.mark("planner")
                exit_event.wait(0.5)
        except Exception:
            runtime.mark("planner", "failed")
            LOG.exception("planner_cycle_failed")
            exit_event.wait(2)


@asynccontextmanager
async def lifespan(app):
    store.initialize()
    stop.clear()
    exit_event = threading.Event()
    (LOCAL / "api.pid").write_text(str(os.getpid()))
    threads = [
        threading.Thread(target=worker, args=(exit_event,), daemon=True),
        threading.Thread(target=planner, args=(exit_event,), daemon=True),
    ]
    for t in threads:
        t.start()
    yield
    stop.set()
    exit_event.set()
    for t in threads:
        t.join(timeout=30)
    pidfile = LOCAL / "api.pid"
    if pidfile.exists() and pidfile.read_text() == str(os.getpid()):
        pidfile.unlink()


app = FastAPI(title="Terminal Recovery Lab", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def protect(request: Request, call_next):
    host = request.headers.get("host", "")
    allowed = os.getenv(
        "TERMINAL_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver"
    ).split(",")
    if host.split(":")[0] not in allowed:
        return Response("Local host only", status_code=403)
    proxy_key = os.getenv("TERMINAL_PROXY_KEY")
    if (
        host.split(":")[0] not in ("127.0.0.1", "localhost", "testserver")
        and not proxy_key
    ):
        return Response(
            "Nonlocal access requires an authenticated proxy", status_code=403
        )
    if proxy_key and not secrets.compare_digest(
        request.headers.get("x-terminal-proxy", ""), proxy_key
    ):
        return Response("Authenticated proxy required", status_code=403)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        # Bound the actual body, including chunked requests, before parsing.
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 65536:
                return Response("Request body exceeds 64 KiB", status_code=413)
        request._body = bytes(body)
        origin = request.headers.get("origin")
        if origin and origin not in (f"http://{host}", f"https://{host}"):
            return Response("Cross-origin mutation rejected", status_code=403)
        if request.url.path not in ("/api/session", "/api/integrations/equipment"):
            session = sessions.get(request.cookies.get("terminal_session", ""))
            if (
                not session
                or session.get("expires", 0) < time.time()
                or request.headers.get("x-csrf-token") != session["csrf"]
            ):
                return Response(
                    "Valid local session and CSRF token required", status_code=403
                )
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = (
        "no-store" if request.url.path.startswith("/api") else "no-cache"
    )
    return response


@app.exception_handler(RuleError)
async def rule_error(request, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse({"detail": str(exc)}, status_code=409)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Strict):
    code: str | None = None


@app.post("/api/session")
def session(body: Login, response: Response):
    if body.code and not secrets.compare_digest(body.code, ADMIN_CODE):
        raise HTTPException(403, "Scenario administrator code incorrect")
    role = "scenario-admin" if body.code else "operator"
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    for expired in [
        k for k, v in sessions.items() if v.get("expires", 0) < time.time()
    ]:
        sessions.pop(expired, None)
    if len(sessions) >= 1000:
        raise HTTPException(429, "Session limit reached")
    sessions[token] = dict(role=role, csrf=csrf, expires=time.time() + 86400)
    response.set_cookie(
        "terminal_session",
        token,
        httponly=True,
        samesite="strict",
        max_age=86400,
        secure=os.getenv("TERMINAL_SECURE_COOKIE") == "1",
    )
    return dict(role=role, csrf=csrf)


def role(request):
    return sessions.get(request.cookies.get("terminal_session", ""), {}).get(
        "role", "reader"
    )


def admin(request):
    if role(request) != "scenario-admin":
        raise HTTPException(403, "Scenario administrator session required")


@app.get("/api/health")
def health():
    with store.connect() as c:
        c.execute("SELECT 1")
    return dict(
        status="ok",
        database="PostgreSQL",
        data="synthetic",
        llm=(
            "OpenAI configured"
            if configured()
            else "evidence fallback; OpenAI not configured"
        ),
    )


@app.get("/api/runs")
def runs():
    return store.list_rows("runs")


@app.get("/api/state")
def state(run: str = "main"):
    return enrich(store.read(run))


@app.get("/api/events")
def events(run: str = "main", limit: int = 100):
    return store.list_rows("events", run, max(1, min(limit, 300)))


@app.get("/api/commands")
def commands(run: str = "main"):
    return store.list_rows("commands", run, 30)


@app.get("/api/history/{revision}")
def history(revision: int, run: str = "main"):
    result = store.history(run, revision)
    result["state"] = enrich(result["state"])
    with store.connect() as c:
        result["events"] = c.execute(
            "SELECT * FROM events WHERE run_id=%s AND revision<=%s ORDER BY id DESC LIMIT 100",
            (run, revision),
        ).fetchall()
    return result


@app.get("/api/evidence")
def evidence():
    return store.list_rows("source_assertions")


@app.get("/api/tools/inspect/{entity_id}")
def inspect(entity_id: str, run: str = "main"):
    return inspect_entity(store.read(run), entity_id)


@app.get("/api/access/{job_id}")
def access_preview(job_id: str, run: str = "main"):
    from .rehandles import propose

    return propose(store.read(run), job_id)


class Command(Strict):
    command_id: str = Field(min_length=8, max_length=80)
    expected_revision: int = Field(ge=0)
    action: Literal[
        "advance",
        "clock",
        "pause",
        "close_route",
        "open_route",
        "fail",
        "repair",
        "dispatch",
        "release",
        "approve_plan",
        "approve_schedule",
        "approve_placement",
        "withdraw_schedule",
        "resume_dispatch",
        "correct",
        "approve_access",
        "obstruct",
    ]
    entity_id: str | None = Field(default=None, max_length=80)
    minutes: int = Field(default=1, ge=1, le=15)
    running: bool = False
    speed: Literal[1, 2, 5] = 1
    released: bool = False
    valid_minute: int = Field(default=0, ge=0)
    value: Literal["available", "failed"] = "available"
    plan_id: str | None = None
    destination_id: str | None = Field(default=None, max_length=80)
    proposal_token: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def require_target(self):
        if (
            self.action
            in (
                "close_route",
                "open_route",
                "fail",
                "repair",
                "release",
                "correct",
                "dispatch",
                "approve_access",
                "obstruct",
            )
            and not self.entity_id
        ):
            raise ValueError("This action requires entity_id")
        if (
            self.action in ("approve_plan", "approve_schedule", "approve_placement")
            and not self.plan_id
        ):
            raise ValueError("Plan approval requires plan_id")
        if self.action == "approve_placement" and not self.destination_id:
            raise ValueError("Placement approval requires destination_id")
        if self.action == "approve_access" and not self.proposal_token:
            raise ValueError("Access approval needs a preview token")
        return self


@app.post("/api/commands", status_code=202)
def command(body: Command, request: Request, run: str = "main"):
    if body.action in (
        "fail",
        "repair",
        "release",
        "correct",
        "obstruct",
        "close_route",
        "open_route",
    ):
        admin(request)
    result = store.enqueue(run, body.model_dump(exclude_none=True), role(request))
    if result["status"] == "rejected":
        raise HTTPException(409, result["result"]["error"])
    return result


class PlacementRequest(Strict):
    expected_revision: int = Field(ge=0)
    job_id: str = Field(min_length=1, max_length=80)


@app.post("/api/placements")
def placement(body: PlacementRequest, run: str = "main"):
    from .placement_store import create

    return create(store, run, body.expected_revision, body.job_id)


@app.get("/api/placements")
def placements(job_id: str, run: str = "main"):
    from .placement_store import listing

    return listing(store, run, job_id)


class ScheduleRequest(Strict):
    expected_revision: int = Field(ge=0)
    focus_commitment: str = Field(min_length=1, max_length=80)
    horizon: int = Field(default=180, ge=30, le=240)


@app.post("/api/schedules", status_code=202)
def schedule(body: ScheduleRequest, run: str = "main"):
    from .schedule_store import enqueue

    return dict(
        id=enqueue(
            store, run, body.expected_revision, body.focus_commitment, body.horizon
        )
    )


@app.get("/api/schedules")
def schedules(run: str = "main"):
    from .schedule_store import listing

    return listing(store, run)


@app.get("/api/schedules/feedback")
def schedule_feedback(run: str = "main"):
    from .schedule_store import feedback

    return feedback(store, run)


class EvaluationRequest(Strict):
    expected_revision: int = Field(ge=0)
    suite: Literal["development", "holdout", "case", "movement"] = "holdout"
    source_request: str | None = Field(default=None, max_length=80)


@app.post("/api/evaluations", status_code=202)
def evaluate(body: EvaluationRequest, run: str = "main"):
    from .evaluation_store import enqueue

    return dict(
        id=enqueue(store, run, body.expected_revision, body.suite, body.source_request)
    )


@app.get("/api/evaluations")
def evaluations(run: str = "main"):
    from .evaluation_store import listing

    return listing(store, run)


@app.get("/api/evaluations/{eid}")
def evaluation_report(eid: str, run: str = "main", export: bool = False):
    from .evaluation_store import report

    return report(store, run, eid, export)


@app.post("/api/evaluations/{eid}/cancel")
def cancel_evaluation(eid: str, run: str = "main"):
    from .evaluation_store import cancel

    return cancel(store, run, eid)


@app.get("/api/assistant/traces")
def assistant_traces(run: str = "main"):
    with store.connect() as c:
        return c.execute(
            "SELECT id,revision,mode,question,answer,elapsed_ms,usage,created_at FROM assistant_traces WHERE run_id=%s ORDER BY created_at DESC LIMIT 20",
            (run,),
        ).fetchall()


class Experiment(Strict):
    seeds: int = Field(default=5, ge=2, le=12)
    horizon: int = Field(default=180, ge=30, le=240)


@app.post("/api/experiments", status_code=202)
def experiment(body: Experiment, run: str = "main"):
    # Stable approval evidence: the planner explicitly pauses before comparison.
    current = store.read(run)
    if current.get("schedule"):
        raise HTTPException(
            409, "Use executable schedule comparison while a schedule controls this run"
        )
    if current["running"]:
        raise HTTPException(409, "Pause the clock before comparing recovery plans")
    return dict(id=enqueue_experiment(store, run, body.seeds, body.horizon))


@app.get("/api/experiments")
def experiments(run: str = "main"):
    rows = store.list_rows("experiments", run, 12)
    return [{k: v for k, v in r.items() if k != "snapshot"} for r in rows]


@app.post("/api/experiments/{id}/cancel")
def cancel(id: str):
    with store.connect() as c:
        c.execute(
            "UPDATE experiments SET status='cancelled' WHERE id=%s AND status IN ('queued','running')",
            (id,),
        )
    return dict(status="cancelled")


@app.get("/api/experiments/{id}/export")
def export(id: str):
    with store.connect() as c:
        row = c.execute("SELECT * FROM experiments WHERE id=%s", (id,)).fetchone()
    if not row:
        raise HTTPException(404, "Experiment not found")
    return row


@app.get("/api/plans")
def plans(run: str = "main"):
    return store.list_rows("plans", run, 20)


class Fork(Strict):
    name: str = Field(min_length=1, max_length=80)
    fresh: bool = False
    profile: Literal["small", "standard"] = "standard"


@app.post("/api/runs", status_code=201)
def fork(body: Fork, request: Request, run: str = "main"):
    admin(request)
    with store.connect() as c:
        s = seed_state(body.profile) if body.fresh else store.read(run, c, lock=True)
        s["revision"] = 0
        s["running"] = False
        s["plan_id"] = None
        # A branch inherits physical work, not another run's resource bookings.
        s.pop("schedule", None)
        # Observations remain inherited with their provenance; revision references belong to parent.
        s["parent"] = (
            dict(run_id=run, revision=store.read(run, c)["revision"])
            if not body.fresh
            else None
        )
        s["observations"] = []
        id = str(uuid.uuid4())[:8]
        store.create_run(c, id, body.name, s)
    return dict(id=id)


class InputEvent(Strict):
    source: str = Field(min_length=1, max_length=80)
    source_event_id: str = Field(min_length=1, max_length=100)
    entity_id: str = Field(min_length=1, max_length=80)
    event_time: int = Field(ge=0)
    value: Literal["available", "failed"]


@app.post("/api/inputs")
def input_event(body: InputEvent, request: Request, run: str = "main"):
    admin(request)
    from .inputs import record

    return record(store, run, body.model_dump())


@app.get("/api/inputs")
def inputs(run: str = "main"):
    with store.connect() as c:
        return c.execute(
            "SELECT * FROM input_events WHERE run_id=%s ORDER BY id DESC LIMIT 100",
            (run,),
        ).fetchall()


@app.get("/api/diagnosis")
def departure_diagnosis(run: str = "main", revision: int | None = None):
    from .diagnosis import diagnose

    return diagnose(store, run, revision)


@app.get("/api/datasets")
def dataset_catalog():
    from .datasets import catalog

    return catalog()


class DatasetImport(Strict):
    pack_id: str = Field(max_length=80)
    request_id: uuid.UUID
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


@app.post("/api/datasets/import", status_code=201)
def dataset_import(body: DatasetImport, request: Request):
    admin(request)
    from .datasets import import_pack

    return import_pack(store, body.pack_id, str(body.request_id), body.expected_digest)


@app.get("/api/datasets/evidence")
def dataset_evidence(
    run: str = "main", revision: int | None = None, entity: str = "YC-1"
):
    from .data_evidence import evidence

    return evidence(store, run, revision, entity)


class Ask(Strict):
    evaluation_id: str | None = Field(default=None, max_length=80)
    question: str = Field(min_length=1, max_length=1000)
    selected: str | None = None
    revision: int | None = Field(default=None, ge=0)


@app.post("/api/assistant")
def ask(body: Ask, run: str = "main"):
    return assistant(
        store, run, body.question, body.selected, body.revision, body.evaluation_id
    )


@app.get("/api/stream")
def stream(run: str = "main"):
    # Database is the replay authority; SSE is only an invalidation hint.
    def generate():
        import json

        last = -1
        while not stop.is_set():
            try:
                with store.connect() as c:
                    row = c.execute(
                        "SELECT revision FROM runs WHERE id=%s", (run,)
                    ).fetchone()
                if not row:
                    break
                if row["revision"] != last:
                    last = row["revision"]
                    yield f"id: {last}\ndata: " + json.dumps(
                        {"revision": last}
                    ) + "\n\n"
                else:
                    yield ": heartbeat\n\n"
            except Exception:
                yield "event: degraded\ndata: {}\n\n"
            time.sleep(2)

    return StreamingResponse(generate(), media_type="text/event-stream")


DIST = ROOT / "frontend/dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/")
    def index():
        return FileResponse(DIST / "index.html")


class EquipmentObservation(Strict):
    schema_version: Literal[1]
    source: str = Field(min_length=1, max_length=120)
    event_id: str = Field(min_length=1, max_length=120)
    external_id: str = Field(min_length=1, max_length=120)
    kind: Literal["equipment.status"]
    observed_at: str = Field(min_length=1, max_length=120)
    sequence: int = Field(ge=0, strict=True)
    value: Literal["available", "failed"]


@app.post("/api/integrations/equipment", status_code=201)
def equipment_observation(body: EquipmentObservation, request: Request, run: str):
    token = os.getenv("TERMINAL_FEED_TOKEN", "")
    if len(token) < 32:
        raise HTTPException(503, "Equipment adapter is not configured")
    if not secrets.compare_digest(
        request.headers.get("authorization", ""), "Bearer " + token
    ):
        raise HTTPException(401, "Equipment sender authentication required")
    if run != os.getenv("TERMINAL_FEED_RUN") or body.source != os.getenv(
        "TERMINAL_FEED_SOURCE", "fleet"
    ):
        raise HTTPException(403, "Sender is not scoped to this run/source")
    from .integration import receive

    return receive(store, run, body.model_dump(exclude={"schema_version"}))


@app.get("/api/integrations/equipment/status")
def equipment_feed_status(run: str):
    from .integration import status

    return status(store, run)


@app.get("/api/live")
def live():
    return {"status": "alive"}


@app.get("/api/ready")
def ready(response: Response):
    try:
        with store.connect() as c:
            c.execute("SELECT 1")
        workers = runtime.snapshot()
        healthy = all(
            name in workers
            and workers[name]["phase"] != "failed"
            and workers[name]["age_seconds"] < (600 if name == "planner" else 60)
            for name in ("commands", "planner")
        )
        response.status_code = 200 if healthy else 503
        return dict(status="ready" if healthy else "worker stale", workers=workers)
    except Exception:
        response.status_code = 503
        return dict(status="database unavailable")
