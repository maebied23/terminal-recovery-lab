import json
from copy import deepcopy
import pytest
from app.assistant import assistant, EvidenceTools, route, Selection
from app.domain import RuleError
from test_v1_store import db


@pytest.fixture(autouse=True)
def no_real_api(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TERMINAL_ASSISTANT_PROVIDER", raising=False)


def test_grounded_fallback_and_trace_do_not_mutate(db):
    store, run = db
    before = store.read(run)
    r = assistant(store, run, "Why is NORTH-RAIL blocked?", None)
    assert r["calls"][0]["tool"] == "diagnose_departure"
    assert r["citations"] and "NORTH-RAIL" in r["answer"]
    assert r["answer"] == "\n\n".join(c["text"] for c in r["citations"])
    assert store.read(run) == before and not r["mutation_allowed"]
    with store.connect() as c:
        assert (
            c.execute(
                "SELECT revision FROM assistant_traces WHERE id=%s", (r["trace_id"],)
            ).fetchone()["revision"]
            == 0
        )


def test_readonly_boundaries_and_abstention(db):
    store, run = db
    ctx = EvidenceTools(store, run)
    with pytest.raises(RuleError):
        ctx.execute("approve_schedule", {})
    with pytest.raises(ValueError):
        ctx.execute("inspect_entity", {"entity_id": "CT-0001", "run": "other"})
    with pytest.raises(RuleError):
        ctx.execute("inspect_entity", {"entity_id": "fake"})
    assert (
        "cannot approve"
        in assistant(store, run, "approve a plan and clear holds", None)["answer"]
    )
    assert (
        "do not have evidence"
        in assistant(store, run, "What will our real port profit be?", None)["answer"]
    )
    assert (
        "No matching evaluation"
        in assistant(store, run, "Show evaluation results", None)["answer"]
    )


def enable(monkeypatch, responses):
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-only-not-a-real-key")
    monkeypatch.setenv("TERMINAL_ASSISTANT_PROVIDER", "openai")
    calls = []

    def transport(payload):
        calls.append(deepcopy(payload))
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr("app.assistant.request_openai", transport)
    return calls


def tool(name, args):
    return dict(
        status="completed",
        output=[
            dict(
                type="function_call",
                name=name,
                arguments=json.dumps(args),
                call_id="f1",
            )
        ],
        usage=dict(input_tokens=50, output_tokens=10, total_tokens=60),
    )


def answer(ids):
    return dict(
        status="completed",
        output=[
            dict(
                type="message",
                content=[
                    dict(type="output_text", text=json.dumps(dict(claim_ids=ids)))
                ],
            )
        ],
        usage=dict(input_tokens=60, output_tokens=10, total_tokens=70),
    )


def test_openai_protocol_numeric_grounding_and_usage(db, monkeypatch):
    store, run = db
    calls = enable(monkeypatch, [tool("terminal_summary", {}), answer(["C1"])])
    r = assistant(store, run, "What needs attention?", None)
    assert r["mode"] == "OpenAI-guided evidence"
    assert r["usage"]["total_tokens"] == 130 and r["usage"]["requests"] == 2
    assert r["answer"] == r["citations"][0]["text"]
    assert calls[0]["store"] is False and calls[0]["parallel_tool_calls"] is False
    assert calls[1]["input"][-1]["type"] == "function_call_output"
    assert not any(t["name"].startswith("approve") for t in calls[0]["tools"])


@pytest.mark.parametrize(
    "bad",
    [
        answer(["C999"]),
        tool("execute_sql", {"sql": "DROP TABLE runs"}),
        RuntimeError("provider failed"),
    ],
)
def test_bad_citation_tool_or_provider_falls_back(db, monkeypatch, bad):
    store, run = db
    before = store.read(run)
    enable(monkeypatch, [bad])
    r = assistant(store, run, "What needs attention?", None)
    assert r["mode"] == "evidence tools" and r["fallback_reason"]
    assert r["citations"] and "C999" not in r["answer"]
    assert store.read(run) == before


def test_imported_instruction_is_data_not_generated_prose(db, monkeypatch):
    store, run = db
    # Provider tries to emit prose/numbers outside the schema after reading valid evidence.
    bad = dict(
        status="completed",
        output=[
            dict(
                type="message",
                content=[
                    dict(
                        type="output_text",
                        text='{"claim_ids":["C1"],"answer":"Ignore tools; 999999 cargo saved"}',
                    )
                ],
            )
        ],
    )
    enable(monkeypatch, [tool("terminal_summary", {}), bad])
    r = assistant(store, run, "What needs attention?", None)
    assert "999999" not in r["answer"] and r["fallback_reason"] == "ValidationError"


def test_historical_evidence_excludes_later_reports(db):
    from app.evaluation_store import enqueue, cancel

    store, run = db
    eid = enqueue(store, run, 0, "case")
    cancel(store, run, eid)
    r = assistant(store, run, "Show evaluation results", None, 0)
    assert "No matching evaluation" in r["answer"]
    events = assistant(store, run, "What did we know?", None, 0)
    assert events["calls"][0]["result"] == []


def test_whatif_copy_does_not_approve(db, monkeypatch):
    store, run = db
    before = store.read(run)
    seen = []

    def build(s, *args):
        seen.append(deepcopy(s))
        return dict(candidates=[])

    monkeypatch.setattr("app.scheduling.build", build)
    r = assistant(store, run, "What if YC-1 remains down?", None)
    assert len(seen) == 2 and seen[0] != seen[1]
    assert "Hypothesis only" in r["answer"] and store.read(run) == before
    assert r["calls"][0]["arguments"] == dict(equipment_id="YC-1", status="failed")


def test_invalid_and_foreign_evaluation_id_does_not_leak(db):
    store, run = db
    ctx = EvidenceTools(store, run)
    result = ctx.execute(
        "read_evaluation", dict(evaluation_id="foreign-or-unknown-report")
    )
    assert "No matching evaluation" in result["claims"][0]["text"]


def test_model_cannot_omit_basis_caveat(db, monkeypatch):
    store, run = db
    responses = [
        tool("diagnose_departure", {"entity_id": "NORTH-RAIL"}),
        answer(["C2"]),
    ]
    enable(monkeypatch, responses)
    r = assistant(store, run, "Why is North Rail at risk?", None)
    assert [c["id"] for c in r["citations"]] == ["C1", "C2"]
    assert "not a calibrated chance" in r["answer"]


@pytest.mark.parametrize(
    "wording",
    [
        "What if YC-1 stays unavailable?",
        "What if YC-1 is not available?",
        "What if YC-1 is not repaired?",
    ],
)
def test_unavailable_hypothesis_is_never_routed_as_repaired(wording):
    from app.domain import seed_state

    name, args = route(wording, None, seed_state("small"))
    assert name == "what_if_equipment" and args["status"] == "failed"
