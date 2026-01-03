-- makepic.lua
-- Draw /home/logo.lua centered & fitted to screen, then save to /home/background.pic

local component = require("component")
local term = require("term")
local shell = require("shell")
local gpu = component.gpu

local img = dofile("/home/logo.lua")

local function fitToScreen(imgW, imgH, scrW, scrH)
  local scale = math.min(scrW / imgW, scrH / imgH)
  local w = math.max(1, math.floor(imgW * scale))
  local h = math.max(1, math.floor(imgH * scale))
  return w, h
end

local function drawScaledCentered(img, outW, outH)
  local scrW, scrH = gpu.getResolution()
  local x0 = math.floor((scrW - outW) / 2) + 1
  local y0 = math.floor((scrH - outH) / 2) + 1

  for y = 1, outH do
    local srcY = math.floor((y - 1) * img.h / outH) + 1
    local line = img.chars[srcY]
    for x = 1, outW do
      local srcX = math.floor((x - 1) * img.w / outW) + 1
      local c = img.col[srcY][srcX] or 0x000000
      gpu.setBackground(c)
      gpu.setForeground(c)
      gpu.set(x0 + x - 1, y0 + y - 1, line:sub(srcX, srcX))
    end
  end
end

term.clear()

local scrW, scrH = gpu.getResolution()
local outW, outH = fitToScreen(img.w, img.h, scrW, scrH)

drawScaledCentered(img, outW, outH)

local outPath = "/home/background.pic"
local ok = shell.execute("pic save " .. outPath)
if not ok then
  io.stderr:write("pic not found. Install: oppm install pic\n")
else
  print("Saved: " .. outPath)
end
