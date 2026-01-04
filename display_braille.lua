-- display_braille.lua
-- Draw a Braille image table (produced by braille_converter.py) centered on the screen.

local component = require("component")
local term = require("term")

local args = {...}
local path = args[1] or "/home/braille.lua"

local gpu = component.gpu
local ok, img_or_err = pcall(dofile, path)
if not ok then
  io.stderr:write("Failed to load Braille file: " .. tostring(img_or_err) .. "\n")
  os.exit(1)
end
local img = img_or_err

local function fit(out_w, out_h, in_w, in_h)
  local scale = math.min(out_w / in_w, out_h / in_h)
  scale = math.max(scale, 1e-6)
  local w = math.max(1, math.floor(in_w * scale))
  local h = math.max(1, math.floor(in_h * scale))
  return w, h, scale
end

local function draw_image()
  local sw, sh = gpu.getResolution()
  local dw, dh, scale = fit(sw, sh, img.w, img.h)
  local x0 = math.floor((sw - dw) / 2)
  local y0 = math.floor((sh - dh) / 2)

  term.clear()

  for y = 1, dh do
    local src_y = math.floor((y - 1) / scale) + 1
    local line = img.chars[src_y]
    local fg_row = img.fg[src_y]
    local bg_row = img.bg[src_y]
    for x = 1, dw do
      local src_x = math.floor((x - 1) / scale) + 1
      gpu.setBackground(bg_row[src_x])
      gpu.setForeground(fg_row[src_x])
      gpu.set(x0 + x, y0 + y, line:sub(src_x, src_x))
    end
  end
end

draw_image()
