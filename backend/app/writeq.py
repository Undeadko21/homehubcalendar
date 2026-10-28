"""Надёжная запись в Яндекс: журнал изменений (с отменой) и очередь повторов.

Любая запись сначала меняет локальную копию (интерфейс видит результат сразу), затем уходит на сервер.
Если сервер недоступен, операция остаётся в очереди (`kv writeq`) и повторяется планировщиком; после
каждой синхронизации ещё не отправленное накладывается поверх свежих данных (`reapply`).
Ошибки, которые повтор не исправит (нет прав, неверный пароль, календарь не найден), в очередь не попадают.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Callable

from . import writer
from .db import Database, now_iso

log = logging.getLogger(__name__)

QUEUE_KEY = "writeq"
LOG_KEY = "changelog"
ERR_KEY = "writeq:error"
LOG_LIMIT = 40

PERMANENT = ("400", "401", "403", "404", "409", "412", "Forbidden", "Unauthorized", "Not Found")


def is_transient(e: Exception) -> bool:
    if isinstance(e, writer.WriteError):
        return False
    s = str(e)
    return not any(p in s for p in PERMANENT)


class WriteService:
    def __init__(self, db: Database, get_target: Callable[[str], object], on_change: Callable[[], None]):
        self.db = db
        self.get_target = get_target   # key календаря -> цель записи (можно подменять в тестах)
        self.on_change = on_change

    # ---------- очередь ----------
    def queue(self) -> list[dict]:
        return self.db.kv_get(QUEUE_KEY)[0] or []

    def _save_queue(self, q: list[dict]) -> None:
        self.db.kv_set(QUEUE_KEY, q)

    def pending_count(self) -> int:
        return len(self.queue())

    def last_error(self) -> str | None:
        return self.db.kv_get(ERR_KEY)[0] or None

    def reapply(self) -> None:
        """После синхронизации возвращаем локально то, что ещё не дошло до Яндекса."""
        for op in self.queue():
            if op["kind"] == "delete":
                self.db.delete_object(op["cal"], op["href"])
            else:
                self.db.put_object(op["cal"], op["href"], op["ics"])

    def _enqueue(self, kind: str, cal: str, href: str, ics: str = "") -> None:
        q = self.queue()
        same = next((o for o in q if o["cal"] == cal and o["href"] == href), None)
        if same:
            if kind == "delete":
                q.remove(same)
                if same["kind"] != "create":
                    q.append({**same, "kind": "delete", "ics": ""})
            else:
                same["ics"] = ics   # create остаётся create, update — update
        else:
            q.append({"id": uuid.uuid4().hex[:10], "kind": kind, "cal": cal, "href": href, "ics": ics, "t": now_iso()})
        self._save_queue(q)

    def _run(self, op: dict) -> str | None:
        """Выполняет операцию на сервере; для create возвращает настоящий href."""
        t = self.get_target(op["cal"])
        rid = op["cal"].split("/", 1)[1]
        if op["kind"] == "create":
            return t.create(rid, op["ics"])
        if op["kind"] == "update":
            t.update(rid, op["href"], op["ics"])
        else:
            t.delete(rid, op["href"])
        return None

    def flush(self) -> dict:
        """Повторяет очередь по порядку; на первой временной ошибке останавливается."""
        done = failed = 0
        q = self.queue()
        for op in list(q):
            try:
                real = self._run(op)
            except Exception as e:  # noqa: BLE001
                if is_transient(e):
                    log.info("Очередь записи: сервер недоступен (%s)", e)
                    break
                log.warning("Очередь записи: операция отклонена: %s", e)
                q.remove(op)
                failed += 1
                self.db.kv_set(ERR_KEY, f"{op['kind']}: {writer.friendly(e)}")
                continue
            q.remove(op)
            done += 1
            if real and op["kind"] == "create":
                self.db.delete_object(op["cal"], op["href"])
                self.db.put_object(op["cal"], real, op["ics"])
                for o in q:   # правки, накопленные поверх ещё не созданного события
                    if o["href"] == op["href"]:
                        o["href"] = real
        self._save_queue(q)
        if done or failed:
            self.on_change()
        return {"done": done, "failed": failed, "left": len(q)}

    # ---------- журнал ----------
    def journal(self) -> list[dict]:
        return self.db.kv_get(LOG_KEY)[0] or []

    def _log(self, action: str, cal: str, uid: str, title: str, before: str | None, after: str | None) -> None:
        items = self.journal()
        items.append({"id": uuid.uuid4().hex[:10], "t": datetime.now().astimezone().isoformat(timespec="seconds"),
                      "action": action, "calendar": cal, "uid": uid, "title": title,
                      "before": before, "after": after})
        self.db.kv_set(LOG_KEY, items[-LOG_LIMIT:])

    # ---------- операции (локально сразу, на сервер сразу или через очередь) ----------
    def _send(self, kind: str, cal: str, href: str, ics: str) -> tuple[str, bool]:
        """Возвращает (href, ушло_ли_сразу)."""
        op = {"kind": kind, "cal": cal, "href": href, "ics": ics}
        queued = any(o["cal"] == cal and o["href"] == href for o in self.queue())
        if href.startswith("pending:") or queued:   # не создано на сервере или уже есть очередь — сохраняем порядок
            self._enqueue(kind, cal, href, ics)
            return href, False
        try:
            real = self._run(op)
            return real or href, True
        except Exception as e:  # noqa: BLE001
            if not is_transient(e):
                raise
            log.warning("Запись отложена: %s", e)
            self._enqueue(kind, cal, href, ics)
            return href, False

    def create(self, cal: str, ics: str, action: str = "create", log_it: bool = True) -> bool:
        uid, title = writer.uid_of(ics), writer.title_of(ics)
        href, sent = self._create(cal, ics)
        self.db.put_object(cal, href, ics)
        if log_it:
            self._log(action, cal, uid, title, None, ics)
        return sent

    def _create(self, cal: str, ics: str) -> tuple[str, bool]:
        try:
            return self._run({"kind": "create", "cal": cal, "href": "", "ics": ics}), True
        except Exception as e:  # noqa: BLE001
            if not is_transient(e):
                raise
            log.warning("Создание отложено: %s", e)
            href = f"pending:{uuid.uuid4().hex}"
            self._enqueue("create", cal, href, ics)
            return href, False

    def update(self, cal: str, href: str, old_ics: str, new_ics: str, action: str = "update") -> bool:
        _, sent = self._send("update", cal, href, new_ics)
        self.db.put_object(cal, href, new_ics)
        self._log(action, cal, writer.uid_of(new_ics), writer.title_of(new_ics), old_ics, new_ics)
        return sent

    def delete(self, cal: str, href: str, old_ics: str, action: str = "delete") -> bool:
        _, sent = self._send("delete", cal, href, "")
        self.db.delete_object(cal, href)
        self._log(action, cal, writer.uid_of(old_ics), writer.title_of(old_ics), old_ics, None)
        return sent

    # ---------- отмена ----------
    def undo(self, entry_id: str) -> str:
        entry = next((e for e in self.journal() if e["id"] == entry_id), None)
        if not entry:
            raise writer.WriteError("Запись журнала не найдена")
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
