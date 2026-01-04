#!/usr/bin/env python3
"""
Преобразователь изображений в символы Брайля для OpenComputers / OpenOS.

- Масштабирует картинку под сетку 2x4 точек Брайля с нужным количеством
  символов (по умолчанию 160x50 → 320x200 пикселей).
- Внутри каждой ячейки подбирает 2 цвета (фон/текст) и по желанию
  применяет упорядоченное дизеринг.
- Выдаёт Lua-таблицу с шириной/высотой и массивами символов/цветов, которые
  можно сразу рисовать на GPU.
"""
from __future__ import annotations

import argparse
import pathlib
from dataclasses import dataclass
import math
from typing import Iterable, List, Sequence, Tuple

from PIL import Image

# 4x4 матрица Байера для упорядоченного дизеринга.
_BAYER_4X4 = [
    [0, 8, 2, 10],
    [12, 4, 14, 6],
    [3, 11, 1, 9],
    [15, 7, 13, 5],
]


@dataclass
class Options:
    input_path: pathlib.Path
    output_path: pathlib.Path
    char_width: int
    char_height: int
    dither: bool
    min_contrast: float
    min_dots: int
    min_neighbors: int


Color = Tuple[float, float, float]


def parse_args() -> Options:
    parser = argparse.ArgumentParser(
        description="Конвертировать изображение в символы Брайля для OpenOS."
    )
    parser.add_argument("input", type=pathlib.Path, help="Путь к исходной картинке")
    parser.add_argument(
        "output",
        type=pathlib.Path,
        help="Путь к Lua-файлу (w/h/chars/fg/bg)",
    )
    parser.add_argument(
        "--chars-width",
        type=int,
        default=160,
        help="Ширина в символах (по умолчанию 160 → 320 пикселей с Брайлем)",
    )
    parser.add_argument(
        "--chars-height",
        type=int,
        default=50,
        help="Высота в символах (по умолчанию 50 → 200 пикселей с Брайлем)",
    )
    parser.add_argument(
        "--min-contrast",
        type=float,
        default=12.0,
        help=(
            "Минимальная разница RGB (0–441) между фоном и текстом в ячейке."
            " Если меньше — ячейка заливается одним цветом, чтобы убрать шум."
        ),
    )
    parser.add_argument(
        "--min-dots",
        type=int,
        default=2,
        help=(
            "Если точек меньше значения — ячейка очищается, чтобы убирать одиночные"
            " «вопросики»"
        ),
    )
    parser.add_argument(
        "--min-neighbors",
        type=int,
        default=2,
        help=(
            "Сколько соседних ячеек с точками нужно, чтобы не считать её шумом."
            " Одиночные пятна автоматически глушатся."
        ),
    )
    parser.add_argument(
        "--no-dither",
        action="store_true",
        help="Отключить упорядоченное дизеринг внутри ячейки",
    )
    args = parser.parse_args()

    return Options(
        input_path=args.input,
        output_path=args.output,
        char_width=args.chars_width,
        char_height=args.chars_height,
        dither=not args.no_dither,
        min_contrast=max(0.0, args.min_contrast),
        min_dots=max(0, args.min_dots),
        min_neighbors=max(0, args.min_neighbors),
    )


def load_image(path: pathlib.Path) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    return img


def _composite_on_black(pix: Tuple[int, int, int, int]) -> Tuple[int, int, int]:
    r, g, b, a = pix
    alpha = a / 255.0
    return (
        int(r * alpha),
        int(g * alpha),
        int(b * alpha),
    )


def resize_and_letterbox(img: Image.Image, target_px_w: int, target_px_h: int) -> Image.Image:
    scale = min(target_px_w / img.width, target_px_h / img.height)
    scale = max(scale, 1e-6)
    resized_w = max(1, int(img.width * scale))
    resized_h = max(1, int(img.height * scale))
    resized = img.resize((resized_w, resized_h), Image.Resampling.LANCZOS)

    canvas = Image.new("RGBA", (target_px_w, target_px_h), (0, 0, 0, 255))
    offset_x = (target_px_w - resized_w) // 2
    offset_y = (target_px_h - resized_h) // 2
    canvas.paste(resized, (offset_x, offset_y))
    return canvas


def _luminance(c: Color) -> float:
    r, g, b = c
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _avg_color(colors: Iterable[Color]) -> Color:
    count = 0
    r = g = b = 0.0
    for cr, cg, cb in colors:
        r += cr
        g += cg
        b += cb
        count += 1
    if count == 0:
        return (0.0, 0.0, 0.0)
    return (r / count, g / count, b / count)


def _dist2(a: Color, b: Color) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2


def _kmeans_two(colors: Sequence[Color]) -> Tuple[Color, Color]:
    if not colors:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)

    sorted_by_lum = sorted(colors, key=_luminance)
    low = sorted_by_lum[0]
    high = sorted_by_lum[-1]
    if low == high:
        return low, high

    center_a = low
    center_b = high
    for _ in range(4):
        cluster_a: List[Color] = []
        cluster_b: List[Color] = []
        for color in colors:
            if _dist2(color, center_a) <= _dist2(color, center_b):
                cluster_a.append(color)
            else:
                cluster_b.append(color)
        if not cluster_a:
            cluster_a.append(center_a)
        if not cluster_b:
            cluster_b.append(center_b)
        new_a = _avg_color(cluster_a)
        new_b = _avg_color(cluster_b)
        if new_a == center_a and new_b == center_b:
            break
        center_a, center_b = new_a, new_b
    return center_a, center_b


def _choose_pixel(color: Color, bg: Color, fg: Color, x: int, y: int, dither: bool) -> bool:
    """Вернуть True, если пиксель должен уйти в цвет текста."""
    if bg == fg:
        return False

    if dither:
        lum_bg = _luminance(bg)
        lum_fg = _luminance(fg)
        delta = lum_fg - lum_bg
        if abs(delta) < 1e-6:
            delta = 1e-6
        lum = _luminance(color)
        t = (lum - lum_bg) / delta
        t = max(0.0, min(1.0, t))
        threshold = _BAYER_4X4[y % 4][x % 4] / 16.0
        return t >= threshold

    return _dist2(color, fg) <= _dist2(color, bg)


def _color_to_hex(c: Color) -> int:
    return (int(round(c[0])) << 16) | (int(round(c[1])) << 8) | int(round(c[2]))


def _block_to_braille(
    block: Sequence[Sequence[Color]], dither: bool, min_contrast: float, min_dots: int
) -> Tuple[int, int, int, int]:
    flat: List[Color] = [pix for row in block for pix in row]
    bg, fg = _kmeans_two(flat)

    # Если цвета почти не отличаются — сразу считаем ячейку заливкой.
    if math.sqrt(_dist2(bg, fg)) < min_contrast:
        flat_color = _color_to_hex(_avg_color(flat))
        return 0, flat_color, flat_color, 0

    bits = 0
    for y, row in enumerate(block):
        for x, pix in enumerate(row):
            if _choose_pixel(pix, bg, fg, x, y, dither):
                bits |= 1 << _BRAILLE_BIT_INDEX[y][x]

    # Убираем мелкие одиночные точки, которые превращаются в «вопросики».
    dot_count = bin(bits).count("1")
    if bits != 0 and dot_count < min_dots:
        flat_color = _color_to_hex(_avg_color(flat))
        return 0, flat_color, flat_color, 0

    return bits, _color_to_hex(fg), _color_to_hex(bg), dot_count


_BRAILLE_BIT_INDEX = [
    [0, 3],  # y=0: точки 1,4
    [1, 4],  # y=1: точки 2,5
    [2, 5],  # y=2: точки 3,6
    [6, 7],  # y=3: точки 7,8
]


@dataclass
class BrailleFrame:
    chars: List[str]
    fg_rows: List[List[int]]
    bg_rows: List[List[int]]


def to_braille_grid(
    img: Image.Image,
    char_w: int,
    char_h: int,
    dither: bool,
    min_contrast: float,
    min_dots: int,
    min_neighbors: int,
) -> BrailleFrame:
    assert img.width == char_w * 2 and img.height == char_h * 4
    pixels = img.load()

    # Сначала собираем всю сетку с битовыми масками, чтобы потом зачистить шум
    # по соседям.
    bit_rows: List[List[int]] = []
    fg_rows: List[List[int]] = []
    bg_rows: List[List[int]] = []

    for cy in range(char_h):
        fg_line: List[int] = []
        bg_line: List[int] = []
        bit_line: List[int] = []
        for cx in range(char_w):
            block: List[List[Color]] = []
            for py in range(4):
                row: List[Color] = []
                for px in range(2):
                    r, g, b, a = pixels[cx * 2 + px, cy * 4 + py]
                    row.append(_composite_on_black((r, g, b, a)))
                block.append(row)
            bits, fg, bg, _ = _block_to_braille(block, dither, min_contrast, min_dots)
            bit_line.append(bits)
            fg_line.append(fg)
            bg_line.append(bg)
        bit_rows.append(bit_line)
        fg_rows.append(fg_line)
        bg_rows.append(bg_line)

    # Второй проход: убираем одиночные ячейки, если вокруг слишком мало «чернил».
    cleaned_bits: List[List[int]] = []
    for y in range(char_h):
        cleaned_line: List[int] = []
        for x in range(char_w):
            bits = bit_rows[y][x]
            if bits == 0:
                cleaned_line.append(0)
                continue

            neighbor_dots = 0
            for ny in range(max(0, y - 1), min(char_h, y + 2)):
                for nx in range(max(0, x - 1), min(char_w, x + 2)):
                    if ny == y and nx == x:
                        continue
                    if bit_rows[ny][nx] != 0:
                        neighbor_dots += 1
            if neighbor_dots < min_neighbors:
                cleaned_line.append(0)
                fg_rows[y][x] = bg_rows[y][x]  # превращаем в заливку
            else:
                cleaned_line.append(bits)
        cleaned_bits.append(cleaned_line)

    # Переводим в строки символов.
    chars: List[str] = []
    for y in range(char_h):
        line_chars: List[str] = []
        for x in range(char_w):
            bits = cleaned_bits[y][x]
            line_chars.append(chr(0x2800 + bits))
        chars.append("".join(line_chars))

    return BrailleFrame(chars=chars, fg_rows=fg_rows, bg_rows=bg_rows)


def frame_to_lua(frame: BrailleFrame) -> str:
    def lua_table(rows: List[List[int]]) -> str:
        parts = []
        for row in rows:
            # Десятичные литералы — для совместимости со старыми билдами OpenOS,
            # где шестнадцатеричные числа могли ломаться.
            nums = ", ".join(str(value) for value in row)
            parts.append(f"    {{{nums}}}")
        return "{\n" + ",\n".join(parts) + "\n}"

    def lua_string_literal(text: str) -> str:
        # Lua не понимает JSON-экранирование \u, поэтому пишем сразу UTF-8 и
        # экранируем только спецсимволы Lua-строки.
        escaped = text.replace("\\", "\\\\").replace("\"", "\\\"")
        return f'"{escaped}"'

    chars_lines = ",\n  ".join(lua_string_literal(line) for line in frame.chars)
    lua = [
        "return {",
        f"  w = {len(frame.chars[0])},",
        f"  h = {len(frame.chars)},",
        "  chars = {",
        f"  {chars_lines}",
        "  },",
        "  fg = " + lua_table(frame.fg_rows) + ",",
        "  bg = " + lua_table(frame.bg_rows),
        "}",
    ]
    return "\n".join(lua)


def main() -> None:
    opts = parse_args()
    if opts.char_width <= 0 or opts.char_height <= 0:
        raise SystemExit("Ширина и высота в символах должны быть больше нуля")

    img = load_image(opts.input_path)
    target_px_w = opts.char_width * 2
    target_px_h = opts.char_height * 4
    prepared = resize_and_letterbox(img, target_px_w, target_px_h)
    frame = to_braille_grid(
        prepared,
        opts.char_width,
        opts.char_height,
        opts.dither,
        opts.min_contrast,
        opts.min_dots,
        opts.min_neighbors,
    )
    opts.output_path.write_text(frame_to_lua(frame), encoding="utf-8")
    print(
        f"Сохранено в {opts.output_path} (символы: {opts.char_width}x{opts.char_height})"
    )


if __name__ == "__main__":
    main()
