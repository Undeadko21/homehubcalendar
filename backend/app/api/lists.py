"""Списки дел и покупок."""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from pydantic import BaseModel

from fastapi import APIRouter

from .. import core

router = APIRouter()


# ---------- списки дел и покупок ----------
class ListIn(BaseModel):
    name: str


def _check_due(due: str | None) -> str | None:
    if not due:
        return None
    try:
        return date.fromisoformat(due[:10]).isoformat()
    except ValueError:
        raise HTTPException(400, "Срок вида ГГГГ-ММ-ДД")


class ItemIn(BaseModel):
    text: str
    person_id: str | None = None
    due: str | None = None      # срок, YYYY-MM-DD


class ItemPatch(BaseModel):
    text: str | None = None
    done: bool | None = None
    person_id: str | None = None
    due: str | None = None


@router.get("/api/lists")
def get_lists():
    return core.db.lists()


@router.post("/api/lists")
def create_list(body: ListIn):
    if not body.name.strip():
        raise HTTPException(400, "Укажите название")
    return {"ok": True, "id": core.db.add_list(body.name)}


@router.put("/api/lists/{lid}")
def rename_list(lid: int, body: ListIn):
    core.db.rename_list(lid, body.name)
    return {"ok": True}


@router.delete("/api/lists/{lid}")
def delete_list(lid: int):
    core.db.delete_list(lid)
    return {"ok": True}


@router.post("/api/lists/{lid}/items")
def add_item(lid: int, body: ItemIn):
    if not body.text.strip():
        raise HTTPException(400, "Пустая запись")
    return {"ok": True, "id": core.db.add_item(lid, body.text, body.person_id, _check_due(body.due))}


@router.post("/api/lists/{lid}/clear-done")
def clear_done(lid: int):
    core.db.clear_done(lid)
    return {"ok": True}


@router.patch("/api/items/{iid}")
def patch_item(iid: int, body: ItemPatch):
    fields = body.model_dump(exclude_unset=True)
    if "due" in fields:
        fields["due"] = _check_due(fields["due"])
    core.db.update_item(iid, fields)
    return {"ok": True}


@router.delete("/api/items/{iid}")
def delete_item(iid: int):
    core.db.delete_item(iid)
    return {"ok": True}
