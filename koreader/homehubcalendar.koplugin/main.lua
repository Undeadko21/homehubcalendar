local DataStorage = require("datastorage")
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

local HomeHub = WidgetContainer:extend {
    name = "homehubcalendar",
    is_doc_only = false,
}

function HomeHub:init()
    self.settings = LuaSettings:open(DataStorage:getSettingsDir() .. "/homehubcalendar.lua")
    self.ui.menu:registerToMainMenu(self)
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
    self:showDay(1)
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
                self:showDay(1)
            end },
        }},
    }
    UIManager:show(dialog)
    dialog:onShowKeyboard()
end

function HomeHub:closeViewer()
    if self.viewer then
        UIManager:close(self.viewer)
        self.viewer = nil
    end
end

function HomeHub:showDay(index, status)
    self:closeViewer()
    local connected = self.settings:readSetting("widget_token")
    local cache = connected and Data.normalize(self.settings:readSetting("schedule"))
    local today = cache and Data.today(cache.generated)
    index = index or (today and cache.days[2].date <= today and 2 or 1)
    local buttons = {}
    if cache then
        buttons[1] = {}
        for day = 1, 2 do
            local selected = day
            buttons[1][day] = {
                text = Data.dateLabel(cache.days[day].date):sub(1, 5),
                enabled = day ~= index,
                callback = function() self:showDay(selected, status) end,
            }
        end
    end
    buttons[#buttons + 1] = {
        {
            text = connected and "Обновить" or "Подключить",
            callback = function()
                if connected then
                    self:refresh(index)
                else
                    self:connectCalendar()
                end
            end,
        },
        { text = "Закрыть", callback = function() self:closeViewer() end },
    }
    local viewer
    viewer = TextViewer:new {
        title = "Домашний календарь",
        text = Data.render(cache, index, status or (not connected and "Сначала подключите календарь." or nil),
            today),
        buttons_table = buttons,
        close_callback = function()
            if self.viewer == viewer then self.viewer = nil end
        end,
    }
    self.viewer = viewer
    UIManager:show(viewer)
end

function HomeHub:refresh(index)
    if self.loading then return end
    NetworkMgr:runWhenConnected(function()
        if self.loading then return end
        local token = self.settings:readSetting("widget_token")
        if not token then return end
        self.loading = true
        local ok, payload, failure = pcall(function()
            return require("homehub_network").fetch(token, self.path .. "/isrg-roots.pem")
        end)
        self.loading = false
        if not ok or not payload then
            self:showDay(index, ok and failure or "Не удалось обновить расписание.")
            return
        end
        local decoded, response = pcall(json.decode, payload)
        response = decoded and Data.normalize(response)
        if not response then
            self:showDay(index, "Сервер вернул расписание в неожиданном формате.")
            return
        end
        self.settings:saveSetting("schedule", response)
        self.settings:flush()
        self:showDay(index)
    end)
end

return HomeHub
