#!/usr/bin/env python3
# img2braille + OpenComputers .pic helper
#
# What it does:
# - Converts image -> braille text (2x4 pixels per char)
# - Optionally generates OpenOS Lua script that:
#     1) draws the braille image with colors on screen
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

# NEW: generate OpenOS script that saves .pic
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
    # Convert to grayscale by picking one channel
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
        # treat as RGB anyway for simplicity
        return img.convert("RGB")
    return img.convert("RGB")


def calc_average(img, algorithm, autocontrast):
    # Matches your original logic, but fixes a bug (average reset inside loops)
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

    # Normalize so threshold is still comparable to r+g+b for RGBsum
    if algorithm in {"R", "G", "B"}:
        # channel threshold in 0..255, but our get_dot_value uses sum r+g+b
        # We'll scale it by *3 to keep behavior closer.
        return (total / (w * h)) * 3

    return total / (w * h)


def get_dot_value(img, pos, average):
    px = img.getpixel(pos)
    r, g, b = px[0], px[1], px[2]
    if (r + g + b) < average:
        return not args.invert
    return args.invert


def block_from_cursor(img, pos, average, noempty, blank):
    if blank:
        return chr(0x28FF)

    block_val = 0x2800

    if get_dot_value(img, pos, average):
        block_val += 0x0001
    if get_dot_value(img, (pos[0] + 1, pos[1]), average):
        block_val += 0x0008
    if get_dot_value(img, (pos[0], pos[1] + 1), average):
        block_val += 0x0002
    if get_dot_value(img, (pos[0] + 1, pos[1] + 1), average):
        block_val += 0x0010
    if get_dot_value(img, (pos[0], pos[1] + 2), average):
        block_val += 0x0004
    if get_dot_value(img, (pos[0] + 1, pos[1] + 2), average):
        block_val += 0x0020
    if get_dot_value(img, (pos[0], pos[1] + 3), average):
        block_val += 0x0040
    if get_dot_value(img, (pos[0] + 1, pos[1] + 3), average):
        block_val += 0x0080

    if noempty and block_val == 0x2800:
        block_val = 0x2801

    return chr(block_val)


def rgb_to_hex(px):
    r, g, b = int(px[0]), int(px[1]), int(px[2])
    return (r << 16) | (g << 8) | b


def iterate_image(img, original_img, dither, autocontrast, noempty, blank):
    img = apply_algo(img, args.calc).convert("RGB")
    average = calc_average(img, args.calc, autocontrast)

    if dither:
        # Pillow dithering to 1-bit, then back to RGB (keeps the on/off pattern)
        img = img.convert("1")
        img = img.convert("RGB")

    y_size = img.size[1]
    x_size = img.size[0]

    out_lines = []
    out_cols = []

    y_pos = 0
    while y_pos < y_size - 3:
        x_pos = 0
        line_chars = []
        line_colors = []

        while x_pos < x_size:
            # Color sampling:
            # original script used top-left pixel; keep it for compatibility
            px = original_img.getpixel((x_pos, y_pos))
            if not isinstance(px, tuple):
                px = (px, px, px)

            ch = block_from_cursor(img, (x_pos, y_pos), average, noempty, blank)
            line_chars.append(ch)
            line_colors.append(px)

            x_pos += 2

        out_lines.append("".join(line_chars))
        out_cols.append(line_colors)
        y_pos += 4

    return out_lines, out_cols


def write_makepic_lua(lines, cols, out_pic_path, lua_filename):
    h = len(lines)
    w = len(lines[0]) if h else 0

    with open(lua_filename, "w", encoding="utf-8") as f:
        f.write("-- generated: draw braille image and save to .pic (OpenComputers)\n")
        f.write("local component = require('component')\n")
        f.write("local term = require('term')\n")
        f.write("local shell = require('shell')\n")
        f.write("local gpu = component.gpu\n\n")

        f.write("local img = {\n")
        f.write(f"  w = {w},\n")
        f.write(f"  h = {h},\n")
        f.write("  chars = {\n")
        for line in lines:
            safe = line.replace("\\", "\\\\").replace('"', '\\"')
            f.write(f'    "{safe}",\n')
        f.write("  },\n")
        f.write("  col = {\n")
        for y in range(h):
            row = [f"0x{rgb_to_hex(cols[y][x]):06X}" for x in range(w)]
            f.write("    {" + ", ".join(row) + "},\n")
        f.write("  }\n")
        f.write("}\n\n")

        f.write("term.clear()\n")
        f.write("for y = 1, img.h do\n")
        f.write("  local line = img.chars[y]\n")
        f.write("  for x = 1, img.w do\n")
        f.write("    local c = img.col[y][x]\n")
        f.write("    gpu.setBackground(c)\n")
        f.write("    gpu.setForeground(c)\n")
        f.write("    gpu.set(x, y, line:sub(x, x))\n")
        f.write("  end\n")
        f.write("end\n\n")

        # Save .pic
        safe_path = out_pic_path.replace("'", "\\'")
        f.write(f"shell.execute('pic save {safe_path}')\n")
        f.write(f"print('Saved: {safe_path}')\n")


# --- Main flow ---

img = Image.open(args.input)

# Resize to requested width, preserve aspect ratio
new_w = int(args.width)
new_h = int(round((new_w * img.size[1]) / img.size[0]))
img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

# Ensure dimensions fit braille grid: width multiple of 2, height multiple of 4
off_x = img.size[0] % 2
off_y = img.size[1] % 4
if off_x != 0 or off_y != 0:
    img = img.resize((img.size[0] + (2 - off_x if off_x else 0),
                      img.size[1] + (4 - off_y if off_y else 0)),
                     Image.Resampling.NEAREST)

original_img = img.convert("RGB").copy()

lines, cols = iterate_image(
    img=img,
    original_img=original_img,
    dither=args.dither,
    autocontrast=args.autocontrast,
    noempty=args.noempty,
    blank=args.blank
)

if args.oc_pic:
    write_makepic_lua(lines, cols, args.oc_pic, args.lua_out)
    print(f"Generated {args.lua_out}. Copy it to OpenOS and run: lua /home/{args.lua_out}")
else:
    for line in lines:
        print(line)
