#!/usr/bin/env python3
"""Cắt lại một video với đoạn bỏ do mình chỉ định (dùng khi QC thấy máy cắt lệch).

    python recut.py <video gốc> <thư mục xuất> --cut 12.70-end [--cut 2.0-3.5 ...]
    python recut.py <video gốc> <thư mục xuất> --keep-until 12.70     # = --cut 12.70-end

Thời gian tính bằng giây trên video GỐC. Ghi đè file cùng tên trong thư mục xuất
(chính là bản máy đã xuất sai của video này).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cat_tutorial as c  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("out_dir")
    ap.add_argument("--cut", action="append", default=[], help="đoạn bỏ dạng a-b, b có thể là 'end'")
    ap.add_argument("--keep-until", type=float)
    a = ap.parse_args()
    src = Path(a.video)
    info = c.probe(src)
    segs = []
    for s in a.cut:
        x, y = s.split("-", 1)
        segs.append((float(x), info["duration"] if y.strip() == "end" else float(y)))
    if a.keep_until is not None:
        segs.append((a.keep_until, info["duration"]))
    dst = c.export(src, Path(a.out_dir), c.merge(segs), info)
    print(dst, f"giữ {sum(e - s for s, e in c.keeps_from(segs, info['duration'])):.2f}s / {info['duration']:.2f}s")


if __name__ == "__main__":
    main()
