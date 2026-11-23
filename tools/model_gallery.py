"""Publish the Blender review images and verify the Season 1 spacecraft gallery."""

import argparse
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from parts import ROOT


def linked_images(root):
    gallery = (root / "docs/models").resolve()
    references = set()
    guide = root / "docs/season-1-model-review.md"
    for doc in (root / "README.md", guide):
        links = re.findall(r"\]\(([^)]+)\)", doc.read_text(encoding="utf-8"))
        for link in links:
            path = link.partition("#")[0]
            if not path or "://" in path:
                continue
            target = (doc.parent / path).resolve()
            if target.parent == gallery:
                references.add(target)
            elif doc == guide and not target.exists():
                raise ValueError(f"Missing gallery link in {doc.name}: {link}")
    return references


def review_images(root):
    references = linked_images(root)
    files = {p.resolve() for p in (root / "docs/models").iterdir() if p.is_file() and not p.name.startswith(".")}
    if not references or files != references:
        missing = sorted(p.name for p in references - files)
        unused = sorted(p.name for p in files - references)
        raise ValueError(f"Review gallery differs from documentation. Missing {missing}, unreferenced {unused}")
    return sorted(files)


def paired_view(renders, panels):
    from PIL import Image, ImageDraw, ImageOps
    from preview import font

    backdrop = (69, 69, 69)
    canvas = Image.new("RGB", (2440, 1040), backdrop)
    draw = ImageDraw.Draw(canvas)
    for name, label, left, right in panels:
        with Image.open(renders / (name + ".png")) as image:
            width, height = image.size
            if name == "jamestown-airlock-stairs" or name in ("jamestown-fairing", "jamestown-packed"):
                pad = int(width * 0.16)
                image = image.crop((pad, 0, width - pad, height))
            panel = ImageOps.contain(image.convert("RGB"), (right - left, 940), Image.Resampling.LANCZOS)
            background = panel.getpixel((1, 1))
            draw.rectangle((left, 0, right - 1, 1039), fill=background)
            canvas.paste(panel, ((left + right - panel.width) // 2, (940 - panel.height) // 2))
        draw.text(((left + right) / 2, 977), label, font=font(36), fill=(238, 240, 235), anchor="mm")
    return canvas


JAMESTOWN_VIEWS = {
    "jamestown-hardware": (("jamestown-airlock-stairs", "Detachable airlock", 0, 1090),
                           ("jamestown-raised", "Expansion height   2.60 m", 1090, 2440)),
    "jamestown-packed": (("jamestown-fairing", "Flight fairing", 0, 1220),
                         ("jamestown-packed", "Roof-stowed airlock", 1220, 2440)),
}


def publish(renders, kit):
    from PIL import Image

    gallery = ROOT / "docs/models"
    wanted = {p for p in linked_images(ROOT) if p.stem.startswith(kit + "-")}
    if not wanted:
        raise ValueError(f"No linked images for {kit}")
    # Finish all JPEGs before replacing an existing gallery or pruning its retired views.
    with TemporaryDirectory(dir=gallery.parent) as work:
        for target in wanted:
            image = paired_view(renders, JAMESTOWN_VIEWS[target.stem]) if target.stem in JAMESTOWN_VIEWS else Image.open(
                renders / (target.stem + ".png"))
            with image:
                image.convert("RGB").save(Path(work) / target.name, quality=94, subsampling=0, optimize=True)
        for target in wanted:
            (Path(work) / target.name).replace(target)
        for retired in set(gallery.glob(kit + "-*.jpg")) - wanted:
            retired.unlink()
    print(f"Published {len(wanted)} {kit} images. Verified {len(review_images(ROOT))} gallery files.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renders", type=Path, required=True)
    parser.add_argument("--kit", choices=("jamestown", "launchers", "soviet", "apollo", "lsam"), required=True)
    args = parser.parse_args()
    publish(args.renders, args.kit)
