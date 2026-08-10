"""Draw packaging/icon.ico — a pin on a globe.

Run once with any Python that has Pillow (the project venv does); the .ico is
committed, so building the installer needs nothing but the standard library.

    venv\\Scripts\\python.exe packaging\\gen_icon.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 1024  # drawn large, downsampled per icon size for clean edges
GLOBE = (46, 125, 50)
GLOBE_DARK = (27, 94, 32)
OCEAN_LINE = (255, 255, 255, 90)
PIN = (198, 40, 40)
SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]


def draw() -> Image.Image:
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)

    margin = SIZE * 0.06
    box = (margin, margin, SIZE - margin, SIZE - margin)
    pen.ellipse(box, fill=GLOBE)

    # Latitude lines, then meridians as progressively narrower ellipses.
    radius = (SIZE - 2 * margin) / 2
    centre = SIZE / 2
    for fraction in (-0.55, -0.2, 0.2, 0.55):
        offset = radius * fraction
        half_width = radius * (1 - fraction**2) ** 0.5
        pen.line(
            (centre - half_width, centre + offset, centre + half_width, centre + offset),
            fill=OCEAN_LINE,
            width=int(SIZE * 0.018),
        )
    for fraction in (0.32, 0.68):
        half_width = radius * fraction
        pen.ellipse(
            (centre - half_width, margin, centre + half_width, SIZE - margin),
            outline=OCEAN_LINE,
            width=int(SIZE * 0.018),
        )
    pen.ellipse(box, outline=GLOBE_DARK, width=int(SIZE * 0.02))

    # The pin: teardrop head plus tip, sitting off-centre so it reads at 16px.
    pin_centre = (SIZE * 0.62, SIZE * 0.38)
    head = SIZE * 0.17
    pen.ellipse(
        (
            pin_centre[0] - head,
            pin_centre[1] - head,
            pin_centre[0] + head,
            pin_centre[1] + head,
        ),
        fill=PIN,
    )
    pen.polygon(
        [
            (pin_centre[0] - head * 0.72, pin_centre[1] + head * 0.66),
            (pin_centre[0] + head * 0.72, pin_centre[1] + head * 0.66),
            (pin_centre[0], pin_centre[1] + head * 2.05),
        ],
        fill=PIN,
    )
    pen.ellipse(
        (
            pin_centre[0] - head * 0.34,
            pin_centre[1] - head * 0.34,
            pin_centre[0] + head * 0.34,
            pin_centre[1] + head * 0.34,
        ),
        fill=(255, 255, 255),
    )
    return image


if __name__ == "__main__":
    target = Path(__file__).with_name("icon.ico")
    draw().save(target, format="ICO", sizes=SIZES)
    print(f"wrote {target} ({target.stat().st_size} bytes)")
