# Архитектура и данные

Как устроены данные: события, люди, поездки детей, дни рождения, напоминания; карта модулей бэкенда.

## Архитектура

```
Яндекс CalDAV / ICS ──► sync.py (раз в N минут) ──► SQLite: сырые VCALENDAR-объекты
                                                        │
браузер ◄── Vue SPA ◄── FastAPI /api/events ◄── events.py: разворачивание повторов
                                                (expand.py) → люди → склейка дублей
```

- Храним **сырые** iCalendar-объекты, повторы разворачиваем при запросе диапазона.
  Логику отображения можно менять без пересинхронизации.
- Чьё событие (по приоритету): 1) участники, выбранные вручную в карточке события
  (`event_people`, по UID — на все повторы); 2) иначе все владельцы календаря
  (`calendar_people`, их может быть несколько) + люди, чьи слова автопривязки
  (`people.keywords`, через запятую) встречаются в названии. `calendars.person_id` —
  устаревшее поле, держится равным первому владельцу.
- Дети (`people.needs_escort`): у их событий со временем есть роли «отвезти»/«забрать»
  (`escorts`: uid + occurrence ('*' — серия, иначе время начала) + role; '-' — не нужно).
  `escorts.py` считает окна (настройка `kv settings:escort`), конфликты и кто свободен;
  `EventService.events` строит ленту с запасом ±1 день, чтобы конфликты на границах считались.
  «Как добирается» (`escorts` role='mode': escort | together | home): вручную или само —
  «дома» по словам/адресу из `settings:escort` (home_words, home_address), «вместе» — если
  среди участников есть взрослый. При together/home роли пропускаются, конфликтов нет.
  `escorts.add_to_adults`: назначенные поездки становятся событиями взрослого (поле `duty`,
  `id = <id события>:<role>`, тот же uid, `duty.parent` — исходное событие; клик открывает его),
  «все вместе» без взрослых участников показывается у всех взрослых. В freetime поездки
  считаются через duty_intervals, события с `duty` пропускаются, чтобы не было дублей.
  **Время в дороге** (`escorts` role='travel', значение — минуты): окно «отвезти» = дорога + запас до начала,
  «забрать» — после конца; приоритет: на день → на серию → правило по месту (`settings:escort.places`,
  слова в названии/месте → минуты) → фиксированные before/after. **Шаблоны** (`escort_templates`: ребёнок,
  день недели, слова, кто отвозит/забирает) — значение по умолчанию (scope='template'), ручные назначения важнее.
- Дни рождения: `birthdays.py` (таблица `birthdays` + целодневные события со словами «день рождения/ДР/birthday»
  автоматически, дубли по основе имени отсекаются). Списки дел/покупок: `lists`, `list_items`, общие на семью.
- Напоминания: `reminders.py` считает (поездки за `lead` минут, вечерний дайджест проблем на завтра, дни рождения),
  отдаёт `GET /api/reminders`; показывает их только Android-приложение (локальные уведомления).
- Связь вне дома без VPN: `snapshot.py` собирает снимок (виджет на 3 дня + напоминания на 7 дней; у поездок —
  `start` и `people`, а «за сколько минут» и «чьи» решает телефон), `cloud.py` шифрует его (AES-256-GCM, AAD
  `homehub-v1`, формат nonce(12)+ct) и кладёт в папку приложения на Яндекс.Диске, публикует; токен записи — `kv cloud:token`
  (вводится в настройках), ключ — `kv cloud:key`, код подключения `hhc1.<base64url JSON {u, k}>`. APScheduler раз в 2 минуты
  проверяет хэш снимка, пишет при изменениях и раз в час. `GET /api/snapshot` — тот же JSON без шифра (для приложения дома).
- **Подписки ICS из интерфейса** (Teams/Outlook, Битрикс24…): `kv ics:feeds` (шифруется, в URL секретный токен), `SyncEngine.sources` = config.yaml + подписки; `GET|PUT /api/feeds`, `DELETE /api/feeds/{id}` (URL наружу не отдаётся, только хост; принимаются только http(s)/webcal),
  UI — «Подключение» → `FeedsSettings.vue`. Ошибки ICS-источника не содержат ссылку. Отменённые встречи («Отменено:», «Canceled:» в начале названия) скрываются в `expand.py` (`is_cancelled_title`).
- **Цвет общих встреч.** `kv settings:shared_color` (`PUT /api/settings/shared-color`, в `/api/config` — `shared_color`) красит встречи с ≥2 людьми; свой цвет события — `kv event_colors {uid: #hex}` (`POST /api/event-color`, важнее общего, по UID — на все повторы).
  `EventService._apply_colors` кладёт `color` в событие (до добавления поездок взрослым, у `duty` цвета нет); фронт: `eventColor`, `EventPill`, `DayGrid`, `TimelineView` берут `e.color` первым; `widget.py` отдаёт его в `colors`. UI: `ColorPick.vue`, карточка события и «Люди» → «Общие встречи».
- Свободное время: `freetime.py` — объединение занятости выбранных людей (+ их поездки).
- Настройки из UI (`configured=1`) важнее правил из config.yaml и не перетираются синхронизацией.

## Бэкенд (`backend/app`)

| Файл | Что внутри |
|---|---|
| `config.py` | config.yaml + подстановка `${ENV}` |
| `db.py` | SQLite, миграции списком `MIGRATIONS` (только дописывать в конец!) |
| `sources/` | источники; новый тип = класс с `@register("тип")` + импорт в `__init__.py` |
| `expand.py` | iCalendar → вхождения (recurring-ical-events), часовые пояса |
| `unusual.py` | «необычная неделя»: пропуски/сдвиги серий за 4 прошлые недели, «не идёт», поздно у детей (`/api/unusual`, сводка понедельника) |
| `webpush.py` | уведомления в браузере: VAPID + шифрование RFC 8291 на `cryptography`, подписки `push:subs`, отправка раз в минуту из снимка |
| `feedback.py` | «Сообщить о проблеме»: сообщения семьи дома → `/api/watch` («Сообщение: …») → дозор |
| `trends.py` | итог дня (p95 маршрутов, ошибки экранов) → «Тренд: …» при ухудшении к прошлой неделе |
| `events.py` | сборка ленты, склейка дублей (UID+start, нечёткая по названию+времени), маскировка приватных |
| `holidays.py` | производственный календарь (isdayoff.ru с кэшем, запасной — фиксированные праздники) |
| `sync.py` | движок синхронизации, автосоздание людей из конфига |
| `escorts.py` | «кто отвозит/забирает», конфликты, свободные взрослые |
| `freetime.py` | общие свободные окна по дням |
| `birthdays.py` | ближайшие дни рождения, обратный отсчёт |
| `snapshot.py`, `cloud.py` | снимок для телефона и выгрузка на Яндекс.Диск |
| `reminders.py` | что и когда напомнить телефону |
| `main.py`, `core.py`, `api/*.py` | приложение и middleware / общие объекты / маршруты по темам |
| `conflicts.py`, `perf.py`, `live.py` | предупреждения о конфликтах, замер запросов, счётчик изменений для SSE |

API: `GET /api/config`, `GET /api/events?start&end`, `GET /api/holidays?start&end`,
`GET /api/status`, `POST /api/sync`, `PUT|DELETE /api/people/{id}`, `PATCH /api/calendars/{key}`,
`POST /api/event-people {uid, people|null}`, `POST /api/escort {uid, occurrence|null, role (dropoff|pickup|mode), person|'-'|mode|null}`,
`PUT /api/settings/escort`, `GET /api/free?people&start&end&day_from&day_to&min_minutes&all_day`, `PUT /api/accounts/{source_id}` (логин/пароль CalDAV из интерфейса, хранятся в `kv` как `auth:<id>`, важнее пустых значений из config.yaml).
Новое (v0.5): `GET|PUT /api/templates`, `DELETE /api/templates/{id}`; `GET /api/birthdays?days`, `PUT /api/birthdays`,
`DELETE /api/birthdays/{id}`; `GET /api/search?q`; `GET|POST /api/lists`, `PUT|DELETE /api/lists/{id}`,
`POST /api/lists/{id}/items|clear-done`, `PATCH|DELETE /api/items/{id}`; `GET /api/reminders?hours&lead&people`;
`POST /api/escort` принимает role=travel (минуты строкой); `PUT /api/settings/escort` — ещё `travel_buffer` и `places`.
Время в запросах без пояса трактуется в поясе из config.yaml.
