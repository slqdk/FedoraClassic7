#!/usr/bin/env python3
"""
Draw the Classic 7 Aero wallpaper (our own abstract picture: deep blue, a soft light and a few
glowing ribbons) into system_files/usr/share/wallpapers/Classic7Aero.

    python3 tools/make_wallpaper.py

Needs numpy and Pillow (development only; the image is committed).
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "system_files/usr/share/wallpapers/Classic7Aero"
SIZES = [(1920, 1080), (2560, 1440)]


def draw(w: int, h: int, seed: int = 7) -> Image.Image:
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    nx, ny = x / w, y / h
    # base: navy at the top to a deep sky blue at the bottom
    top = np.array([6, 30, 78], np.float32)
    bottom = np.array([18, 92, 170], np.float32)
    t = np.clip(ny ** 1.2, 0, 1)[..., None]
    img = top * (1 - t) + bottom * t
    # a broad soft light, low and right of the middle
    d = np.sqrt(((nx - 0.62) * 1.25) ** 2 + ((ny - 0.66) * 1.7) ** 2)
    glow = np.exp(-(d / 0.42) ** 2)[..., None]
    img = img + glow * np.array([70, 150, 210], np.float32) * 0.85
    # a darker band from the upper left, for depth
    band = np.exp(-(((nx * 0.8 + ny * 0.5) - 0.28) / 0.22) ** 2)[..., None]
    img = img * (1 - 0.25 * band)
    base = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")

    # ribbons of light: smooth curves, blurred, added on top
    ribbons = np.zeros((h, w), np.float32)
    for k, (amp, freq, phase, y0, width, strength) in enumerate([
        (0.10, 1.10, 0.4, 0.70, 0.010, 1.00), (0.12, 0.95, 1.2, 0.74, 0.020, 0.55),
        (0.08, 1.30, 2.1, 0.66, 0.006, 0.85), (0.14, 0.80, 2.9, 0.80, 0.035, 0.35),
        (0.06, 1.60, 0.9, 0.61, 0.004, 0.65),
    ]):
        curve = y0 + amp * np.sin(nx * np.pi * freq + phase) * (0.4 + 0.6 * nx) - 0.18 * (nx - 0.5) ** 2
        dist = np.abs(ny - curve)
        fade = np.clip((nx - 0.02) / 0.35, 0, 1) * np.clip((1.02 - nx) / 0.25, 0, 1)
        ribbons += strength * np.exp(-(dist / width) ** 2) * fade
    rib = Image.fromarray(np.clip(ribbons * 255, 0, 255).astype(np.uint8), "L")
    rib = rib.filter(ImageFilter.GaussianBlur(radius=w / 900))
    soft = rib.filter(ImageFilter.GaussianBlur(radius=w / 120))
    r = np.asarray(rib, np.float32)[..., None] / 255
    s = np.asarray(soft, np.float32)[..., None] / 255
    light = np.array([200, 240, 255], np.float32)
    arr = np.asarray(base, np.float32)
    arr = arr + (255 - arr) * (r * 0.75 + s * 0.45) * (light / 255)

    # soft round lights in the bright part
    dots = np.zeros((h, w), np.float32)
    for _ in range(26):
        cx, cy = rng.uniform(0.35, 0.98) * w, rng.uniform(0.40, 0.95) * h
        rad = rng.uniform(0.006, 0.03) * w
        a = rng.uniform(0.05, 0.22)
        dd = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
        dots += a * np.clip(1 - dd / rad, 0, 1) ** 0.6
    dots_img = Image.fromarray(np.clip(dots * 255, 0, 255).astype(np.uint8), "L").filter(
        ImageFilter.GaussianBlur(radius=w / 700))
    dd = np.asarray(dots_img, np.float32)[..., None] / 255
    arr = arr + (255 - arr) * dd * 0.8

    # darker corners, and a little noise against banding
    vig = np.sqrt((nx - 0.55) ** 2 + (ny - 0.55) ** 2)
    arr = arr * (1 - 0.35 * np.clip(vig - 0.35, 0, 1)[..., None])
    arr = arr + rng.normal(0, 0.9, arr.shape)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")


def main():
    images = OUT / "contents" / "images"
    images.mkdir(parents=True, exist_ok=True)
    for w, h in SIZES:
        path = images / f"{w}x{h}.jpg"
        draw(w, h).save(path, quality=90, optimize=True, progressive=True)
        print("wrote", path.relative_to(REPO), path.stat().st_size)
    (OUT / "metadata.json").write_text(json.dumps({
        "KPlugin": {"Authors": [{"Name": "Classic7 project"}], "Id": "Classic7Aero",
                    "License": "Apache-2.0", "Name": "Classic 7 Aero"}}, indent=4) + "\n")
    draw(400, 225).save(OUT / "contents" / "screenshot.png")


if __name__ == "__main__":
    main()
