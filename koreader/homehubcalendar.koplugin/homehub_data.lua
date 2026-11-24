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

function Data.normalize(payload)
    if type(payload) ~= "table" or type(payload.days) ~= "table" then
        return nil
    end
    local generated = line(payload.generated)
    if not generated:match("^%d%d%d%d%-%d%d%-%d%dT%d%d:%d%d") then
        return nil
    end
    local result = { generated = generated, days = {} }
    for i = 1, 2 do
        local day = payload.days[i]
        if type(day) ~= "table" or type(day.events) ~= "table" then
            return nil
        end
        local date = line(day.date)
        if not date:match("^%d%d%d%d%-%d%d%-%d%d$") then
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
    if day.date == today then
        date = "Сегодня · " .. date
    elseif index == 2 and cache.days[1].date == today then
        date = "Завтра · " .. date
    end
    local rows = { date, "Данные от " .. Data.dateLabel(cache.generated) .. " в " .. cache.generated:sub(12, 16) }
    if status then
        rows[#rows + 1] = status .. " Показано сохранённое расписание."
    end
    if #day.events == 0 then
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
