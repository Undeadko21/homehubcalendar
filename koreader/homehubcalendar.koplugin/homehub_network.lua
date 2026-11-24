local http = require("socket.http")
local socket = require("socket")
local ssl = require("ssl")
local Data = require("homehub_data")

local Network = {}
local MAX_BYTES = 512 * 1024
local TIMEOUT = 8

local function hasServerName(cert)
    local extensions = cert and cert:extensions()
    local san = extensions and extensions["2.5.29.17"]
    for _, name in ipairs(san and san.dNSName or {}) do
        if name:lower() == Data.host then
            return true
        end
    end
    return false
end

local function connect(ca_file)
    local stream = assert(socket.tcp())
    local connection = {}
    local deadline = socket.gettime() + TIMEOUT
    function connection:settimeout()
        return stream:settimeout(math.max(0, deadline - socket.gettime()), "t")
    end
    function connection:connect(host, port)
        if host ~= Data.host or tonumber(port) ~= 443 then
            stream:close()
            return nil, "unexpected host"
        end
        self:settimeout()
        local ok, err = stream:connect(host, port)
        if not ok then
            stream:close()
            return nil, err
        end
        local wrapped
        wrapped, err = ssl.wrap(stream, {
            mode = "client",
            protocol = "tlsv1_2",
            verify = "peer",
            cafile = ca_file,
        })
        if not wrapped then
            stream:close()
            return nil, err
        end
        stream = wrapped
        stream:sni(host)
        self:settimeout()
        ok, err = stream:dohandshake()
        if not ok or not hasServerName(stream:getpeercertificate()) then
            stream:close()
            return nil, err or "certificate name mismatch"
        end
        return 1
    end
    for _, method in ipairs({ "close", "send", "receive", "getfd", "dirty" }) do
        connection[method] = function(_, ...)
            if method == "send" or method == "receive" then
                connection:settimeout()
            end
            return stream[method](stream, ...)
        end
    end
    return connection
end

function Network.fetch(token, ca_file)
    local chunks, size = {}, 0
    local ok, code = http.request {
        url = Data.origin .. ":443/api/widget?days=2",
        method = "GET",
        headers = {
            ["X-Widget-Token"] = token,
            ["Accept"] = "application/json",
            ["Accept-Encoding"] = "identity",
        },
        redirect = false,
        create = function() return connect(ca_file) end,
        sink = function(chunk, err)
            if not chunk then
                if err then
                    return nil, err
                end
                return 1
            end
            size = size + #chunk
            if size > MAX_BYTES then
                return nil, "response too large"
            end
            chunks[#chunks + 1] = chunk
            return 1
        end,
    }
    if not ok then
        return nil, "Не удалось связаться с календарём."
    end
    if code == 401 or code == 403 then
        return nil, "Сервер не принял код. Проверьте доступ виджетов и подключитесь заново."
    end
    if code ~= 200 then
        return nil, "Сервер не смог отдать расписание."
    end
    return table.concat(chunks)
end

return Network
