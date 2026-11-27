local DataStorage = require("datastorage")
local Dispatcher = require("dispatcher")
local Event = require("ui/event")
local Screen = require("device").screen
local InfoMessage = require("ui/widget/infomessage")
local InputDialog = require("ui/widget/inputdialog")
local LuaSettings = require("luasettings")
local NetworkMgr = require("ui/network/manager")
local TextViewer = require("ui/widget/textviewer")
local UIManager = require("ui/uimanager")
local WidgetContainer = require("ui/widget/container/widgetcontainer")
local json = require("json")
local mime = require("mime")
local Data = require("homehub_data")

local CONNECT_FILE = "/homehubcalendar-connect.txt"

local FallbackViewer = TextViewer:extend {}

function FallbackViewer:onCloseWidget()
    TextViewer.onCloseWidget(self)
    if self.close_callback then self.close_callback() end
end

local HomeHub = WidgetContainer:extend {
    name = "homehubcalendar",
    is_doc_only = false,
}

function HomeHub:init()
    self.settings = LuaSettings:open(DataStorage:getSettingsDir() .. "/homehubcalendar.lua")
    self:onDispatcherRegisterActions()
    self.ui.menu:registerToMainMenu(self)
end

function HomeHub:onDispatcherRegisterActions()
    Dispatcher:registerAction("homehubcalendar_open", {
        category = "none",
        event = "OpenHomeHubCalendar",
        title = "Календарь",
        general = true,
    })
end

function HomeHub:onOpenHomeHubCalendar()
    self:showDay()
    return true
end

function HomeHub:addToMainMenu(menu_items)
    menu_items.homehubcalendar = {
        text = "Домашний календарь",
        sorting_hint = "tools",
        sub_item_table = {
            { text = "Открыть расписание", callback = function() self:showDay() end },
            { text = "Подключить календарь", callback = function() self:connectCalendar() end },
            { text = "Импортировать код с USB", callback = function() self:importConnection() end },
        },
    }
end

local function notice(text)
    UIManager:show(InfoMessage:new { text = text })
end

function HomeHub:saveConnection(input)
    local token, message = Data.token(input, mime.unb64, json.decode)
    if not token then
        notice(message)
        return false
    end
    local changed = token ~= self.settings:readSetting("widget_token")
    if changed then
        self.settings:delSetting("schedule")
        self.settings:delSetting("week_schedules")
    end
    self.settings:saveSetting("widget_token", token)
    self.settings:flush()
    local saved = LuaSettings:open(self.settings.file)
    if saved:readSetting("widget_token") ~= token then
        self.settings = saved
        notice("Не удалось сохранить подключение.")
        return false
    end
    if changed then os.remove(self.settings.file .. ".old") end
    return true
end

function HomeHub:importConnection()
    local path = self.path .. CONNECT_FILE
    local file = io.open(path, "rb")
    if not file then
        notice("Положите homehubcalendar-connect.txt с кодом в папку плагина через USB.")
        return
    end
    local input = file:read(8201)
    file:close()
    if not input or #input > 8200 then
        notice("Файл пуст или слишком большой.")
        return
    end
    if not self:saveConnection(input) then return end
    self:showDay()
    if not os.remove(path) then
        notice("Подключение сохранено. Удалите файл с кодом из папки плагина.")
    end
end

function HomeHub:connectCalendar()
    local dialog
    dialog = InputDialog:new {
        title = "Подключить HomeHubCalendar",
        description = "Вставьте код подключения или токен виджета для homehubcalendar.ru.",
        input_hint = "Код или токен",
        text_type = "password",
        buttons = {{
            { text = "Отмена", callback = function() UIManager:close(dialog) end },
            { text = "Сохранить", is_enter_default = true, callback = function()
                if not self:saveConnection(dialog:getInputText()) then return end
                UIManager:close(dialog)
                self:showDay()
            end },
        }},
    }
    UIManager:show(dialog)
    dialog:onShowKeyboard()
end

function HomeHub:closeViewer()
    local viewer = self.viewer
    self.viewer = nil
    if viewer then UIManager:close(viewer) end
end

function HomeHub:setRotation(mode)
    if mode ~= Screen:getRotationMode() then
        UIManager:broadcastEvent(Event:new("SetRotationMode", mode))
    end
end

function HomeHub:leaveCalendar()
    self:closeViewer()
    local rotation = self.book_rotation
    self.book_rotation = nil
    if rotation then self:setRotation(rotation) end
end

function HomeHub:toggleRotation(date)
    local landscape = Screen:getWidth() > Screen:getHeight()
    self:closeViewer()
    self:setRotation(landscape and Screen.DEVICE_ROTATED_UPRIGHT or Screen.DEVICE_ROTATED_CLOCKWISE)
    self:showDay(date)
end

function HomeHub:today()
    local cache = self.settings:readSetting("schedule")
    return cache and cache.generated and Data.today(cache.generated) or os.date("%Y-%m-%d")
end

function HomeHub:showDay(date, status)
    self:closeViewer()
    if self.book_rotation == nil then
        self.book_rotation = Screen:getRotationMode()
        self:setRotation(Screen.DEVICE_ROTATED_CLOCKWISE)
    end
    local token = self.settings:readSetting("widget_token")
    local today = self:today()
    date = date or today
    local current_day_unknown = not self.settings:readSetting("schedule") and date == today
    local start = Data.weekStart(date)
    local weeks = self.settings:readSetting("week_schedules") or {}
    local cached = token and (weeks[start] or self.settings:readSetting("schedule"))
    cached = Data.normalize(cached)
    local cache, index = Data.weekView(cached, date)
    local landscape = Screen:getWidth() > Screen:getHeight()
    local function turn(delta)
        local next_date = Data.offset(date, delta * (landscape and 7 or 1))
        local start_date = Data.weekStart(next_date)
        if token and not weeks[start_date] and start_date ~= start then
            self:refresh(next_date)
        else
            self:showDay(next_date)
        end
        return true
    end
    local function button(label, callback)
        return { text = label, callback = callback }
    end
    local navigation = {
        button("‹", function() turn(-1) end),
        button("Сегодня", function()
            if token and not weeks[Data.weekStart(today)] and start ~= Data.weekStart(today) then
                self:refresh(today)
            else
                self:showDay(today)
            end
        end),
    }
    if landscape then
        navigation[#navigation + 1] = button(token and "Обновить" or "Подключить", function()
            if token then self:refresh(date, current_day_unknown) else self:connectCalendar() end
        end)
        navigation[#navigation + 1] = button("Повернуть", function() self:toggleRotation(date) end)
        navigation[#navigation + 1] = button("К книге", function() self:leaveCalendar() end)
    end
    navigation[#navigation + 1] = button("›", function() turn(1) end)
    local buttons = { navigation }
    if not landscape then
        buttons[2] = {
            button(token and "Обновить" or "Подключить", function()
                if token then self:refresh(date, current_day_unknown) else self:connectCalendar() end
            end),
            button("Повернуть", function() self:toggleRotation(date) end),
            button("К книге", function() self:leaveCalendar() end),
        }
    end
    local viewer
    local function on_close()
        if self.viewer == viewer then
            self.viewer = nil
            self:leaveCalendar()
        end
    end
    local ok, page = pcall(function()
        return require("homehub_page"):new {
            cache = cache, day_index = index, today = today, status = status, buttons = buttons,
            landscape = landscape, turn_day = turn, close_callback = on_close,
            select_day = function(chosen) self:showDay(chosen, status) end,
        }
    end)
    if ok then viewer = page end
    if not viewer then
        viewer = FallbackViewer:new {
            title = "Домашний календарь",
            text = Data.render(cache, index, status, today),
            buttons_table = buttons,
            close_callback = on_close,
        }
    end
    self.viewer = viewer
    UIManager:show(viewer)
end

function HomeHub:refresh(date, use_server_today)
    if self.loading then return end
    local viewer = self.viewer
    NetworkMgr:runWhenConnected(function()
        if self.loading or (viewer and self.viewer ~= viewer) then return end
        local token = self.settings:readSetting("widget_token")
        if not token then return end
        local start = Data.weekStart(date)
        self.loading = true
        local ok, payload, failure = pcall(function()
            local from = not use_server_today and start or nil
            return require("homehub_network").fetch(token, self.path .. "/isrg-roots.pem", from)
        end)
        self.loading = false
        if not ok or not payload then
            self:showDay(date, ok and failure or "Не удалось обновить расписание.")
            return
        end
        local decoded, response = pcall(json.decode, payload)
        response = decoded and Data.normalize(response)
        if not response then
            self:showDay(date, "Сервер вернул расписание в неожиданном формате.")
            return
        end
        if use_server_today then
            date = Data.today(response.generated) or date
            start = Data.weekStart(date)
        end
        local weeks = self.settings:readSetting("week_schedules") or {}
        if response.days[1].date == start and #response.days == 7 then
            weeks[start] = response
            local starts = {}
            for day in pairs(weeks) do starts[#starts + 1] = day end
            table.sort(starts, function(a, b)
                return weeks[a].generated > weeks[b].generated
            end)
            for i = 5, #starts do weeks[starts[i]] = nil end
            self.settings:saveSetting("week_schedules", weeks)
        elseif Data.weekStart(self:today()) ~= start then
            self:showDay(date, "Эта неделя ещё недоступна на сервере.")
            return
        end
        self.settings:saveSetting("schedule", response)
        self.settings:flush()
        self:showDay(date)
    end)
end

return HomeHub
