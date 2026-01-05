#!/usr/bin/env python3
# img2unicode + OpenComputers .pic helper (with OC character-aspect correction)
#
# Modes:
#   braille: 2x4 pixels per char (U+2800..U+28FF)
#   quad   : 2x2 pixels per char (Unicode quadrant blocks)  [recommended]
#   half   : 1x2 pixels per char (▀ upper-half block)
#
# Key fix vs “image gets squished / bars appear”:
# OpenComputers terminal cells are NOT square (they are taller than wide).
# So we correct the resize height using CHAR_ASPECT (~2.0).
#
# Install:
#   pip install pillow
#
# Examples:
#   python script2.py input.png --mode quad -w 320 -d -a --oc-pic /home/background.pic
#   python script2.py input.png --mode braille -w 320 -d -a --oc-pic /home/background.pic

from PIL import Image
import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8")

parser = argparse.ArgumentParser()
parser.add_argument("input", type=str, help="image file")

parser.add_argument(
    "--mode",
    choices=["braille", "quad", "half"],
    default="quad",
    help="render mode: braille (2x4), quad (2x2), half (1x2). Default: quad",
)

parser.add_argument(
    "-w", "--width",
    type=int,
    default=320,
    help="output width in PIXELS before grouping. Default 320.",
)

parser.add_argument(
    "--char-aspect",
    type=float,
    default=2.0,
    help="OpenComputers character cell aspect (height/width). Usually ~2.0. Default 2.0",
)

parser.add_argument(
    "-i", "--noinvert",
    dest="invert",
    action="store_false",
    help="don't invert threshold logic",
)
parser.set_defaults(invert=True)

parser.add_argument(
    "-d", "--dither",
    action="store_true",
    help="use dithering (recommended for gradients)",
)

parser.add_argument(
    "--calc",
    type=str,
    choices=["RGBsum", "R", "G", "B", "BW"],
    default="RGBsum",
    help="channel used to calculate on/off values",
)

parser.add_argument(
    "-a", "--autocontrast",
    action="store_true",
    help="auto adjust threshold based on image average",
)

parser.add_argument(
    "--oc-pic",
    type=str,
    default=None,
    help="generate makepic.lua and save .pic to given OpenOS path, e.g. /home/background.pic",
)

parser.add_argument(
    "--lua-out",
    type=str,
    default="makepic.lua",
    help="output lua filename (default: makepic.lua)",
)

args = parser.parse_args()


# ---------------- Helpers ----------------

def adjust_to_color(img, pos):
    for y in range(img.size[1]):
        for x in range(img.size[0]):
            px = img.getpixel((x, y))
            val = px[pos] if isinstance(px, tuple) else px
            img.putpixel((x, y), (val, val, val))
    return img


def apply_algo(img, algo):
    if algo == "RGBsum":
        return img.convert("RGB")
    if algo in {"R", "G", "B"}:
        img = img.convert("RGB")
        ch = {"R": 0, "G": 1, "B": 2}[algo]
        return adjust_to_color(img, ch)
    if algo == "BW":
        return img.convert("RGB")
    return img.convert("RGB")


def calc_average(img, algorithm, autocontrast):
    if not autocontrast:
        return 382.5  # default for RGBsum (255*3/2)

    total = 0
    w, h = img.size
    for y in range(h):
        for x in range(w):
            px = img.getpixel((x, y))
            if isinstance(px, tuple):
                r, g, b = px[0], px[1], px[2]
                if algorithm == "RGBsum":
                    total += r + g + b
                elif algorithm == "R":
                    total += r
                elif algorithm == "G":
                    total += g
                elif algorithm == "B":
                    total += b
                else:
                    total += r + g + b
            else:
                total += px

    if algorithm in {"R", "G", "B"}:
        return (total / (w * h)) * 3
    return total / (w * h)


def get_on(img_bw, pos, average, invert: bool):
    px = img_bw.getpixel(pos)
    r, g, b = px[0], px[1], px[2]
    is_dark = (r + g + b) < average
    return (not invert) if is_dark else invert


def rgb_to_hex(px):
    r, g, b = int(px[0]), int(px[1]), int(px[2])
    return (r << 16) | (g << 8) | b


def avg_color(pixels):
    if not pixels:
        return (0, 0, 0)
    r = sum(p[0] for p in pixels) / len(pixels)
    g = sum(p[1] for p in pixels) / len(pixels)
    b = sum(p[2] for p in pixels) / len(pixels)
    return (int(r), int(g), int(b))


# ---------------- Glyph builders ----------------

_QUAD_MAP = {
    0b0000: " ",
    0b0001: "▗",
    0b0010: "▖",
    0b0011: "▄",
    0b0100: "▝",
    0b0101: "▐",
    0b0110: "▞",
    0b0111: "▟",
    0b1000: "▘",
    0b1001: "▚",
    0b1010: "▌",
    0b1011: "▙",
    0b1100: "▀",
    0b1101: "▜",
    0b1110: "▛",
    0b1111: "█",
}


def build_cell_braille(img_bw, original_img, x, y, average, invert: bool):
    mapping = [
        ((x,   y),   0x0001),
        ((x+1, y),   0x0008),
        ((x,   y+1), 0x0002),
        ((x+1, y+1), 0x0010),
        ((x,   y+2), 0x0004),
        ((x+1, y+2), 0x0020),
        ((x,   y+3), 0x0040),
        ((x+1, y+3), 0x0080),
    ]

    block_val = 0x2800
    on_pixels, off_pixels = [], []

    for (px, py), bit in mapping:
        on = get_on(img_bw, (px, py), average, invert)
        col = original_img.getpixel((px, py))
        if not isinstance(col, tuple):
            col = (col, col, col)
        if on:
            block_val += bit
            on_pixels.append(col)
        else:
            off_pixels.append(col)

    ch = chr(block_val)
    fg = avg_color(on_pixels) if on_pixels else avg_color(off_pixels)
    bg = avg_color(off_pixels) if off_pixels else fg
    return ch, fg, bg


def build_cell_quad(img_bw, original_img, x, y, average, invert: bool):
    coords = [(x, y), (x+1, y), (x, y+1), (x+1, y+1)]  # tl,tr,bl,br
    bits = 0
    on_pixels, off_pixels = [], []

    for i, (px, py) in enumerate(coords):
        on = get_on(img_bw, (px, py), average, invert)
        col = original_img.getpixel((px, py))
        if not isinstance(col, tuple):
            col = (col, col, col)

        bitmask = [0b1000, 0b0100, 0b0010, 0b0001][i]
        if on:
            bits |= bitmask
            on_pixels.append(col)
        else:
            off_pixels.append(col)

    ch = _QUAD_MAP[bits]
    fg = avg_color(on_pixels) if on_pixels else avg_color(off_pixels)
    bg = avg_color(off_pixels) if off_pixels else fg
    return ch, fg, bg


def build_cell_half(original_img, x, y):
    top_col = original_img.getpixel((x, y))
    bot_col = original_img.getpixel((x, y + 1))
    if not isinstance(top_col, tuple):
        top_col = (top_col, top_col, top_col)
    if not isinstance(bot_col, tuple):
        bot_col = (bot_col, bot_col, bot_col)
    return "▀", top_col, bot_col


# ---------------- Render pipeline ----------------

def iterate_image(img, mode: str):
    img_bw = apply_algo(img, args.calc).convert("RGB")
    average = calc_average(img_bw, args.calc, args.autocontrast)

    if args.dither:
        img_bw = img_bw.convert("1").convert("RGB")

    original = img.convert("RGB")
    w, h = img.size

    if mode == "braille":
        step_x, step_y = 2, 4
        builder = "braille"
    elif mode == "quad":
        step_x, step_y = 2, 2
        builder = "quad"
    else:
        step_x, step_y = 1, 2
        builder = "half"

    out_lines, out_fg, out_bg = [], [], []
    y = 0
    while y <= h - step_y:
        line_chars, line_fg, line_bg = [], [], []
        x = 0
        while x <= w - step_x:
            if builder == "braille":
                ch, fg, bg = build_cell_braille(img_bw, original, x, y, average, args.invert)
            elif builder == "quad":
                ch, fg, bg = build_cell_quad(img_bw, original, x, y, average, args.invert)
            else:
                ch, fg, bg = build_cell_half(original, x, y)

            line_chars.append(ch)
            line_fg.append(fg)
            line_bg.append(bg)
            x += step_x

        out_lines.append("".join(line_chars))
        out_fg.append(line_fg)
        out_bg.append(line_bg)
        y += step_y

    return out_lines, out_fg, out_bg


def write_makepic_lua(lines, fg_cols, bg_cols, out_pic_path, lua_filename):
    h = len(lines)
    w = len(lines[0]) if h else 0

    with open(lua_filename, "w", encoding="utf-8") as f:
        f.write("-- generated: draw unicode image (fg/bg per cell) and save to .pic (OpenComputers)\n")
        f.write("local component = require('component')\n")
        f.write("local term = require('term')\n")
        f.write("local shell = require('shell')\n")
        f.write("local unicode = require('unicode')\n")
        f.write("local gpu = component.gpu\n\n")

        f.write("local img = {\n")
        f.write(f"  w = {w},\n")
        f.write(f"  h = {h},\n")
        f.write("  chars = {\n")
        for line in lines:
            safe = line.replace("\\", "\\\\").replace('"', '\\"')
            f.write(f'    "{safe}",\n')
        f.write("  },\n")

        f.write("  fg = {\n")
        for y in range(h):
            row = [f"0x{rgb_to_hex(fg_cols[y][x]):06X}" for x in range(len(fg_cols[y]))]
            f.write("    {" + ", ".join(row) + "},\n")
        f.write("  },\n")

        f.write("  bg = {\n")
        for y in range(h):
            row = [f"0x{rgb_to_hex(bg_cols[y][x]):06X}" for x in range(len(bg_cols[y]))]
            f.write("    {" + ", ".join(row) + "},\n")
        f.write("  }\n")
        f.write("}\n\n")

        f.write("local maxW, maxH = gpu.maxResolution()\n")
        f.write("gpu.setResolution(maxW, maxH)\n")
        f.write("term.clear()\n\n")

        f.write("local sw, sh = gpu.getResolution()\n")
        f.write("local ox = math.floor((sw - img.w) / 2) + 1\n")
        f.write("local oy = math.floor((sh - img.h) / 2) + 1\n")
        f.write("if ox < 1 then ox = 1 end\n")
        f.write("if oy < 1 then oy = 1 end\n\n")

        f.write("for y = 1, img.h do\n")
        f.write("  local yy = oy + y - 1\n")
        f.write("  if yy > sh then break end\n")
        f.write("  local line = img.chars[y]\n")
        f.write("  local lw = unicode.len(line)\n")
        f.write("  for x = 1, lw do\n")
        f.write("    local xx = ox + x - 1\n")
        f.write("    if xx > sw then break end\n")
        f.write("    gpu.setBackground(img.bg[y][x])\n")
        f.write("    gpu.setForeground(img.fg[y][x])\n")
        f.write("    gpu.set(xx, yy, unicode.sub(line, x, x))\n")
        f.write("  end\n")
        f.write("end\n\n")

        safe_path = out_pic_path.replace("'", "\\'")
        f.write(f"shell.execute('pic save {safe_path}')\n")
        f.write(f"print('Saved: {safe_path}')\n")


# ---------------- Main ----------------

img = Image.open(args.input).convert("RGB")

# Subpixel grid per mode
if args.mode == "braille":
    step_x, step_y = 2, 4
elif args.mode == "quad":
    step_x, step_y = 2, 2
else:  # half
    step_x, step_y = 1, 2

# Resize with OpenComputers character-aspect correction:
# new_h = new_w * (img_h/img_w) * (step_y/step_x) / CHAR_ASPECT
new_w = int(args.width)
img_ratio = img.size[1] / img.size[0]
new_h = int(round(new_w * img_ratio * (step_y / step_x) / float(args.char_aspect)))
if new_h < step_y:
    new_h = step_y

img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

# Pad to fit the grid (NEAREST to avoid changing look too much)
w, h = img.size
pad_w = (step_x - (w % step_x)) % step_x
pad_h = (step_y - (h % step_y)) % step_y
if pad_w or pad_h:
    img = img.resize((w + pad_w, h + pad_h), Image.Resampling.NEAREST)

lines, fg_cols, bg_cols = iterate_image(img, args.mode)

if args.oc_pic:
    write_makepic_lua(lines, fg_cols, bg_cols, args.oc_pic, args.lua_out)
    print(f"Generated {args.lua_out}. Copy it to OpenOS and run: lua /home/{args.lua_out}")
else:
    for line in lines:
        print(line)
