"""Навык Алисы «Семья»: отвечает, когда следующая встреча у человека (Оли, Маши, папы…).

Запускается как функция Yandex Cloud (точка входа `handler.handler`). Домой не обращается: читает
зашифрованный снимок календаря с Яндекс.Диска (его кладёт сервер, см. backend/app/cloud.py).

Переменные окружения функции:
  HOMEHUB_URL  — публичная ссылка на снимок (поле «u» из кода подключения, без «hhc1.»-обёртки: см. README)
  HOMEHUB_KEY  — ключ шифрования (поле «k» из кода подключения), base64url
  HOMEHUB_TOKEN — (необязательно) токен записи Яндекс.Диска (поле «t» из кода подключения): нужен, чтобы
                  говорить «добавь на завтра в 18:00 врача Марку». Без него навык только отвечает на вопросы.
Команда «добавь…» кладёт в папку приложения на Диске маленький зашифрованный файл ops-alice-<id>.bin; сервер дома
подхватывает его в течение минуты, разбирает фразу и создаёт событие (см. backend/app/ops.py, quick.py).
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import uuid
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

SKILL_NAME = "Семья"
CACHE_SECONDS = 120   # снимок на Диске меняется раз в пару минут, чаще ходить незачем
FETCH_TIMEOUT = 8.0   # один запрос к Диску (поток доработает и после ответа Алисе)
WAIT_SECONDS = 2.4    # Алиса ждёт ответ не дольше 3 секунд
_cache: dict = {"t": 0.0, "snap": None}

# --------------------------------------------------------------------------- снимок


def _b64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def decrypt(key: bytes, blob: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM(key).decrypt(blob[:12], blob[12:], b"homehub-v1")


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT) as r:
        return r.read()


def _fetch() -> dict:
    pub = os.environ["HOMEHUB_URL"]
    meta = json.loads(_get("https://cloud-api.yandex.net/v1/disk/public/resources/download?"
                           + urllib.parse.urlencode({"public_key": pub})))
    return json.loads(decrypt(_b64(os.environ["HOMEHUB_KEY"]), _get(meta["href"])))


_job: dict = {"thread": None, "err": None}


def _run_fetch():
    try:
        snap = _fetch()
        _cache.update(t=time.time(), snap=snap)
        _job["err"] = None
    except Exception as e:  # noqa: BLE001
        _job["err"] = e


def load_snapshot() -> dict:
    """Снимок с Диска, копия в памяти. Загрузка идёт в потоке: если на холодном старте Диск отвечает
    дольше ~2,4 с, поток доработает, и повторный вопрос получит готовый ответ."""
    import threading
    if _cache["snap"] and time.time() - _cache["t"] < CACHE_SECONDS:
        return _cache["snap"]
    th = _job["thread"]
    if th is None or not th.is_alive():
        th = threading.Thread(target=_run_fetch, daemon=True)
        _job["thread"] = th
        th.start()
    th.join(WAIT_SECONDS)
    if _cache["snap"]:
        return _cache["snap"]
    raise RuntimeError("снимок ещё грузится: %r" % (_job["err"],))

# --------------------------------------------------------------------------- русский язык

_TAILS_VOWEL = {"а", "я", "ы", "и", "е", "у", "ю", "ой", "ей", "ою", "ею", "ё"}
_TAILS_CONS = {"", "а", "у", "ом", "е", "ы", "ем"}
_TAILS_SOFT = {"ь", "я", "ю", "ем", "е", "й"}


def _name_matches(word: str, name: str) -> bool:
    """Слово из фразы — это имя в каком-то падеже? Оли/Олю/Олей → Оля; папу → Папа."""
    word, name = word.lower().replace("ё", "е"), name.lower().replace("ё", "е")
    if word == name:
        return True
    if name[-1] in "ая":
        stem, tails = name[:-1], _TAILS_VOWEL
    elif name[-1] in "ьй":
        stem, tails = name[:-1], _TAILS_SOFT
    else:
        stem, tails = name, _TAILS_CONS
    return len(stem) >= 2 and word.startswith(stem) and word[len(stem):] in tails


# Полное имя → как его называют дома. Нужны только распространённые; остальное решают слова автопривязки.
_SHORT = {
    "александр": ["саша", "шура", "сашка"], "александра": ["саша", "шура", "сашенька"], "алексей": ["леша", "алеша"],
    "анастасия": ["настя", "настенька"], "анатолий": ["толя", "толик"], "андрей": ["андрюша"], "анна": ["аня", "анечка", "анюта"],
    "артем": ["тема", "темка"], "валентина": ["валя"], "василий": ["вася"], "виктор": ["витя"], "виктория": ["вика"],
    "владимир": ["вова", "володя"], "галина": ["галя"], "дмитрий": ["дима", "митя"], "евгений": ["женя"],
    "евгения": ["женя"], "екатерина": ["катя", "катюша"], "елена": ["лена", "леночка"], "елизавета": ["лиза"],
    "иван": ["ваня"], "игорь": ["игорек"], "ирина": ["ира", "иришка"], "константин": ["костя"], "ксения": ["ксюша"],
    "людмила": ["люда", "люся"], "любовь": ["люба"], "максим": ["макс"], "маргарита": ["рита"],
    "мария": ["маша", "машенька", "маруся"], "михаил": ["миша"], "надежда": ["надя"], "наталья": ["наташа", "ната"],
    "наталия": ["наташа", "ната"], "николай": ["коля"], "ольга": ["оля", "оленька", "олечка"], "павел": ["паша"],
    "полина": ["поля"], "светлана": ["света"], "сергей": ["сережа", "серега"], "софья": ["соня"], "софия": ["соня"],
    "татьяна": ["таня", "танюша"], "юлия": ["юля"], "яна": [],
}


def _aliases(name: str) -> list[str]:
    """Имя и слова из него: «Оля Иванова» → оля, иванова; «Ольга» → ольга, оля, оленька…"""
    out = []
    for w in name.replace("ё", "е").lower().replace("-", " ").split():
        out.append(w)
        out += _SHORT.get(w, [])
    # и в обратную сторону: Оля → Ольга
    for full, shorts in _SHORT.items():
        if any(w in shorts for w in out[:1]):
            out.append(full)
    return out


def genitive(name: str, surname: bool = False) -> str:
    """У Оли, у Маши, у Папы, у Олега."""
    if not name:
        return name
    if " " in name:
        parts = name.split()
        return " ".join(genitive(w, surname=(i > 0 and w.lower().endswith(("ова", "ева", "ина", "ына", "ская", "цкая")) and len(parts) == 2 and parts[0].lower() not in ("бабушка", "дедушка", "тётя", "тетя")))
                        for i, w in enumerate(parts))
    last = name[-1].lower()
    if surname and last == "а":
        return name[:-1] + "ой"
    if last in "ая":
        prev = name[-2].lower() if len(name) > 1 else ""
        return name[:-1] + ("и" if last == "я" or prev in "гкхжчшщц" else "ы")
    if last in "ьй":
        return name[:-1] + "я"
    return name + "а"


WEEKDAY_IN = ["в понедельник", "во вторник", "в среду", "в четверг", "в пятницу", "в субботу", "в воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def when_text(start: datetime, now: datetime) -> tuple[str, str]:
    """('сегодня в 19:00', 'сегодня в 19 часов') — текст и озвучка."""
    d = (start.date() - now.date()).days
    if d == 0:
        day = "сегодня"
    elif d == 1:
        day = "завтра"
    elif d == 2:
        day = "послезавтра"
    elif 2 < d < 7:
        day = WEEKDAY_IN[start.weekday()]
    else:
        day = f"{start.day} {MONTHS[start.month - 1]}"
    text = f"{day} в {start:%H:%M}"
    tts = f"{day} в {start.hour} часов" if start.minute == 0 else f"{day} в {start.hour} {start.minute:02d}"
    return text, tts

# --------------------------------------------------------------------------- разбор фразы


def find_person(snap: dict, words: list[str]) -> dict | None:
    best = None
    for p in snap.get("people", []):
        cands = _aliases(p["name"]) + [k.strip() for k in (p.get("keywords") or "").split(",") if k.strip()]
        for w in words:
            if any(_name_matches(w, c) for c in cands):
                score = len(w)
                if not best or score > best[0]:
                    best = (score, p)
    return best[1] if best else None


def _intent(words: list[str], text: str) -> str:
    t = text.lower()
    if any(w.startswith(x) for w in words for x in ("отвез", "отвоз", "забер", "забир", "везет", "везёт")):
        return "escort"
    if "сейчас" in words:
        return "now"
    if any(w in words for w in ("сегодня", "завтра", "послезавтра")) and not any(w.startswith(("следующ", "ближайш")) for w in words):
        return "day"
    return "next"


def _events_of(snap: dict, pid: str) -> list[dict]:
    return sorted((e for e in snap.get("events", []) if pid in e.get("people", [])), key=lambda e: e["start"])


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _ans(text: str, tts: str | None = None) -> tuple[str, str]:
    return text, tts or text


def answer_next(snap, person, now, whose, whose_gen):
    for e in _events_of(snap, person["id"]):
        if e.get("all_day") or _dt(e["end"]) <= now:
            continue
        s = _dt(e["start"])
        if s <= now:
            return _ans(f"Сейчас {whose}: {e['title']}, до {_dt(e['end']):%H:%M}.")
        text, tts = when_text(s, now)
        return _ans(f"Следующая встреча {whose_gen}: {e['title']}, {text}.", f"Следующая встреча {whose_gen}: {e['title']}, {tts}.")
    return _ans(f"{_cap(whose_gen)} ближайшие дни встреч нет.")


def answer_now(snap, person, now, whose, whose_gen):
    for e in _events_of(snap, person["id"]):
        if not e.get("all_day") and _dt(e["start"]) <= now < _dt(e["end"]):
            return _ans(f"Сейчас {whose_gen}: {e['title']}, до {_dt(e['end']):%H:%M}.")
    return answer_next(snap, person, now, whose, whose_gen)


def answer_day(snap, person, now, words, whose_gen):
    off = 2 if "послезавтра" in words else 1 if "завтра" in words else 0
    day = (now + timedelta(days=off)).date()
    label = ["сегодня", "завтра", "послезавтра"][off]
    evs = [e for e in _events_of(snap, person["id"]) if _dt(e["start"]).date() <= day <= _dt(e["end"] if not e.get("all_day") else e["start"]).date()
           or _dt(e["start"]).date() == day]
    evs = [e for e in evs if e.get("all_day") or _dt(e["end"]) > now or off > 0]
    if not evs:
        return _ans(f"{_cap(whose_gen)} {label} ничего нет.")
    parts = [("весь день " if e.get("all_day") else f"в {_dt(e['start']):%H:%M} ") + e["title"] for e in evs[:6]]
    def _t(e):
        s = _dt(e["start"])
        return "весь день " if e.get("all_day") else (f"в {s.hour} часов " if s.minute == 0 else f"в {s.hour} {s.minute:02d} ")
    tts_parts = [_t(e) + e["title"] for e in evs[:6]]
    more = f" И ещё {len(evs) - 6}." if len(evs) > 6 else ""
    return _ans(f"{_cap(label)} {whose_gen}: " + "; ".join(parts) + "." + more,
                f"{_cap(label)} {whose_gen}: " + "; ".join(tts_parts) + "." + more)


def answer_escort(snap, person, now, whose_gen):
    names = {p["id"]: p["name"] for p in snap.get("people", [])}
    for e in _events_of(snap, person["id"]):
        esc = e.get("escort")
        if not esc or e.get("all_day") or _dt(e["end"]) <= now:
            continue
        if esc.get("mode") == "home":
            return _ans(f"{e['title']}: {person['name']} добирается сам, в доме.")
        if esc.get("mode") == "together":
            return _ans(f"{e['title']}: все идут вместе.")

        def who(role):
            r = esc[role]
            if r.get("skip"):
                return None
            return names.get(r.get("person")) or "никто не назначен"
        text, tts = when_text(_dt(e["start"]), now)
        bits = []
        for role, label in (("dropoff", "Отвезти"), ("pickup", "Забрать")):
            w = who(role)
            if w:
                bits.append(f"{label}: {w}")
        return _ans(f"{e['title']} {whose_gen}, {text}. " + ". ".join(bits) + ".",
                    f"{e['title']} {whose_gen}, {tts}. " + ". ".join(bits) + ".")
    return _ans(f"Поездок {whose_gen} в ближайшие дни нет.")

# --------------------------------------------------------------------------- добавление событий

ADD_WORDS = ("добавь", "запиши", "создай", "поставь", "внеси", "запланируй", "добавить", "записать")
_DAY_RE = re.compile(r"(?<!\w)(сегодня|завтра|послезавтра|понедельник\w*|вторник\w*|сред[уаы]|четверг\w*|пятниц\w*|суббот\w*|"
                     r"воскресень\w*|через\s+\S+|\d{1,2}\.\d{1,2}|\d{1,2}\s+(?:январ|феврал|март|апрел|ма[яй]|июн|июл|август|сентябр|октябр|ноябр|декабр)\w*)")


def normalize_speech(text: str) -> str:
    """Алиса отдаёт время как «в 18 00» — приводим к «в 18:00» для разбора на сервере."""
    return re.sub(r"(?<![\d:])(в|к|с)\s+(\d{1,2})\s+(\d{2})(?!\d)", r"\1 \2:\3", text)


def _encrypt(key: bytes, data: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, data, b"homehub-v1")


def send_command(op: dict) -> None:
    """Кладёт команду на Диск (один файл на команду: гонок между запусками функции нет)."""
    token, key = os.environ["HOMEHUB_TOKEN"], _b64(os.environ["HOMEHUB_KEY"])
    name = f"ops-alice-{op['id']}.bin"
    hdr = {"Authorization": f"OAuth {token}"}
    q = urllib.parse.urlencode({"path": f"app:/{name}", "overwrite": "true"})
    req = urllib.request.Request("https://cloud-api.yandex.net/v1/disk/resources/upload?" + q, headers=hdr)
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as r:
        href = json.loads(r.read())["href"]
    put = urllib.request.Request(href, data=_encrypt(key, json.dumps([op], ensure_ascii=False).encode()), method="PUT")
    urllib.request.urlopen(put, timeout=FETCH_TIMEOUT).read()


def is_add(command: str) -> bool:
    w = command.lower().split()
    return bool(w) and w[0] in ADD_WORDS


def answer_add(req: dict, send=send_command) -> dict:
    command = (req.get("request", {}).get("command") or "").strip()
    state = (req.get("state") or {}).get("user") or {}
    text = normalize_speech(command.split(None, 1)[1] if " " in command else "")
    text = re.sub(r"^(?:в\s+)?(?:календарь|расписание)\s+", "", text, flags=re.I).strip()
    if not os.environ.get("HOMEHUB_TOKEN"):
        return _reply("Чтобы я добавляла события, в настройках навыка нужен токен записи. Пока могу только рассказывать расписание.")
    if not text:
        return _reply("Что добавить? Например: добавь на завтра в 18:00 врача Марку.", end=False)
    if not _DAY_RE.search(text.lower()):
        return _reply("На какой день? Скажите всё вместе: добавь на завтра в 18:00 врача Марку.", end=False)
    op = {"id": uuid.uuid4().hex[:12], "t": int(time.time() * 1000), "type": "event_quick", "text": text}
    if re.search(r"(?<!\w)(мне|мой|моя|моё)(?!\w)", text.lower()) and state.get("person"):
        op["people"] = [state["person"]]
    try:
        send(op)
    except Exception as e:  # noqa: BLE001
        print("send error:", repr(e))
        return _reply("Не получилось отправить в календарь. Попробуйте ещё раз чуть позже.")
    return _reply(f"Записала: {text}. В календаре появится через минуту-две.")


# --------------------------------------------------------------------------- Алиса

HELP = ("Я знаю расписание семьи. Спросите: когда следующая встреча Оли, что завтра у Маши, "
        "кто отвозит Машу. Скажите «я Оля», и я запомню, что «мои» встречи — ваши. "
        "А ещё могу записать: «добавь на завтра в 18:00 врача Марку».")


def _reply(text, tts=None, end=True, user_state=None):
    out = {"response": {"text": text, "tts": tts or text, "end_session": end}, "version": "1.0"}
    if user_state is not None:
        out["user_state_update"] = user_state
    return out


def respond(req: dict, snap: dict, now: datetime | None = None) -> dict:
    r = req.get("request", {})
    command = (r.get("command") or "").strip()
    words = [w for w in (r.get("nlu", {}).get("tokens") or command.lower().replace(",", " ").split()) if w]
    state = (req.get("state") or {}).get("user") or {}
    now = now or datetime.now(_dt(snap["generated"]).tzinfo)

    if not command:
        return _reply("Привет! " + HELP, end=False)
    if any(w in ("помощь", "умеешь", "что") for w in words[:2]) and len(words) <= 3 and "ты" in words:
        return _reply(HELP, end=False)

    # «я Оля», «меня зовут Оля» — запоминаем, кто говорит
    if words and (words[0] == "я" or words[:2] == ["меня", "зовут"] or words[0] == "запомни"):
        me = find_person(snap, words[1:] if words[0] != "я" else words[1:])
        if me:
            return _reply(f"Хорошо, {me['name']}. Теперь «моя встреча» значит ваша.", user_state={"person": me["id"]}, end=False)

    person = find_person(snap, [w for w in words if w not in ("мне", "мои", "моя", "мой", "моё", "я")])
    mine = False
    if not person and any(w in ("мне", "мои", "моя", "мой", "моё", "я", "меня", "у") for w in words):
        pid = state.get("person")
        person = next((p for p in snap.get("people", []) if p["id"] == pid), None)
        mine = True
        if not person:
            return _reply("Скажите, чьё расписание: например, «когда следующая встреча Оли». Или представьтесь: «я Оля».", end=False)
    if not person:
        return _reply("Не поняла, чьё расписание. Я знаю: " + ", ".join(p["name"] for p in snap.get("people", [])) + ". " + HELP, end=False)

    whose = "у вас" if mine else f"у {genitive(person['name'])}"
    whose_gen = "у вас" if mine else genitive(person["name"])
    intent = _intent(words, command)
    if intent == "escort":
        text, tts = answer_escort(snap, person, now, whose)
    elif intent == "now":
        text, tts = answer_now(snap, person, now, whose, whose)
    elif intent == "day":
        text, tts = answer_day(snap, person, now, words, whose)
    else:
        text, tts = answer_next(snap, person, now, whose, whose)
    return _reply(text, tts)


def handler(event, context=None):
    """Точка входа Yandex Cloud Functions."""
    req = event if "request" in event else json.loads(event.get("body") or "{}")
    try:
        if is_add((req.get("request", {}).get("command") or "")):
            out = answer_add(req)   # снимок календаря для записи не нужен
        else:
            out = respond(req, load_snapshot())
    except Exception as e:  # навык не должен молчать
        out = _reply("Календарь ещё просыпается. Повторите вопрос через несколько секунд.")
        print("error:", repr(e))
    return out if "request" in event else {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps(out, ensure_ascii=False)}
