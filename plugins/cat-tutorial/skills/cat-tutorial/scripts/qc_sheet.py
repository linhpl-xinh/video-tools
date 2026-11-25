#!/usr/bin/env python3
"""Tạo ảnh soát mối cắt cho video ĐÃ XUẤT: mỗi hàng = các khung cuối cùng của 1 video
(và quanh mỗi mối nối nếu có cắt giữa), để mắt người/Claude soát xem còn lọt
điện thoại, vệt laser, icon máy quay, mép lật trang hay không.

    python qc_sheet.py <thư mục da_cat_tutorial> <ảnh ra.jpg> [--frames 10] [--per-sheet 8]

Mỗi ảnh tối đa --per-sheet video; nhiều hơn thì ghi <ảnh ra>_2.jpg, _3.jpg...
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cat_tutorial as c  # noqa: E402


def row_for(video: Path, n: int, h: int = 200):
    info = c.probe(video)
    fps = info["fps"] or 30
    fr = c.extract(video, max(0, info["duration"] - (n + 1) / fps), (n + 2) / fps, int(h * 9 / 16))
    fr = fr[-n:]
    if not fr:
        return None
    w = fr[0][1].width
    label_h = 22
    img = Image.new("RGB", (n * (w + 4) + 4, fr[0][1].height + label_h + 4), "white")
    d = ImageDraw.Draw(img)
    d.text((6, 4), f"{video.name[-60:]}  ({info['duration']:.2f}s)", fill="black", font=c._font(14))
    for i, (_, im) in enumerate(fr):
        img.paste(im.convert("RGB"), (4 + i * (w + 4), label_h))
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("out")
    ap.add_argument("--frames", type=int, default=10)
    ap.add_argument("--per-sheet", type=int, default=8)
    a = ap.parse_args()
    vids = sorted((f for f in Path(a.folder).iterdir() if c.is_video(f)),
                  key=lambda f: [int(x) if x.isdigit() else x for x in __import__("re").split(r"(\d+)", f.name)])
    rows = [r for r in (row_for(v, a.frames) for v in vids) if r]
    out = Path(a.out)
    for k in range(0, len(rows), a.per_sheet):
        chunk = rows[k:k + a.per_sheet]
        W = max(r.width for r in chunk)
        sheet = Image.new("RGB", (W, sum(r.height for r in chunk)), "white")
        y = 0
        for r in chunk:
            sheet.paste(r, (0, y))
            y += r.height
        p = out if k == 0 else out.with_name(f"{out.stem}_{k // a.per_sheet + 1}{out.suffix}")
        sheet.save(p, quality=85)
        print(p)


if __name__ == "__main__":
    main()
