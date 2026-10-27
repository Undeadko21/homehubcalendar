# Заметки для разработки (читать перед любыми изменениями)

Проект: семейный календарь-агрегатор. Пользователь общается по-русски, интерфейс и
комментарии на русском. Развёрнут на домашнем Proxmox в LXC с Docker,
обновляется автоматически из ветки `main` (deploy/update.sh по таймеру).
**Значит, любой пуш в main сразу уезжает в прод — перед пушем гоняем тесты и сборку.**

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
- Свободное время: `freetime.py` — объединение занятости выбранных людей (+ их поездки).
- Настройки из UI (`configured=1`) важнее правил из config.yaml и не перетираются синхронизацией.

## Бэкенд (`backend/app`)

| Файл | Что внутри |
|---|---|
| `config.py` | config.yaml + подстановка `${ENV}` |
| `db.py` | SQLite, миграции списком `MIGRATIONS` (только дописывать в конец!) |
| `sources/` | источники; новый тип = класс с `@register("тип")` + импорт в `__init__.py` |
| `expand.py` | iCalendar → вхождения (recurring-ical-events), часовые пояса |
| `events.py` | сборка ленты, склейка дублей (UID+start, нечёткая по названию+времени), маскировка приватных |
| `holidays.py` | производственный календарь (isdayoff.ru с кэшем, запасной — фиксированные праздники) |
| `sync.py` | движок синхронизации, автосоздание людей из конфига |
| `escorts.py` | «кто отвозит/забирает», конфликты, свободные взрослые |
| `freetime.py` | общие свободные окна по дням |
| `main.py` | API, PIN-защита, раздача SPA |

API: `GET /api/config`, `GET /api/events?start&end`, `GET /api/holidays?start&end`,
`GET /api/status`, `POST /api/sync`, `PUT|DELETE /api/people/{id}`, `PATCH /api/calendars/{key}`,
`POST /api/event-people {uid, people|null}`, `POST /api/escort {uid, occurrence|null, role (dropoff|pickup|mode), person|'-'|mode|null}`,
`PUT /api/settings/escort`, `GET /api/free?people&start&end&day_from&day_to&min_minutes&all_day`, `PUT /api/accounts/{source_id}` (логин/пароль CalDAV из интерфейса, хранятся в `kv` как `auth:<id>`, важнее пустых значений из config.yaml).
Время в запросах без пояса трактуется в поясе из config.yaml.

## Фронтенд (`frontend/src`)

Vue 3 + Vite, FullCalendar только для «Недели» и «Месяца». Без роутера: вид в `state.view`.

- `lib/store.js` — общее состояние, фильтр людей (localStorage), кэш запросов.
- `lib/report.js` — ловит ошибки клиента, показывает красный баннер в App.vue и шлёт на `POST /api/client-log` (смотреть `GET /api/client-log`). Для старых WebView: `@vitejs/plugin-legacy` (полифилы) и класс `no-color-mix` на `<html>` с запасными стилями.
- `lib/useRange.js` — загрузка событий для диапазона; перезагрузка по `state.revision`.
- `views/` — Today, Timeline (собственная «семейная лента»), Calendar (FullCalendar), Agenda, Free, Settings.
- `components/` — EventPill (таблетка события), EventDialog (карточка-лист), EscortBadge (→ кто / ← кто),
  Sheet (лист снизу на телефоне / карточка на компьютере), MiniMonth, PeopleList, PeoplePicker,
  DayGrid (дневная сетка «Сегодня»: общая шкала часов, колонка на человека, линия «сейчас»;
  общие события и поездки рисуются одной полосой через соседние колонки участников, кроме
  колонок, где в это время есть другое событие; порядок колонок = порядок людей в настройках).

Дизайн — по просьбе пользователя «как Календарь Apple»: системный шрифт (SF, на Android — Inter),
красный `--red` для «сегодня/сейчас» и кнопок-ссылок, тонкие линии, сгруппированные списки
(`.group/.row` в styles.css), боковая панель с мини-календарём на компьютере (≥900px),
нижние вкладки на телефоне; на узком экране «Неделя» = 3 дня. Цвет несут только люди,
палитра — системные цвета Apple. Токены в `styles.css` (светлая/тёмная тема).

## Приложение для Android (`android/`)

Kotlin, без лишних зависимостей (core-ktx, WorkManager). Пакет `ru.homehub.calendar`, minSdk 26.
- `SetupActivity` — поиск календаря в /24-подсети телефона (порты 8080 и 80, `/api/health`) или ввод адреса.
- `MainActivity` — WebView с веб-интерфейсом; UA содержит `HomeHubApp/<версия>`, мост
  `window.HomeHubApp` (changeServer, refreshWidget, version). Внешние ссылки — в браузер.
  Проверяет `/api/app` и предлагает обновиться (скачивание `/app.apk`).
- Виджет `WidgetProvider` + `WidgetService` (список) + `RefreshWorker` (WorkManager, каждые 15 мин и
  по кнопке). Данные — `GET /api/widget` (`backend/app/widget.py`): сервер отдаёт готовые строки,
  поэтому содержимое виджета меняется на сервере без обновления приложения. Вход по PIN — куки WebView.
- Сборка: SDK в /opt/android-sdk (ставится cmdline-tools → `sdkmanager "platforms;android-35"
  "build-tools;35.0.0"`). Выпуск: увеличить versionCode в `android/version.properties`,
  `./android/build-release.sh` → `android/release/` (APK + version.json) → закоммитить. Сервер раздаёт
  `android/release` по `/app.apk` и `/api/app`.
- Подпись — постоянный ключ `android/keystore/homehub-release.jks` (пароль в app/build.gradle.kts),
  иначе обновления не встанут поверх. Не менять!
- Снимки макетов без телефона: `./gradlew recordPaparazziDebug` → `app/src/test/snapshots/images`.

## Проверка перед пушем

```bash
cd backend && python -m pytest -q
cd ../frontend && npm run build
```
Для визуальной проверки: `python backend/tools/make_demo.py demo` + `demo/config.yaml`
(источники type: ics на локальные файлы), запустить uvicorn и открыть виды.

## Дорожная карта

Сделано (v0.1): чтение из CalDAV/ICS, 5 видов, фильтр, склейка дублей, приватность,
праздники РФ, киоск, PIN, автодеплой.
v0.2: логин/пароль в интерфейсе, несколько владельцев календаря, участники события
вручную, слова автопривязки. CLASS:PRIVATE из Яндекса по умолчанию игнорируется
(Яндекс ставит его почти всем событиям) — см. `privacy.respect_event_class`.

v0.3: «кто отвозит/забирает» детей с конфликтами, поиск общего свободного времени,
редизайн в стиле Apple Calendar.
v0.4: «как добирается» (вместе/дома), поездки в календарях взрослых, дневная сетка «Сегодня»
с растягиванием общих событий, приложение для Android с виджетом (раздаётся с сервера).

Дальше (по согласованию с пользователем):
- Уведомления: Telegram в РФ не подходит; варианты — веб-push в PWA, ntfy на сервере,
  локальные напоминания в Android-приложении. Для работы вне дома нужен доступ снаружи (VPN/домен).
- Дни рождения с обратным отсчётом.
- Запись событий в Яндекс (CalDAV PUT) — второй этап.
- Рабочие календари одной полосой «на работе».
- Списки дел/покупок.
