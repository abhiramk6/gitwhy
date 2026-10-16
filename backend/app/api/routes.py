import time
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..models.provider import Provider
from . import service
from ..config import Settings
from .deps import get_conn, get_org_id, get_provider, optional_user_id, require_write, settings_dep

router = APIRouter(prefix="/api")


class PlanRequest(BaseModel):
    request: str = Field(min_length=8, max_length=2000)
    depth: int = Field(default=3, ge=1, le=5)


class AskTurn(BaseModel):
    question: str = Field(default="", max_length=1000)
    text: str = Field(default="", max_length=4000)


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    history: list[AskTurn] = Field(default_factory=list, max_length=6)


class FeedbackBody(BaseModel):
    event_id: int
    resolved: bool
    correct: Literal["yes", "no", "unsure"]
    onboarding: bool = False


class TimedTaskBody(BaseModel):
    task: str = Field(min_length=3, max_length=300)
    arm: Literal["manual", "gitwhy"]
    seconds: float = Field(ge=0, lt=86400)
    found: bool


class ImpactBody(BaseModel):
    question: str = Field(min_length=5, max_length=500)


class RememberBody(BaseModel):
    text: str = Field(min_length=3, max_length=2000)
    author: str = Field(min_length=1, max_length=80)
    scope: Literal["org", "repo", "team"] = "org"
    repo: str | None = None


class OverrideBody(BaseModel):
    rule: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=5, max_length=1000)
    author: str = Field(min_length=1, max_length=80)
    temporary: bool = True
    approver: str | None = None
    repo: str | None = None
    valid_until: str | None = None


class StatusBody(BaseModel):
    status: Literal["active", "rejected", "candidate"]


class PlanStatusBody(BaseModel):
    status: Literal["approved", "rejected", "draft"]


@router.get("/overview")
def overview(conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id)):
    return service.overview(conn, org)


@router.get("/ingestion")
def ingestion(conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id)):
    return service.ingestion_runs(conn, org)


@router.get("/graph")
def graph(types: list[str] | None = Query(default=None), rels: list[str] | None = Query(default=None),
          conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id)):
    return service.graph(conn, org, types, rels)


@router.get("/entities/{entity_id}")
def entity(entity_id: int, conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id)):
    e = service.entity_detail(conn, org, entity_id)
    if not e:
        raise HTTPException(404, "entity not found")
    return e


@router.get("/search")
def search(q: str = Query(min_length=2, max_length=300), k: int = Query(default=10, ge=1, le=25),
           conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id),
           provider: Provider = Depends(get_provider)):
    return service.do_search(conn, org, provider, q, k)


@router.get("/knowledge")
def knowledge(status: str | None = None, fact_type: str | None = None,
              conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id)):
    return service.knowledge(conn, org, status, fact_type)


@router.post("/knowledge/{fact_id}/status", dependencies=[Depends(require_write)])
def fact_status(fact_id: int, body: StatusBody, conn: psycopg.Connection = Depends(get_conn),
                org: int = Depends(get_org_id)):
    r = service.set_fact_status(conn, org, fact_id, body.status)
    if not r:
        raise HTTPException(404, "fact not found")
    return r


@router.post("/memory/remember", dependencies=[Depends(require_write)])
def remember(body: RememberBody, conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id)):
    return service.remember(conn, org, body.text, body.author, body.scope, body.repo)


@router.post("/memory/override", dependencies=[Depends(require_write)])
def override(body: OverrideBody, conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id)):
    return service.override(conn, org, body.rule, body.reason, body.author, body.temporary, body.approver,
                            body.repo, body.valid_until)


@router.get("/plans")
def plans(conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id)):
    return service.list_plans(conn, org)


@router.post("/plans", dependencies=[Depends(require_write)])
def create_plan(body: PlanRequest, conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id),
                provider: Provider = Depends(get_provider)):
    return service.make_plan(conn, org, provider, body.request, body.depth)


@router.get("/plans/{plan_id}")
def get_plan(plan_id: int, conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id)):
    p = service.get_plan(conn, org, plan_id)
    if not p:
        raise HTTPException(404, "plan not found")
    return p


@router.post("/plans/{plan_id}/status", dependencies=[Depends(require_write)])
def plan_status(plan_id: int, body: PlanStatusBody, conn: psycopg.Connection = Depends(get_conn),
                org: int = Depends(get_org_id)):
    r = service.approve_plan(conn, org, plan_id, body.status)
    if not r:
        raise HTTPException(404, "plan not found")
    return r


@router.post("/ask", dependencies=[Depends(require_write)])
def ask(body: AskBody, conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id),
        provider: Provider = Depends(get_provider), uid: int | None = Depends(optional_user_id)):
    from ..ask.ask import ask as run_ask
    from ..metrics import metrics
    from ..intelligence.judge import meter
    t0, live0 = time.perf_counter(), meter.snapshot()["live"]
    out = run_ask(conn, org, provider, body.question, [t.model_dump() for t in body.history])
    out["event_id"] = metrics.record(conn, org, uid, "ask", int((time.perf_counter() - t0) * 1000),
                                     {**metrics.ask_detail(out), "live_calls": meter.snapshot()["live"] - live0})
    conn.commit()
    return out


@router.post("/impact", dependencies=[Depends(require_write)])
def change_impact(body: ImpactBody, conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id),
                  provider: Provider = Depends(get_provider), uid: int | None = Depends(optional_user_id)):
    """What else could break if this changes, and which earlier decisions apply. Read-only."""
    from ..impact.change_impact import change_impact as run
    from ..metrics import metrics
    t0 = time.perf_counter()
    out = run(conn, org, provider, body.question)
    metrics.record(conn, org, uid, "impact", int((time.perf_counter() - t0) * 1000), {"status": out.get("status")})
    conn.commit()
    return out


@router.post("/feedback", dependencies=[Depends(require_write)])
def feedback(body: FeedbackBody, conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id),
             uid: int | None = Depends(optional_user_id)):
    from ..metrics import metrics
    if not metrics.feedback(conn, org, uid, body.event_id, body.resolved, body.correct, body.onboarding):
        raise HTTPException(404, "answer not found")
    conn.commit()
    return {"ok": True}


@router.post("/timed-tasks", dependencies=[Depends(require_write)])
def timed_task(body: TimedTaskBody, conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id),
               uid: int | None = Depends(optional_user_id)):
    from ..metrics import metrics
    metrics.record_timed(conn, org, uid, body.task, body.arm, body.seconds, body.found)
    conn.commit()
    return metrics.timed_comparison(conn, org)


@router.get("/results")
def results(assumed_minutes: float | None = Query(default=None, ge=0, le=600), conn: psycopg.Connection = Depends(get_conn),
            org: int = Depends(get_org_id)):
    from ..metrics import metrics
    return metrics.summary(conn, org, assumed_minutes)


@router.get("/people")
def people(conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id)):
    from ..people.people import roster
    return roster(conn, org)


@router.get("/people/{login}")
def person(login: str, conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id)):
    from ..people.people import profile
    p = profile(conn, org, login)
    if not p:
        raise HTTPException(404, "person not found")
    return p


@router.post("/people/{login}/handover", dependencies=[Depends(require_write)])
def handover(login: str, conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id),
             provider: Provider = Depends(get_provider), uid: int | None = Depends(optional_user_id)):
    from ..metrics import metrics
    from ..people.people import handover as run
    t0 = time.perf_counter()
    out = run(conn, org, provider, login)
    if out.get("status") != "unknown_person":
        metrics.record(conn, org, uid, "handover", int((time.perf_counter() - t0) * 1000), {"status": out.get("status"), "person": login})
    conn.commit()
    if out["status"] == "unknown_person":
        raise HTTPException(404, "person not found")
    return out


@router.get("/archaeology")
def archaeology(repo: str = Query(min_length=1), path: str = Query(min_length=1),
                conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id)):
    from ..archaeology.archaeology import trail
    t = trail(conn, org, repo, path)
    if not t:
        raise HTTPException(404, "file not found")
    return t


@router.get("/memory/guidance")
def memory_guidance(conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id)):
    from ..memory.timeline import list_guidance
    return list_guidance(conn, org)


@router.post("/memory/guidance/{fact_id}/timeline", dependencies=[Depends(require_write)])
def memory_timeline(fact_id: int, conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id),
                    provider: Provider = Depends(get_provider)):
    from ..memory.timeline import timeline
    out = timeline(conn, org, provider, fact_id)
    conn.commit()
    if out is None:
        raise HTTPException(404, "guidance not found")
    return out


@router.get("/prs")
def prs(limit: int = Query(default=60, ge=1, le=200), conn: psycopg.Connection = Depends(get_conn),
        org: int = Depends(get_org_id)):
    from . import views
    return views.pr_list(conn, org, limit)


@router.post("/prs/{repo}/{number}/review", dependencies=[Depends(require_write)])
def review_pr(repo: str, number: int, conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id),
              provider: Provider = Depends(get_provider), uid: int | None = Depends(optional_user_id)):
    """Draft review comments for a PR. Returned to the caller only: nothing is written to GitHub or any external service."""
    from ..metrics import metrics
    from ..review.reviewer import draft_review
    t0 = time.perf_counter()
    try:
        out = draft_review(conn, org, provider, repo, number)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    if out.get("status") == "draft":
        metrics.record(conn, org, uid, "review", int((time.perf_counter() - t0) * 1000), metrics.review_detail(out, repo, number))
    conn.commit()
    return out


@router.get("/sources")
def sources(conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id)):
    from . import views
    return views.sources(conn, org)


@router.get("/provenance/{record_id}")
def provenance(record_id: int, conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id)):
    from . import views
    out = views.provenance(conn, org, record_id)
    if not out:
        raise HTTPException(404, "record not found")
    return out


@router.get("/starters")
def starters(conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id)):
    from . import views
    return views.starters(conn, org)


@router.get("/tags")
def tags(ids: str = Query(min_length=1, max_length=8000), conn: psycopg.Connection = Depends(get_conn),
         org: int = Depends(get_org_id)):
    from . import views
    return views.tags(conn, org, [x for x in ids.split(",") if x])


@router.get("/files")
def files(conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id)):
    from . import views
    return views.files(conn, org)


@router.post("/archaeology/explain", dependencies=[Depends(require_write)])
def archaeology_explain(repo: str = Query(min_length=1), path: str = Query(min_length=1),
                        conn: psycopg.Connection = Depends(get_conn), org: int = Depends(get_org_id),
                        provider: Provider = Depends(get_provider)):
    from ..archaeology.archaeology import explain
    out = explain(conn, org, provider, repo, path)
    conn.commit()
    if out is None:
        raise HTTPException(404, "file not found")
    return out


@router.get("/meta")
def meta(settings: Settings = Depends(settings_dep)):
    from ..product import product
    return {**product(), "auth": settings.auth_required}
