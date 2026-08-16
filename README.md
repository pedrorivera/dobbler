# dobbler

Generate **Dobble / Spot-It**-style card decks with custom symbols. Each card's
symbols are placed at evenly-spread random positions, with random size (within
a bounded range) and random rotation. Output is a printable HTML page — open
it in a browser and print to PDF, then cut out the round cards.

## How Dobble works (the math)

A real Dobble deck is **not** just random cards from a pool. It is built from a
**finite projective plane of prime order `p`**, which guarantees the defining
property: *any two cards share exactly one symbol*.

| order `p` | cards | symbols per card | distinct symbols needed |
|----------|------|-----------------|------------------------|
| 2        | 7    | 3               | 7                      |
| 3        | 13   | 4               | 13                     |
| 5        | 31   | 6               | 31                     |
| 7        | 57   | 8               | 57  (closest to commercial Dobble, which uses 55) |
| 11       | 133  | 12              | 133                    |

`p` must be prime (the construction used here works for prime orders; prime-power
orders like 4, 8, 9 also work but need a different field construction).

## Usage

```bash
python3 dobble_gen.py --order 7 --seed 42 -o deck.html
```

Then open `deck.html` in a browser and print to PDF (the page is sized for A4
with cut-friendly round cards).

### Options

| flag            | default        | meaning |
|-----------------|----------------|---------|
| `--order` / `-p`| `7`            | prime order of the projective plane |
| `--seed`        | random         | RNG seed for reproducible decks |
| `--out` / `-o`  | `deck.html`    | output file |
| `--symbols-dir` | *(none)*       | directory of image symbols to use instead of emojis |
| `--embed`       | off            | inline images as base64 data URIs (self-contained HTML) |
| `--card-px`     | `320`          | card diameter in pixels |
| `--min-size`    | `28.0`         | minimum symbol size (px) — font size, or image box side |
| `--max-size`    | `52.0`         | maximum symbol size (px) — font size, or image box side |
| `--margin`      | `14.0`         | keep-out margin from card edge (px) |
| `--min-dist`    | `0.35`         | min spacing between symbols, as a fraction of avg size |
| `--max-rotation`| `180.0`        | max rotation in degrees (applied symmetrically ±) |
| `--card-bg`     | `#fffdf5`      | card background color |
| `--card-border` | `3px solid #d9c9a3` | card border CSS |

### Examples

Quick test deck (13 cards, 4 symbols each):

```bash
python3 dobble_gen.py --order 3 -o deck3.html
```

Larger symbols, less rotation, tighter spacing:

```bash
python3 dobble_gen.py --order 7 --min-size 34 --max-size 60 --max-rotation 45 --min-dist 0.25
```

## Layout algorithm

The card is a **circle**, so symbol centers are constrained to an inner circle
of radius `card_px/2 - margin - max_size/2`. This no-place band is wider than
the largest symbol's radius, guaranteeing every symbol — even the biggest —
stays fully inside the round card by at least `--margin` px, with no clipping
at the border. (Earlier the layout used the square bounding box, which let
symbols near the corners/edges spill outside the circle and get cut.)

Within that inner circle, positions are random but kept evenly spread by
**rejection sampling**: each candidate is rejected if it would sit within
`--min-dist` (scaled by symbol size) of an already-placed symbol. If the
spacing can't be satisfied within a bounded number of attempts, the
inter-symbol distance is relaxed and the card is re-laid from scratch — so
you always get a valid, non-overlapping layout that still looks random. The
border keep-out is never relaxed, so the no-clipping guarantee always holds.
Size is uniform-random in `[min-size, max-size]` and rotation is uniform-random
in `[-max-rotation, max-rotation]`.

## Image symbols

Point `--symbols-dir` at a folder of images and they replace the emoji pool:

```bash
python3 dobble_gen.py --order 7 --symbols-dir symbols \
  --card-px 420 --min-size 46 --max-size 78 -o deck.html
```

Accepted extensions: `.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`, `.svg`. Files are
read sorted by name (dotfiles skipped) and the deck picks `p²+p+1` of them at
random; the script errors out if the folder has too few. Filenames with spaces
are URL-escaped automatically.

Each image is drawn in a `size × size` box with `object-fit: contain`, so
non-square artwork keeps its aspect ratio and fits inside the box the layout
reserved for it. `--min-size` / `--max-size` therefore mean "image box side"
here rather than font size — bump them (and `--card-px`) up from the emoji
defaults, since detailed artwork needs more room than a glyph.

### Linking vs. embedding

By default the HTML references images by **relative path**, so `deck.html` must
stay next to the symbols folder (paths are recomputed relative to `--out`, so
writing the deck elsewhere still works — as long as both stay put).

`--embed` inlines every used image as a base64 data URI, giving one
self-contained file you can move or send anywhere. Only the images actually
selected get encoded, but base64 still adds ~33%, so a folder of phone photos
easily produces a 20 MB+ page that is slow to open and print. Downscaling the
sources first is worth it — they only ever render a few dozen px wide:

```bash
mogrify -resize 512x512 -strip symbols/*.png   # ImageMagick
```

### Using your own emoji set instead

Replace the `EMOJI_POOL` list near the top of `dobble_gen.py` with as many
emojis as your chosen `order` needs (`p²+p+1` distinct).

The deck generation (`generate_cards`) and placement (`place_symbols`) are
independent of how symbols are drawn — only `render_symbol_html` cares whether
a `Symbol` is `"text"` or `"image"`.
