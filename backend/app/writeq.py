"""Надёжная запись в Яндекс: журнал изменений (с отменой) и очередь повторов.

Любая запись сначала меняет локальную копию (интерфейс видит результат сразу), затем уходит на сервер.
Если сервер недоступен, операция остаётся в очереди (`kv writeq:v2`) и повторяется планировщиком; после
каждой синхронизации ещё не отправленное накладывается поверх свежих данных (`reapply`).
Ошибки, которые повтор не исправит (нет прав, неверный пароль, календарь не найден), в очередь не попадают.
"""
from __future__ import annotations

import logging
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
from threading import RLock
from typing import Callable

from . import writer
from .db import Database, now_iso

log = logging.getLogger(__name__)

QUEUE_KEY = "writeq:v2"
LEGACY_QUEUE_KEY = "writeq"
LOG_KEY = "changelog"
ERR_KEY = "writeq:error"
LOG_LIMIT = 40

PERMANENT = ("400", "401", "403", "404", "409", "412", "Forbidden", "Unauthorized", "Not Found")


def is_transient(e: Exception) -> bool:
    if isinstance(e, writer.WriteError):
        return False
    s = str(e)
    return not any(p in s for p in PERMANENT)


def _serialized(method):
    @wraps(method)
    def run(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return run


class WriteService:
    def __init__(self, db: Database, get_target: Callable[[str], object], on_change: Callable[[], None]):
        self._lock = RLock()
        self._deferred = ContextVar("deferred_calendar_write", default=False)
        self.db = db
        self.get_target = get_target   # key календаря -> цель записи (можно подменять в тестах)
        self.on_change = on_change

    @property
    def is_deferred(self) -> bool:
        return self._deferred.get()

    @contextmanager
    def defer(self):
        """Сначала блокировка очереди, затем транзакция базы. Сеть работает после commit."""
        with self._lock:
            token = self._deferred.set(True)
            try:
                yield
            finally:
                self._deferred.reset(token)

    # ---------- очередь ----------
    def queue(self) -> list[dict]:
        if not self.db.kv_get(LEGACY_QUEUE_KEY)[0]:
            return self.db.kv_get(QUEUE_KEY)[0] or []
        # Старый образ при откате не должен отправить новую очередь без предусловий.
        # Если он добавил свои записи или восстановили старую копию, забираем их атомарно.
        with self._lock, self.db.tx():
            q = (self.db.kv_get(QUEUE_KEY)[0] or []) + (self.db.kv_get(LEGACY_QUEUE_KEY)[0] or [])
            self._save_queue(q)
            self.db.kv_set(LEGACY_QUEUE_KEY, [])
            return q

    def _save_queue(self, q: list[dict]) -> None:
        self.db.kv_set(QUEUE_KEY, q)

    def pending_count(self) -> int:
        return len(self.queue())

    def last_error(self) -> str | None:
        return self.db.kv_get(ERR_KEY)[0] or None

    @_serialized
    def reapply(self) -> None:
        """После синхронизации возвращаем локально то, что ещё не дошло до Яндекса."""
        for op in self.queue():
            if op["kind"] in ("delete", "cancel_create"):
                self.db.delete_object(op["cal"], op["href"])
            else:
                self.db.put_object(op["cal"], op["href"], op["ics"])

    def _enqueue(self, kind: str, cal: str, href: str, ics: str = "", *, before: str | None = None,
                 requires: str | None = None, attempted: str | None = None) -> None:
        q = self.queue()
        same = next((o for o in q if o["cal"] == cal and o["href"] == href), None)
        if same:
            if kind == "delete" and same["kind"] == "create":
                settled = {same["id"]: "cancelled"}
                self._discard_dependents(q, settled)
                self._settle(settled)
                if same.get("attempted"):
                    same.update(kind="cancel_create", ics=same["attempted"])
                else:
                    q.remove(same)
            elif kind == "delete":
                same.update(kind="delete", ics="")
            else:
                same["ics"] = ics
        else:
            q.append({"id": uuid.uuid4().hex[:10], "kind": kind, "cal": cal, "href": href, "ics": ics,
                      "before": before, "requires": requires, "attempted": attempted, "t": now_iso()})
        self._save_queue(q)

    def _discard_dependents(self, q: list[dict], settled: dict[str, str]) -> None:
        for item in q[:]:   # Зависимости всегда расположены после исходной операции.
            parent = item.get("requires")
            if parent in settled:
                q.remove(item)
                self.db.delete_object(item["cal"], item["href"])
                settled[item["id"]] = settled[parent]

    def _settle(self, settled: dict[str, str]) -> None:
        items = self.journal()
        for item in items:
            if item.get("queue_id") in settled:
                item["status"] = settled[item.pop("queue_id")]
        self.db.kv_set(LOG_KEY, items)

    def _run(self, op: dict, queued: bool = False) -> str | None:
        """Выполняет операцию на сервере; для create возвращает настоящий href."""
        target = self.get_target(op["cal"])
        rid = op["cal"].split("/", 1)[1]
        kind = op["kind"]
        if kind == "create":
            create = getattr(target, "create_queued", None) if queued else None
            first = (op.get("attempted") or op["ics"]) if queued else op["ics"]
            href = create(rid, first, after=op["ics"]) if create else target.create(rid, first)
            if first != op["ics"]:
                guarded = getattr(target, "change_queued", None)
                if guarded:
                    guarded(rid, href, first, op["ics"])
                else:
                    target.update(rid, href, op["ics"])
            return href
        if kind == "cancel_create":
            cancel = getattr(target, "cancel_queued_create", None)
            if not cancel:
                raise writer.WriteError("Не удалось проверить, было ли создано событие")
            cancel(rid, op["ics"])
            return None
        guarded = getattr(target, "change_queued", None)
        if queued and guarded:
            before = op.get("before")
            if not before:   # Очередь, созданная старой версией.
                before = next((e["before"] for e in self.journal() if e.get("queue_id") == op["id"] and e.get("before")), None)
            guarded(rid, op["href"], before, op["ics"] if kind == "update" else None)
        elif kind == "update":
            target.update(rid, op["href"], op["ics"])
        else:
            target.delete(rid, op["href"])
        return None

    def flush(self) -> dict:
        """Повторяет очередь по порядку; на первой временной ошибке останавливается."""
        result = self._flush()
        if result["done"] or result["failed"]:
            self.on_change()
        return result

    @_serialized
    def _flush(self) -> dict:
        done = failed = 0
        q = self.queue()
        while q:
            op = q[0]
            if op["kind"] == "create" and not op.get("attempted"):
                op["attempted"] = op["ics"]
                self._save_queue(q)
            failure = None
            try:
                real = self._run(op, queued=True)
            except Exception as exc:  # noqa: BLE001
                if is_transient(exc):
                    log.info("Очередь записи: сервер недоступен (%s)", type(exc).__name__)
                    break
                failure = exc

            with self.db.tx():
                q.pop(0)
                settled = {op["id"]: "sent"}
                if failure:
                    log.warning("Очередь записи: операция отклонена (%s)", type(failure).__name__)
                    failed += 1
                    settled[op["id"]] = "failed"
                    self.db.kv_set(ERR_KEY, f"{op['kind']}: {writer.friendly(failure)}")
                    if isinstance(failure, writer.WriteConflict):
                        settled[op["id"]] = "conflict"
                        if failure.remote is None or op["href"].startswith("pending:"):
                            self.db.delete_object(op["cal"], op["href"])
                        if failure.remote is not None:
                            href = failure.href if op["href"].startswith("pending:") else op["href"]
                            if href:
                                self.db.put_object(op["cal"], href, failure.remote)
                    if op["kind"] == "create":
                        self.db.delete_object(op["cal"], op["href"])
                    self._discard_dependents(q, settled)
                    failed += len(settled) - 1
                else:
                    done += 1
                    if real and op["kind"] == "create":
                        self.db.delete_object(op["cal"], op["href"])
                        self.db.put_object(op["cal"], real, op["ics"])
                        for item in q:
                            if item["cal"] == op["cal"] and item["href"] == op["href"]:
                                item["href"] = real
                    for item in q:
                        if item.get("requires") == op["id"]:
                            item.pop("requires")
                self._save_queue(q)
                self._settle(settled)
        return {"done": done, "failed": failed, "left": len(q)}

    # ---------- журнал ----------
    def journal(self) -> list[dict]:
        return self.db.kv_get(LOG_KEY)[0] or []

    @_serialized
    def event_status(self, cal: str, uid: str) -> str | None:
        # Старые записи журнала не содержат результата отправки. Уже ожидающую
        # операцию определяем по локальному объекту даже для старых данных.
        found = self.db.find_object(uid, cal)
        if found and any(op["cal"] == cal and op["href"] == found[1] for op in self.queue()):
            return "pending"
        latest = next((item for item in reversed(self.journal())
                       if item["calendar"] == cal and item["uid"] == uid), None)
        return latest.get("status") if latest and latest.get("status") != "pending" else None

    def _log(self, action: str, cal: str, uid: str, title: str, before: str | None,
             after: str | None, href: str, sent: bool) -> None:
        items = self.journal()
        op = next((op for op in self.queue() if op["cal"] == cal and op["href"] == href), None) if not sent else None
        items.append({"id": uuid.uuid4().hex[:10], "t": datetime.now().astimezone().isoformat(timespec="seconds"),
                      "action": action, "calendar": cal, "uid": uid, "title": title,
                      "before": before, "after": after,
                      "status": "sent" if sent else "pending", "queue_id": op["id"] if op else None})
        self.db.kv_set(LOG_KEY, items[-LOG_LIMIT:])

    # ---------- операции (локально сразу, на сервер сразу или через очередь) ----------
    def _send(self, kind: str, cal: str, href: str, ics: str, before: str) -> tuple[str, bool]:
        """Возвращает (href, ушло_ли_сразу)."""
        op = {"kind": kind, "cal": cal, "href": href, "ics": ics}
        queued = any(o["cal"] == cal and o["href"] == href for o in self.queue())
        if self.is_deferred or href.startswith("pending:") or queued:   # не создано на сервере или уже есть очередь — сохраняем порядок
            self._enqueue(kind, cal, href, ics, before=before)
            return href, False
        try:
            real = self._run(op)
            return real or href, True
        except Exception as e:  # noqa: BLE001
            if not is_transient(e):
                raise
            log.warning("Запись отложена: %s", e)
            self._enqueue(kind, cal, href, ics, before=before)
            return href, False

    @_serialized
    def create(self, cal: str, ics: str, action: str = "create", log_it: bool = True, *, requires: str | None = None) -> bool:
        uid, title = writer.uid_of(ics), writer.title_of(ics)
        href, sent = self._create(cal, ics, requires=requires)
        self.db.put_object(cal, href, ics)
        if log_it:
            self._log(action, cal, uid, title, None, ics, href, sent)
        return sent

    def _create(self, cal: str, ics: str, *, requires: str | None = None) -> tuple[str, bool]:
        attempted = None
        if not self.is_deferred and not requires:
            try:
                return self._run({"kind": "create", "cal": cal, "href": "", "ics": ics}), True
            except Exception as exc:  # noqa: BLE001
                if not is_transient(exc):
                    raise
                log.warning("Создание отложено: %s", type(exc).__name__)
                attempted = ics
        href = f"pending:{uuid.uuid4().hex}"
        self._enqueue("create", cal, href, ics, requires=requires, attempted=attempted)
        return href, False

    @_serialized
    def split(self, cal: str, href: str, before: str, series: str, new_ics: str) -> bool:
        sent = self.update(cal, href, before, series)
        parent = next((op["id"] for op in self.queue() if op["cal"] == cal and op["href"] == href), None)
        created = self.create(cal, new_ics, requires=parent)
        return sent and created

    @_serialized
    def update(self, cal: str, href: str, old_ics: str, new_ics: str, action: str = "update") -> bool:
        _, sent = self._send("update", cal, href, new_ics, old_ics)
        self.db.put_object(cal, href, new_ics)
        self._log(action, cal, writer.uid_of(new_ics), writer.title_of(new_ics), old_ics, new_ics, href, sent)
        return sent

    @_serialized
    def delete(self, cal: str, href: str, old_ics: str, action: str = "delete") -> bool:
        _, sent = self._send("delete", cal, href, "", old_ics)
        self.db.delete_object(cal, href)
        self._log(action, cal, writer.uid_of(old_ics), writer.title_of(old_ics), old_ics, None, href, sent)
        return sent

    # ---------- отмена ----------
    @_serialized
    def undo(self, entry_id: str) -> str:
        entry = next((e for e in self.journal() if e["id"] == entry_id), None)
        if not entry:
            raise writer.WriteError("Запись журнала не найдена")
        if entry.get("status") in ("conflict", "failed", "cancelled"):
            raise writer.WriteError("Правка не отправлена. Откройте событие и внесите изменения заново.")
        cal, uid = entry["calendar"], entry["uid"]
        found = self.db.find_object(uid, cal)
        if entry["action"] == "create":
            if not found:
                raise writer.WriteError("Событие уже удалено")
            self.delete(cal, found[1], found[2], action="undo")
        elif entry["action"] == "delete":
            if found:
                raise writer.WriteError("Событие уже есть в календаре")
            self.create(cal, entry["before"], action="undo")
        else:
            if not found:
                raise writer.WriteError("Событие уже удалено")
            self.update(cal, found[1], found[2], entry["before"], action="undo")
        return entry["title"]
