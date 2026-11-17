# Приложения: Android, iPhone, Mac, навык Алисы, виджеты

Swift и Kotlin здесь не запускаются: Swift проверяет только CI (GitHub Actions), Android собирается локально (`android/build-release.sh`).

- **Навык Алисы** (`alice/`): функция Yandex Cloud (python312, точка входа `handler.handler`, переменные `HOMEHUB_URL` и `HOMEHUB_KEY` из блока
  «Для навыка Алисы» в настройках → Облако). Читает тот же зашифрованный снимок с Диска (`GET /api/cloud` → `alice:{url,key}`), домой не ходит.
  Отвечает на «когда следующая/что сейчас/что завтра/кто отвозит у Оли»; имена — склонения и уменьшительные, «я Оля» хранится в user_state.
  Алиса ждёт ≤3 с: снимок грузится в потоке (`WAIT_SECONDS=2.4`), кэш 120 с; на холодном старте возможно «Календарь ещё просыпается» — повтор.
  Код обновляется вручную: `alice/function.zip` (handler.py + requirements.txt) → консоль функции → Редактор → ZIP-архив → «Сохранить изменения»
  (пересобрать zip после правок). Навык в Яндекс Диалогах — «Приватный», активация «Моя семья»; тесты: `python -m pytest alice/test_handler.py`.
- **Приложение для macOS** (`macos/`, SwiftPM, macOS 13+): `HomeHubCore` (код подключения, расшифровка снимка CryptoKit, `Agenda` — «что дальше»; тесты
  `swift test`, включая блоб, зашифрованный сервером) и `HomeHubMac` (SwiftUI: окно = WKWebView сервера, иначе офлайн-список из снимка; значок в строке меню
  с ближайшим событием; локальные уведомления из `reminders`; запуск при входе). Дома берёт `/api/snapshot`, вне дома — снимок с Диска по коду `hhc1.`.
  Swift локально недоступен: собирает и тестирует GitHub Actions (`.github/workflows/macos.yml`, macos-15 (macos-14 GitHub больше не даёт)) и кладёт `macos/release/HomeHub-Calendar.zip` +
  `version.json` в main (`[skip ci]`); сервер раздаёт `/app-mac.zip`, `/api/app-mac` (`HOMECAL_MAC_DIR`). Версия — `macos/version.txt`. Ошибки CI смотреть:
  `gh api repos/Undeadko21/homehubcalendar/actions/jobs/<id>/logs`. Подпись ad-hoc (без аккаунта Apple): первый запуск через «Открыть».
- **Приложение для iPhone** (`ios/`, SwiftUI, iOS 16+, ставится через AltStore бесплатным Apple ID): проект генерирует XcodeGen из `ios/project.yml` (в нём же
  Info.plist), в цель входят общие файлы Mac-приложения (`HomeHubCore/`, `AppModel.swift`, `Notifier.swift` — поэтому там `#if canImport(HomeHubCore)`
  и `#if os(macOS)`). Интерфейс: NavigationStack с WebView сервера (или список из снимка), листы «Ближайшие» и «Настройки», фоновое обновление BGAppRefresh.
  GitHub Actions (`ios.yml`, macos-15) собирает **неподписанный** `.ipa` (AltStore подписывает на телефоне) и кладёт в `ios/release/` (`[skip ci]`).
  Сервер раздаёт `/app-ios.ipa`, `/api/app-ios` и источник для AltStore `/altstore.json` (адрес берётся из запроса; AltStore → Sources → «+»).
  **Виджет (iOS 17+, `ios/Widget/Widget.swift`, WidgetKit + AppIntent):** отдельная цель `HomeHubWidget`; общего хранилища с приложением нет (App Groups на бесплатном аккаунте ненадёжны),
  поэтому у каждого виджета свои настройки (адрес сервера, код `hhc1.`, дни, подробности, размер текста, прозрачность, люди). Дома — `/api/widget`, вне дома — снимок с Диска. Версия — `ios/version.txt`.
- **Автообновление Mac.** `macos/Sources/HomeHubMac/Updater.swift`: проверка `/api/app-mac` (при запуске и раз в 6 ч), сравнение с `CFBundleVersion` (= номер запуска CI), скачивание zip, распаковка `ditto`,
  замена .app скриптом после выхода процесса + перезапуск. Не работает из «Загрузок» (AppTranslocation) и без прав на папку; вне дома — вручную. Первая версия с обновлением ставится вручную.
- **Виджеты (Android 2.0, macOS 1.2).** Android: масштабируется от 1 клетки (`widget_info.xml`), у каждого виджета свои настройки `WidgetCfg` (текст, прозрачность фона, дни, подробности, шапка; `WidgetPrefs`, экран `WidgetConfigActivity`, открывается при добавлении и «Настроить» на Android 12+); шапка перестраивается по размеру (`OPTION_APPWIDGET_MIN_*`). macOS: настоящий WidgetKit не делали (без Apple ID-подписи и App Groups он ненадёжен, проверить без Mac нельзя) — вместо него `DesktopWidget.swift`: окно SwiftUI, превращённое в виджет через `NSWindow` (уровень рабочего стола, все Spaces, без рамки), пресеты размера и произвольное растягивание, настройки в `UserDefaults` (`widget.*`), открывается при запуске, если `widget.on`.
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
