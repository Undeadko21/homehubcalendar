"""Списки дел и покупок."""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from pydantic import BaseModel

from fastapi import APIRouter

from .. import core, shops
from .files import drop as drop_files


def _item_ids(lid: int, done_only: bool = False) -> list[int]:
    return [i["id"] for l in core.db.lists() if l["id"] == lid for i in l["items"] if i["done"] or not done_only]

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
    category: str | None = None     # отдел магазина (shops.ORDER)


@router.get("/api/shops")
def get_shops():
    """Отделы магазина для списка покупок, в порядке обхода."""
    return [shops.INFO[k] for k in shops.ORDER]


@router.get("/api/lists")
def get_lists():
    out = core.db.lists()
    for l in out:      # старые покупки без отдела — угадываем на лету (в базе остаётся пусто, пока не поменяют руками)
        if shops.is_shopping(l["name"]):
            for i in l["items"]:
                i["category"] = i.get("category") or shops.guess(i["text"])
    return out


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
    for iid in _item_ids(lid):
        drop_files(f"item:{iid}")
    core.db.delete_list(lid)
    return {"ok": True}


@router.post("/api/lists/{lid}/items")
def add_item(lid: int, body: ItemIn):
    if not body.text.strip():
        raise HTTPException(400, "Пустая запись")
    return {"ok": True, "id": core.db.add_item(lid, body.text, body.person_id, _check_due(body.due))}


@router.post("/api/lists/{lid}/clear-done")
def clear_done(lid: int):
    for iid in _item_ids(lid, done_only=True):
        drop_files(f"item:{iid}")
    core.db.clear_done(lid)
    return {"ok": True}


@router.patch("/api/items/{iid}")
def patch_item(iid: int, body: ItemPatch):
    fields = body.model_dump(exclude_unset=True)
    if "due" in fields:
        fields["due"] = _check_due(fields["due"])
    if fields.get("category") and fields["category"] not in shops.INFO:
        raise HTTPException(400, "Неизвестный отдел")
    core.db.update_item(iid, fields)
    return {"ok": True}


@router.delete("/api/items/{iid}")
def delete_item(iid: int):
    drop_files(f"item:{iid}")
    core.db.delete_item(iid)
    return {"ok": True}
