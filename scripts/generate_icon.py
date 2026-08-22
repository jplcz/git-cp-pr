#!/usr/bin/env python3
"""Generate the PNG icon used by the Tkinter window from icon.svg."""

import argparse
from pathlib import Path

try:
    import cairosvg
    from PIL import Image
except ImportError as error:
    raise SystemExit("Install developer requirements with: python3 -m pip install -r scripts/requirements-screenshots.txt") from error


PROJECT_DIR = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a Tk-compatible PNG icon from icon.svg.")
    parser.add_argument("--source", type=Path, default=PROJECT_DIR / "icon.svg")
    parser.add_argument("--output", type=Path, default=PROJECT_DIR / "icon.png")
    parser.add_argument("--ico-output", type=Path, default=PROJECT_DIR / "icon.ico")
    parser.add_argument("--size", type=int, default=256)
    args = parser.parse_args()

    if args.size < 16:
        parser.error("--size must be at least 16 pixels")
    if not args.source.is_file():
        parser.error(f"SVG source not found: {args.source}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    cairosvg.svg2png(
        url=str(args.source),
        write_to=str(args.output),
        output_width=args.size,
        output_height=args.size,
    )
    with Image.open(args.output) as image:
        image.save(args.ico_output, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (256, 256)])
    print(f"Wrote {args.output}")
    print(f"Wrote {args.ico_output}")


if __name__ == "__main__":
    main()