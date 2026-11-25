#!/usr/bin/env python3
"""Tự nhận diện và cắt bỏ đoạn in-app / tutorial khỏi video.

Cách dùng:
    python cat_tutorial.py <thư mục hoặc file video> [...]

Kết quả: <thư mục>/da_cat_tutorial/<tên gốc>.mp4 + bao_cao.html.

Quy trình cho mỗi video:
  1. Lấy khung thưa (2 khung/giây) -> Claude đánh dấu khung nào là in-app/tutorial.
  2. Ở mỗi ranh giới, lấy từng khung gốc trong ~0,8 giây -> Claude chọn đúng khung
     bắt đầu (hoặc kết thúc) hiệu ứng chuyển cảnh.
  3. Soát lại: xem phóng to các khung sát điểm cắt, lọt khung nào thì cắt thêm.
  4. Cắt bằng ffmpeg, giảm dần tiếng ở mỗi mối cắt, xuất báo cáo.
"""
from __future__ import annotations

import base64
import concurrent.futures as cf
import html
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))  # để nạp local_detect.py cạnh file này

# local = nhận diện trên máy (miễn phí, không cần key); claude = gọi Claude API (cần ANTHROPIC_API_KEY)
BACKEND = os.environ.get("CAT_TUTORIAL_BACKEND", "local")
MODEL = os.environ.get("CAT_TUTORIAL_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("CAT_TUTORIAL_EFFORT", "medium")
WORKERS = int(os.environ.get("CAT_TUTORIAL_WORKERS", "4"))
OUT_DIRNAME = os.environ.get("CAT_TUTORIAL_OUTDIR", "da_cat_tutorial")
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}


def is_video(p: Path) -> bool:
    """Nhận video theo NỘI DUNG file, không chỉ theo đuôi.
    Google Drive khi nén zip hay cắt tên dài (emoji, chữ Nga...) làm mất đuôi .mp4 -> tên kết thúc bằng '._'."""
    if p.name.startswith(".") or not p.is_file():
        return False
    if p.suffix.lower() in VIDEO_EXT:
        return True
    try:
        with open(p, "rb") as f:
            head = f.read(12)
    except OSError:
        return False
    return head[4:8] == b"ftyp" or head[:4] == b"\x1a\x45\xdf\xa3"  # MP4/MOV hoặc MKV/WebM


def out_name(src: Path) -> str:
    """Tên file xuất: bỏ đuôi hỏng ('._', '..') rồi gắn '.mp4'; giữ dưới giới hạn 255 byte của macOS."""
    stem = src.stem if src.suffix.lower() in VIDEO_EXT or src.suffix in ("._", "._ ") else src.name
    stem = re.sub(r"[.\s_]+$", "", stem) or "video"
    while len((stem + ".mp4").encode()) > 240:
        stem = stem[:-1]
    return stem + ".mp4"
MIN_KEEP = 0.3  # bỏ đoạn giữ lại ngắn hơn 0,3s (thường là vụn chuyển cảnh)

DEFINITION = """\
Video là clip quảng cáo/khoe hiệu ứng ảnh-video AI (thường đăng TikTok/Reels).
"Đoạn TUTORIAL / IN-APP" (cần CẮT) gồm:
- Quay hoặc ghi màn hình điện thoại/máy tính bảng/máy tính đang hiện giao diện app
  (TikTok, CapCut, Instagram, trang mẫu template, thư viện ảnh, bảng chia sẻ, nút bấm...),
  kể cả có tay/bút cảm ứng bấm vào.
- Màn hình logo/splash của app (vd CapCut ID), ảnh chụp trang cá nhân/kêu gọi vào profile,
  mũi tên chỉ link, hướng dẫn từng bước.
- Cảnh mồi dẫn vào phần hướng dẫn nằm sát ngay trước nó (vd câu "I'll show you how" trên cảnh khác).
- MỌI khung hình của hiệu ứng chuyển cảnh dẫn vào hoặc đi ra khỏi phần trên
  (vệt laser, icon máy quay, lật trang, nhoè chuyển động, cắt chéo...) – dù chỉ lộ một mép nhỏ.
"Đoạn NỘI DUNG" (GIỮ) là phần khoe kết quả: ảnh/video thành phẩm full màn hình,
cảnh hook có người thật, chuyển cảnh giữa các ảnh thành phẩm với nhau."""

_client = None


def get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(max_retries=4)
    return _client


# ---------------------------------------------------------------- ffmpeg helpers
def run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def probe(path: Path) -> dict:
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    info = json.loads(r.stdout)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    num, den = v.get("avg_frame_rate", "30/1").split("/")
    fps = float(num) / float(den) if float(den) else 30.0
    return {
        "duration": float(info["format"]["duration"]),
        "fps": fps,
        "has_audio": any(s["codec_type"] == "audio" for s in info["streams"]),
        "width": int(v["width"]),
        "height": int(v["height"]),
    }


def extract(path: Path, start: float, dur: float, width: int, fps: float | None = None) -> list[tuple[float, Image.Image]]:
    """Trả về [(thời điểm tuyệt đối, ảnh)] trong [start, start+dur)."""
    start = max(0.0, start)
    with tempfile.TemporaryDirectory() as td:
        vf = (f"fps={fps}," if fps else "") + f"scale={width}:-2,showinfo"
        cmd = ["ffmpeg", "-hide_banner", "-copyts", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}",
               "-i", str(path), "-an", "-vf", vf, "-fps_mode", "passthrough",
               "-q:v", "3", f"{td}/%05d.jpg"]
        r = run(cmd)
        times = [float(m) for m in re.findall(r"pts_time:([0-9.]+)", r.stderr)]
        files = sorted(Path(td).glob("*.jpg"))
        out = []
        for t, f in zip(times, files):
            img = Image.open(f)
            img.load()
            out.append((t, img))
    return out


# ---------------------------------------------------------------- image grids
def _font(size: int):
    for p in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
              "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def grid(frames: list[Image.Image], cols: int, labels: list[str]) -> Image.Image:
    w, h = frames[0].size
    rows = (len(frames) + cols - 1) // cols
    pad = 6
    sheet = Image.new("RGB", (cols * (w + pad) + pad, rows * (h + pad) + pad), "white")
    d = ImageDraw.Draw(sheet)
    font = _font(max(16, w // 6))
    for i, (img, lab) in enumerate(zip(frames, labels)):
        x = pad + (i % cols) * (w + pad)
        y = pad + (i // cols) * (h + pad)
        sheet.paste(img.convert("RGB").resize((w, h)), (x, y))
        tb = d.textbbox((0, 0), lab, font=font)
        d.rectangle([x, y, x + tb[2] + 8, y + tb[3] + 6], fill="black")
        d.text((x + 4, y + 2), lab, fill="yellow", font=font)
    return sheet


def b64(img: Image.Image) -> dict:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                         "data": base64.standard_b64encode(buf.getvalue()).decode()}}


# ---------------------------------------------------------------- Claude
def ask(images: list[Image.Image], prompt: str, schema: dict) -> dict:
    content = [b64(i) for i in images] + [{"type": "text", "text": prompt}]
    resp = get_client().beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": schema}},
        system=DEFINITION,
        messages=[{"role": "user", "content": content}],
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"Claude từ chối: {getattr(resp.stop_details, 'explanation', '')}")
    text = next(b.text for b in resp.content if b.type == "text")
    return json.loads(text)


COARSE_SCHEMA = {
    "type": "object",
    "properties": {
        "tutorial_frames": {"type": "array", "items": {"type": "integer"},
                            "description": "Số thứ tự các khung thuộc đoạn tutorial/in-app (kể cả khung đang chuyển cảnh)."},
        "note": {"type": "string", "description": "Ghi chú ngắn bằng tiếng Việt về video, vd lời/chữ hướng dẫn đè lên cảnh nội dung."},
    },
    "required": ["tutorial_frames", "note"],
    "additionalProperties": False,
}

EDGE_SCHEMA = {
    "type": "object",
    "properties": {"index": {"type": "integer"}, "reason": {"type": "string"}},
    "required": ["index", "reason"],
    "additionalProperties": False,
}

FLAG_SCHEMA = {
    "type": "object",
    "properties": {"bad_frames": {"type": "array", "items": {"type": "integer"}}},
    "required": ["bad_frames"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------- pipeline
@dataclass
class Result:
    src: Path
    dst: Path | None = None
    duration: float = 0
    cuts: list[tuple[float, float]] = field(default_factory=list)  # đoạn đã bỏ
    keeps: list[tuple[float, float]] = field(default_factory=list)
    note: str = ""
    error: str = ""
    thumbs: list[tuple[str, Image.Image]] = field(default_factory=list)


def ranges(idx: list[int]) -> list[tuple[int, int]]:
    idx = sorted(set(idx))
    out = []
    for i in idx:
        if out and i == out[-1][1] + 1:
            out[-1] = (out[-1][0], i)
        else:
            out.append((i, i))
    return out


def find_segments(path: Path, info: dict, log) -> tuple[list[tuple[float, float]], str]:
    dur, fps = info["duration"], info["fps"]
    step_fps = 2 if dur <= 90 else 1
    frames = extract(path, 0, dur, 150, fps=step_fps)
    if not frames:
        raise RuntimeError("không đọc được khung hình")
    times = [t for t, _ in frames]
    tutorial: list[int] = []
    notes = []
    per = 40  # khung mỗi lượt hỏi
    for off in range(0, len(frames), per):
        chunk = frames[off:off + per]
        sheet = grid([im for _, im in chunk], 10, [str(off + i) for i in range(len(chunk))])
        res = ask([sheet],
                  f"Đây là các khung lấy mỗi {1/step_fps:g}s từ video dài {dur:.1f}s, đánh số theo thứ tự thời gian "
                  f"(khung {off}..{off+len(chunk)-1}). Liệt kê số các khung thuộc đoạn TUTORIAL/IN-APP.",
                  COARSE_SCHEMA)
        tutorial += [i for i in res["tutorial_frames"] if off <= i < off + len(chunk)]
        if res["note"]:
            notes.append(res["note"])
    log(f"  thô: khung tutorial {ranges(tutorial)}")

    frame_dt = 1 / fps
    segs = []
    for a, b in ranges(tutorial):
        # điểm bắt đầu: nằm trong (times[a-1], times[a]]
        if a == 0:
            s = 0.0
        else:
            s = refine(path, times[a - 1], times[a] + frame_dt, fps, "start", log)
        if b == len(times) - 1:
            e = dur
        else:
            e = refine(path, times[b], times[b + 1] + frame_dt, fps, "end", log)
        if e > s:
            segs.append((s, e))
    return segs, " ".join(notes)


def window_frames(path: Path, lo: float, hi: float, fps: float, width: int):
    """Mọi khung gốc trong [lo, hi], tối đa 30 khung (video 60fps thì lấy cách 1)."""
    fr = extract(path, lo, hi - lo, width)
    if len(fr) > 30:
        k = (len(fr) + 29) // 30
        fr = fr[::k]
    return fr


def refine(path: Path, lo: float, hi: float, fps: float, kind: str, log) -> float:
    lo -= 0.15
    fr = window_frames(path, lo, hi, fps, 200)
    if not fr:
        return hi
    sheet = grid([im for _, im in fr], 10, [str(i) for i in range(len(fr))])
    if kind == "start":
        q = ("Các khung liên tiếp quanh chỗ video chuyển từ NỘI DUNG sang TUTORIAL. "
             "Trả về index của khung ĐẦU TIÊN có bất kỳ dấu hiệu nào của hiệu ứng chuyển cảnh hoặc nội dung "
             "tutorial (dù chỉ một mép, một vệt sáng, một icon nhỏ). Nếu tất cả đều sạch, trả về số khung.")
    else:
        q = ("Các khung liên tiếp quanh chỗ video chuyển từ TUTORIAL quay lại NỘI DUNG. "
             "Trả về index của khung ĐẦU TIÊN hoàn toàn sạch (không còn chút hiệu ứng chuyển cảnh hay "
             "tutorial nào). Nếu không có khung sạch, trả về số khung.")
    idx = ask([sheet], q, EDGE_SCHEMA)["index"]
    idx = max(0, min(idx, len(fr)))
    t = fr[idx][0] if idx < len(fr) else fr[-1][0] + 1 / fps
    log(f"  tinh {kind}: {t:.3f}s")
    return t


def verify(path: Path, segs: list[tuple[float, float]], info: dict, log) -> list[tuple[float, float]]:
    """Soát phóng to các khung sát mép đoạn giữ lại; lọt khung bẩn thì nới đoạn cắt."""
    fps, dur = info["fps"], info["duration"]
    n = 8
    out = []
    for s, e in segs:
        for _ in range(3):
            if s <= 0:
                break
            fr = extract(path, max(0, s - n / fps - 0.01), n / fps + 0.005, 320)
            fr = [x for x in fr if x[0] < s - 1e-4][-n:]
            if not fr:
                break
            bad = ask([grid([im for _, im in fr], n, [str(i) for i in range(len(fr))])],
                      "Đây là các khung CUỐI CÙNG được giữ lại ngay trước chỗ cắt bỏ đoạn tutorial. "
                      "Liệt kê index các khung có BẤT KỲ dấu hiệu nào của hiệu ứng chuyển cảnh hoặc tutorial/in-app "
                      "(vệt laser, icon, mép lật trang, điện thoại, nhoè chuyển động bất thường...). Sạch hết thì trả [].",
                      FLAG_SCHEMA)["bad_frames"]
            bad = [i for i in bad if 0 <= i < len(fr)]
            if not bad:
                break
            s = fr[min(bad)][0]
            log(f"  soát: lùi điểm cắt đầu về {s:.3f}s")
        for _ in range(3):
            if e >= dur:
                break
            fr = extract(path, e, n / fps + 0.005, 320)[:n]
            if not fr:
                break
            bad = ask([grid([im for _, im in fr], n, [str(i) for i in range(len(fr))])],
                      "Đây là các khung ĐẦU TIÊN được giữ lại ngay sau chỗ cắt bỏ đoạn tutorial. "
                      "Liệt kê index các khung có BẤT KỲ dấu hiệu nào của hiệu ứng chuyển cảnh hoặc tutorial/in-app. "
                      "Sạch hết thì trả [].", FLAG_SCHEMA)["bad_frames"]
            bad = [i for i in bad if 0 <= i < len(fr)]
            if not bad:
                break
            e = fr[max(bad)][0] + 0.001  # loại khung bẩn, giữ khung kế tiếp
            log(f"  soát: đẩy điểm cắt cuối tới {e:.3f}s")
        out.append((s, e))
    return out


def merge(segs):
    segs = sorted(segs)
    out = []
    for s, e in segs:
        if out and s <= out[-1][1] + MIN_KEEP:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def render(src: Path, dst: Path, keeps: list[tuple[float, float]], info: dict):
    fade = 0.25
    parts, labels = [], []
    for i, (a, b) in enumerate(keeps):
        parts.append(f"[0:v]trim=start={a:.4f}:end={b:.4f},setpts=PTS-STARTPTS[v{i}]")
        if info["has_audio"]:
            L = b - a
            af = f"[0:a]atrim=start={a:.4f}:end={b:.4f},asetpts=PTS-STARTPTS"
            if i > 0:
                af += ",afade=t=in:d=0.08"
            if b < info["duration"] - 0.05:
                af += f",afade=t=out:st={max(0, L - fade):.4f}:d={min(fade, L):.4f}"
            parts.append(af + f"[a{i}]")
            labels.append(f"[v{i}][a{i}]")
        else:
            labels.append(f"[v{i}]")
    a = 1 if info["has_audio"] else 0
    fc = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(keeps)}:v=1:a={a}[v]" + ("[a]" if a else "")
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(src), "-filter_complex", fc, "-map", "[v]"]
    if a:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k"]
    cmd += ["-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", str(dst)]
    r = run(cmd)
    if r.returncode:
        raise RuntimeError("ffmpeg lỗi: " + r.stderr[-500:])


def analyze(src: Path, info: dict, log) -> tuple[list[tuple[float, float]], str]:
    """Chỉ nhận diện: trả về các đoạn cần bỏ + ghi chú."""
    vlog = lambda m: log(f"[{src.name}]{m}")  # noqa: E731
    if BACKEND == "claude":
        segs, note = find_segments(src, info, vlog)
        return merge(verify(src, merge(segs), info, vlog)), note
    import local_detect
    segs, note = local_detect.find_segments(src, info, extract, vlog)
    return merge(segs), note


def keeps_from(segs: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    keeps, t = [], 0.0
    for s, e in sorted(segs):
        if s - t >= MIN_KEEP:
            keeps.append((t, s))
        t = max(t, e)
    if duration - t >= MIN_KEEP:
        keeps.append((t, duration))
    return keeps


def export(src: Path, out_dir: Path, segs: list[tuple[float, float]], info: dict) -> Path:
    """Xuất video đã bỏ các đoạn segs. Không có đoạn nào thì chép nguyên file."""
    out_dir.mkdir(exist_ok=True)
    keeps = keeps_from(segs, info["duration"])
    if not keeps:
        raise RuntimeError("cả video đều bị đánh dấu cắt – không xuất")
    if not segs:
        dst = out_dir / out_name(src)
        shutil.copy2(src, dst)
        return dst
    dst = out_dir / out_name(src)
    render(src, dst, keeps, info)
    return dst


def process(src: Path, out_dir: Path, log) -> Result:
    res = Result(src=src)
    try:
        info = probe(src)
        res.duration = info["duration"]
        segs, res.note = analyze(src, info, log)
        res.cuts = segs
        res.keeps = keeps_from(segs, info["duration"])
        res.dst = export(src, out_dir, segs, info)
        # ảnh soát cho báo cáo: khung cuối trước & khung đầu sau mỗi mối cắt
        for s, e in segs:
            if s > 0:
                f = extract(src, max(0, s - 0.2), 0.2, 200)
                if f:
                    res.thumbs.append((f"trước cắt {s:.2f}s", f[-1][1]))
            if e < info["duration"]:
                f = extract(src, e, 0.1, 200)
                if f:
                    res.thumbs.append((f"sau cắt {e:.2f}s", f[0][1]))
    except Exception as ex:  # noqa: BLE001 – báo lỗi từng video, không dừng cả lô
        res.error = f"{type(ex).__name__}: {ex}"
    return res


def report(results: list[Result], out_dir: Path) -> Path:
    rows = []
    for r in results:
        imgs = "".join(
            f'<figure><img src="data:image/jpeg;base64,{b64(im)["source"]["data"]}"><figcaption>{html.escape(c)}</figcaption></figure>'
            for c, im in r.thumbs)
        cuts = ", ".join(f"{s:.2f}–{e:.2f}s" for s, e in r.cuts) or "không có tutorial"
        kept = sum(b - a for a, b in r.keeps)
        status = f'<b class="err">{html.escape(r.error)}</b>' if r.error else f"giữ {kept:.1f}s / {r.duration:.1f}s"
        rows.append(f"<section><h2>{html.escape(r.src.name)}</h2><p>Đã bỏ: {cuts} · {status}</p>"
                    f"<p class='note'>{html.escape(r.note)}</p><div class='th'>{imgs}</div></section>")
    page = f"""<!doctype html><meta charset="utf-8"><title>Báo cáo cắt tutorial</title>
<style>body{{font:14px -apple-system,sans-serif;margin:24px;background:#fafafa;color:#222}}
section{{background:#fff;border:1px solid #ddd;border-radius:8px;padding:12px 16px;margin:12px 0}}
h2{{font-size:16px;margin:0 0 4px}}.note{{color:#666}}.err{{color:#c00}}
.th{{display:flex;gap:8px;flex-wrap:wrap}}figure{{margin:0}}img{{width:150px;border-radius:4px}}
figcaption{{font-size:12px;color:#555}}</style>
<h1>Báo cáo cắt tutorial – {time.strftime('%d/%m/%Y %H:%M')}</h1>
<p>Xem ảnh "trước cắt"/"sau cắt": nếu còn lộ điện thoại hoặc hiệu ứng chuyển cảnh thì video đó cần sửa tay.</p>
{''.join(rows)}"""
    p = out_dir / "bao_cao.html"
    p.write_text(page, encoding="utf-8")
    return p


def collect(targets: list[str]) -> dict[Path, list[Path]]:
    groups: dict[Path, list[Path]] = {}
    for t in targets:
        p = Path(t).expanduser()
        if p.is_dir():
            vids = sorted(f for f in p.iterdir() if is_video(f))
            if vids:
                groups.setdefault(p, []).extend(vids)
        elif is_video(p):
            groups.setdefault(p.parent, []).append(p)
    return groups


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    groups = collect(argv)
    if not groups:
        print("Không tìm thấy video nào.")
        return 1

    def log(m):
        print(m, flush=True)

    for folder, vids in groups.items():
        out_dir = folder / OUT_DIRNAME
        out_dir.mkdir(exist_ok=True)
        log(f"\n== {folder}  ({len(vids)} video) -> {out_dir}")
        results = []
        with cf.ThreadPoolExecutor(WORKERS) as ex:
            futs = {ex.submit(process, v, out_dir, log): v for v in vids}
            for f in cf.as_completed(futs):
                r = f.result()
                results.append(r)
                tag = "LỖI " + r.error if r.error else ", ".join(f"{s:.2f}-{e:.2f}s" for s, e in r.cuts) or "không có tutorial"
                log(f"✓ {r.src.name}: {tag}")
        results.sort(key=lambda r: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", r.src.name)])
        rp = report(results, out_dir)
        log(f"Báo cáo: {rp}")
        if sys.platform == "darwin" and not os.environ.get("CAT_TUTORIAL_NO_OPEN"):
            subprocess.run(["open", str(rp)])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
