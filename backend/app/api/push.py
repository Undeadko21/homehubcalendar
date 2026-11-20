"""Уведомления в браузере на компьютере (Web Push) — подписка этого браузера, проверка, список (app/webpush.py)."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import core, webpush

router = APIRouter()


class SubIn(BaseModel):
    subscription: dict
    people: list[str] = Field(default_factory=list, max_length=20)
    name: str = Field("", max_length=60)


class EndpointIn(BaseModel):
    endpoint: str


@router.get("/api/push/key")
def push_key():
    return {"key": webpush.public_key(core.db)}


@router.post("/api/push/subscribe")
def push_subscribe(body: SubIn, request: Request):
    from ..main import current_session
    try:
        webpush.subscribe(core.db, body.subscription, body.people, body.name, current_session(request))
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e)) from e
    return {"ok": True}


@router.post("/api/push/unsubscribe")
def push_unsubscribe(body: EndpointIn):
    webpush.unsubscribe(core.db, body.endpoint)
    return {"ok": True}


@router.post("/api/push/test")
def push_test(body: EndpointIn):
    sub = webpush.find(core.db, body.endpoint)
    if not sub:
        raise HTTPException(404, "Этот браузер не подписан")
    code = webpush.send(core.db, sub, "Календарь", "Проверка: уведомления на этом компьютере работают", "test")
    if code not in (200, 201, 202):
        raise HTTPException(502, f"Служба уведомлений браузера ответила {code or 'ошибкой сети'}")
    return {"ok": True}


@router.post("/api/push/status")
def push_status(body: EndpointIn):
    """Подписан ли этот браузер и чьи уведомления получает (адреса других подписок не отдаём)."""
    sub = webpush.find(core.db, body.endpoint)
    return {"subscribed": bool(sub), "people": (sub or {}).get("people", []), "count": len(webpush.subs(core.db))}
