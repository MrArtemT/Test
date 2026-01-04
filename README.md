# Braille image converter for OpenOS

This repo contains:

- `braille_converter.py` — Python CLI that resizes an image to a Braille grid, clusters two colors per 2x4 cell, optionally dithers, and writes a Lua table (`w`, `h`, `chars`, `fg`, `bg`).
- `display_braille.lua` — OpenOS viewer that reads the Lua table and draws it centered on the screen with the GPU.

## Requirements

- Python 3.9+ with [Pillow](https://pillow.readthedocs.io/) installed (`pip install pillow`).
- Your source image (e.g., `imput_2.png`).

## Convert an image (example with `imput_2.png`)

1. Install Pillow once:
   ```bash
   python -m pip install pillow
   ```

2. Run the converter. For a standard 80x25 OpenOS resolution, use:
   ```bash
   python braille_converter.py "C:\\Users\\vreme\\Downloads\\imput_2.png" output_braille.lua --chars-width 80 --chars-height 25
   ```

   Notes:
   - Quote Windows paths and escape backslashes as shown above.
   - If your in-game screen is larger, replace `--chars-width/--chars-height` with the resolution you actually use (e.g., `160 50` for tier-3 at 160x50).
   - To disable dithering, add `--no-dither`.

3. Copy the generated `output_braille.lua` to your OpenOS computer along with `display_braille.lua`.

4. On OpenOS, display the image:
   ```lua
   lua display_braille.lua /home/output_braille.lua
   ```

   The viewer will clear the terminal, center the art, and scale down if the screen is smaller than the precomputed size.

## Tips

- Letterboxing: the converter centers your image in the target grid without distortion, filling empty space with black.
- Color: each Braille cell uses up to two colors (foreground/background). Ordered dithering is enabled by default for better detail.
- The generated Lua file now uses decimal color values to avoid syntax issues on some OpenOS builds and writes UTF-8 Braille
  characters directly (no JSON-style escapes), so `dofile` can load it without errors.
- If you want to batch multiple images, just run the converter for each source image and give each output a unique filename.
