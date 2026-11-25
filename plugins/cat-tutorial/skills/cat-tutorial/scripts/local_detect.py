"""Nhận diện đoạn tutorial/in-app hoàn toàn trên máy (không cần API key).

1. CLIP (model nhận diện ảnh mã nguồn mở) chấm mỗi khung (4 khung/giây):
   giống "điện thoại / giao diện app" hay "ảnh thành phẩm".
2. Khung chấm chắc chắn làm mẫu; khung lưỡng lự được xếp theo mẫu giống nhất
   TRONG CÙNG video (cảnh tutorial cùng bàn, cùng điện thoại nên rất giống nhau).
3. Làm mượt, bỏ đoạn vụn, lấp khoảng hở ngắn.
4. Tinh chỉnh từng ranh giới tới từng khung: hiệu ứng chuyển cảnh (laser, lật trang,
   icon máy quay, nhoè...) làm khung thay đổi mạnh liên tục -> lần ngược tới khung
   đầu tiên của chuỗi thay đổi đó.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np

STEP_FPS = 4
TUT_PROMPTS = [
    "a smartphone screen showing a mobile app interface",
    "a hand holding a smartphone",
    "a phone lying on a table with a stylus tapping the screen",
    "a screenshot of a social media profile page",
    "a black screen with an app logo",
    "a phone screen showing a grid gallery of photos",
]
CON_PROMPTS = [
    "a full screen photograph of a person",
    "a studio portrait photo of a person sitting",
    "people outdoors in a car",
    "an AI generated fashion photo",
]
SEED_HI, SEED_LO = 0.75, 0.05
MIN_TUT = 1.0     # đoạn tutorial ngắn hơn -> bỏ (nhiễu)
MAX_GAP = 2.0     # khoảng nội dung ngắn hơn kẹp giữa 2 đoạn tutorial -> lấp
SEARCH_BACK = 2.0  # giây tìm ngược hiệu ứng chuyển cảnh
STRONG, WEAK = 25.0, 10.0  # ngưỡng độ thay đổi khung: hiệu ứng mạnh / chuyển động

_model = None
_lock = threading.Lock()


def _load():
    global _model
    with _lock:
        if _model is None:
            import open_clip
            import torch
            torch.set_num_threads(max(1, (os.cpu_count() or 4) // 2))
            model, _, pre = open_clip.create_model_and_transforms(
                "ViT-B-32", pretrained="laion2b_s34b_b79k")
            model.eval()
            tok = open_clip.get_tokenizer("ViT-B-32")
            with torch.no_grad():
                tf = model.encode_text(tok(TUT_PROMPTS + CON_PROMPTS))
                tf = tf / tf.norm(dim=-1, keepdim=True)
            _model = (model, pre, tf)
    return _model


def embed(images):
    import torch
    model, pre, tf = _load()
    x = torch.stack([pre(im.convert("RGB")) for im in images])
    with _lock, torch.no_grad():
        f = model.encode_image(x)
        f = f / f.norm(dim=-1, keepdim=True)
        p = (100 * f @ tf.T).softmax(-1)[:, :len(TUT_PROMPTS)].sum(-1)
    return f.numpy(), p.numpy()


def _runs(mask):
    out, start = [], None
    for i, v in enumerate(list(mask) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i - 1))
            start = None
    return out


def classify(feats: np.ndarray, p: np.ndarray) -> np.ndarray:
    """Gán nhãn từng khung theo 'tâm cụm' tutorial và nội dung của chính video đó."""
    core = p > SEED_HI  # khung chắc chắn là tutorial
    if not core.any():
        return np.zeros(len(p), bool), None, None
    idx = np.arange(len(p))
    dist = np.array([np.min(np.abs(idx[core] - i)) for i in idx])
    # khung chắc chắn là nội dung: điểm ~0 VÀ cách xa mọi khung tutorial >= 2 giây
    con = (p < SEED_LO) & (dist >= 2 * STEP_FPS)
    if not con.any():
        con = p < SEED_LO
    if not con.any():
        return np.ones(len(p), bool), None, None
    tut_c = feats[core].mean(0)
    con_c = feats[con].mean(0)
    lab = (feats @ tut_c) > (feats @ con_c)
    lab[core] = True
    # 1) bỏ khung tutorial lẻ (vd khung loé sáng khi chuyển giữa 2 ảnh nội dung)
    for a, b in _runs(lab):
        if b - a + 1 < 2:
            lab[a:b + 1] = False
    # 2) lấp khoảng nội dung ngắn kẹp giữa tutorial
    gap = int(MAX_GAP * STEP_FPS)
    for a, b in _runs(~lab):
        if a > 0 and b < len(lab) - 1 and b - a + 1 <= gap:
            lab[a:b + 1] = True
    # 3) bỏ đoạn tutorial vụn hoặc không có khung nào chắc chắn
    for a, b in _runs(lab):
        if (b - a + 1) < MIN_TUT * STEP_FPS or not core[a:b + 1].any():
            lab[a:b + 1] = False
    return lab, tut_c, con_c


def _change(a, b) -> float:
    """Độ thay đổi cục bộ lớn nhất giữa 2 khung (bắt được cả vệt laser nhỏ)."""
    a = np.asarray(a.convert("L").resize((48, 85)), dtype=np.float32)
    b = np.asarray(b.convert("L").resize((48, 85)), dtype=np.float32)
    d = np.abs(a - b)[:80, :48].reshape(10, 8, 6, 8).mean(axis=(1, 3))
    return float(d.max())


AHEAD = 1.0  # giây nhìn quá mốc (mốc có thể sớm hơn hiệu ứng thật)


def _pick(cands, fr, times, judge, kind):
    """Chọn hiệu ứng làm khung chuyển từ 'nội dung' sang 'tutorial' (hoặc ngược lại) rõ nhất."""
    best, best_score = None, 0.0
    n = len(fr)
    for a, b in cands:
        i0 = max(0, a - 2)
        t_after = times[b] + 0.25
        i1 = min(n - 1, next((i for i, t in enumerate(times) if t >= t_after), n - 1))
        before, after = judge(fr[i0][1]), judge(fr[i1][1])
        score = (after - before) if kind == "start" else (before - after)
        if score > best_score:
            best, best_score = (a, b), score
    return best


def edge(extract, path: Path, t_anchor: float, kind: str, judge) -> float:
    """kind='start': t_anchor = mẫu tutorial đầu tiên; trả về thời điểm khung đầu của hiệu ứng.
    kind='end': t_anchor = mẫu tutorial cuối; trả về thời điểm khung sạch đầu tiên sau đó.
    judge(ảnh) > 0 nghĩa là ảnh giống tutorial hơn nội dung."""
    if kind == "start":
        fr = extract(path, t_anchor - SEARCH_BACK - 1.0, SEARCH_BACK + 1.0 + AHEAD, 256)
    else:
        fr = extract(path, t_anchor - AHEAD, SEARCH_BACK + 1.0 + AHEAD, 256)
    if len(fr) < 3:
        return t_anchor
    d = [0.0] + [_change(fr[i - 1][1], fr[i][1]) for i in range(1, len(fr))]
    times = [t for t, _ in fr]
    # chuỗi hiệu ứng mạnh: >= 0,08 giây liên tục thay đổi mạnh
    strong = [(a, b) for a, b in _runs([x > STRONG for x in d]) if times[b] - times[a] >= 0.08 - 1e-6]
    if kind == "start":
        lo = t_anchor - SEARCH_BACK
        cand = _pick([(a, b) for a, b in strong if times[a] > lo], fr, times, judge, "start")
        if cand:
            k = cand[0]
        else:
            hits = [i for i, t in enumerate(times) if t > lo and d[i] > WEAK]
            if not hits:  # không thấy hiệu ứng: cắt luôn tại mẫu tutorial
                return t_anchor
            k = hits[-1]
        t_k = times[k]
        while k > 1 and d[k - 1] > WEAK and times[k - 1] > t_k - 0.5:
            k -= 1
        base_idx = [i for i, t in enumerate(times) if 0 < i and t < times[k] - 0.3]
        base = float(np.median([d[i] for i in base_idx])) if base_idx else 2.0
        if k - 1 > 0 and d[k - 1] > max(4.0, 2 * base):
            k -= 1  # khung mở màn hiệu ứng thường chỉ đổi nhẹ
        return times[max(0, k - 2)]  # chừa 2 khung an toàn (hiệu ứng lật trang lộ mép sớm)
    else:
        hi = t_anchor + SEARCH_BACK
        cand = _pick([(a, b) for a, b in strong if times[b] < hi], fr, times, judge, "end")
        if cand:
            k = cand[1]
        else:
            hits = [i for i, t in enumerate(times) if t > t_anchor and t < hi and d[i] > WEAK]
            if not hits:
                return t_anchor + 1 / STEP_FPS
            k = hits[0]
        t_k = times[k]
        while k + 1 < len(fr) and d[k + 1] > WEAK and times[k + 1] < t_k + 0.5:
            k += 1
        return times[min(k + 3, len(fr) - 1)]  # chừa 2 khung an toàn


def find_segments(path: Path, info: dict, extract, log) -> tuple[list[tuple[float, float]], str]:
    dur = info["duration"]
    fr = extract(path, 0, dur, 256, fps=STEP_FPS)
    if not fr:
        raise RuntimeError("không đọc được khung hình")
    times = [t for t, _ in fr]
    feats, p = embed([im for _, im in fr])
    lab, tut_c, con_c = classify(feats, p)

    def judge(img):
        f, _ = embed([img])
        return float(f[0] @ tut_c - f[0] @ con_c)

    segs = []
    for a, b in _runs(lab):
        s = 0.0 if a == 0 else edge(extract, path, times[a], "start", judge)
        e = dur if b == len(times) - 1 else edge(extract, path, times[b], "end", judge)
        segs.append((s, e))
    log("  nhãn: " + "".join("#" if v else "." for v in lab))
    note = ""
    if segs and segs[0][0] > 0:
        note = "Kiểm tra lời đọc/chữ ở cuối phần giữ lại: có thể bị ngắt giữa câu hướng dẫn."
    return segs, note
