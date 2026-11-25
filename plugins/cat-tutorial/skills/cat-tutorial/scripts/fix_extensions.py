#!/usr/bin/env python3
"""Sửa video bị mất đuôi .mp4 (vd tải nhiều file từ Google Drive: zip cắt tên dài -> tên kết thúc bằng '._').

    python fix_extensions.py <thư mục> [...] [--dry-run]

- Chỉ đổi tên file mà NỘI DUNG là video (đọc header MP4/MOV/MKV), bỏ qua file khác.
- Không bao giờ ghi đè: trùng tên thì thêm " (2)", " (3)"...
- Ghi nhật ký tên cũ -> tên mới ở ~/.cat-tutorial/rename_logs/ để hoàn tác.
"""
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cat_tutorial as c  # noqa: E402


def main(argv):
    dry = "--dry-run" in argv
    dirs = [Path(a).expanduser() for a in argv if a != "--dry-run"]
    if not dirs:
        print(__doc__)
        return 1
    logdir = Path.home() / ".cat-tutorial" / "rename_logs"
    logdir.mkdir(parents=True, exist_ok=True)
    log = logdir / f"doi_ten_{time.strftime('%Y%m%d_%H%M%S')}.tsv"
    total = 0
    rows = []
    for d in dirs:
        n = 0
        for f in sorted(d.iterdir()) if d.is_dir() else []:
            if not f.is_file() or f.name.startswith(".") or f.suffix.lower() in c.VIDEO_EXT or not c.is_video(f):
                continue
            new = f.with_name(c.out_name(f))
            k = 2
            while new.exists():
                new = f.with_name(c.out_name(f)[:-4] + f" ({k}).mp4")
                k += 1
            if not dry:
                f.rename(new)
            rows.append((str(f), str(new)))
            n += 1
        total += n
        print(f"{d.name}: {'sẽ đổi' if dry else 'đã đổi'} {n} file")
    if rows and not dry:
        with open(log, "w", newline="") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(["ten_cu", "ten_moi"])
            w.writerows(rows)
        print("Nhật ký hoàn tác:", log)
    print("Tổng:", total)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
