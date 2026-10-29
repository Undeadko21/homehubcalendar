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
- **Этап 2 (v0.7): команды с телефона вне дома.** Снимок v2 дополнен `people`, `events`, `lists`, `applied`. Телефон кладёт в папку
  приложения на Диске зашифрованный файл `ops-<device>.bin` (список команд `escort`/`item_add`/`item_done`/`item_delete`, у каждой `id`, `t`);
  код подключения содержит токен записи (`t`) — это доступ к папке, не светить. `cloud.poll_ops` раз в минуту смотрит md5 файлов `ops-*.bin`,
  `ops.py` применяет команды идемпотентно (id в `cloud:applied`, отклонённые тоже), затем сбрасывает кэш и принудительно пишет снимок.
  Android: `Outbox.kt` (очередь + последний снимок), `Sync.run` сначала отправляет очередь; `MainActivity.load()` проверяет сервер за 2,5 с и при
  неудаче (облако подключено + есть снимок) показывает офлайн-экран `assets/offline/` (события, списки, назначение поездок).
- **Токен Диска** проверяется (`cloud.token_ok`: ≥20 символов, ASCII, без пробелов); `PUT /api/cloud` отвечает 400 на мусор, `tick` пишет
  `last_error`. Неверный токен = снимок v2 не пишется, телефон и Алиса видят старый.
- **Навык Алисы** (`alice/`): функция Yandex Cloud (python312, точка входа `handler.handler`, переменные `HOMEHUB_URL` и `HOMEHUB_KEY` из блока
  «Для навыка Алисы» в настройках → Облако). Читает тот же зашифрованный снимок с Диска (`GET /api/cloud` → `alice:{url,key}`), домой не ходит.
  Отвечает на «когда следующая/что сейчас/что завтра/кто отвозит у Оли»; имена — склонения и уменьшительные, «я Оля» хранится в user_state.
  Алиса ждёт ≤3 с: снимок грузится в потоке (`WAIT_SECONDS=2.4`), кэш 120 с; на холодном старте возможно «Календарь ещё просыпается» — повтор.
  Код обновляется вручную: `alice/function.zip` (handler.py + requirements.txt) → консоль функции → Редактор → ZIP-архив → «Сохранить изменения»
  (пересобрать zip после правок). Навык в Яндекс Диалогах — «Приватный», активация «Моя семья»; тесты: `python -m pytest alice/test_handler.py`.
- **v0.7.7.** `backup.py`: раз в сутки (03:30) зашифрованная ключом облака копия SQLite (backup API + gzip + AES-GCM, AAD `homehub-backup-v1`) в
  `app:/backups/` на Диске, хранится 14 последних; расшифровка — `backend/tools/restore_backup.py файл ключ выход.db`. `school.py`: школьные каникулы
  (`kv settings:school`, диапазоны задаёт семья) подмешиваются в `/api/holidays` (поле `vacation` или type=vacation, выходным днём не считаются).
  `stats.py`: `GET /api/stats?start&end` (встречи/часы/поездки по людям, дни недели, частые названия). `GET /api/system`: версия, синхронизация, облако,
  копии, ошибки клиентов и список `problems` (красная точка в меню настроек). API: `GET|PUT /api/school`, `GET|POST /api/backup`. UI: в настройках
  страницы «Итоги семьи», «Состояние и копии», «Дни рождения и каникулы». Погода (WeatherNow, open-meteo из браузера) дополнена прогнозом на завтра и подсказкой.
- **Приложение для macOS** (`macos/`, SwiftPM, macOS 13+): `HomeHubCore` (код подключения, расшифровка снимка CryptoKit, `Agenda` — «что дальше»; тесты
  `swift test`, включая блоб, зашифрованный сервером) и `HomeHubMac` (SwiftUI: окно = WKWebView сервера, иначе офлайн-список из снимка; значок в строке меню
  с ближайшим событием; локальные уведомления из `reminders`; запуск при входе). Дома берёт `/api/snapshot`, вне дома — снимок с Диска по коду `hhc1.`.
  Swift локально недоступен: собирает и тестирует GitHub Actions (`.github/workflows/macos.yml`, macos-14) и кладёт `macos/release/HomeHub-Calendar.zip` +
  `version.json` в main (`[skip ci]`); сервер раздаёт `/app-mac.zip`, `/api/app-mac` (`HOMECAL_MAC_DIR`). Версия — `macos/version.txt`. Ошибки CI смотреть:
  `gh api repos/Undeadko21/homehubcalendar/actions/jobs/<id>/logs`. Подпись ad-hoc (без аккаунта Apple): первый запуск через «Открыть».
- **Приложение для iPhone** (`ios/`, SwiftUI, iOS 16+, ставится через AltStore бесплатным Apple ID): проект генерирует XcodeGen из `ios/project.yml` (в нём же
  Info.plist), в цель входят общие файлы Mac-приложения (`HomeHubCore/`, `AppModel.swift`, `Notifier.swift` — поэтому там `#if canImport(HomeHubCore)`
  и `#if os(macOS)`). Интерфейс: NavigationStack с WebView сервера (или список из снимка), листы «Ближайшие» и «Настройки», фоновое обновление BGAppRefresh.
  GitHub Actions (`ios.yml`, macos-15) собирает **неподписанный** `.ipa` (AltStore подписывает на телефоне) и кладёт в `ios/release/` (`[skip ci]`).
  Сервер раздаёт `/app-ios.ipa`, `/api/app-ios` и источник для AltStore `/altstore.json` (адрес берётся из запроса; AltStore → Sources → «+»).
  Виджета нет (App Groups на бесплатном аккаунте ненадёжны). Версия — `ios/version.txt`.
- **Запись событий в Яндекс (v0.8).** `writer.py`: `build_ics` (TZID конфигурационного пояса, весь день — VALUE=DATE с исключающим концом, RRULE daily/weekly/monthly/yearly + interval/count/until),
  `apply_edit` (правка мастер-VEVENT; для серии — сдвиг на разницу от редактируемого вхождения, `occurrence`), `add_exdate` («удалить только это»), `CalDavTarget` (caldav: create/update/delete). API:
  `POST /api/event`, `PUT /api/event/{uid}`, `DELETE /api/event/{uid}?calendar=&occurrence=`; после записи объект кладётся в `objects` (`put_object/delete_object/find_object`), кэш сбрасывается,
  снимок обновляется. Календарь пишущий, если его источник `type: caldav` (поле `writable` в `/api/config`, `write: false` в источнике отключает). Правка серии — вся серия. `make_target` в main подменяется в тестах.
  **На настоящем Яндексе проверялось только вручную пользователем** (в среде разработки доступа нет). UI: `EventEditor.vue`, кнопка «+» в тулбаре, «Изменить» в `EventDialog`.
- **Напоминания о встречах (v0.8).** `kv settings:event_reminders` = `{people: {id: [минуты…]}}` (`reminders.load_rules/save_rules`, `GET|PUT /api/settings/event-reminders`, UI `EventReminders.vue`). `reminders.build(... event_rules)`
  даёт `kind: event` с готовым `at`, `people` (кому именно это время) и `start`; устройства только фильтруют по своим выбранным людям (Android `Reminders.apply`, `Notifier.swift`). Событий на весь день, приватных и поездок это не касается.
- **Автообновление Mac.** `macos/Sources/HomeHubMac/Updater.swift`: проверка `/api/app-mac` (при запуске и раз в 6 ч), сравнение с `CFBundleVersion` (= номер запуска CI), скачивание zip, распаковка `ditto`,
  замена .app скриптом после выхода процесса + перезапуск. Не работает из «Загрузок» (AppTranslocation) и без прав на папку; вне дома — вручную. Первая версия с обновлением ставится вручную.
- **Надёжная запись (v0.8).** `writeq.py`: `WriteService` — локально сразу, на Яндекс сразу или в очередь (`kv writeq`, повтор раз в 2 мин `ws.flush`; временные ошибки = не 400/401/403/404/409/412,
  `reapply` после синхронизации возвращает неотправленное; у ещё не созданных событий href `pending:<id>`). Журнал `kv changelog` (40 правок, до/после ICS): `GET /api/changes`, `POST /api/changes/{id}/undo|flush`;
  UI — настройки → «Журнал изменений» (`ChangeLog.vue`); неотправленное — в `problems` системы. `quick.py` + `POST /api/quick`: разбор фразы («Йога завтра в 18:30 у Оли») в поля формы (проверка человеком).
  Перетаскивание событий (`lib/moveEvent.js` `canMove/moveEvent`, `lib/drag.js` — мышь сразу, палец после долгого нажатия): «Неделя»/«Месяц» через `@fullcalendar/interaction`, «Сегодня» (`DayGrid`: время шагом 15 мин + нижний край = длительность), «Лента» (шкала 1–3 дня: время и день; неделя и весь день — на другой день по `data-day`), «Список» (на другой видимый день). Повторяющиеся: `MoveScope.vue` спрашивает «только это» (`writer.split_occurrence`: EXDATE + новое событие) или «вся серия». Нельзя: приватные, поездки, дни рождения, календари без записи. `portable.py`: `GET /api/export`, `POST /api/import`
  (люди, привязки, шаблоны, дни рождения, списки, `settings:*`; без событий, паролей и токенов), кнопки в «Состояние и копии».
- **Виджеты (Android 2.0, macOS 1.2).** Android: масштабируется от 1 клетки (`widget_info.xml`), у каждого виджета свои настройки `WidgetCfg` (текст, прозрачность фона, дни, подробности, шапка; `WidgetPrefs`, экран `WidgetConfigActivity`, открывается при добавлении и «Настроить» на Android 12+); шапка перестраивается по размеру (`OPTION_APPWIDGET_MIN_*`). macOS: настоящий WidgetKit не делали (без Apple ID-подписи и App Groups он ненадёжен, проверить без Mac нельзя) — вместо него `DesktopWidget.swift`: окно SwiftUI, превращённое в виджет через `NSWindow` (уровень рабочего стола, все Spaces, без рамки), пресеты размера и произвольное растягивание, настройки в `UserDefaults` (`widget.*`), открывается при запуске, если `widget.on`.
- **v0.9: надёжность и предупреждения.** *Синхронизация инкрементальная:* `CalDavSource.fetch(known)` читает `CS:getctag` каждого календаря и не качает объекты, если метка та же (`RemoteCalendar.unchanged`);
  метки в `kv sync:ctags`; `SyncEngine.run(full=False)` — каждый 12-й запуск (≈2 ч) и ручная «Синхронизировать» качают всё; кэш событий сбрасывается (`on_change`) только если объекты реально изменились.
  *Деплой с откатом:* `deploy/update.sh` после `docker compose up --build` ждёт `/api/health` ≤90 с, иначе `git reset` на прошлый коммит, пересборка и запись плохого коммита в `data/.bad_commit` (повторно не пробует; `--force` — пробует).
  CI: `.github/workflows/backend.yml` (pytest backend + alice, сборка фронта). *Восстановление:* `backup.check_db` (integrity_check) проверяет копию при создании; `BackupService.files/verify/restore`
  (restore: страховочный `before-restore.db.gz` рядом с базой, затем sqlite backup API в живое соединение + миграции); API `GET /api/backup/files`, `POST /api/backup/verify|restore`; UI — «Состояние и копии».
  *Скорость:* `perf.py` + middleware `timing` (по шаблону маршрута, медленные ≥700 мс в лог и в `GET /api/perf`, число — `slow_requests` в `/api/system`; секция «Скорость» в UI).
  *Конфликты:* `conflicts.check` примеряет событие к ленте ±1 день (копии, ничего не пишет): занятость участников (включая их поездки), поездки ребёнка (не сможет/некому/нужно назначить), поездки других детей, которые это событие ломает.
  `POST /api/conflicts {calendar,title,start,end,people,uid}` → `items[{level warn|info,text}]`; `EventEditor` показывает их по мере ввода, перетаскивание (`moveEvent.confirmConflicts`, `MoveWarn.vue`) спрашивает «Всё равно перенести» только при `warn`. События на весь день и повторы (кроме первого вхождения) не проверяются.
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
| `birthdays.py` | ближайшие дни рождения, обратный отсчёт |
| `snapshot.py`, `cloud.py` | снимок для телефона и выгрузка на Яндекс.Диск |
| `reminders.py` | что и когда напомнить телефону |
| `main.py` | API, PIN-защита, раздача SPA |

API: `GET /api/config`, `GET /api/events?start&end`, `GET /api/holidays?start&end`,
`GET /api/status`, `POST /api/sync`, `PUT|DELETE /api/people/{id}`, `PATCH /api/calendars/{key}`,
`POST /api/event-people {uid, people|null}`, `POST /api/escort {uid, occurrence|null, role (dropoff|pickup|mode), person|'-'|mode|null}`,
`PUT /api/settings/escort`, `GET /api/free?people&start&end&day_from&day_to&min_minutes&all_day`, `PUT /api/accounts/{source_id}` (логин/пароль CalDAV из интерфейса, хранятся в `kv` как `auth:<id>`, важнее пустых значений из config.yaml).
Новое (v0.5): `GET|PUT /api/templates`, `DELETE /api/templates/{id}`; `GET /api/birthdays?days`, `PUT /api/birthdays`,
`DELETE /api/birthdays/{id}`; `GET /api/search?q`; `GET|POST /api/lists`, `PUT|DELETE /api/lists/{id}`,
`POST /api/lists/{id}/items|clear-done`, `PATCH|DELETE /api/items/{id}`; `GET /api/reminders?hours&lead&people`;
`POST /api/escort` принимает role=travel (минуты строкой); `PUT /api/settings/escort` — ещё `travel_buffer` и `places`.
Время в запросах без пояса трактуется в поясе из config.yaml.

## Фронтенд (`frontend/src`)

Vue 3 + Vite, FullCalendar только для «Недели» и «Месяца». Без роутера: вид в `state.view`.

- `lib/store.js` — общее состояние, фильтр людей (localStorage), кэш запросов.
- `lib/report.js` — ловит ошибки клиента, показывает красный баннер в App.vue и шлёт на `POST /api/client-log` (смотреть `GET /api/client-log`). Для старых WebView: `@vitejs/plugin-legacy` (полифилы) и класс `no-color-mix` на `<html>` с запасными стилями.
- `lib/useRange.js` — загрузка событий для диапазона; перезагрузка по `state.revision`.
- `views/` — Today, Timeline (собственная «семейная лента»), Calendar (FullCalendar), Agenda, Free, Lists, Search, Settings.
  Редакторы в настройках: `TemplatesEditor`, `BirthdaysEditor`, `RemindersSettings` (только внутри приложения), `BirthdayStrip` — на «Сегодня».
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
- Единое обновление `Sync.kt` (WorkManager раз в 15 мин, `RefreshWorker`): сначала `/api/snapshot` с сервера, если не
  отвечает — `Cloud.kt` читает зашифрованный снимок с Яндекс.Диска по публичной ссылке (без кук); из снимка — виджет и
  напоминания. Подключение: `AppBridge.setCloud(код)` (кнопка в настройках сервера, дома). Тест совместимости шифра: `CloudTest`.
- Напоминания (`Reminders.kt`): из снимка, ставит `AlarmManager`
  (inexact, без спец. разрешений), `ReminderReceiver` показывает уведомление; показанные id — в `Prefs.shownReminders`.
  Настройки (вкл/кто/за сколько минут) — на телефоне, мост `getNotify/setNotify/requestNotifications/testNotification`.
  По умолчанию выключены: человек выбирает, чьи поездки ему напоминать. Строка дней рождения в виджете — `birthdays` из `/api/widget`.
- Обновление: приложение само качает APK в кэш и открывает установщик (FileProvider, REQUEST_INSTALL_PACKAGES).
- Экран рисуется под системными панелями (Android 15) — `padForSystemBars()` в `Insets.kt`.
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

v0.5: время в дороге и шаблоны поездок, напоминания в Android-приложении, дни рождения (в т.ч. в виджете),
поиск, списки дел и покупок.

Дальше (по согласованию с пользователем):
v0.6: снимок на Яндекс.Диске (виджет и напоминания вне дома). Этап 2 (идея): телефон кладёт в облако очередь команд
(назначить водителя, список покупок), сервер применяет; для этого нужен токен записи в приложении и офлайн-слой в интерфейсе.
Полный доступ вне дома (VPN/домен) пользователь не хочет.
- Запись событий в Яндекс (CalDAV PUT) — второй этап.
Пользователь отказался от: «кто я» на телефоне, рабочих календарей одной полосой.
