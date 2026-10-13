#!/usr/bin/python3
"""Makes Classic 7's Plymouth theme (the start-up screen) into the folder given:

    make_theme.py /usr/share/plymouth/themes/classic7 [SPINNER_THEME_DIR]

Black, with four coloured lights circling slowly (frames for Plymouth's two-step plugin, which
loops them), and Plymouth's own text under them: "Starting Classic 7", "Shutting down...",
"Restarting...", or the update messages. The password prompt's pictures (for encrypted disks)
come from the spinner theme."""
import math
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

W, H = 310, 210
FRAMES = 60
LIGHTS = [(42, 112, 224), (60, 196, 60), (240, 192, 32), (224, 64, 48)]   # blue, green, yellow, red


def frame(i: int) -> Image.Image:
    img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    core = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd, cd = ImageDraw.Draw(glow), ImageDraw.Draw(core)
    cx, cy, rx, ry = W / 2, H / 2, 90, 43
    t = i / FRAMES
    for k, color in enumerate(LIGHTS):
        # each light runs a little ahead of the next, with a fading trail behind it
        for tail in range(14, -1, -1):
            a = 2 * math.pi * (t + k / len(LIGHTS)) - tail * 0.07
            depth = (math.sin(a) + 1) / 2              # 0 = far (top), 1 = near (bottom)
            x, y = cx + rx * math.cos(a), cy + ry * math.sin(a)
            r = 4.2 + 5.0 * depth - tail * 0.21
            alpha = int(255 * (1 - tail / 15) * (0.55 + 0.45 * depth))
            if r <= 0.5 or alpha <= 0:
                continue
            gd.ellipse((x - r * 3, y - r * 3, x + r * 3, y + r * 3), fill=color + (alpha // 3,))
            if tail == 0:
                cd.ellipse((x - r, y - r, x + r, y + r), fill=tuple(min(255, c + 90) for c in color) + (255,))
    glow = glow.filter(ImageFilter.GaussianBlur(8))
    img = Image.alpha_composite(img, glow)
    img = Image.alpha_composite(img, core.filter(ImageFilter.GaussianBlur(0.8)))
    return img.convert("RGB")


THEME = """[Plymouth Theme]
Name=Classic 7
Description=Starting Classic 7
ModuleName=two-step

[two-step]
Font=Noto Sans 12
TitleFont=Noto Sans 18
ImageDir={dir}
HorizontalAlignment=.5
VerticalAlignment=.44
TitleHorizontalAlignment=.5
TitleVerticalAlignment=.60
DialogHorizontalAlignment=.5
DialogVerticalAlignment=.70
WatermarkHorizontalAlignment=.5
WatermarkVerticalAlignment=.96
Transition=none
TransitionDuration=0.0
BackgroundStartColor=0x000000
BackgroundEndColor=0x000000
ProgressBarBackgroundColor=0x404040
ProgressBarForegroundColor=0xd0d0d0
MessageBelowAnimation=true

[boot-up]
UseEndAnimation=false
UseFirmwareBackground=false
Title=Starting Classic 7

[shutdown]
UseEndAnimation=false
UseFirmwareBackground=false
Title=Shutting down...

[reboot]
UseEndAnimation=false
UseFirmwareBackground=false
Title=Restarting...

[updates]
SuppressMessages=true
ProgressBarShowPercentComplete=true
UseProgressBar=true
UseFirmwareBackground=false
Title=Configuring updates
SubTitle=Do not turn off your computer

[system-upgrade]
SuppressMessages=true
ProgressBarShowPercentComplete=true
UseProgressBar=true
UseFirmwareBackground=false
Title=Upgrading Classic 7
SubTitle=Do not turn off your computer

[firmware-upgrade]
SuppressMessages=true
ProgressBarShowPercentComplete=true
UseProgressBar=true
UseFirmwareBackground=false
Title=Updating firmware
SubTitle=Do not turn off your computer
"""


def main() -> int:
    out = Path(sys.argv[1])
    spinner = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("/usr/share/plymouth/themes/spinner")
    out.mkdir(parents=True, exist_ok=True)
    for i in range(FRAMES):
        frame(i).save(out / f"throbber-{i + 1:04d}.png", optimize=True)
    # the password prompt and keyboard pictures
    for name in ("entry.png", "bullet.png", "lock.png", "capslock.png", "keyboard.png", "keymap-render.png", "box.png"):
        src = spinner / name
        if src.exists():
            shutil.copy2(src, out / name)
    (out / "classic7.plymouth").write_text(THEME.format(dir=str(out)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
