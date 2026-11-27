local Data = {}

Data.host = "homehubcalendar.ru"
Data.origin = "https://" .. Data.host

function Data.token(input, decode_base64, decode_json)
    input = input:match("^%s*(.-)%s*$")
    if input:sub(1, 5) == "hhc1." then
        local encoded = input:sub(6)
        if #encoded > 8192 or not encoded:match("^[%w_%-]+$") then
            return nil, "Не удалось прочитать код подключения."
        end
        encoded = encoded:gsub("-", "+"):gsub("_", "/")
        local ok, code = pcall(function()
            local decoded = decode_base64(encoded .. string.rep("=", (4 - #encoded % 4) % 4))
            return decode_json(decoded)
        end)
        if not ok or type(code) ~= "table" then
            return nil, "Не удалось прочитать код подключения."
        end
        if code.s ~= Data.origin and code.s ~= Data.origin .. "/" then
            return nil, "Нужен код для homehubcalendar.ru с включённым доступом виджетов."
        end
        input = code.w
    end
    if type(input) ~= "string" or #input ~= 32 or not input:match("^[%w_%-]+$") then
        return nil, "Нужен код подключения или токен виджета только для чтения."
    end
    return input
end

local function line(value)
    return type(value) == "string" and (value:gsub("%c", " "):match("^%s*(.-)%s*$")) or ""
end

local function dateParts(date)
    local year, month, day = date:match("^(%d%d%d%d)%-(%d%d)%-(%d%d)$")
    if not year then return end
    return { year = tonumber(year), month = tonumber(month), day = tonumber(day), hour = 12 }
end

function Data.offset(date, days)
    local parts = dateParts(date)
    if not parts then return end
    local start = os.time(parts)
    if not start or os.date("%Y-%m-%d", start) ~= date then return end
    parts.day = parts.day + days
    return os.date("%Y-%m-%d", os.time(parts))
end

function Data.weekStart(date)
    local parts = dateParts(date)
    if not parts then return end
    local weekday = os.date("*t", os.time(parts)).wday
    return Data.offset(date, -((weekday + 5) % 7))
end

function Data.normalize(payload)
    if type(payload) ~= "table" or type(payload.days) ~= "table" then
        return nil
    end
    local generated = line(payload.generated)
    if not generated:match("^%d%d%d%d%-%d%d%-%d%dT%d%d:%d%d") then
        return nil
    end
    local result = { generated = generated, days = {} }
    if #payload.days < 2 or #payload.days > 7 then return end
    for i = 1, #payload.days do
        local day = payload.days[i]
        if type(day) ~= "table" or type(day.events) ~= "table" then
            return nil
        end
        local date = line(day.date)
        if not Data.offset(date, 0) or (i > 1 and date ~= Data.offset(result.days[i - 1].date, 1)) then
            return nil
        end
        local events = {}
        for _, item in ipairs(day.events) do
            if type(item) == "table" and line(item.title) ~= "" then
                events[#events + 1] = {
                    title = line(item.title),
                    time = line(item.time),
                    who = line(item.who),
                    location = line(item.location),
                    note = line(item.note):gsub("→%s*", "Отвезти: "):gsub("←%s*", "Забрать: "),
                }
            end
        end
        result.days[i] = { date = date, events = events }
    end
    return result
end

function Data.dateLabel(date)
    return date:sub(9, 10) .. "." .. date:sub(6, 7) .. "." .. date:sub(1, 4)
end

local WEEKDAYS = { "Воскресенье", "Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота" }
local MONTHS = { "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря" }

function Data.dayHeading(date)
    local year, month, day = date:match("^(%d%d%d%d)%-(%d%d)%-(%d%d)$")
    year, month, day = tonumber(year), tonumber(month), tonumber(day)
    if not year or not MONTHS[month] or day < 1 or day > 31 then
        return "", Data.dateLabel(date), ""
    end
    local instant = os.time { year = year, month = month, day = day, hour = 12 }
    return tostring(day), MONTHS[month] .. " " .. year, WEEKDAYS[os.date("*t", instant).wday]
end

local SHORT = { "ВС", "ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ" }

function Data.shortDay(date)
    return SHORT[os.date("*t", os.time(dateParts(date))).wday] .. " " .. date:sub(9, 10)
end

function Data.weekHeading(start)
    local last = Data.offset(start, 6)
    local a, b = dateParts(start), dateParts(last)
    if a.month == b.month then
        return a.day .. "–" .. b.day .. " " .. MONTHS[b.month]
    end
    return a.day .. " " .. MONTHS[a.month] .. " – " .. b.day .. " " .. MONTHS[b.month]
end

function Data.weekView(cache, date)
    local first = Data.weekStart(date)
    local by_date = {}
    for _, day in ipairs(cache and cache.days or {}) do by_date[day.date] = day end
    local view = { generated = cache and cache.generated, days = {} }
    local selected
    for i = 1, 7 do
        local day = Data.offset(first, i - 1)
        view.days[i] = by_date[day] or { date = day, events = {}, unavailable = true }
        if day == date then selected = i end
    end
    return view, selected
end

function Data.relativeDay(cache, index, today)
    if cache.days[index].date == today then return "Сегодня" end
    if today and cache.days[index].date == Data.offset(today, 1) then return "Завтра" end
end

function Data.isTripNote(note)
    return note:find("Отвезти:", 1, true) ~= nil or note:find("Забрать:", 1, true) ~= nil
end

function Data.today(generated, now)
    now = now or os.time()
    if generated:sub(-1) == "Z" then
        return os.date("!%Y-%m-%d", now)
    end
    local sign, hours, minutes = generated:match("([+-])(%d%d):(%d%d)$")
    if sign then
        local offset = (tonumber(hours) * 60 + tonumber(minutes)) * 60
        return os.date("!%Y-%m-%d", now + (sign == "-" and -offset or offset))
    end
end

function Data.render(cache, index, status, today)
    if not cache then
        return status or "Нажмите «Обновить», чтобы загрузить расписание."
    end
    local day = cache.days[index]
    local date = Data.dateLabel(day.date)
    local relative = Data.relativeDay(cache, index, today)
    if relative then date = relative .. " · " .. date end
    local rows = { date }
    if cache.generated then
        rows[#rows + 1] = "Данные от " .. Data.dateLabel(cache.generated) .. " в " .. cache.generated:sub(12, 16)
    end
    if status then
        rows[#rows + 1] = status .. " Показано сохранённое расписание."
    end
    if day.unavailable then
        rows[#rows + 1] = "\nРасписание не загружено. Нажмите «Обновить»."
    elseif #day.events == 0 then
        rows[#rows + 1] = "\nНа этот день событий нет."
    end
    for _, event in ipairs(day.events) do
        local title = event.time ~= "" and (event.time .. "  " .. event.title) or event.title
        rows[#rows + 1] = "\n" .. title
        for _, value in ipairs({ event.who, event.location, event.note }) do
            if value ~= "" then
                rows[#rows + 1] = value
            end
        end
    end
    return table.concat(rows, "\n")
end

return Data
