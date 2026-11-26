"""Регрессии ввода фразой и применения шаблонов в редакторе."""

from test_e2e import _open_new, page, pytestmark, stack, sync_api  # noqa: F401


def _event(page):
    _open_new(page)
    return page.get_by_role("dialog", name="Новое событие", exact=True)


def _optional_input(page, event):
    event.get_by_role("button", name="Подробнее").click()
    event.get_by_role("button", name="Частые события, дела и покупки").click()
    return page.get_by_role("dialog", name="Добавить фразой", exact=True)


def test_optional_phrase_preserves_selected_schedule(page):
    event = _event(page)
    event.locator("#ee-sd").fill("2026-12-24")
    event.locator("input[type=time]").first.fill("18:00")
    event.locator("input[type=time]").last.fill("20:00")
    event.get_by_role("button", name="Подробнее").click()
    event.locator("#ee-rep").select_option("weekly")
    event.get_by_role("button", name="Частые события, дела и покупки").click()
    phrase = page.get_by_role("dialog", name="Добавить фразой", exact=True)
    phrase.get_by_role("textbox").fill("Танцы")
    phrase.get_by_role("button", name="Добавить", exact=True).click()
    phrase.wait_for(state="detached")
    sync_api.expect(event.get_by_role("textbox", name="Название")).to_have_value("Танцы")
    sync_api.expect(event.locator("#ee-sd")).to_have_value("2026-12-24")
    sync_api.expect(event.locator("input[type=time]").first).to_have_value("18:00")
    sync_api.expect(event.locator("input[type=time]").last).to_have_value("20:00")
    sync_api.expect(event.locator("#ee-rep")).to_have_value("weekly")


def test_explicit_all_day_phrase_sets_switch_and_cleans_title(page):
    event = _event(page)
    field = event.get_by_role("textbox", name="Добавить фразой")
    field.fill("Отпуск завтра весь день")
    field.press("Enter")
    sync_api.expect(event.get_by_role("textbox", name="Название")).to_have_value("Отпуск")
    sync_api.expect(event.locator("#ee-all")).to_be_checked()
    sync_api.expect(event.locator("input[type=time]")).to_have_count(0)


def test_pending_phrase_preserves_later_manual_edits(page, stack):
    page.evaluate("""(day) => {
        const original = window.fetch.bind(window);
        window.fetch = (url, init) => String(url).includes('/api/quick') ? new Promise(resolve => {
            window.completePhrase = () => resolve(new Response(JSON.stringify({
                kind: 'event', title: 'Йога', date: day, start: '18:00', end: '19:00',
                all_day: false, people: [], notes: []
            }), {headers: {'Content-Type': 'application/json'}}));
        }) : original(url, init);
    }""", stack["event_day"])
    event = _event(page)
    field = event.get_by_role("textbox", name="Добавить фразой")
    field.fill("Йога в 18:00")
    field.press("Enter")
    page.wait_for_function("typeof window.completePhrase === 'function'")
    start = event.locator("input[type=time]").first
    start.fill("20:00")
    page.evaluate("window.completePhrase()")
    sync_api.expect(event.get_by_role("alert")).to_contain_text("Поля изменились")
    sync_api.expect(start).to_have_value("20:00")
    sync_api.expect(field).to_have_value("Йога в 18:00")


def test_late_voice_cannot_replace_manually_processed_phrase(page, stack):
    page.add_init_script("""window.SpeechRecognition = class {
        start() {
            window.completeDictation = (text) => {
                this.onresult({results: [[{transcript: text}]]});
                this.onend();
            };
        }
        stop() { this.onend(); }
    };""")
    calls = []

    def parsed(route):
        text = route.request.post_data_json["text"]
        calls.append(text)
        route.fulfill(json={"kind": "event", "title": text, "date": stack["event_day"], "all_day": False,
                            "start": "18:00", "end": "19:00", "people": [], "notes": []})

    page.route("**/api/quick", parsed)
    page.reload()
    event = _event(page)
    event.get_by_role("button", name="Сказать голосом").click()
    field = event.get_by_role("textbox", name="Добавить фразой")
    field.fill("Ручной ввод")
    field.press("Enter")
    title = event.get_by_role("textbox", name="Название")
    sync_api.expect(title).to_have_value("Ручной ввод")
    page.evaluate("window.completeDictation('Поздняя диктовка')")
    sync_api.expect(event.get_by_role("button", name="Сказать голосом")).to_be_visible()
    sync_api.expect(title).to_have_value("Ручной ввод")
    assert calls == ["Ручной ввод"]


def test_recent_template_preserves_selected_date(page):
    page.evaluate("""() => {
        const original = window.fetch.bind(window);
        window.fetch = (url, init) => String(url).includes('/api/recent-events')
            ? Promise.resolve(new Response(JSON.stringify({items: [{title:'Бассейн', minutes:60}]}),
                    {headers: {'Content-Type': 'application/json'}}))
            : original(url, init);
    }""")
    event = _event(page)
    event.locator("#ee-sd").fill("2026-12-24")
    optional = _optional_input(page, event)
    optional.get_by_role("button", name="Бассейн").click()
    optional.wait_for(state="detached")
    sync_api.expect(event.get_by_role("textbox", name="Название")).to_have_value("Бассейн")
    sync_api.expect(event.locator("#ee-sd")).to_have_value("2026-12-24")
