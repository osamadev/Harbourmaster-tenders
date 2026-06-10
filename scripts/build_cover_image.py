"""Generate a 1920x1080 (16:9) cover image for the Harbourmaster project."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


W, H = 1920, 1080

# palette (matches the deck)
NAVY_DARK = (5, 14, 30)
NAVY = (11, 31, 58)
NAVY_MID = (18, 42, 75)
TEAL = (20, 184, 166)
TEAL_DIM = (10, 110, 100)
SLATE = (51, 65, 85)
LIGHT = (241, 245, 249)
GREY = (148, 163, 184)
WHITE = (255, 255, 255)
AMBER = (245, 158, 11)
ROSE = (225, 29, 72)
INDIGO = (79, 70, 229)
GREEN = (22, 163, 74)


# ----------------------- font loading -----------------------

def _try_fonts(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def font_bold(size: int) -> ImageFont.FreeTypeFont:
    return _try_fonts(
        [
            "C:/Windows/Fonts/segoeuib.ttf",
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/calibrib.ttf",
            "Arial Bold.ttf",
            "DejaVuSans-Bold.ttf",
        ],
        size,
    )


def font_regular(size: int) -> ImageFont.FreeTypeFont:
    return _try_fonts(
        [
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
            "Arial.ttf",
            "DejaVuSans.ttf",
        ],
        size,
    )


def font_mono(size: int) -> ImageFont.FreeTypeFont:
    return _try_fonts(
        [
            "C:/Windows/Fonts/consola.ttf",
            "C:/Windows/Fonts/cour.ttf",
            "DejaVuSansMono.ttf",
        ],
        size,
    )


# ----------------------- drawing helpers -----------------------

def vertical_gradient(size: tuple[int, int], top: tuple[int, int, int],
                      bottom: tuple[int, int, int]) -> Image.Image:
    w, h = size
    base = Image.new("RGB", (1, h))
    px = base.load()
    for y in range(h):
        t = y / max(1, h - 1)
        px[0, y] = (
            int(top[0] + (bottom[0] - top[0]) * t),
            int(top[1] + (bottom[1] - top[1]) * t),
            int(top[2] + (bottom[2] - top[2]) * t),
        )
    return base.resize((w, h))


def draw_glow(canvas: Image.Image, center: tuple[int, int],
              radius: int, color: tuple[int, int, int], alpha: int = 110) -> None:
    """Soft radial glow blob."""
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = center
    d.ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
              fill=(*color, alpha))
    layer = layer.filter(ImageFilter.GaussianBlur(radius // 2))
    canvas.alpha_composite(layer)


def rounded_rect(draw: ImageDraw.ImageDraw, box, radius: int,
                 fill=None, outline=None, width: int = 0) -> None:
    draw.rounded_rectangle(box, radius=radius, fill=fill,
                           outline=outline, width=width)


def text_size(draw: ImageDraw.ImageDraw, text: str,
              font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    return r - l, b - t


def draw_arrow(draw: ImageDraw.ImageDraw, x1, y1, x2, y2,
               color, width: int = 4, head: int = 14) -> None:
    draw.line((x1, y1, x2, y2), fill=color, width=width)
    angle = math.atan2(y2 - y1, x2 - x1)
    p1 = (x2 - head * math.cos(angle - math.pi / 7),
          y2 - head * math.sin(angle - math.pi / 7))
    p2 = (x2 - head * math.cos(angle + math.pi / 7),
          y2 - head * math.sin(angle + math.pi / 7))
    draw.polygon([(x2, y2), p1, p2], fill=color)


def pipeline_chip(draw: ImageDraw.ImageDraw, cx: int, cy: int,
                  w: int, h: int, label: str, sub: str,
                  fill: tuple[int, int, int],
                  font_label, font_sub) -> tuple[int, int]:
    box = (cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2)
    rounded_rect(draw, box, radius=18, fill=fill)
    # label
    lw, lh = text_size(draw, label, font_label)
    draw.text((cx - lw // 2, cy - lh - 2), label, fill=WHITE, font=font_label)
    # sub
    sw, sh = text_size(draw, sub, font_sub)
    draw.text((cx - sw // 2, cy + 6), sub, fill=LIGHT, font=font_sub)
    return box[0], box[2]


# ----------------------- composition -----------------------

def build(path: Path) -> Path:
    # base gradient
    bg = vertical_gradient((W, H), NAVY_DARK, NAVY_MID).convert("RGBA")

    # decorative glows
    draw_glow(bg, (260, 220), 420, TEAL, alpha=70)
    draw_glow(bg, (W - 280, H - 260), 520, INDIGO, alpha=55)
    draw_glow(bg, (W // 2, H // 2 + 60), 600, NAVY, alpha=30)

    # subtle dotted grid overlay (faint security-control vibe)
    grid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    step = 48
    for x in range(0, W, step):
        for y in range(0, H, step):
            gd.point((x, y), fill=(255, 255, 255, 18))
    bg.alpha_composite(grid)

    draw = ImageDraw.Draw(bg)

    # ---------------- header band ----------------
    # left teal accent bar
    draw.rectangle((0, 60, 14, 760), fill=TEAL)

    # eyebrow / category
    f_eyebrow = font_bold(34)
    draw.text((90, 110), "ENTERPRISE  ·  AGENTIC GOVERNANCE",
              fill=TEAL, font=f_eyebrow)

    # title
    f_title = font_bold(168)
    draw.text((86, 160), "Harbourmaster", fill=WHITE, font=f_title)

    # subtitle
    f_sub = font_regular(56)
    draw.text((90, 360),
              "A Workflow Governance Control Plane",
              fill=LIGHT, font=f_sub)

    # tagline (kicker)
    f_kicker = font_regular(38)
    draw.text((90, 440),
              "for agentic tender & contract review",
              fill=GREY, font=f_kicker)

    # divider
    draw.line((90, 530, 1830, 530), fill=(255, 255, 255, 60), width=2)

    # two-pillar tagline
    f_pillar_h = font_bold(34)
    f_pillar_b = font_regular(28)

    # pillar 1 — Inline Guard
    px = 90
    py = 570
    draw.rectangle((px, py, px + 8, py + 110), fill=ROSE)
    draw.text((px + 28, py - 4), "Inline Guard", fill=WHITE, font=f_pillar_h)
    draw.text((px + 28, py + 44),
              "LLM-as-judge — ALLOW · HUMAN_REVIEW · DENY",
              fill=GREY, font=f_pillar_b)

    # pillar 2 — Harbourmaster
    px = 990
    draw.rectangle((px, py, px + 8, py + 110), fill=TEAL)
    draw.text((px + 28, py - 4), "Harbourmaster", fill=WHITE, font=f_pillar_h)
    draw.text((px + 28, py + 44),
              "Workflow governor — risk-routed, policy-aware, human-in-loop",
              fill=GREY, font=f_pillar_b)

    # ---------------- bottom architecture band ----------------
    band_top = 770
    band_h = H - band_top
    # band background
    band = Image.new("RGBA", (W, band_h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    rounded_rect(bd, (0, 0, W, band_h), radius=0, fill=(7, 18, 36, 235))
    # teal top edge
    bd.rectangle((0, 0, W, 4), fill=TEAL)
    bg.alpha_composite(band, (0, band_top))

    draw = ImageDraw.Draw(bg)

    f_pipe_h = font_bold(28)
    f_pipe_lbl = font_bold(28)
    f_pipe_sub = font_regular(20)

    draw.text((90, band_top + 28),
              "REQUEST PATH  ·  every LLM call is governed end-to-end",
              fill=TEAL, font=f_pipe_h)

    # pipeline chips
    chip_y = band_top + 175
    chip_w = 270
    chip_h = 110
    gap = 70

    chips = [
        ("Guard", "guard.py", ROSE),
        ("Agent", "GovernedLLM", SLATE),
        ("Gemini API", "OpenAI-compat", NAVY),
        ("Phoenix", "Traces  :6006", INDIGO),
    ]
    total_w = chip_w * len(chips) + gap * (len(chips) - 1)
    start_x = (W - total_w) // 2 + chip_w // 2

    centers = []
    f_chip_l = font_bold(30)
    f_chip_s = font_regular(20)
    for i, (label, sub, color) in enumerate(chips):
        cx = start_x + i * (chip_w + gap)
        pipeline_chip(draw, cx, chip_y, chip_w, chip_h,
                      label, sub, color, f_chip_l, f_chip_s)
        centers.append(cx)

    # arrows between chips
    for i in range(len(chips) - 1):
        x1 = centers[i] + chip_w // 2 + 8
        x2 = centers[i + 1] - chip_w // 2 - 8
        draw_arrow(draw, x1, chip_y, x2, chip_y, color=TEAL, width=4, head=16)

    # right-side success chip
    succ_cx = centers[-1] + chip_w // 2 + 56 + 36
    succ_box = (succ_cx - 36, chip_y - 36, succ_cx + 36, chip_y + 36)
    draw.ellipse(succ_box, fill=GREEN)
    f_tick = font_bold(46)
    tw, th = text_size(draw, "✓", f_tick)
    draw.text((succ_cx - tw // 2, chip_y - th // 2 - 4), "✓",
              fill=WHITE, font=f_tick)

    # ---------------- footer stack strip ----------------
    f_stack = font_bold(22)
    f_stack_v = font_regular(22)
    stack_y = H - 70
    chips_stack = [
        ("MODELS", "Google Gemini 2.5"),
        ("ORCHESTRATION", "LangGraph"),
        ("OBSERVABILITY", "Arize Phoenix"),
        ("MEMORY", "Elasticsearch"),
        ("UI", "Streamlit"),
        ("RUNTIME", "Docker Compose"),
    ]
    # measure
    pieces = []
    for k, v in chips_stack:
        kw, _ = text_size(draw, k, f_stack)
        vw, _ = text_size(draw, v, f_stack_v)
        pieces.append((k, v, kw, vw))
    sep = "   ·   "
    sep_w, _ = text_size(draw, sep, f_stack_v)
    total = sum(kw + 10 + vw for _, _, kw, vw in pieces) + sep_w * (len(pieces) - 1)
    x = (W - total) // 2
    for i, (k, v, kw, vw) in enumerate(pieces):
        draw.text((x, stack_y), k, fill=TEAL, font=f_stack)
        x += kw + 10
        draw.text((x, stack_y), v, fill=LIGHT, font=f_stack_v)
        x += vw
        if i < len(pieces) - 1:
            draw.text((x, stack_y), sep, fill=GREY, font=f_stack_v)
            x += sep_w

    # ---------------- top-right badge ----------------
    badge_w, badge_h = 360, 80
    bx2 = W - 80
    bx1 = bx2 - badge_w
    by1 = 100
    by2 = by1 + badge_h
    rounded_rect(draw, (bx1, by1, bx2, by2), radius=14,
                 fill=TEAL, outline=TEAL, width=2)
    f_badge = font_bold(28)
    label = "TWO-LAYER GOVERNANCE"
    lw, lh = text_size(draw, label, f_badge)
    draw.text((bx1 + (badge_w - lw) // 2,
               by1 + (badge_h - lh) // 2 - 4),
              label, fill=NAVY_DARK, font=f_badge)

    # save
    out = bg.convert("RGB")
    out.save(path, "PNG", optimize=True)
    return path


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "assets" / "cover.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    saved = build(out)
    print(f"Saved {saved}  ({W}x{H})")
