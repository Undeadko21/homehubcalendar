local Blitbuffer = require("ffi/blitbuffer")
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
    return LineWidget:new { dimen = Geom:new { w = width, h = scale(thickness) } }
end

local function text(value, width, size, bold)
    return TextBoxWidget:new {
        text = value,
        width = width,
        face = Font:getFace(bold and "tfont" or "cfont", size),
        line_height = 0.18,
        fgcolor = BLACK,
        bgcolor = WHITE,
    }
end

local function eventRow(event, width, clock_width)
    local gap = scale(12)
    local description_width = width - clock_width - gap
    local description = VerticalGroup:new { align = "left", allow_mirroring = false }
    description[1] = text(event.title, description_width, 23, true)
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

function DayPage:init()
    local screen_width, screen_height = Screen:getWidth(), Screen:getHeight()
    self.dimen = Geom:new { w = screen_width, h = screen_height }
    self.key_events.Close = { { "Back" } }
    local margin = scale(20)
    local width = screen_width - 2 * margin
    local day = self.cache.days[self.day_index]
    local number, month, weekday = Data.dayHeading(day.date)
    local relative = Data.relativeDay(self.cache, self.day_index, self.today)
    local label = relative and (weekday .. " · " .. relative) or weekday
    local date_width = scale(92)
    local header = VerticalGroup:new {
        align = "left",
        allow_mirroring = false,
        HorizontalGroup:new {
            allow_mirroring = false,
            text(number, date_width, 56, true),
            VerticalGroup:new {
                align = "left",
                text(label, width - date_width, 26, true),
                text(month, width - date_width, 19),
            },
        },
        space(8),
        rule(width, 2),
    }
    local footer = ButtonTable:new { width = width, buttons = self.buttons, show_parent = self }
    local viewport = math.max(1, screen_height - 2 * margin - header:getSize().h - footer:getSize().h - scale(14))
    local content_width = width - ScrollableContainer:getScrollbarWidth()
    local agenda = VerticalGroup:new { align = "left", allow_mirroring = false }
    local generated = self.cache.generated
    agenda[1] = space(8)
    agenda[2] = text("Сводка от " .. Data.dateLabel(generated) .. " в " .. generated:sub(12, 16), content_width, 16)
    if self.status then
        agenda[#agenda + 1] = text(self.status .. " Показано сохранённое расписание.", content_width, 16)
    end
    agenda[#agenda + 1] = space(8)
    if #day.events == 0 then
        agenda[#agenda + 1] = text("На этот день событий нет.", content_width, 23)
    end
    local clock_width = math.floor(content_width * 0.21)
    for _, event in ipairs(day.events) do
        agenda[#agenda + 1] = space(7)
        agenda[#agenda + 1] = eventRow(event, content_width, clock_width)
        agenda[#agenda + 1] = space(10)
        agenda[#agenda + 1] = rule(content_width, 1)
    end
    local scroll = AgendaScroll:new {
        dimen = Geom:new { w = width, h = viewport },
        show_parent = self,
        turn_day = self.turn_day,
        agenda,
    }
    self.cropping_widget = scroll
    self[1] = FrameContainer:new {
        padding = margin,
        bordersize = 0,
        width = screen_width,
        height = screen_height,
        background = WHITE,
        VerticalGroup:new { header, scroll, space(14), footer },
    }
end

function DayPage:onShow()
    UIManager:setDirty(self, "ui")
    return true
end

function DayPage:onClose()
    UIManager:close(self)
    if self.close_callback then self.close_callback() end
    return true
end

function DayPage:onCloseWidget()
    UIManager:setDirty(nil, "ui")
end

return DayPage
