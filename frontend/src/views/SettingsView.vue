<template>
  <div class="settings" :class="{ split: wide }">
    <!-- Меню: на телефоне — экран, на компьютере — колонка слева -->
    <nav v-show="wide || !page" class="menu-col" aria-label="Разделы настроек">
      <label class="search">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.500-3.500"/></svg>
        <input v-model="q" type="search" placeholder="Поиск по настройкам" aria-label="Поиск по настройкам" autocomplete="off" />
      </label>
      <template v-if="q.trim()">
        <div v-if="found.length" class="group menu">
          <button v-for="m in found" :key="m.id" class="row menu-row" @click="pick(m.id)">
            <span class="micon" :style="{ background: m.color }" v-html="m.icon"></span>
            <span class="pmain"><span class="pname">{{ m.title }}</span>
              <span class="psub">{{ parentOf[m.id] ? titleOf(parentOf[m.id]) + ' · ' : '' }}{{ m.sub }}</span></span>
            <span class="chev" aria-hidden="true">›</span>
          </button>
        </div>
        <p v-else class="group-note">Ничего не нашлось. Попробуйте другое слово: «пароль», «копия», «виджет».</p>
      </template>
      <template v-else>
      <button class="row status-card" :class="{ bad: sysProblems > 0 || bad }" @click="open('system')">
        <span class="sicon" aria-hidden="true">{{ sysProblems > 0 || bad ? '!' : '✓' }}</span>
        <span class="pmain">
          <span class="pname">{{ sysProblems > 0 || bad ? 'Требует внимания' : 'Всё работает' }}</span>
          <span class="psub">{{ statusLine }}</span>
        </span>
        <span class="chev" aria-hidden="true">›</span>
      </button>
      <template v-for="g in groups" :key="g.title">
        <h3 class="group-title">{{ g.title }}</h3>
        <div class="group menu">
          <button v-for="m in g.items" :key="m.id" class="row menu-row" :class="{ sel: wide && (page === m.id || parentOf[page] === m.id) }" @click="open(m.id)">
            <span class="micon" :style="{ background: m.color }" v-html="m.icon"></span>
            <span class="pmain">
              <span class="pname">{{ m.title }}</span>
              <span class="psub">{{ m.sub }}</span>
            </span>
            <span v-if="m.warn" class="dot" aria-label="Требует внимания"></span>
            <span class="chev" aria-hidden="true">›</span>
          </button>
        </div>
      </template>
      </template>
      <p class="group-note version">Версия {{ state.config?.version }}<template v-if="UI_BUILD"> · интерфейс {{ UI_BUILD }}</template></p>
    </nav>

    <section v-if="page" class="detail">
      <div class="subhead">
        <button v-if="!wide || parentOf[page]" class="back" @click="open(parentOf[page] || null)">‹ {{ parentOf[page] ? titleOf(parentOf[page]) : 'Настройки' }}</button>
        <h2>{{ current?.title }}</h2>
        <p v-if="current?.lead" class="lead">{{ current.lead }}</p>
      </div>

    <!-- Люди -->
    <template v-if="page === 'people'">
    <h3 class="group-title">Общие встречи</h3>
    <div class="group">
      <div class="row stack">
        <span class="lbl">Цвет встреч с несколькими участниками</span>
        <ColorPick :model-value="sharedColor" none-label="Цвет первого участника" label="Цвет общих встреч" @update:model-value="saveShared" />
      </div>
    </div>
    <p class="group-note">Так общие события выделяются в ленте, неделе, «Сегодня» и виджетах. У отдельного события цвет можно поменять в его карточке — он важнее.</p>
    <h3 class="group-title">Люди</h3>
    <div class="group">
      <button v-for="p in editPeople" :key="p.id" class="row person-row" @click="openPerson(p)">
        <span class="avatar" :style="{ background: p.color }">{{ p.emoji || p.name[0] }}</span>
        <span class="pmain">
          <span class="pname">{{ p.name }}<span v-if="p.needs_escort" class="tag">ребёнок</span><span v-if="p.hidden" class="tag">скрыт</span></span>
          <span v-if="p.keywords" class="psub">автопривязка: {{ p.keywords }}</span>
        </span>
        <span class="chev" aria-hidden="true">›</span>
      </button>
      <form class="row" @submit.prevent="addPerson">
        <input v-model="newName" class="inline grow" placeholder="Добавить человека, например «Бабушка»" aria-label="Имя нового человека" />
        <button class="btn" :disabled="!newName.trim()">Добавить</button>
      </form>
    </div>
    <p class="group-note">Нажмите на человека, чтобы поменять цвет, отметить ребёнка или задать слова для автопривязки.</p>


    </template>

    <!-- Календари -->
    <template v-if="page === 'calendars'">
    <p v-if="!editCals.length" class="group-note">Календари появятся после первой синхронизации.</p>
    <p v-if="!editCals.length" class="group-note">Календари появятся после первой синхронизации.</p>
    <div v-for="c in editCals" :key="c.key" class="group cal" :class="{ hidden: c.hidden }">
      <div class="row">
        <span class="swatch" :style="{ background: colorOf(c) }"></span>
        <span class="lbl cname">{{ c.name }}</span>
      </div>
      <div class="row stack">
        <span class="small muted">{{ c.people.length ? 'Чьи события' : 'Нет владельца: события попадут в «Без владельца»' }}</span>
        <PeoplePicker v-model="c.people" :label="'Чей календарь ' + c.name" @update:model-value="(v) => patch(c, { people: v })" />
      </div>
      <label class="row">
        <span class="lbl">Только «занят», без деталей</span>
        <input v-model="c.private" type="checkbox" class="switch" @change="patch(c, { private: c.private })" />
      </label>
      <label class="row">
        <span class="lbl">Скрыть календарь</span>
        <input v-model="c.hidden" type="checkbox" class="switch" @change="patch(c, { hidden: c.hidden })" />
      </label>
    </div>
    </template>

    <!-- Поездки -->
    <template v-if="page === 'trips'">
    <h3 class="group-title">Отвезти и забрать</h3>
    <div class="group">
      <label class="row">
        <span class="lbl">Отвезти: минут до начала</span>
        <input v-model.number="escort.before_minutes" class="num" type="number" min="0" max="240" step="5" @change="saveEscort" />
      </label>
      <label class="row">
        <span class="lbl">Забрать: минут после конца</span>
        <input v-model.number="escort.after_minutes" class="num" type="number" min="0" max="240" step="5" @change="saveEscort" />
      </label>
      <label class="row">
        <span class="lbl">Слова «дома»</span>
        <input v-model="escort.home_words" class="inline" placeholder="дома" @change="saveEscort" />
      </label>
      <label class="row">
        <span class="lbl">Домашний адрес</span>
        <input v-model="escort.home_address" class="inline" placeholder="например: Ленина, 5" @change="saveEscort" />
      </label>
    </div>
    <Help title="Что значат эти числа">
      <p>Столько времени взрослый должен быть свободен, чтобы отвезти или забрать ребёнка: в эти минуты проверяются конфликты. Кто отвозит, назначается в карточке события ребёнка.</p>
      <p>Событие считается «дома», если в названии или месте есть одно из слов (через запятую) или адрес; «все вместе» — если в нём участвует кто-то из взрослых. Это всегда можно поменять в карточке.</p>
    </Help>

    <h3 class="group-title">Поездки в календаре</h3>
    <div class="group">
      <label class="row">
        <span class="lbl">Показывать «Отвезти / Забрать» отдельными событиями <small class="muted block">Выключено: кто везёт и забирает видно на самом событии ребёнка (→ и ←), копий в календарях взрослых нет. Напоминания водителю работают в любом случае.</small></span>
        <input v-model="escort.show_duties" type="checkbox" class="switch" @change="saveEscort" />
      </label>
    </div>
    <h3 class="group-title">Время в дороге по карте</h3>
    <div class="group">
      <label class="row">
        <span class="lbl">Считать по карте <small class="muted block">Если у события ребёнка указано место, а время в пути не задано — посчитать дорогу от дома на машине.</small></span>
        <input v-model="escort.map_travel" type="checkbox" class="switch" @change="saveEscort" />
      </label>
      <label class="row">
        <span class="lbl">Адрес дома для карты</span>
        <input v-model="escort.map_home" class="inline" placeholder="город, улица, дом" @change="saveEscort" />
      </label>
    </div>
    <Help title="Как считается и что уходит в интернет">
      <p>Адрес дома и место события отправляются в открытые сервисы OpenStreetMap (поиск адреса и маршрут). Пробок они не знают, поэтому ко времени добавляется 30% и оно округляется вверх до 5 минут.</p>
      <p>Порядок: время, заданное в карточке события → правило по словам ниже → карта → обычные «минут до начала». В карточке события есть кнопка «По карте» — она работает и без этого переключателя, достаточно адреса дома.</p>
    </Help>

    <h3 class="group-title">Время в дороге</h3>
    <div class="group">
      <label class="row">
        <span class="lbl">Запас к дороге, минут</span>
        <input v-model.number="escort.travel_buffer" class="num" type="number" min="0" max="60" step="5" @change="saveEscort" />
      </label>
      <div v-for="(pl, i) in escort.places" :key="i" class="row place">
        <input v-model="pl.words" class="inline grow" placeholder="слова: бассейн, секция" aria-label="Слова в названии или месте" @change="saveEscort" />
        <input v-model.number="pl.minutes" class="num" type="number" min="0" max="240" step="5" aria-label="Минут в пути" @change="saveEscort" />
        <span class="muted small">мин</span>
        <button class="x" aria-label="Удалить" @click="removePlace(i)">×</button>
      </div>
      <div class="row"><button class="btn" @click="addPlace">＋ Место</button></div>
    </div>
    <Help title="Как считается дорога">
      <p>Если в названии или месте события есть слово из правила, окно «отвезти» = дорога + запас до начала, а «забрать» — столько же после конца. Для отдельного события время в пути можно задать в его карточке. Без правила работают минуты из блока выше.</p>
    </Help>

    <h3 class="group-title">Шаблоны поездок по дням недели</h3>
    <TemplatesEditor />

    </template>

    <!-- Дни рождения -->
    <template v-if="page === 'birthdays'">
    <h3 class="group-title">Дни рождения</h3>
    <BirthdaysEditor />
    <h3 class="group-title">Школьные каникулы</h3>
    <SchoolBreaks />
    </template>

    <!-- Напоминания -->
    <template v-if="page === 'reminders'">
    <template v-if="inApp">
      <h3 class="group-title">На этом телефоне</h3>
      <RemindersSettings />
    </template>
    <h3 class="group-title">Перед встречами</h3>
    <EventReminders />
    </template>

    <!-- Источники событий -->
    <template v-if="page === 'sources'">
    <template v-for="acc in accounts" :key="acc.id">
      <h3 class="group-title">Яндекс.Календарь</h3>
      <form class="group" @submit.prevent="saveAccount(acc)">
        <label class="row">
          <span class="lbl">Логин</span>
          <input v-model="acc.username" class="inline" type="email" autocomplete="username" autocapitalize="off" placeholder="ivanov@yandex.ru" />
        </label>
        <label class="row">
          <span class="lbl">Пароль</span>
          <input v-model="acc.password" class="inline" type="password" autocomplete="new-password"
                 :placeholder="acc.has_password ? 'сохранён' : 'пароль приложения'" />
        </label>
        <div class="row">
          <button class="btn filled" :disabled="acc.busy || !acc.username">{{ acc.busy ? 'Проверяю…' : 'Сохранить и подключить' }}</button>
        </div>
      </form>
      <p v-if="acc.result" class="group-note" :class="acc.result.ok ? 'ok' : 'err'">
        {{ acc.result.ok ? `Подключено: календарей ${acc.result.calendars}, записей ${acc.result.objects}.` : 'Не удалось подключиться: ' + acc.result.error }}
      </p>
      <p v-else class="group-note">
        Нужен <strong>пароль приложения</strong>, а не основной пароль: <a href="https://id.yandex.ru/security/app-passwords" target="_blank" rel="noopener">id.yandex.ru → Пароли приложений</a>, тип «Календарь». Хранится только на вашем сервере.
      </p>
    </template>


    <FeedsSettings />

    <h3 class="group-title">Синхронизация</h3>
    <div class="group">
      <div v-for="s in sources" :key="s.source_id" class="row">
        <span class="lbl">{{ s.source_id }}</span>
        <span v-if="s.last_error" class="val err">{{ s.last_error }}</span>
        <span v-else class="val muted">{{ s.last_ok ? fmt(s.last_ok) : 'ещё не обновлялось' }}</span>
      </div>
      <div class="row">
        <button class="btn" :disabled="busy" @click="sync">{{ busy ? 'Обновляю…' : 'Обновить сейчас' }}</button>
      </div>
    </div>
    </template>

    <!-- Связь вне дома: сводка и переходы -->
    <template v-if="page === 'outside'">
    <AccessSettings part="status" />
    <h3 class="group-title">Настройка</h3>
    <div class="group menu">
      <button v-for="m in outsideItems" :key="m.id" class="row menu-row" @click="open(m.id)">
        <span class="micon" :style="{ background: m.color }" v-html="m.icon"></span>
        <span class="pmain"><span class="pname">{{ m.title }}</span><span class="psub">{{ m.sub }}</span></span>
        <span class="chev" aria-hidden="true">›</span>
      </button>
    </div>
    </template>
    <template v-if="page === 'cloud'">
    <CloudSettings />
    </template>
    <AccessSettings v-if="page === 'address' || page === 'devices' || page === 'vps'" :part="page" />

    <!-- Приложения и виджеты -->
    <template v-if="page === 'app'">
    <!-- Приложение для Android -->
    <h3 class="group-title">Приложение для Android</h3>
    <div class="group">
      <template v-if="inApp">
        <div class="row">
          <span class="lbl">Установлено</span>
          <span class="val muted">версия {{ appVersionInstalled }}</span>
        </div>
        <div class="row"><span class="lbl">Сервер</span><span class="val muted">{{ hostName }}</span></div>
        <div class="row">
          <span class="lbl">Виджет <small class="muted block">{{ widgetState }}</small></span>
          <button v-if="canPin" class="btn filled" @click="pinWidget">Добавить на экран</button>
        </div>
        <div class="row"><button class="btn" @click="changeServer">Сменить сервер</button></div>
      </template>
      <div v-if="appInfo?.available" class="row">
        <span class="lbl">Версия {{ appInfo.versionName }} <small class="muted block">{{ Math.round(appInfo.size / 1024) }} КБ{{ canUpdate && !hasUpdate ? ' · у вас последняя' : '' }}</small></span>
        <button v-if="canUpdate" class="btn filled" :disabled="!hasUpdate" @click="updateApp">{{ hasUpdate ? 'Обновить' : 'Актуальна' }}</button>
        <a v-else class="btn filled" href="/app.apk" download>Скачать</a>
      </div>
      <div v-else-if="appInfo" class="row"><span class="muted small">Приложение ещё не собрано на этом сервере.</span></div>
    </div>
    <template v-if="!inApp">
      <h3 class="group-title">Приложение для Mac</h3>
      <div class="group">
        <div v-if="macInfo?.available" class="row">
          <span class="lbl">Версия {{ macInfo.version }} <small class="muted block">{{ (macInfo.size / 1048576).toFixed(1) }} МБ · macOS 13+</small></span>
          <a class="btn filled" href="/app-mac.zip" download>Скачать</a>
        </div>
        <div v-else-if="macInfo" class="row"><span class="muted small">Сборка для Mac ещё не готова.</span></div>
      </div>
      <Help title="Как установить">
        <p>Распакуйте zip, перенесите программу в «Программы» и при первом запуске нажмите на ней правой кнопкой → «Открыть» (приложение подписано без аккаунта разработчика Apple). Вне дома читает снимок из облака — код подключения в «Связь вне дома».</p>
      </Help>
    </template>
    <template v-if="!inApp">
      <h3 class="group-title">Приложение для iPhone</h3>
      <div class="group">
        <div v-if="iosInfo?.available" class="row">
          <span class="lbl">Версия {{ iosInfo.version }} <small class="muted block">{{ (iosInfo.size / 1048576).toFixed(1) }} МБ · iOS 16+</small></span>
          <a class="btn" href="/app-ios.ipa" download>.ipa</a>
        </div>
        <div v-else-if="iosInfo" class="row"><span class="muted small">Сборка для iPhone ещё не готова.</span></div>
        <div class="row stack">
          <span class="lbl">Источник для AltStore <small class="muted block">AltStore → Sources → «+» → вставьте адрес; приложение будет обновляться оттуда</small></span>
          <div class="code"><code>{{ origin }}/altstore.json</code><button class="btn" @click="copyText(origin + '/altstore.json')">Копировать</button></div>
        </div>
      </div>
      <Help title="Установка и ошибки AltStore">
        <p>AltStore ставит приложение с вашим бесплатным Apple ID; подпись живёт 7 дней, AltStore продлевает её сам, когда iPhone и компьютер с AltServer в одной Wi-Fi сети.</p>
        <p><b>Если AltStore выдаёт ошибку</b> (503, «No anisette server»): скачайте .ipa кнопкой выше и установите через Sideloadly на компьютере — тот же Apple ID, USB-кабель, кнопка Start. Подпись так же живёт 7 дней; данные приложения сохраняются.</p>
      </Help>
    </template>
    <Help title="Виджет на рабочий стол">
      <p>Откройте эту страницу на телефоне и нажмите «Скачать». Android спросит разрешение ставить приложения из браузера — разрешите. Виджет «Семейный день» добавляется кнопкой в приложении (⚙ → «Добавить на экран») или вручную: долгое нажатие на пустом месте рабочего стола → «Виджеты» → «Календарь» (на Xiaomi — раздел «Виджеты Android» внизу списка).</p>
    </Help>
    </template>

    <!-- Экран на стене -->
    <!-- Внешний вид -->
    <template v-if="page === 'look'">
    <h3 class="group-title">Размер текста</h3>
    <div class="group">
      <div class="row">
        <div class="seg look-seg" role="radiogroup" aria-label="Размер текста">
          <button v-for="o in TEXT_SIZES" :key="o.id" role="radio" :aria-checked="state.textSize === o.id"
                  :class="{ on: state.textSize === o.id }" @click="setTextSize(o.id)">{{ o.label }}</button>
        </div>
      </div>
      <div class="row look-sample"><span>Пример: Бассейн, 17:00–18:00</span></div>
    </div>
    <p class="group-note">Запоминается на этом устройстве. Для экрана на стене — добавьте к ссылке <code>&amp;size=large</code> или <code>&amp;size=xlarge</code>.</p>

    <h3 class="group-title">Различать людей не только по цвету</h3>
    <div class="group">
      <label class="row">
        <span class="lbl">Буквы на плашках <small class="muted block">Перед названием события — первая буква имени каждого участника. Удобно, если цвета трудно различать.</small></span>
        <input :checked="state.initials" type="checkbox" class="switch" @change="setInitials($event.target.checked)" />
      </label>
    </div>

    <h3 class="group-title">Значки и отклик</h3>
    <div class="group">
      <label class="row">
        <span class="lbl">Значки событий <small class="muted block">По словам в названии: 🏊 бассейн, 🩺 врач, 🎂 день рождения, 📚 школа, ⚽ футбол…</small></span>
        <input :checked="state.icons" type="checkbox" class="switch" @change="setIcons($event.target.checked)" />
      </label>
      <label class="row">
        <span class="lbl">Отклик на нажатия <small class="muted block">Лёгкая вибрация телефона: назначили водителя, отметили покупку, перенесли событие.</small></span>
        <input :checked="state.haptics" type="checkbox" class="switch" @change="setHaptics($event.target.checked)" />
      </label>
    </div>

    <h3 class="group-title">Знакомство</h3>
    <div class="group">
      <button class="row linkrow" @click="state.onboarding = true">Показать знакомство заново</button>
    </div>
    <p class="group-note">Четыре шага для нового члена семьи: чьи события показывать, напоминания, связь вне дома, виджет.</p>
    </template>

    <template v-if="page === 'wall'">
    <h3 class="group-title">Сегодня</h3>
    <div class="group">
      <div class="row stack"><span class="lbl">Ссылка <small class="muted block">день по людям, крупно</small></span>
        <div class="code"><code>{{ kioskUrl }}</code><button class="btn" @click="copyText(kioskUrl)">Копировать</button></div></div>
    </div>
    <h3 class="group-title">Кухня</h3>
    <div class="group">
      <div class="row stack"><span class="lbl">Ссылка <small class="muted block">часы, погода, ближайшие события, поездки и дела</small></span>
        <div class="code"><code>{{ kitchenUrl }}</code><button class="btn" @click="copyText(kitchenUrl)">Копировать</button></div></div>
    </div>
    <p class="group-note">Откройте ссылку на планшете в полноэкранном режиме: ночью экран приглушается, данные обновляются сами. Добавьте <code>&amp;rotate=60</code>, чтобы каждую минуту переключаться между «Сегодня» и «Лентой».</p>
    <p class="group-note">С 21:00 до 7:00 экран сам переходит на тёмную тему. Своё время — <code>&amp;dark=22-6</code> (можно с минутами: <code>&amp;dark=21:30-6:45</code>), всегда тёмная — <code>&amp;dark=always</code>, не переключать — <code>&amp;dark=0</code>.</p>
    </template>

    <!-- Данные -->
    <template v-if="page === 'changes'">
    <ChangeLog />
    </template>
    <template v-if="page === 'stats'">
    <StatsPanel />
    </template>
    <template v-if="page === 'system'">
    <SystemPanel part="overview" @goto="open" />
    <h3 class="group-title">Подробнее</h3>
    <div class="group menu">
      <button v-for="m in systemItems" :key="m.id" class="row menu-row" @click="open(m.id)">
        <span class="micon" :style="{ background: m.color }" v-html="m.icon"></span>
        <span class="pmain"><span class="pname">{{ m.title }}</span><span class="psub">{{ m.sub }}</span></span>
        <span class="chev" aria-hidden="true">›</span>
      </button>
    </div>
    </template>
    <SystemPanel v-if="page && page.startsWith('sys-')" :key="page" :part="page.slice(4)" />
    </section>

    <!-- Карточка человека -->
    <Sheet :open="!!editing" :title="editing?.name || ''" @close="closePerson">
      <template #actions>
        <button class="btn done" @click="closePerson">Готово</button>
      </template>
      <div v-if="editing" class="pedit">
        <div class="group">
          <label class="row">
            <span class="lbl">Имя</span>
            <input v-model="editing.name" class="inline" @change="savePerson(editing)" />
          </label>
          <label class="row">
            <span class="lbl">Значок</span>
            <input v-model="editing.emoji" class="inline" maxlength="4" placeholder="🙂" @change="savePerson(editing)" />
          </label>
          <div class="row stack">
            <span class="lbl">Цвет</span>
            <div class="swatches" role="radiogroup" aria-label="Цвет">
              <button v-for="col in PALETTE" :key="col" role="radio" :aria-checked="editing.color === col"
                      class="sw" :class="{ on: editing.color === col }" :style="{ background: col }"
                      :aria-label="col" @click="pickColor(col)"></button>
              <label class="sw custom" :class="{ on: !PALETTE.includes(editing.color) }" title="Свой цвет">
                <input v-model="editing.color" type="color" @change="savePerson(editing)" />
              </label>
            </div>
          </div>
        </div>

        <div class="group">
          <div class="row">
            <span class="lbl">Порядок колонок <small class="muted block">соседние колонки удобнее для общих событий</small></span>
            <button class="btn" :disabled="!canMove(editing, -1)" @click="move(editing, -1)">Выше</button>
            <button class="btn" :disabled="!canMove(editing, 1)" @click="move(editing, 1)">Ниже</button>
          </div>
        </div>

        <div class="group">
          <label class="row">
            <span class="lbl">Ребёнок <small class="muted block">его нужно отвозить и забирать</small></span>
            <input v-model="editing.needs_escort" type="checkbox" class="switch" @change="savePerson(editing)" />
          </label>
          <label class="row">
            <span class="lbl">Скрыть из календаря</span>
            <input v-model="editing.hidden" type="checkbox" class="switch" @change="savePerson(editing)" />
          </label>
        </div>

        <h3 class="group-title">Слова для автопривязки</h3>
        <div class="group">
          <div class="row">
            <input v-model="editing.keywords" class="inline grow" placeholder="Например: Марк, бассейн, садик" @change="savePerson(editing)" />
          </div>
        </div>
        <p class="group-note">Если слово есть в названии события из любого календаря, событие появится и у этого человека.</p>

        <div class="group danger">
          <button class="row del" @click="removePerson(editing)">Удалить человека</button>
        </div>
      </div>
    </Sheet>
  </div>
</template>

<script setup>
import { copyToClipboard } from '../lib/clipboard'
import { computed, reactive, ref, watch } from 'vue'
import { api } from '../lib/api'
import { state, reload, syncNow, UI_BUILD, setTextSize, setInitials, setIcons, setHaptics } from '../lib/store'

const TEXT_SIZES = [{ id: 'compact', label: 'Мельче' }, { id: 'normal', label: 'Обычно' }, { id: 'large', label: 'Крупнее' }, { id: 'xlarge', label: 'Максимум' }]
import PeoplePicker from '../components/PeoplePicker.vue'
import Sheet from '../components/Sheet.vue'
import TemplatesEditor from '../components/TemplatesEditor.vue'
import BirthdaysEditor from '../components/BirthdaysEditor.vue'
import RemindersSettings from '../components/RemindersSettings.vue'
import CloudSettings from '../components/CloudSettings.vue'
import AccessSettings from '../components/AccessSettings.vue'
import FeedsSettings from '../components/FeedsSettings.vue'
import ColorPick from '../components/ColorPick.vue'
import EventReminders from '../components/EventReminders.vue'
import ChangeLog from '../components/ChangeLog.vue'
import SchoolBreaks from '../components/SchoolBreaks.vue'
import StatsPanel from '../components/StatsPanel.vue'
import SystemPanel from '../components/SystemPanel.vue'
import Help from '../components/Help.vue'

// Системные цвета Apple
const PALETTE = ['#ff3b30', '#ff9500', '#ffcc00', '#34c759', '#00c7be', '#007aff', '#5856d6', '#af52de', '#ff2d55', '#a2845e']

const busy = ref(false)
// Широкий экран: меню слева, страница справа (как «Системные настройки» на Mac)
const wideMq = typeof matchMedia === 'function' ? matchMedia('(min-width: 900px)') : null
const wide = ref(!!wideMq?.matches)
wideMq?.addEventListener?.('change', (e) => { wide.value = e.matches })
const page = ref(null)
try { page.value = sessionStorage.getItem('settingsPage') || null } catch { /* без хранилища */ }
if (wide.value && !page.value) page.value = 'people'
watch(wide, (w) => { if (w && !page.value) page.value = 'people' })
// Вложенные страницы: «Связь вне дома» → облако, адрес, устройства, VPS
const parentOf = { cloud: 'outside', address: 'outside', devices: 'outside', vps: 'outside',
  'sys-checks': 'system', 'sys-backup': 'system', 'sys-transfer': 'system', 'sys-server': 'system' }
function open(id) {
  page.value = id
  try { id ? sessionStorage.setItem('settingsPage', id) : sessionStorage.removeItem('settingsPage') } catch { /* ок */ }
  window.scrollTo?.(0, 0)
}
const ico = (d) => `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`
const accInfo = ref(null)
const devCount = ref(null)
api.access().then((r) => { accInfo.value = r }).catch(() => {})
api.sessions().then((r) => { devCount.value = r.pin ? r.sessions.length : null }).catch(() => {})
const outsideBad = computed(() => (accInfo.value?.checks || []).some((c) => c.level === 'bad'))
const outsideItems = computed(() => {
  const a = accInfo.value
  return [
    { id: 'cloud', title: 'Облако Яндекс.Диска', color: '#007aff', sub: 'снимок для виджетов и телефона вне дома',
      icon: ico('<path d="M7 18a4.500 4.500 0 01-.600-8.960A6 6 0 0118 10a4 4 0 010 8z"/>') },
    { id: 'address', title: 'Адрес и доступ приложений', color: '#34c759', sub: a?.public_url ? a.public_url.replace('https://', '') : 'публичный адрес не задан',
      icon: ico('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.500 2.500 3.500 5.500 3.500 9s-1 6.500-3.500 9c-2.500-2.500-3.500-5.500-3.500-9s1-6.500 3.500-9z"/>') },
    { id: 'devices', title: 'Устройства и вход', color: '#ff9500', sub: devCount.value != null ? `вошло устройств: ${devCount.value} · QR-код, журнал` : 'QR-код, журнал входов',
      icon: ico('<rect x="3" y="5" width="13" height="10" rx="1.500"/><path d="M1 19h17M19 9h2.500v10H19z"/>') },
    { id: 'vps', title: 'Сервер и уведомления', color: '#5856d6', sub: a?.vps?.enabled ? 'агент подключён' + (a?.ntfy?.enabled ? ', уведомления включены' : '') : 'агент на VPS, ntfy',
      icon: ico('<rect x="3" y="4" width="18" height="6" rx="1.500"/><rect x="3" y="14" width="18" height="6" rx="1.500"/><path d="M7 7h.01M7 17h.01"/>') },
  ]
})
const systemItems = [
  { id: 'sys-checks', title: 'Проверки', color: '#34c759', sub: 'данные календаря и запись в Яндекс', kw: 'проверка данных водитель дубли самопроверка запись',
    icon: ico('<path d="M5 12.500l4.500 4.500L19 7.500"/>') },
  { id: 'sys-backup', title: 'Резервные копии', color: '#007aff', sub: 'создать, проверить, восстановить', kw: 'копия бэкап backup восстановление диск',
    icon: ico('<path d="M12 3v12M7 10l5 5 5-5M4 20h16"/>') },
  { id: 'sys-transfer', title: 'Перенос настроек', color: '#ff9500', sub: 'скачать или загрузить файл настроек', kw: 'экспорт импорт файл перенос',
    icon: ico('<path d="M7 7h11l-3-3M17 17H6l3 3"/>') },
  { id: 'sys-server', title: 'Сервер и скорость', color: '#8e8e93', sub: 'синхронизация, время ответов, версия', kw: 'версия скорость медленно база ошибки сервер',
    icon: ico('<rect x="3" y="4" width="18" height="6" rx="1.500"/><rect x="3" y="14" width="18" height="6" rx="1.500"/><path d="M7 7h.01M7 17h.01"/>') },
]
const KW = {
  people: 'цвет ребёнок автопривязка слова порядок колонок общие встречи', calendars: 'владелец скрыть занят приватный',
  trips: 'отвезти забрать дорога шаблон водитель дома', birthdays: 'др каникулы школа', reminders: 'уведомления напомнить минут',
  sources: 'яндекс логин пароль приложения teams битрикс outlook ics подписка синхронизация', outside: 'интернет vpn облако доступ',
  cloud: 'токен диск код подключения алиса снимок', address: 'домен публичный адрес токен чтение виджет', devices: 'qr вход пароль сессии журнал безопасность отключить',
  vps: 'агент ntfy уведомления сертификат туннель', app: 'android mac iphone altstore apk скачать виджет обновление', wall: 'планшет киоск кухня',
  changes: 'отмена правки история', stats: 'статистика часы', system: 'состояние проблемы',
}
const q = ref('')
const found = computed(() => {
  const words = q.value.toLowerCase().split(/\s+/).filter(Boolean)
  return flat.value.filter((m) => {
    const hay = `${m.title} ${m.sub || ''} ${m.kw || KW[m.id] || ''}`.toLowerCase()
    return words.every((w) => hay.includes(w))
  })
})
function pick(id) { q.value = ''; open(id) }
const groups = computed(() => {
  const people = (state.config?.people || []).filter((p) => !p.id.startsWith('_'))
  const cals = state.config?.calendars || []
  const srcs = sources.value
  const bad = srcs.some((s) => s.last_error)
  const kids = people.filter((p) => p.needs_escort).length
  return [
    { title: 'Семья', items: [
      { id: 'people', title: 'Люди', color: '#007aff', sub: people.length ? people.map((p) => p.name).slice(0, 4).join(', ') : 'добавьте семью',
        icon: ico('<circle cx="9" cy="8" r="3.500"/><path d="M2.500 20c.600-3.600 3.200-5.500 6.500-5.500s5.900 1.900 6.500 5.500"/><path d="M16 4.500a3.500 3.500 0 010 7M18 14.800c2 .600 3.200 2.300 3.500 5.200"/>') },
      { id: 'calendars', title: 'Календари', color: '#ff3b30', sub: `${cals.length} шт. · чей, скрыть, «занят»`,
        icon: ico('<rect x="3.500" y="5" width="17" height="15" rx="2.500"/><path d="M3.500 10h17M8 3v4M16 3v4"/>') },
      { id: 'trips', title: 'Поездки детей', color: '#ff9500', sub: kids ? `детей: ${kids} · дорога, шаблоны` : 'дорога, шаблоны, «дома»',
        icon: ico('<path d="M5 16V9l2-4h10l2 4v7M3 16h18v3H3zM7.500 12.500h.01M16.500 12.500h.01"/>') },
      { id: 'birthdays', title: 'Дни рождения и каникулы', color: '#ff2d55', sub: 'даты и школьные каникулы',
        icon: ico('<path d="M4 20h16v-7H4zM12 13V8M12 8c-1.200 0-1.500-1.300-.800-2.200L12 4l.8 1.800c.7.900.4 2.200-.8 2.200zM4 16c2 1.500 3.500 1.500 5.500 0s3.500-1.500 5.500 0 3 1 5 0"/>') },
    ] },
    { title: 'Уведомления', items: [
      { id: 'reminders', title: 'Напоминания', color: '#ff3b30', sub: inApp ? 'на этом телефоне и перед встречами' : 'за сколько минут — для каждого',
        icon: ico('<path d="M6 16V11a6 6 0 0112 0v5l1.500 2h-15zM10 20a2 2 0 004 0"/>') },
    ] },
    { title: 'Подключения', items: [
      { id: 'sources', title: 'Яндекс и другие календари', color: '#34c759', warn: bad,
        sub: bad ? 'есть ошибка синхронизации' : (srcs.find((s) => s.last_ok) ? 'обновлено ' + fmt(srcs.find((s) => s.last_ok).last_ok) : 'аккаунт, подписки, синхронизация'),
        icon: ico('<path d="M20 12a8 8 0 01-14 5.300M4 12a8 8 0 0114-5.300"/><path d="M18 3v4h-4M6 21v-4h4"/>') },
      { id: 'outside', title: 'Связь вне дома', color: '#5ac8fa', warn: outsideBad,
        sub: outsideBad ? 'нет связи снаружи' : 'облако, интернет-адрес, устройства',
        icon: ico('<path d="M2 9a15 15 0 0120 0M5 12.500a10 10 0 0114 0M8.500 16a5 5 0 017 0M12 19.500h.01"/>') },
    ] },
    { title: 'Приложения и экраны', items: [
      { id: 'app', title: 'Приложения и виджеты', color: '#5856d6', sub: inApp ? 'версия ' + appVersionInstalled : 'Android, Mac, iPhone',
        icon: ico('<rect x="7" y="2.500" width="10" height="19" rx="2"/><path d="M11 18.500h2"/>') },
      { id: 'look', title: 'Внешний вид', color: '#ff9500', sub: 'размер текста, буквы и значки на плашках, отклик',
        kw: 'шрифт размер крупно компактно плотность буквы инициалы цвет дальтонизм знакомство мастер первый запуск значки иконки эмодзи вибрация отклик' },
      { id: 'wall', title: 'Экран на стене', color: '#af52de', sub: 'планшет на кухне, ссылки',
        icon: ico('<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>') },
    ] },
    { title: 'Данные', items: [
      { id: 'changes', title: 'Журнал изменений', color: '#8e8e93', sub: 'правки событий и отмена',
        icon: ico('<path d="M3 12a9 9 0 109-9 9 9 0 00-7 3.500M3 4v4h4M12 7v5l3 2"/>') },
      { id: 'stats', title: 'Итоги семьи', color: '#00c7be', sub: 'встречи, часы и поездки по людям',
        icon: ico('<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>') },
      { id: 'system', title: 'Состояние и копии', color: '#30b0c7', warn: sysProblems.value > 0,
        sub: sysProblems.value ? `проблем: ${sysProblems.value}` : 'синхронизация, резервные копии, перенос',
        icon: ico('<path d="M3 12h4l3-8 4 16 3-8h4"/>') },
    ] },
  ]
})
const flat = computed(() => [...groups.value.flatMap((g) => g.items), ...outsideItems.value, ...systemItems])
const titleOf = (id) => flat.value.find((m) => m.id === id)?.title || ''
const current = computed(() => flat.value.find((m) => m.id === page.value))
const bad = computed(() => sources.value.some((s) => s.last_error) || outsideBad.value)
const statusLine = computed(() => {
  const ok = sources.value.find((s) => s.last_ok)
  const bits = []
  if (sysProblems.value) bits.push(`проблем: ${sysProblems.value}`)
  else if (bad.value) bits.push('есть ошибка — откройте «Состояние»')
  if (ok) bits.push('обновлено ' + fmt(ok.last_ok))
  return bits.join(' · ') || 'синхронизация, копии, проверки'
})
const newName = ref('')
const sysProblems = ref(0)
api.system().then((r) => { sysProblems.value = r.problems.length }).catch(() => {})
const sources = computed(() => state.status?.sources || [])
const editPeople = ref([])
const editCals = ref([])
const accounts = ref([])
const sharedColor = computed(() => state.config?.shared_color || null)
async function saveShared(c) {
  try { await api.setSharedColor(c || null); await reload() } catch (e) { alert(e.message) }
}
const editing = ref(null)
const escort = reactive({ before_minutes: 30, after_minutes: 30, home_words: 'дома', home_address: '', travel_buffer: 5, places: [], show_duties: false, map_travel: false, map_home: '' })

watch(() => state.config, (c) => {
  editPeople.value = (c?.people || []).filter((p) => !p.id.startsWith('_'))
    .map((p) => ({ ...p, hidden: !!p.hidden, needs_escort: !!p.needs_escort, keywords: p.keywords || '' }))
  editCals.value = (c?.calendars || []).map((x) => ({ ...x, people: [...(x.people || [])], hidden: !!x.hidden, private: !!x.private }))
  const prev = Object.fromEntries(accounts.value.map((a) => [a.id, a]))
  accounts.value = (c?.accounts || []).map((a) => ({ ...a, password: '', busy: false, result: prev[a.id]?.result || null }))
  Object.assign(escort, c?.escort || {})
}, { immediate: true })

const kioskUrl = computed(() => `${location.origin}/?kiosk&view=today`)
const kitchenUrl = computed(() => `${location.origin}/?kiosk&view=kitchen`)

// Приложение для Android (внутри приложения доступен мост window.HomeHubApp)
const inApp = typeof window !== 'undefined' && !!window.HomeHubApp
const appVersionInstalled = inApp ? (() => { try { return window.HomeHubApp.version() } catch { return '?' } })() : ''
const hostName = location.host
const appInfo = ref(null)
api.appInfo().then((v) => (appInfo.value = v)).catch(() => (appInfo.value = { available: false }))
const iosInfo = ref(null)
fetch('/api/app-ios').then((r) => r.json()).then((v) => (iosInfo.value = v)).catch(() => (iosInfo.value = { available: false }))
const origin = location.origin
const copyText = copyToClipboard
const macInfo = ref(null)
fetch('/api/app-mac').then((r) => r.json()).then((v) => (macInfo.value = v)).catch(() => (macInfo.value = { available: false }))
const canUpdate = inApp && !!window.HomeHubApp.updateApp  // в приложении 1.6+
const hasUpdate = computed(() => canUpdate && appInfo.value?.available && Number(appInfo.value.versionCode) > Number(bridge('versionCode', 0)))
function updateApp() { try { window.HomeHubApp.updateApp() } catch {} }
function changeServer() { try { window.HomeHubApp.changeServer() } catch {} }
const bridge = (name, fallback) => { try { return window.HomeHubApp?.[name] ? window.HomeHubApp[name]() : fallback } catch { return fallback } }
const canPin = ref(inApp && bridge('canPinWidget', false))
const hasWidget = ref(inApp && bridge('hasWidget', false))
const widgetState = computed(() => hasWidget.value ? 'уже на рабочем столе' : canPin.value ? 'ещё не добавлен' : 'добавьте вручную — см. ниже')
function pinWidget() {
  bridge('pinWidget', false)
  setTimeout(() => { hasWidget.value = bridge('hasWidget', false) }, 4000)
}
const fmt = (s) => new Date(s).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
const colorOf = (c) => editPeople.value.find((p) => p.id === c.people[0])?.color || c.color || '#8e8e93'

async function sync() {
  busy.value = true
  try { await syncNow() } finally { busy.value = false }
}
async function saveAccount(acc) {
  acc.busy = true
  acc.result = null
  try {
    acc.result = await api.saveAccount(acc.id, acc.username, acc.password || null)
    acc.password = ''
    await reload()
  } catch (e) {
    acc.result = { ok: false, error: e.message }
  } finally {
    acc.busy = false
  }
}
function openPerson(p) { editing.value = { ...p } }
// Порядок людей = порядок колонок. Переставляем соседей и сохраняем порядок всем.
function canMove(p, dir) {
  const i = editPeople.value.findIndex((x) => x.id === p.id)
  return i >= 0 && i + dir >= 0 && i + dir < editPeople.value.length
}
async function move(p, dir) {
  const list = [...editPeople.value]
  const i = list.findIndex((x) => x.id === p.id)
  ;[list[i], list[i + dir]] = [list[i + dir], list[i]]
  for (const [k, x] of list.entries()) {
    const src = x.id === p.id ? editing.value : x
    if (Number(x.sort) !== k || x.id === p.id) await savePersonRaw({ ...src, sort: k })
  }
  editing.value = { ...editing.value, sort: list.findIndex((x) => x.id === p.id) }
  await reload()
}
function closePerson() { editing.value = null }
function pickColor(col) {
  editing.value.color = col
  savePerson(editing.value)
}
async function savePerson(p) {
  await savePersonRaw(p)
  await reload()
}
async function savePersonRaw(p) {
  await api.savePerson({
    id: p.id, name: p.name, color: p.color, emoji: p.emoji || '', sort: Number(p.sort) || 0,
    hidden: !!p.hidden, keywords: p.keywords || '', needs_escort: !!p.needs_escort,
  })
}
async function removePerson(p) {
  if (!confirm(`Удалить «${p.name}»? Его календари и события останутся у других владельцев или без владельца.`)) return
  await api.deletePerson(p.id)
  editing.value = null
  await reload()
}
async function addPerson() {
  const name = newName.value.trim()
  const id = translit(name) || 'p' + Date.now()
  await api.savePerson({ id, name, color: PALETTE[(editPeople.value.length + 5) % PALETTE.length], emoji: '',
    sort: editPeople.value.length, hidden: false, keywords: '', needs_escort: false })
  newName.value = ''
  await reload()
}
function addPlace() { escort.places = [...(escort.places || []), { words: '', minutes: 20 }] }
function removePlace(i) { escort.places.splice(i, 1); saveEscort() }
async function saveEscort() {
  await api.saveEscortSettings({
    before_minutes: Number(escort.before_minutes) || 0,
    after_minutes: Number(escort.after_minutes) || 0,
    home_words: escort.home_words || '',
    home_address: escort.home_address || '',
    travel_buffer: Number(escort.travel_buffer) || 0,
    show_duties: !!escort.show_duties,
    map_travel: !!escort.map_travel,
    map_home: (escort.map_home || '').trim(),
    places: (escort.places || []).filter((p) => (p.words || '').trim()).map((p) => ({ words: p.words.trim(), minutes: Number(p.minutes) || 0 })),
  })
  await reload()
}
async function patch(c, fields) {
  await api.patchCalendar(c.key, fields)
  await reload()
}
function translit(s) {
  const map = { а:'a',б:'b',в:'v',г:'g',д:'d',е:'e',ё:'e',ж:'zh',з:'z',и:'i',й:'y',к:'k',л:'l',м:'m',н:'n',о:'o',п:'p',р:'r',с:'s',т:'t',у:'u',ф:'f',х:'h',ц:'c',ч:'ch',ш:'sh',щ:'sch',ъ:'',ы:'y',ь:'',э:'e',ю:'yu',я:'ya' }
  return s.toLowerCase().split('').map((ch) => map[ch] ?? ch).join('').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
}
</script>

<style scoped>
.settings { max-width: 680px; width: 100%; margin: 0 auto; padding: 4px 20px 48px; }
.settings.split { max-width: 1060px; display: grid; grid-template-columns: 330px minmax(0, 1fr); gap: 32px; align-items: start; padding-top: 12px; }
.menu-col { min-width: 0; }
.split .menu-col { position: sticky; top: 8px; max-height: calc(100vh - 24px); overflow-y: auto; padding-right: 4px; }
.detail { min-width: 0; max-width: 680px; }
.split .detail .subhead { padding-top: 0; }
.menu-row.sel { background: var(--fill); }
.menu-row.sel .pname { color: var(--red); }
.status-card { width: 100%; border: 0; text-align: left; color: inherit; background: var(--surface-2); border-radius: var(--radius-m); margin-top: 12px; min-height: 60px; cursor: pointer; }
.status-card:hover { background: var(--fill); }
.sicon { width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center; flex: none; background: #34c759; color: #fff; font-weight: 700; font-size: 18px; }
.status-card.bad .sicon { background: #ff9500; }
.settings :deep(.row.stack .inline) { text-align: left; background: var(--fill); border-radius: 8px; padding: 9px 11px; }
.search { display: flex; align-items: center; gap: 8px; margin-top: 12px; padding: 0 10px; height: 36px; border-radius: 10px; background: var(--fill); color: var(--ink-2); }
.search input { flex: 1; min-width: 0; border: 0; background: none; outline: none; color: var(--ink); font-size: 16px; }
.search input::-webkit-search-cancel-button { cursor: pointer; }
.search + .group { margin-top: 12px; }
.lead { margin: 2px 0 0; color: var(--ink-2); font-size: 15px; }
.group, .settings :deep(.group) { background: var(--surface-2); }
.cal { margin-bottom: 12px; }
.cal.hidden .cname { color: var(--ink-3); text-decoration: line-through; }
.lbl { flex: 1; min-width: 0; }
.block { display: block; font-weight: 400; font-size: 13px; }
.val { text-align: right; font-size: 14px; overflow-wrap: anywhere; max-width: 60%; }
.err { color: var(--red); }
.ok { color: var(--ok); }
.inline { border: 0; background: none; text-align: right; flex: 1; min-width: 0; padding: 4px 0; outline: none; }
.inline::placeholder { color: var(--ink-3); }
.grow { text-align: left; }
.num { width: 72px; border: 0; background: var(--fill); border-radius: 8px; padding: 6px 8px; text-align: right; }
.row.stack { flex-direction: column; align-items: stretch; gap: 8px; padding-top: 10px; padding-bottom: 12px; }
.small { font-size: 13px; }
a.btn.filled { text-decoration: none; }
.person-row { width: 100%; border: 0; background: none; text-align: left; color: inherit; }
.person-row:hover { background: var(--fill); }
.avatar { width: 32px; height: 32px; border-radius: 50%; display: grid; place-items: center; color: #fff; font-weight: 600; flex: none; font-size: 16px; }
.pmain { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.pname { font-weight: 500; }
.psub { font-size: 12px; color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tag { font-size: 12px; color: var(--ink-2); background: var(--fill); border-radius: 5px; padding: 1px 6px; margin-left: 6px; }
.chev { color: var(--ink-3); font-size: 22px; line-height: 1; }
.swatch { width: 12px; height: 12px; border-radius: 50%; flex: none; }
.cname { font-weight: 600; }
.link { overflow-wrap: anywhere; font-size: 13px; }
.version { margin-top: 24px; text-align: center; }
.group-title:first-child { margin-top: 12px; }
.menu { margin-top: 0; }
.menu-row { width: 100%; border: 0; background: none; text-align: left; color: inherit; min-height: 56px; }
.menu-row:hover { background: var(--fill); }
.micon { width: 30px; height: 30px; border-radius: 8px; display: grid; place-items: center; flex: none; }
.dot { width: 9px; height: 9px; border-radius: 50%; background: var(--red); flex: none; }
.subhead { position: relative; padding: 6px 0 2px; }
.back { border: 0; background: none; color: var(--red); font-size: 17px; padding: 6px 0; cursor: pointer; }
.subhead h2 { margin: 2px 0 0; font-size: 28px; font-weight: 700; }
.done { font-weight: 600; }

.switch {
  appearance: none; width: 51px; height: 31px; border-radius: 16px; background: var(--fill); position: relative;
  transition: background .2s; flex: none; margin: 0; cursor: pointer;
}
.switch::after {
  content: ''; position: absolute; top: 2px; left: 2px; width: 27px; height: 27px; border-radius: 50%;
  background: #fff; box-shadow: 0 2px 6px rgba(0,0,0,.2); transition: transform .2s;
}
.switch:checked { background: var(--ok); }
.switch:checked::after { transform: translateX(20px); }

.place .x { border: 0; background: none; color: var(--ink-3); font-size: 22px; line-height: 1; padding: 4px 8px; }
.pedit .group { margin-top: 14px; }
.pedit .group-title { margin-top: 22px; }
.swatches { display: flex; flex-wrap: wrap; gap: 10px; }
.sw { width: 30px; height: 30px; border-radius: 50%; border: 0; padding: 0; position: relative; cursor: pointer; }
.sw.on { box-shadow: 0 0 0 2px var(--surface-2), 0 0 0 4px var(--ink-2); }
.sw.custom { background: conic-gradient(#ff3b30, #ffcc00, #34c759, #00c7be, #007aff, #af52de, #ff3b30); overflow: hidden; }
.sw.custom input { opacity: 0; width: 100%; height: 100%; cursor: pointer; }
.danger { margin-top: 24px; }
.del { width: 100%; border: 0; background: none; color: var(--red); justify-content: center; font-weight: 500; }
@media (max-width: 899px) { .settings { padding: 0 12px 36px; } }
.code { display: flex; gap: 8px; align-items: center; }
.code code { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; background: var(--fill); padding: 6px 8px; border-radius: 8px; }
.look-seg { width: 100%; }
.look-seg button { flex: 1; padding-left: 4px; padding-right: 4px; min-width: 0; }
.look-sample span { font-size: 16px; font-weight: 600; }
.linkrow { width: 100%; border: 0; background: none; text-align: left; font: inherit; color: var(--tint); }
</style>
