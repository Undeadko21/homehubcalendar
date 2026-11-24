-- Запуск из корня проекта: lua koreader/tests/test_data.lua
package.path = "koreader/homehubcalendar.koplugin/?.lua;" .. package.path

local Data = require("homehub_data")
local token = string.rep("a", 32)
local encode_test = function(encoded)
    assert(encoded == "a+8=")
    return "payload"
end
local function pairing(decoded)
    assert(decoded == "payload")
    return { s = Data.origin, w = token, k = "unused", t = "unused" }
end

assert(Data.token("  " .. token .. "\n") == token)
assert(Data.token("hhc1.a-8", encode_test, pairing) == token)
assert(not Data.token("hhc1.a-8", encode_test, function()
    return { s = "https://example.org", w = token }
end))
assert(not Data.token("hhc1.a-8", encode_test, function()
    return { s = Data.origin, t = token }
end))
assert(not Data.token("hhc1.invalid!", encode_test, pairing))

local cache = assert(Data.normalize {
    generated = "2026-11-24T09:12:00+05:00",
    days = {
        { date = "2026-11-24", events = {
            { title = " Школа\n7 ", time = "08:00–13:00", who = "Маша", note = "→ Папа  ← Мама" },
            { title = false },
        } },
        { date = "2026-11-25", events = {} },
    },
})
assert(not Data.normalize { generated = cache.generated, days = { cache.days[1] } })
assert(#cache.days[1].events == 1)
assert(cache.days[1].events[1].title == "Школа 7")
assert(cache.days[1].events[1].note == "Отвезти: Папа  Забрать: Мама")
assert(Data.render(cache, 1, nil, "2026-11-24"):find("Сегодня", 1, true))
assert(Data.render(cache, 2, nil, "2026-11-25"):find("Сегодня", 1, true))
assert(Data.today(cache.generated, 0) == "1970-01-01")
assert(Data.today("1970-01-01T00:00:00-05:00", 0) == "1969-12-31")
local stale = Data.render(cache, 2, "Нет Wi-Fi.", "2026-11-26")
assert(stale:find("25.11.2026", 1, true) and stale:find("09:12", 1, true))
assert(stale:find("Показано сохранённое расписание.", 1, true))
assert(stale:find("На этот день событий нет.", 1, true))
assert(not stale:find("Завтра", 1, true))
print("KOReader: подключение, формат сводки и отображение старого расписания проверены.")
