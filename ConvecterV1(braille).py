#!/usr/bin/env python3
# img2braille + OpenComputers .pic helper (2 colors per braille cell) + UTF-8 safe Lua
#
# What it does:
# - Converts image -> braille text (2x4 pixels per char)
# - For every braille char computes TWO colors:
#     FG = average color of "ON" dots, BG = average color of "OFF" dots
# - Optionally generates OpenOS Lua script that:
#     1) draws the braille image with fg/bg colors on screen (UTF-8 safe)
#     2) runs: pic save <path>
#
# Install:
#   pip install pillow
#
# Examples (Windows):
#   python script_ocpic.py "C:\Users\vreme\Downloads\input.png" -w 160 -d -a --oc-pic /home/background.pic
#   (then copy makepic.lua to OpenOS and run: lua /home/makepic.lua)

from PIL import Image
import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8")

parser = argparse.ArgumentParser()
parser.add_argument("input", type=str, help="image file")

parser.add_argument(
    "-w", "--width",
    type=int,
    default=160,
    help="output width in number of pixels BEFORE braille grouping (must be even). Default 160.",
)

parser.add_argument(
    "-i", "--noinvert",
    dest="invert",
    action="store_false",
    help="don't invert colors (for bright backgrounds with dark pixels)",
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
    help="channel used to calculate dot on/off values",
)

parser.add_argument(
    "-n", "--noempty",
    action="store_true",
    help="don't use U+2800 empty braille (can fix spacing issues)",
)

parser.add_argument(
    "-a", "--autocontrast",
    action="store_true",
    help="auto adjust threshold based on image average",
)

parser.add_argument(
    "-b", "--blank",
    action="store_true",
    help="U+28FF everywhere (useful if you only want color blocks)",
)

parser.add_argument(
    "--oc-pic",
    type=str,
    default=None,
    help="generate makepic.lua that draws image and saves it as .pic to given OpenOS path, e.g. /home/background.pic",
)

parser.add_argument(
    "--lua-out",
    type=str,
    default="makepic.lua",
    help="output lua filename (default: makepic.lua)",
)

args = parser.parse_args()


# --- Helpers ---

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
    if algo == "R":
        img = img.convert("RGB")
        return adjust_to_color(img, 0)
    if algo == "G":
        img = img.convert("RGB")
        return adjust_to_color(img, 1)
    if algo == "B":
        img = img.convert("RGB")
        return adjust_to_color(img, 2)
    if algo == "BW":
        return img.convert("RGB")
    return img.convert("RGB")


def calc_average(img, algorithm, autocontrast):
    if not autocontrast:
        return 382.5  # default threshold for RGBsum (255*3/2)

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
                elif algorithm == "BW":
                    total += r + g + b
                else:
                    total += r + g + b
            else:
                total += px

    if algorithm in {"R", "G", "B"}:
        return (total / (w * h)) * 3

    return total / (w * h)


def get_dot_value(img, pos, average):
    px = img.getpixel(pos)
    r, g, b = px[0], px[1], px[2]
    if (r + g + b) < average:
        return not args.invert
    return args.invert


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


def block_char_and_two_colors(img_bw, original_img, pos, average, noempty, blank):
    pts = [
        (pos[0],     pos[1]),      # 1
        (pos[0],     pos[1] + 1),  # 2
        (pos[0],     pos[1] + 2),  # 3
        (pos[0],     pos[1] + 3),  # 7
        (pos[0] + 1, pos[1]),      # 4
        (pos[0] + 1, pos[1] + 1),  # 5
        (pos[0] + 1, pos[1] + 2),  # 6
        (pos[0] + 1, pos[1] + 3),  # 8
    ]

    if blank:
        ch = chr(0x28FF)
        block_pixels = []
        for p in pts:
            px = original_img.getpixel(p)
            if not isinstance(px, tuple):
                px = (px, px, px)
            block_pixels.append(px)
        c = avg_color(block_pixels)
        return ch, c, c

    on_pixels = []
    off_pixels = []
    block_val = 0x2800

    mapping = [
        (pts[0], 0x0001),
        (pts[4], 0x0008),
        (pts[1], 0x0002),
        (pts[5], 0x0010),
        (pts[2], 0x0004),
        (pts[6], 0x0020),
        (pts[3], 0x0040),
        (pts[7], 0x0080),
    ]

    for p, bit in mapping:
        is_on = get_dot_value(img_bw, p, average)
        px = original_img.getpixel(p)
        if not isinstance(px, tuple):
            px = (px, px, px)

        if is_on:
            block_val += bit
            on_pixels.append(px)
        else:
            off_pixels.append(px)

    if noempty and block_val == 0x2800:
        block_val = 0x2801

    ch = chr(block_val)

    fg = avg_color(on_pixels)
    bg = avg_color(off_pixels)

    if not on_pixels:
        fg = bg
    if not off_pixels:
        bg = fg

    return ch, fg, bg


def iterate_image(img, original_img, dither, autocontrast, noempty, blank):
    img = apply_algo(img, args.calc).convert("RGB")
    average = calc_average(img, args.calc, autocontrast)

    if dither:
        img = img.convert("1")
        img = img.convert("RGB")

    y_size = img.size[1]
    x_size = img.size[0]

    out_lines = []
    out_fg = []
    out_bg = []

    y_pos = 0
    while y_pos < y_size - 3:
        x_pos = 0
        line_chars = []
        line_fg = []
        line_bg = []

        while x_pos < x_size:
            ch, fg, bg = block_char_and_two_colors(
                img_bw=img,
                original_img=original_img,
                pos=(x_pos, y_pos),
                average=average,
                noempty=noempty,
                blank=blank
            )

            line_chars.append(ch)
            line_fg.append(fg)
            line_bg.append(bg)

            x_pos += 2

        out_lines.append("".join(line_chars))
        out_fg.append(line_fg)
        out_bg.append(line_bg)
        y_pos += 4

    return out_lines, out_fg, out_bg


def write_makepic_lua(lines, fg_cols, bg_cols, out_pic_path, lua_filename):
    h = len(lines)
    w = len(lines[0]) if h else 0

    with open(lua_filename, "w", encoding="utf-8") as f:
        f.write("-- generated: draw braille image with 2 colors per cell and save to .pic (OpenComputers)\n")
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
            row = [f"0x{rgb_to_hex(fg_cols[y][x]):06X}" for x in range(w)]
            f.write("    {" + ", ".join(row) + "},\n")
        f.write("  },\n")

        f.write("  bg = {\n")
        for y in range(h):
            row = [f"0x{rgb_to_hex(bg_cols[y][x]):06X}" for x in range(w)]
            f.write("    {" + ", ".join(row) + "},\n")
        f.write("  }\n")
        f.write("}\n\n")

        f.write("term.clear()\n")
        f.write("for y = 1, img.h do\n")
        f.write("  local line = img.chars[y]\n")
        f.write("  local lw = unicode.len(line)\n")
        f.write("  for x = 1, lw do\n")
        f.write("    gpu.setBackground(img.bg[y][x])\n")
        f.write("    gpu.setForeground(img.fg[y][x])\n")
        f.write("    gpu.set(x, y, unicode.sub(line, x, x))\n")
        f.write("  end\n")
        f.write("end\n\n")

        safe_path = out_pic_path.replace("'", "\\'")
        f.write(f"shell.execute('pic save {safe_path}')\n")
        f.write(f"print('Saved: {safe_path}')\n")


# --- Main flow ---

img = Image.open(args.input)

new_w = int(args.width)
new_h = int(round((new_w * img.size[1]) / img.size[0]))
img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

off_x = img.size[0] % 2
off_y = img.size[1] % 4
if off_x != 0 or off_y != 0:
    img = img.resize(
        (
            img.size[0] + (2 - off_x if off_x else 0),
            img.size[1] + (4 - off_y if off_y else 0),
        ),
        Image.Resampling.NEAREST
    )

original_img = img.convert("RGB").copy()

lines, fg_cols, bg_cols = iterate_image(
    img=img,
    original_img=original_img,
    dither=args.dither,
    autocontrast=args.autocontrast,
    noempty=args.noempty,
    blank=args.blank
)

if args.oc_pic:
    write_makepic_lua(lines, fg_cols, bg_cols, args.oc_pic, args.lua_out)
    print(f"Generated {args.lua_out}. Copy it to OpenOS and run: lua /home/{args.lua_out}")
else:
    for line in lines:
        print(line)
