"""Nhận ra watermark chữ (CapCut AI, ...) trong video để che lại bằng ffmpeg delogo.

Dùng rapidocr-onnxruntime (CPU, không cần API key). Chưa cài thư viện -> trả về [] (không che, không lỗi).
Kết quả: [{"x","y","w","h","t0","t1"}] theo toạ độ video gốc + khoảng thời gian (giây) cần che.
"""
from __future__ import annotations

import difflib
import hashlib
import os
import re
from pathlib import Path

import numpy as np

# Chữ cần che. Thêm từ khoá bằng biến môi trường CAT_WM_WORDS="a|b|c"
WORDS = r"cap\s*cu|capcut|jianying|kling|hailuo|runway|made\s*with|ai\s*generated|veo|剪映" + \
        (("|" + os.environ["CAT_WM_WORDS"]) if os.environ.get("CAT_WM_WORDS") else "")
PAT = re.compile(WORDS, re.I)
FUZZY = re.compile(r"^\s*cap\w{0,3}(\s?a[il1])?\s*$", re.I)  # OCR hay đọc \"CapCut AI\" thành \"capGin\"...
TAIL = re.compile(r"^\s*(a\.?i|a[l1|]|ai\s*)\s*$", re.I)  # chữ "AI" đứng cạnh nhãn (OCR hay đọc nhầm thành "Al")
PAD = 0.35          # nới khung theo chiều cao chữ
MIN_SCORE = 0.5
CORNER_W, CORNER_H, ZOOM = 0.5, 0.14, 3   # vùng góc cần soi: rộng 50%, cao 14% khung, phóng 3 lần
TARGETS = ("capcut", "capcut ai")
_ocr = None


def _engine():
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


def _rect(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return [min(xs), min(ys), max(xs), max(ys)]


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def _fuzzy_hit(t: str) -> bool:
    if PAT.search(t) or FUZZY.match(t):
        return True
    t = t.lower().strip()
    return len(t) >= 4 and any(difflib.SequenceMatcher(None, t, k).ratio() >= 0.62 for k in TARGETS)


def find_in_image(img) -> list[list[float]]:
    """Các khung [x0,y0,x1,y1] (px của ảnh) chứa chữ watermark. Soi 4 góc phóng to, vì chữ mờ nhỏ hay bị đọc sai ở khung nguyên."""
    from PIL import ImageOps
    img = img.convert("RGB")
    W, H = img.size
    cw, ch = int(W * CORNER_W), int(H * CORNER_H)
    zones = [(0, 0), (W - cw, 0), (0, H - ch), (W - cw, H - ch)]
    out = []
    for zx, zy in zones:
        crop = img.crop((zx, zy, zx + cw, zy + ch))
        crop = ImageOps.autocontrast(crop.resize((cw * ZOOM, ch * ZOOM)).convert("L")).convert("RGB")
        res, _ = _engine()(np.array(crop)[:, :, ::-1])
        items = [([v / ZOOM for v in _rect(b)], str(t), float(sc)) for b, t, sc in (res or [])]
        for r in items:
            r[0][0] += zx; r[0][2] += zx; r[0][1] += zy; r[0][3] += zy
        hits = [r for r, t, sc in items if sc >= MIN_SCORE and _fuzzy_hit(t)]
        for h in hits:
            box = list(h)
            hh = h[3] - h[1]
            for r, t, sc in items:  # gom chữ "AI" đứng sát bên
                if r is h or not TAIL.match(t):
                    continue
                if abs((r[1] + r[3]) / 2 - (h[1] + h[3]) / 2) < hh and (0 <= r[0] - h[2] < 2 * hh or 0 <= h[0] - r[2] < 2 * hh):
                    box = [min(box[0], r[0]), min(box[1], r[1]), max(box[2], r[2]), max(box[3], r[3])]
            out.append(box)
    return out


def find_watermarks(src, info: dict, extract, log=lambda m: None, width: int = 720) -> list[dict]:
    """Soi ~10 khung rải đều (chỉ 4 góc), gom các lần thấy chữ thành vùng + khoảng thời gian cần che."""
    try:
        _engine()
    except Exception as ex:  # noqa: BLE001
        log(f"  che chữ: bỏ qua ({type(ex).__name__}: chưa cài rapidocr?)")
        return []
    dur, W, H = info["duration"], info["width"], info["height"]
    n = max(3, min(10, int(dur // 2)))
    step = dur / n
    frames = extract(src, 0, dur, min(width, W), 1.0 / step)
    if not frames:
        return []
    t0 = frames[0][0]
    k = W / frames[0][1].size[0]
    clusters = []  # {"box","hits":[t]}
    for t, im in frames:
        for b in find_in_image(im):
            b = [v * k for v in b]
            for c in clusters:
                if _iou(c["box"], b) > 0.3:
                    c["box"] = [min(c["box"][0], b[0]), min(c["box"][1], b[1]), max(c["box"][2], b[2]), max(c["box"][3], b[3])]
                    c["hits"].append(t - t0)
                    break
            else:
                clusters.append({"box": b, "hits": [t - t0]})
    out = []
    full = []  # vùng có chữ suốt cả video -> che bằng removelogo với mặt nạ đúng nét chữ (đẹp hơn delogo)
    for c in clusters:
        x0, y0, x1, y1 = c["box"]
        pad = (y1 - y0) * PAD
        x0, y0, x1, y1 = max(1, x0 - pad), max(1, y0 - pad), min(W - 1, x1 + pad), min(H - 1, y1 + pad)
        a, b = min(c["hits"]), max(c["hits"])
        a = 0.0 if a <= step * 1.5 else a - step / 2
        b = dur if b >= dur - step * 1.5 else b + step / 2
        item = {"x": int(x0), "y": int(y0), "w": int(x1 - x0) // 2 * 2, "h": int(y1 - y0) // 2 * 2,
                "t0": round(a, 2), "t1": round(b, 2)}
        out.append(item)
        if a <= 0.3 and b >= dur - 0.3:
            full.append(item)
    if full:
        mp = _save_mask(src, full, frames, (W, H), k)
        for it in full:
            it["mask"] = str(mp) if mp else None
    if out:
        log(f"  che chữ: {len(out)} vùng " + "; ".join(f'({o["x"]},{o["y"]},{o["w"]}x{o["h"]}) {o["t0"]}-{o["t1"]}s' for o in out))
    return out


def _save_mask(src, items, frames, size, k) -> Path | None:
    """Mặt nạ (trắng = chữ) khớp từng nét chữ: điểm sáng hơn nền xung quanh và có mặt ở mọi khung đã soi (chữ đứng yên, nền thì đổi)."""
    try:
        import cv2
        W, H = size
        sm = []
        for _, im in frames[:6]:
            g = cv2.cvtColor(np.array(im.convert("RGB")), cv2.COLOR_RGB2GRAY).astype(np.float32)
            sm.append(((g - cv2.GaussianBlur(g, (0, 0), 6)) > 8))
        h0, w0 = sm[0].shape
        and_m = np.logical_and.reduce(sm) if len(sm) > 1 else sm[0]
        mask = np.zeros((h0, w0), np.uint8)
        for it in items:
            x0, y0 = int(it["x"] / k), int(it["y"] / k)
            x1, y1 = int((it["x"] + it["w"]) / k), int((it["y"] + it["h"]) / k)
            part = and_m[y0:y1, x0:x1]
            if part.sum() < 20:  # không tách được nét chữ -> che nguyên khung
                part = np.ones_like(part)
            mask[y0:y1, x0:x1] = part.astype(np.uint8)
        mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=1)
        mask = cv2.resize(mask * 255, (W, H), interpolation=cv2.INTER_NEAREST)
        d = Path.home() / ".cat-tutorial" / "cache"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"wm_{hashlib.md5(str(src).encode()).hexdigest()[:16]}.png"
        cv2.imwrite(str(path), mask)
        return path
    except Exception:  # noqa: BLE001
        return None
