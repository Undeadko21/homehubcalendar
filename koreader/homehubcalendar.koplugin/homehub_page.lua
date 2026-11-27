local Blitbuffer = require("ffi/blitbuffer")
local CenterContainer = require("ui/widget/container/centercontainer")
local GestureRange = require("ui/gesturerange")
local ButtonTable = require("ui/widget/buttontable")
local Device = require("device")
local Font = require("ui/font")
local FrameContainer = require("ui/widget/container/framecontainer")
local Geom = require("ui/geometry")
local HorizontalGroup = require("ui/widget/horizontalgroup")
local HorizontalSpan = require("ui/widget/horizontalspan")
local InputContainer = require("ui/widget/container/inputcontainer")
local LineWidget = require("ui/widget/linewidget")
local ScrollableContainer = require("ui/widget/container/scrollablecontainer")
local TextWidget = require("ui/widget/textwidget")
local TextBoxWidget = require("ui/widget/textboxwidget")
local UIManager = require("ui/uimanager")
local VerticalGroup = require("ui/widget/verticalgroup")
local VerticalSpan = require("ui/widget/verticalspan")
local Data = require("homehub_data")

local Screen = Device.screen
local BLACK = Blitbuffer.COLOR_BLACK
local WHITE = Blitbuffer.COLOR_WHITE
local DayPage = InputContainer:extend { covers_fullscreen = true }
local AgendaScroll = ScrollableContainer:extend {}

local function scale(size)
    return Screen:scaleBySize(size)
end

local function space(size)
    return VerticalSpan:new { width = scale(size) }
end

local function rule(width, thickness)
    return LineWidget:new { dimen = Geom:new { w = width, h = math.max(1, math.floor(scale(thickness))) } }
end

local function text(value, width, size, bold)
    return TextBoxWidget:new {
        text = value,
        width = width,
        face = Font:getFace(bold and "NotoSerif-Bold.ttf" or "NotoSerif-Regular.ttf", size),
        line_height = 0.18,
        fgcolor = BLACK,
        bgcolor = WHITE,
    }
end

local function eventRow(event, width, clock_width, compact)
    local gap = scale(12)
    local description_width = width - clock_width - gap
    local description = VerticalGroup:new { align = "left", allow_mirroring = false }
    description[1] = text(event.title, description_width, compact and 21 or 23, true)
    for _, detail in ipairs({ event.who, event.location }) do
        if detail ~= "" then
            description[#description + 1] = text(detail, description_width, 17)
        end
    end
    if event.note ~= "" then
        description[#description + 1] = space(5)
        if Data.isTripNote(event.note) then
            local padding, border = scale(6), scale(1)
            local note = event.note:gsub("%s+(Забрать:)", "\n%1")
            description[#description + 1] = FrameContainer:new {
                padding = padding,
                bordersize = border,
                text(note, description_width - 2 * (padding + border), 17, true),
            }
        else
            description[#description + 1] = text(event.note, description_width, 17)
        end
    end
    local clock = event.time:gsub("^(%d%d:%d%d)–(%d%d:%d%d)$", "%1\n– %2")
    return HorizontalGroup:new {
        align = "top",
        allow_mirroring = false,
        text(clock, clock_width, 18, true),
        HorizontalSpan:new { width = gap },
        description,
    }
end

function AgendaScroll:onScrollableSwipe(_, gesture)
    if gesture.pos:intersectWith(self.dimen) then
        if gesture.direction == "west" then return self.turn_day(1) end
        if gesture.direction == "east" then return self.turn_day(-1) end
    end
    return ScrollableContainer.onScrollableSwipe(self, nil, gesture)
end

local function headline(value, width, size)
    return TextWidget:new {
        text = value, max_width = width, face = Font:getFace("NotoSerif-Bold.ttf", size), bold = true,
    }
end

function DayPage:weekColumn(width, height)
    local group = VerticalGroup:new { align = "left", allow_mirroring = false }
    local row_h = math.floor(height / 7)
    self.week_row_height = row_h
    for i, day in ipairs(self.cache.days) do
        local inset = scale(7)
        local divider = i < 7 and 1 or 0
        local border = i == self.day_index and scale(2) or 0
        local line = CenterContainer:new {
            dimen = Geom:new { w = width - 2 * (inset + border), h = row_h - divider - 2 * (inset + border) },
            headline(Data.shortDay(day.date), width - 2 * (inset + border), 19),
        }
        group[#group + 1] = FrameContainer:new {
            padding = inset, bordersize = border, radius = 0, line,
        }
        if divider > 0 then
            group[#group + 1] = LineWidget:new { dimen = Geom:new { w = width, h = divider } }
        end
    end
    return group
end

function DayPage:onSelectDay(_, gesture)
    local index = math.floor((gesture.pos.y - self.week_top) / self.week_row_height) + 1
    local day = self.cache.days[index]
    if day then self.select_day(day.date) end
    return true
end

function DayPage:init()
    local screen_width, screen_height = Screen:getWidth(), Screen:getHeight()
    self.dimen = Geom:new { w = screen_width, h = screen_height }
    self.key_events.Close = { { "Back" } }
    local margin = scale(self.landscape and 12 or 18)
    local width = screen_width - 2 * margin
    local day = self.cache.days[self.day_index]
    local number, month, weekday = Data.dayHeading(day.date)
    local month_name = month:gsub(" %d%d%d%d$", "")
    local relative = Data.relativeDay(self.cache, self.day_index, self.today)
    local daily_title = weekday .. ", " .. number .. " " .. month_name
    local header = VerticalGroup:new {
        align = "left", allow_mirroring = false,
        headline(self.landscape and Data.weekHeading(self.cache.days[1].date) or daily_title, width, 32),
        space(6),
        rule(width, 2),
    }
    local footer = ButtonTable:new { width = width, buttons = self.buttons, show_parent = self, font_size = 17 }
    local viewport = math.max(1, screen_height - 2 * margin - header:getSize().h - footer:getSize().h - scale(10))
    local left = self.landscape and math.min(scale(100), math.floor(width / 4)) or 0
    local gap = self.landscape and scale(12) or 0
    local agenda_width = width - left - gap * 2
    local content_width = agenda_width - ScrollableContainer:getScrollbarWidth()
    local agenda = VerticalGroup:new { align = "left", allow_mirroring = false }
    agenda[#agenda + 1] = space(7)
    if self.landscape then
        agenda[#agenda + 1] = headline(daily_title, content_width, 24)
    elseif relative then
        agenda[#agenda + 1] = text(relative, content_width, 18, true)
    end
    local generated = self.cache.generated
    if generated then
        agenda[#agenda + 1] = text("Сводка от " .. Data.dateLabel(generated) .. " в " .. generated:sub(12, 16), content_width, 14)
    end
    if self.status then
        agenda[#agenda + 1] = text(self.status, content_width, 16)
    end
    agenda[#agenda + 1] = space(7)
    if day.unavailable then
        agenda[#agenda + 1] = text("Расписание не загружено. Нажмите «Обновить».", content_width, 21)
    elseif #day.events == 0 then
        agenda[#agenda + 1] = text("На этот день событий нет.", content_width, 21)
    end
    local clock_width = math.floor(content_width * 0.23)
    if self.landscape then clock_width = math.min(clock_width, scale(100)) end
    for _, event in ipairs(day.events) do
        agenda[#agenda + 1] = space(7)
        agenda[#agenda + 1] = eventRow(event, content_width, clock_width, self.landscape)
        agenda[#agenda + 1] = space(8)
        agenda[#agenda + 1] = rule(content_width, 1)
    end
    local scroll = AgendaScroll:new {
        dimen = Geom:new { w = agenda_width, h = viewport },
        show_parent = self, turn_day = self.turn_day, agenda,
    }
    self.cropping_widget = scroll
    local body = scroll
    if self.landscape then
        local column = self:weekColumn(left, viewport)
        self.week_top = margin + header:getSize().h
        self.ges_events.SelectDay = {
            GestureRange:new {
                ges = "tap",
                range = Geom:new { x = margin, y = self.week_top, w = left, h = 7 * self.week_row_height },
            },
        }
        body = HorizontalGroup:new {
            align = "top", allow_mirroring = false,
            column,
            HorizontalSpan:new { width = gap - 1 },
            LineWidget:new { dimen = Geom:new { w = 1, h = viewport } },
            HorizontalSpan:new { width = gap },
            scroll,
        }
    end
    self[1] = FrameContainer:new {
        padding = margin, bordersize = 0, width = screen_width, height = screen_height, background = WHITE,
        VerticalGroup:new { header, body, space(10), footer },
    }
end

function DayPage:onShow()
    UIManager:setDirty(self, "ui")
    return true
end

function DayPage:onClose()
    UIManager:close(self)
    return true
end

function DayPage:onCloseWidget()
    UIManager:setDirty(nil, "ui")
    if self.close_callback then self.close_callback() end
end

return DayPage
