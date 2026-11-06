#!/usr/bin/env python3
"""Generate Dobble-style card decks with custom (emoji) symbols.

A Dobble / Spot-It deck is built from a finite projective plane of prime order p:
  - cards:   p^2 + p + 1
  - symbols per card: p + 1
  - total distinct symbols: p^2 + p + 1
  - any two cards share exactly one symbol

Each card's symbols are laid out with evenly-spread random positions
(Poisson-disk-style rejection sampling), random size within a bounded
range, and random rotation. Output is a printable HTML page where emojis
render natively; print to PDF / cut out the cards.

Symbols come either from the built-in EMOJI_POOL or, with --symbols-dir,
from a directory of image files (PNG/JPG/WEBP/GIF/SVG).
"""

from __future__ import annotations

import argparse
import base64
import html
import math
import mimetypes
import os
import random
from dataclasses import dataclass, replace
from typing import List, Sequence, Tuple
from urllib.parse import quote


# --------------------------------------------------------------------------- #
# Projective plane card generation (prime order p)
# --------------------------------------------------------------------------- #

def is_prime(n: int) -> bool:
    if n < 2:
        return False
    if n % 2 == 0:
        return n == 2
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True


def generate_cards(p: int) -> List[List[int]]:
    """Return the deck for a projective plane of prime order p.

    Symbol indices, 0 .. p^2+p (total p^2+p+1):
      - affine points (x, y):  index = x * p + y            (x, y in 0..p-1)
      - vertical directions:  index = p*p + m              (m in 0..p-1)
      - point at infinity:     index = p*p + p
    """
    if not is_prime(p):
        raise ValueError(f"order p must be prime, got {p}")

    def affine(x: int, y: int) -> int:
        return x * p + y

    def point_m(m: int) -> int:
        return p * p + m

    infinity = p * p + p

    cards: List[List[int]] = []

    # 1) Non-vertical lines: slope m, intercept b -> {(x, m*x+b mod p)} U {m}
    for m in range(p):
        for b in range(p):
            card = [affine(x, (m * x + b) % p) for x in range(p)]
            card.append(point_m(m))
            cards.append(card)

    # 2) Vertical lines: x = c -> {(c, y)} U {infinity}
    for c in range(p):
        card = [affine(c, y) for y in range(p)]
        card.append(infinity)
        cards.append(card)

    # 3) Line at infinity: {m for all m} U {infinity}
    cards.append([point_m(m) for m in range(p)] + [infinity])

    assert len(cards) == p * p + p + 1
    for c in cards:
        assert len(c) == p + 1
    return cards


# --------------------------------------------------------------------------- #
# Placement: evenly-spread random positions via rejection sampling
# --------------------------------------------------------------------------- #

def place_symbols(
    count: int,
    card_size: float,
    min_size: float,
    max_size: float,
    margin: float,
    min_dist_factor: float,
    max_rotation: float,
    rng: random.Random,
    symbol_padding: float = 4.0,
) -> List[Tuple[float, float, float, float]]:
    """Return list of (x, y, size, rotation_deg) for `count` symbols.

    The card is a circle of radius card_size/2. To guarantee no symbol is
    clipped by the round edge, symbol centers are constrained to an inner
    circle of radius (card_size/2 - keepout), where keepout = margin +
    max_size/2. That no-place band is wider than the largest symbol's radius,
    so even the biggest symbol stays fully inside the card by at least
    `margin` px, regardless of where it is placed.

    Inter-symbol spacing is enforced by rejecting candidates closer than
    `(size + other_size) / 2 + symbol_padding` — a hard non-overlap
    constraint — plus `min_dist_factor * avg_size`, which is relaxed if the
    layout genuinely can't fit. The hard padding is never relaxed. Sizes are
    uniform-random in [min_size, max_size]; rotation uniform in
    [-max_rotation, max_rotation].
    """
    symbol_padding = max(0.0, symbol_padding)
    R = card_size / 2.0
    cx = cy = R
    keepout = margin + max_size / 2.0
    avail_radius = R - keepout
    if avail_radius <= 0:
        raise ValueError(
            f"Card too small for the requested sizes/margin: the available "
            f"radius for symbol centers is {avail_radius:.1f}px (need > 0). "
            f"Reduce --margin or --max-size, or raise --card-px."
        )

    base_min_dist = min_dist_factor * (min_size + max_size) / 2.0
    placed: List[Tuple[float, float, float, float]] = []
    min_dist = base_min_dist
    attempts_per_point = 400

    while len(placed) < count:
        success = False
        for _ in range(attempts_per_point):
            size = rng.uniform(min_size, max_size)
            # uniform random point inside the available inner circle
            ang = rng.uniform(0.0, 2.0 * math.pi)
            rad = avail_radius * math.sqrt(rng.random())
            x = cx + rad * math.cos(ang)
            y = cy + rad * math.sin(ang)
            ok = True
            for px, py, ps, _ in placed:
                clear = (size + ps) / 2.0 + symbol_padding
                if math.hypot(x - px, y - py) < min_dist + clear:
                    ok = False
                    break
            if ok:
                rot = rng.uniform(-max_rotation, max_rotation)
                placed.append((x, y, size, rot))
                success = True
                break
        if not success:
            # can't fit with current spacing -> relax only the soft spacing
            if min_dist == 0.0:
                if attempts_per_point >= 4000:
                    raise ValueError(
                        f"Could not place {count} symbols of size "
                        f"[{min_size},{max_size}] on a {card_size}px card with "
                        f"margin {margin} and padding {symbol_padding}px. "
                        f"Reduce --order, --max-size, or --symbol-padding, or "
                        f"raise --card-px."
                    )
                attempts_per_point = 4000
            else:
                min_dist *= 0.85
                if min_dist < 0.05 * base_min_dist:
                    min_dist = 0.0
                    attempts_per_point = 4000
            placed = []

    return placed


# --------------------------------------------------------------------------- #
# Symbol pool (emojis for now) and rendering
# --------------------------------------------------------------------------- #

EMOJI_POOL: List[str] = [
    "🍎", "🍌", "🍇", "🍓", "🍒", "🍑", "🍍", "🥝", "🍉", "🥥",
    "🥕", "🌽", "🥦", "🍅", "🥑", "🍆", "🧄", "🧅", "🥔", "🌶️",
    "🍞", "🧀", "🥚", "🥓", "🍔", "🍟", "🍕", "🌭", "🥪", "🌮",
    "🍣", "🍩", "🍪", "🎂", "🍰", "🍫", "🍬", "🍭", "🍿", "🥨",
    "☕", "🍵", "🥤", "🍺", "🍷", "🥃", "🍸", "🍾", "🧊", "🥛",
    "🐶", "🐱", "🐭", "🐹", "🐰", "🦊", "🐻", "🐼", "🐨", "🐯",
    "🦁", "🐮", "🐷", "🐸", "🐵", "🐔", "🐧", "🐦", "🦆", "🦉",
    "🦇", "🐺", "🐗", "🐴", "🦄", "🐝", "🐛", "🦋", "🐌", "🐞",
    "🐢", "🐍", "🦎", "🐙", "🦑", "🦀", "🐠", "🐟", "🐬", "🐳",
    "🌵", "🌴", "🌲", "🌳", "🌿", "🍀", "🌷", "🌹", "🌺", "🌻",
    "🌼", "🍁", "🍄", "🌍", "🌙", "⭐", "🌟", "✨", "⚡", "🔥",
    "❄️", "☀️", "☁️", "🌈", "⛄", "🌊", "⚽", "🏀", "🏈", "⚾",
]

# Deduplicate while preserving order.
EMOJI_POOL = list(dict.fromkeys(EMOJI_POOL))

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")


@dataclass(frozen=True)
class Symbol:
    """One drawable symbol: either a text glyph or an image source."""
    kind: str         # "text" | "image"
    value: str        # emoji character, or an <img> src (relative URL or data URI)
    path: str = ""    # for images: the source file on disk


def emoji_pool() -> List[Symbol]:
    return [Symbol("text", e) for e in EMOJI_POOL]


def _data_uri(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as f:
        return f"data:{mime};base64,{base64.b64encode(f.read()).decode('ascii')}"


def image_pool(symbols_dir: str, out_path: str) -> List[Symbol]:
    """Load image symbols from a directory, sorted by filename.

    The src is a path relative to the output HTML file, so the deck must stay
    next to the symbols dir; `embed_images` swaps that for inline data URIs.
    """
    if not os.path.isdir(symbols_dir):
        raise ValueError(f"--symbols-dir is not a directory: {symbols_dir}")

    names = sorted(n for n in os.listdir(symbols_dir)
                   if n.lower().endswith(IMAGE_EXTS) and not n.startswith("."))
    if not names:
        raise ValueError(f"No image files ({', '.join(IMAGE_EXTS)}) in {symbols_dir}")

    out_dir = os.path.dirname(os.path.abspath(out_path))
    pool = []
    for n in names:
        path = os.path.join(symbols_dir, n)
        rel = os.path.relpath(os.path.abspath(path), out_dir)
        # URL-quote so spaces etc. in filenames survive; keep path separators
        pool.append(Symbol("image", quote(rel.replace(os.sep, "/")), path))
    return pool


def embed_images(symbols: Sequence[Symbol]) -> List[Symbol]:
    """Inline each image as a base64 data URI (self-contained but much larger).

    Applied after selection so only the images actually used get encoded.
    """
    return [replace(s, value=_data_uri(s.path)) if s.kind == "image" else s
            for s in symbols]


def assign_symbols(cards: List[List[int]], pool: Sequence[Symbol],
                   rng: random.Random) -> List[Symbol]:
    """Map every distinct symbol index to a symbol from the pool."""
    indices = sorted({i for card in cards for i in card})
    needed = len(indices)
    if len(pool) < needed:
        raise ValueError(
            f"Symbol pool too small: need {needed} distinct symbols for this "
            f"deck, pool has {len(pool)}."
        )
    # sample (not truncate-then-shuffle) so a larger pool gets fully used
    return rng.sample(list(pool), needed)


# --------------------------------------------------------------------------- #
# HTML rendering
# --------------------------------------------------------------------------- #

HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  @page {{ size: {page_w_mm}mm {page_h_mm}mm; margin: {page_margin_mm}mm; }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: "Apple Color Emoji", "Segoe UI Emoji", "Noto Color Emoji",
                 "Twemoji Mozilla", "EmojiOne Color", sans-serif;
    background: {card_bg};
    display: flex; flex-wrap: wrap; gap: 8px;
    padding: 8px;
  }}
  .card {{
    position: relative;
    width: {card_px}px;
    height: {card_px}px;
    background: {card_bg};
    border: {border};
    border-radius: 50%;
    overflow: hidden;
    box-shadow: {card_shadow};
    break-inside: avoid;
  }}
  .sym {{
    position: absolute;
    transform-origin: center;
    line-height: 1;
    user-select: none;
    white-space: nowrap;
  }}
  img.sym {{
    /* size is a square box; contain keeps each image's aspect ratio inside it */
    object-fit: contain;
    -webkit-user-drag: none;
  }}
  /* cutting guide: sits on top of the symbols, marks the exact card center */
  .center-dot {{
    position: absolute;
    left: 50%; top: 50%;
    width: {dot_px}px; height: {dot_px}px;
    margin: {dot_offset_px}px 0 0 {dot_offset_px}px;
    border-radius: 50%;
    background: {dot_color};
  }}
  @media print {{
    body {{ gap: 0; padding: 0; }}
    .card {{ box-shadow: none; }}
    /* keep image/background colors when printing */
    * {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  }}
</style>
</head>
<body>
{cards_html}
</body>
</html>
"""


def render_symbol_html(sym: Symbol, x: float, y: float, size: float, rot: float) -> str:
    """Emit one absolutely-positioned symbol, centered on (x, y)."""
    pos = (f'left:{x:.2f}px; top:{y:.2f}px;'
           f' transform:translate(-50%,-50%) rotate({rot:.1f}deg);')
    if sym.kind == "image":
        return (f'<img class="sym" src="{html.escape(sym.value, quote=True)}" alt=""'
                f' style="{pos} width:{size:.1f}px; height:{size:.1f}px;">')
    return (f'<span class="sym" style="{pos} font-size:{size:.1f}px;">'
            f'{html.escape(sym.value)}</span>')


def render_card_html(
    card_indices: List[int],
    symbol_map: List[Symbol],
    card_px: int,
    min_size: float,
    max_size: float,
    margin: float,
    min_dist_factor: float,
    max_rotation: float,
    rng: random.Random,
    center_dot: bool = True,
    symbol_padding: float = 4.0,
) -> str:
    placements = place_symbols(
        count=len(card_indices),
        card_size=card_px,
        min_size=min_size,
        max_size=max_size,
        margin=margin,
        min_dist_factor=min_dist_factor,
        max_rotation=max_rotation,
        rng=rng,
        symbol_padding=symbol_padding,
    )
    # shuffle which symbol goes to which slot so the layout isn't tied to index order
    order = list(range(len(card_indices)))
    rng.shuffle(order)
    parts = []
    for slot, idx in enumerate(order):
        x, y, size, rot = placements[slot]
        parts.append(render_symbol_html(symbol_map[card_indices[idx]], x, y, size, rot))
    if center_dot:
        parts.append('<div class="center-dot"></div>')
    return f'<div class="card">{"".join(parts)}</div>'


def build_html(
    cards: List[List[int]],
    symbol_map: List[Symbol],
    cfg: argparse.Namespace,
    rng: random.Random,
) -> str:
    cards_html = "\n".join(
        render_card_html(
            card,
            symbol_map,
            card_px=cfg.card_px,
            min_size=cfg.min_size,
            max_size=cfg.max_size,
            margin=cfg.margin,
            min_dist_factor=cfg.min_dist,
            max_rotation=cfg.max_rotation,
            rng=rng,
            center_dot=cfg.center_dot > 0,
            symbol_padding=cfg.symbol_padding,
        )
        for card in cards
    )
    # A4-ish page; tweak as needed for your printer
    page_w_mm, page_h_mm = 210, 297
    return HTML_TEMPLATE.format(
        title=f"Dobble deck (order {cfg.order}, {len(cards)} cards)",
        page_w_mm=page_w_mm,
        page_h_mm=page_h_mm,
        page_margin_mm=10,
        card_px=cfg.card_px,
        card_bg=cfg.card_bg,
        border="none" if cfg.borderless else cfg.card_border,
        # the on-screen shadow would still draw a card outline, so drop it too
        card_shadow="none" if cfg.borderless else "0 2px 6px rgba(0,0,0,.25)",
        dot_px=f"{cfg.center_dot:.2f}",
        dot_offset_px=f"{-cfg.center_dot / 2:.2f}",
        dot_color=cfg.center_dot_color,
        cards_html=cards_html,
    )


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Generate a Dobble-style deck (HTML).")
    ap.add_argument("--order", "-p", type=int, default=7,
                    help="prime order p of the projective plane (default 7 -> "
                         "57 cards, 8 symbols each). Smaller primes: 2,3,5,7,11...")
    ap.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    ap.add_argument("--out", "-o", default="deck.html", help="output HTML file")
    ap.add_argument("--symbols-dir", default=None,
                    help="directory of image symbols (png/jpg/webp/gif/svg) to use "
                         "instead of the built-in emoji pool")
    ap.add_argument("--embed", action="store_true",
                    help="inline images as base64 data URIs (self-contained HTML, "
                         "much bigger); default is relative paths to --symbols-dir")
    ap.add_argument("--card-px", type=int, default=320, help="card diameter in px")
    ap.add_argument("--min-size", type=float, default=28.0,
                    help="min symbol size px (font size, or image box side)")
    ap.add_argument("--max-size", type=float, default=52.0,
                    help="max symbol size px (font size, or image box side)")
    ap.add_argument("--margin", type=float, default=14.0,
                    help="empty band inside the round card edge, in px; symbols "
                         "are kept fully inside the circle by at least this much")
    ap.add_argument("--min-dist", type=float, default=0.35,
                    help="extra spacing between symbols as a fraction of avg size")
    ap.add_argument("--symbol-padding", type=float, default=4.0,
                    help="hard minimum empty gap between symbol boxes in px; "
                         "never relaxed, so symbols cannot overlap (default 4.0)")
    ap.add_argument("--max-rotation", type=float, default=180.0,
                    help="max rotation in degrees (symmetric +/-)")
    ap.add_argument("--center-dot", type=float, default=3.0,
                    help="diameter in px of the gray dot marking the card center "
                         "(cutting guide); 0 disables it")
    ap.add_argument("--center-dot-color", default="#9a9a9a",
                    help="color of the center dot")
    ap.add_argument("--card-bg", default="#fffdf5", help="card background color")
    ap.add_argument("--card-border", default="3px solid #d9c9a3", help="card border CSS")
    ap.add_argument("--borderless", action="store_true",
                    help="draw cards with no border (overrides --card-border)")
    return ap.parse_args()


def main() -> None:
    cfg = parse_args()
    rng = random.Random(cfg.seed)

    cards = generate_cards(cfg.order)
    if cfg.symbols_dir:
        pool = image_pool(cfg.symbols_dir, cfg.out)
        source = f"{len(pool)} images from {cfg.symbols_dir}"
    else:
        pool = emoji_pool()
        source = f"{len(pool)} built-in emojis"
    symbol_map = assign_symbols(cards, pool, rng)
    if cfg.embed:
        symbol_map = embed_images(symbol_map)

    print(f"Order {cfg.order}: {len(cards)} cards, {cfg.order + 1} symbols/card, "
          f"{len(symbol_map)} distinct symbols ({source}).")

    html_doc = build_html(cards, symbol_map, cfg, rng)
    with open(cfg.out, "w", encoding="utf-8") as f:
        f.write(html_doc)
    print(f"Wrote {cfg.out}  ({len(html_doc)} bytes)")


if __name__ == "__main__":
    main()
