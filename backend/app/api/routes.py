from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..models.provider import Provider
from . import service
from .deps import get_conn, get_org_id, get_provider, require_write

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
        provider: Provider = Depends(get_provider)):
    from ..ask.ask import ask as run_ask
    out = run_ask(conn, org, provider, body.question, [t.model_dump() for t in body.history])
    conn.commit()
    return out


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
             provider: Provider = Depends(get_provider)):
    from ..people.people import handover as run
    out = run(conn, org, provider, login)
    conn.commit()
    if out["status"] == "unknown_person":
        raise HTTPException(404, "person not found")
    return out
