#!/usr/bin/env python3
"""Giao diện Cắt Tutorial: server cục bộ (127.0.0.1) + trang web trong trình duyệt.

    python ui_server.py [thư mục video]

Nếu đã có một giao diện đang chạy, lệnh này chỉ mở thư mục mới trong giao diện đó.
Server tự tắt khi đóng trang web khoảng 2 phút và không còn việc đang chạy.
"""
from __future__ import annotations

import base64
import hashlib
import concurrent.futures as cf
import io
import json
import math
import mimetypes
import os
import re
import secrets
import shutil
import zipfile
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cat_tutorial as ct  # noqa: E402

PORT_FILE = Path.home() / ".cat-tutorial" / "ui.json"
IDLE_EXIT = 120  # giây không có trang nào mở thì tự tắt
CACHE = Path.home() / ".cat-tutorial" / "cache"  # ảnh thu nhỏ, bản xem trước (giữ qua các lần mở)
CACHE.mkdir(parents=True, exist_ok=True)
SESSION = Path.home() / ".cat-tutorial" / "session.json"  # danh sách thư mục + điểm cắt + trạng thái duyệt

# ---- chế độ web (CAT_TUTORIAL_WEB=1): nhiều người dùng qua Internet, tải video lên / tải bản cắt về.
# Mỗi trình duyệt có một khu riêng (cookie ngẫu nhiên); không ai đọc được ổ đĩa máy chủ hay khu của người khác.
WEB = bool(os.environ.get("CAT_TUTORIAL_WEB"))
WEB_ROOT = Path.home() / ".cat-tutorial" / "web"
MAX_FILE = int(float(os.environ.get("CAT_TUTORIAL_MAX_FILE_MB", "500")) * 2**20)   # mỗi video
MAX_WS = int(float(os.environ.get("CAT_TUTORIAL_MAX_WS_GB", "5")) * 2**30)          # mỗi người
MIN_FREE = int(float(os.environ.get("CAT_TUTORIAL_MIN_FREE_GB", "10")) * 2**30)     # chừa trống ổ đĩa
TTL = float(os.environ.get("CAT_TUTORIAL_TTL_H", "24")) * 3600                      # tự xoá sau
_WS_RE = re.compile(r"^[0-9a-f]{32}$")
if WEB:
    SESSION = Path.home() / ".cat-tutorial" / "web_session.json"
    WEB_ROOT.mkdir(parents=True, exist_ok=True)


def ws_dir(ws: str) -> Path:
    return WEB_ROOT / ws


def to_pub(path: str | None, ws: str | None) -> str | None:
    """Đường dẫn thật -> tên hiển thị trong khu của người dùng (không lộ đường dẫn máy chủ)."""
    if not WEB or path is None:
        return path
    return str(Path(path).relative_to(ws_dir(ws)))


def from_pub(s: str, ws: str | None) -> str | None:
    """Tên từ trình duyệt -> đường dẫn thật, chỉ khi nằm trong khu của chính người đó."""
    if not WEB:
        return s
    if not s or not ws:
        return None
    root = ws_dir(ws).resolve()
    p = (root / s).resolve()
    return str(p) if p != root and p.is_relative_to(root) else None


def _safe_name(s: str, fallback: str) -> str:
    s = re.sub(r'[\x00-\x1f/\\:<>"|?*]', "_", (s or "").strip()).strip(". ")  # gồm ký tự Windows cấm
    return s[:120] or fallback


def _key(vid: str) -> str:
    return hashlib.md5(vid.encode()).hexdigest()[:16]

lock = threading.RLock()
state: dict = {"groups": [], "videos": {}, "order": []}  # videos: id (đường dẫn đầy đủ) -> thông tin
analyze_pool = cf.ThreadPoolExecutor(ct.WORKERS)
export_pool = cf.ThreadPoolExecutor(2)
last_ping = time.time()
busy = 0
_natural = lambda s: [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", s)]  # noqa: E731


# ------------------------------------------------------------------ jobs
def _set(vid, **kw):
    with lock:
        if vid in state["videos"]:
            state["videos"][vid].update(kw)


def _sprite(vid: str, info: dict) -> dict:
    rate = min(2.0, 240 / max(info["duration"], 1))  # tối đa ~240 ảnh thu nhỏ
    n = max(1, math.ceil(info["duration"] * rate))
    sprite = CACHE / f"{_key(vid)}.jpg"
    if not sprite.exists():
        ct.run(["ffmpeg", "-v", "error", "-y", "-i", vid, "-vf",
                f"fps={rate:.4f},scale=-2:120,tile={n}x1", "-frames:v", "1", "-q:v", "4", str(sprite)])
    return {"sprite": str(sprite), "sprite_n": n}


def _restore(vid: str, status: str):
    """Mở lại video từ phiên trước: chỉ đọc thông số + ảnh thu nhỏ, không nhận diện lại."""
    global busy
    with lock:
        busy += 1
    try:
        info = ct.probe(Path(vid))
        _set(vid, info=info, duration=info["duration"], fps=info["fps"], status=status, error=None, **_sprite(vid, info))
    except Exception as ex:  # noqa: BLE001
        _set(vid, status="error", error=f"{type(ex).__name__}: {ex}")
    finally:
        with lock:
            busy -= 1


KEEP = ("id", "name", "folder", "segs", "auto_segs", "note", "reviewed", "exported_segs", "output",
        "duration", "fps", "status")


def save_session():
    with lock:
        data = {"groups": state["groups"],
                "videos": [{k: state["videos"][i].get(k) for k in KEEP} for i in state["order"]]}
    tmp = SESSION.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(SESSION)


def _heal(vid: str, folder: str) -> str | None:
    """File đã bị đổi tên (vd thêm đuôi .mp4 cho file mất đuôi '._')? Tìm lại theo tên mới."""
    if Path(vid).exists():
        return vid
    cand = Path(folder) / ct.out_name(Path(vid))
    return str(cand) if cand.exists() else None


def load_session():
    try:
        data = json.loads(SESSION.read_text())
    except Exception:  # noqa: BLE001
        return
    todo = []
    with lock:
        for g in data.get("groups", []):
            if Path(g["folder"]).is_dir():
                state["groups"].append(g)
        known = {g["folder"] for g in state["groups"]}
        for v in data.get("videos", []):
            if v.get("folder") not in known:
                continue
            vid = _heal(v["id"], v["folder"])
            if not vid or vid in state["videos"]:
                continue
            v = dict(v, id=vid, name=Path(vid).name)
            analyzed = (v.get("duration") or 0) > 0 and v.get("auto_segs") is not None
            if v.get("output") and not Path(v["output"]).exists():
                v["output"], v["exported_segs"] = None, None
            st = "done" if v.get("output") and v.get("exported_segs") is not None else "ready"
            v["status"] = "loading" if analyzed else "queued"
            state["videos"][vid] = v
            state["order"].append(vid)
            todo.append((vid, st if analyzed else None))
        # thư mục có thêm video mới từ lần trước
        for g in state["groups"]:
            for vf in _video_files(Path(g["folder"])):
                if str(vf) not in state["videos"]:
                    vid = str(vf)
                    state["videos"][vid] = {"id": vid, "name": vf.name, "folder": g["folder"], "status": "queued",
                                            "segs": [], "auto_segs": [], "note": "", "duration": 0, "fps": 30}
                    state["order"].append(vid)
                    todo.append((vid, None))
    for vid, st in todo:
        analyze_pool.submit(_restore, vid, st) if st else analyze_pool.submit(_analyze, vid)


def _analyze(vid: str):
    global busy
    with lock:
        if vid not in state["videos"]:
            return  # thư mục đã bị gỡ khỏi danh sách
        busy += 1
    src = Path(vid)
    try:
        _set(vid, status="analyzing")
        info = ct.probe(src)
        _set(vid, duration=info["duration"], fps=info["fps"], info=info, **_sprite(vid, info))
        segs, note = ct.analyze(src, info, lambda m: None)
        segs = [[round(s, 4), round(e, 4)] for s, e in segs]
        _set(vid, status="ready", segs=segs, auto_segs=[list(x) for x in segs], note=note)
        save_session()
    except Exception as ex:  # noqa: BLE001
        _set(vid, status="error", error=f"{type(ex).__name__}: {ex}")
    finally:
        with lock:
            busy -= 1


def _export(vid: str):
    global busy
    with lock:
        v = state["videos"].get(vid)
        if not v:
            return
        out_dir = Path(v["folder"]) / ct.OUT_DIRNAME
        segs = [tuple(x) for x in v["segs"]]
        info = v["info"]
        busy += 1
    try:
        _set(vid, status="exporting")
        dst = ct.export(Path(vid), out_dir, segs, info)
        _set(vid, status="done", output=str(dst), exported_segs=[list(x) for x in segs])
        save_session()
    except Exception as ex:  # noqa: BLE001
        _set(vid, status="error", error=f"{type(ex).__name__}: {ex}")
    finally:
        with lock:
            busy -= 1


def _video_files(p: Path) -> list[Path]:
    return sorted((f for f in p.iterdir() if ct.is_video(f)), key=lambda f: _natural(f.name))


def _expand(target: str) -> list[Path]:
    """Thư mục có video -> chính nó; thư mục chỉ chứa thư mục con -> các thư mục con có video; file -> thư mục cha."""
    p = Path(target).expanduser()
    if p.is_file():
        p = p.parent
    if not p.is_dir():
        return []
    if _video_files(p):
        return [p]
    subs = sorted((d for d in p.iterdir() if d.is_dir() and not d.name.startswith(".")
                   and d.name != ct.OUT_DIRNAME), key=lambda d: _natural(d.name))
    return [d for d in subs if _video_files(d)]


def add_folders(targets: list[str]) -> dict:
    folders = [f for t in targets for f in _expand(t)]
    if not folders:
        raise ValueError("Không tìm thấy video nào trong thư mục đã chọn")
    new_ids = []
    with lock:
        known = {g["folder"] for g in state["groups"]}
        for f in folders:
            if str(f) in known or f.name == ct.OUT_DIRNAME:
                continue
            known.add(str(f))
            state["groups"].append({"folder": str(f), "name": f.name})
            for vf in _video_files(f):
                vid = str(vf)
                state["videos"][vid] = {"id": vid, "name": vf.name, "folder": str(f), "status": "queued",
                                        "segs": [], "auto_segs": [], "note": "", "duration": 0, "fps": 30}
                state["order"].append(vid)
                new_ids.append(vid)
    for vid in new_ids:
        analyze_pool.submit(_analyze, vid)
    save_session()
    return public_state()


def remove_folder(folder: str) -> dict:
    with lock:
        state["groups"] = [g for g in state["groups"] if g["folder"] != folder]
        for vid in [i for i in state["order"] if state["videos"][i]["folder"] == folder]:
            state["videos"].pop(vid, None)
        state["order"] = [i for i in state["order"] if i in state["videos"]]
    save_session()
    return public_state()


def _mine(folder: str, ws: str | None) -> bool:
    return not WEB or (ws is not None and Path(folder).parent == ws_dir(ws))


def public_state(ws: str | None = None) -> dict:
    with lock:
        vids = [{k: state["videos"][i].get(k) for k in (
            "id", "name", "folder", "status", "segs", "auto_segs", "note", "duration", "fps", "error",
            "output", "sprite_n", "exported_segs", "reviewed")} for i in state["order"]
            if _mine(state["videos"][i]["folder"], ws)]
        groups = [dict(g) for g in state["groups"] if _mine(g["folder"], ws)]
    if WEB:
        for v in vids:
            v["id"], v["folder"], v["output"] = to_pub(v["id"], ws), to_pub(v["folder"], ws), to_pub(v["output"], ws)
            v["error"] = (v["error"] or "").replace(str(WEB_ROOT), "…") or None
        for g in groups:
            g["folder"] = to_pub(g["folder"], ws)
    out = {"groups": groups, "videos": vids, "out_dirname": ct.OUT_DIRNAME, "backend": ct.BACKEND, "web": WEB}
    if WEB:
        out["limits"] = {"file_mb": MAX_FILE // 2**20, "ws_gb": round(MAX_WS / 2**30, 1), "ttl_h": round(TTL / 3600)}
    return out


# ------------------------------------------------------------------ web: tải lên, dọn dẹp
def _du(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def _looks_video(p: Path) -> bool:
    try:
        with open(p, "rb") as f:
            head = f.read(12)
    except OSError:
        return False
    return head[4:8] == b"ftyp" or head[:4] == b"\x1a\x45\xdf\xa3"


def upload_chunk(ws: str, q: dict, rfile, length: int) -> bool:
    """Nhận 1 mảnh của 1 file (Cloudflare chặn mỗi request >100MB nên trình duyệt chia nhỏ).
    Trả về True khi đã nhận đủ file và đưa vào hàng nhận diện."""
    g = lambda k: q.get(k, [""])[0]  # noqa: E731
    up, name, batch = g("id"), g("name"), g("batch")
    offset, total = int(g("offset") or 0), int(g("total") or 0)
    if not re.fullmatch(r"[0-9a-z]{8,40}", up):
        raise ValueError("Mã tải lên không hợp lệ")
    if total <= 0 or length <= 0:
        raise ValueError("File rỗng")
    if total > MAX_FILE:
        raise ValueError(f"{name}: quá lớn (tối đa {MAX_FILE // 2**20}MB mỗi video)")
    if length > 64 * 2**20 or offset + length > total:
        raise ValueError("Mảnh tải lên không hợp lệ")
    root = ws_dir(ws)
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f".up_{up}"
    if offset == 0:
        if not re.search(r"\.(mp4|mov|m4v|webm|mkv|avi)$", name, re.I) and not name.endswith("_"):
            raise ValueError(f"{name}: không phải file video")
        if _du(root) + total > MAX_WS:
            raise ValueError(f"Đã dùng hết {MAX_WS / 2**30:.0f}GB cho phiên này — gỡ bớt thư mục cũ rồi tải tiếp")
        if shutil.disk_usage(WEB_ROOT).free - total < MIN_FREE:
            raise ValueError("Máy chủ sắp đầy ổ đĩa, thử lại sau")
        tmp.unlink(missing_ok=True)
    elif not tmp.exists() or tmp.stat().st_size != offset:
        raise ValueError("Tải lên bị gián đoạn, hãy tải lại file này")
    left = length
    with open(tmp, "ab") as f:
        while left > 0:
            chunk = rfile.read(min(1 << 20, left))
            if not chunk:
                raise ValueError("Tải lên bị ngắt giữa chừng")
            f.write(chunk)
            left -= len(chunk)
    if offset + length < total:
        return False
    if not _looks_video(tmp):
        tmp.unlink(missing_ok=True)
        raise ValueError(f"{name}: không phải file video")
    folder = root / _safe_name(batch, "Video tải lên")
    if folder.name in (ct.OUT_DIRNAME,) or folder.name.startswith("."):
        folder = root / "Video tải lên"
    folder.mkdir(parents=True, exist_ok=True)
    nm = _safe_name(name, "video.mp4")
    dst, k = folder / nm, 1
    while dst.exists():
        dst = folder / f"{Path(nm).stem} ({k}){Path(nm).suffix}"
        k += 1
    tmp.rename(dst)
    vid = str(dst)
    with lock:
        if not any(gr["folder"] == str(folder) for gr in state["groups"]):
            state["groups"].append({"folder": str(folder), "name": folder.name})
        state["videos"][vid] = {"id": vid, "name": dst.name, "folder": str(folder), "status": "queued",
                                "segs": [], "auto_segs": [], "note": "", "duration": 0, "fps": 30}
        same = sorted([i for i in state["order"] if state["videos"][i]["folder"] == str(folder)] + [vid],
                      key=lambda i: _natural(Path(i).name))
        others = [i for i in state["order"] if state["videos"][i]["folder"] != str(folder)]
        state["order"] = others + same
    analyze_pool.submit(_analyze, vid)
    save_session()
    return True


def _drop_cache(vid: str):
    for f in (CACHE / f"{_key(vid)}.jpg", CACHE / f"prev_{_key(vid)}.mp4"):
        f.unlink(missing_ok=True)


def drop_folders(folders: list[str]):
    """Web: gỡ thư mục khỏi danh sách VÀ xoá file trên máy chủ."""
    with lock:
        gone = [i for i in state["order"] if state["videos"][i]["folder"] in folders]
        state["groups"] = [g for g in state["groups"] if g["folder"] not in folders]
        for vid in gone:
            state["videos"].pop(vid, None)
        state["order"] = [i for i in state["order"] if i in state["videos"]]
    for vid in gone:
        _drop_cache(vid)
    for f in folders:
        shutil.rmtree(f, ignore_errors=True)
    save_session()


def _janitor():
    while True:
        time.sleep(600)
        now = time.time()
        for d in WEB_ROOT.iterdir() if WEB_ROOT.exists() else []:
            try:
                if d.is_dir() and now - d.stat().st_mtime > TTL:
                    with lock:
                        mine = [g["folder"] for g in state["groups"] if Path(g["folder"]).parent == d]
                        working = any(state["videos"][i]["status"] in ("analyzing", "exporting")
                                      for i in state["order"] if state["videos"][i]["folder"] in mine)
                    if working:
                        continue
                    drop_folders(mine)
                    shutil.rmtree(d, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass


def zip_outputs(folders: list[str]) -> Path | None:
    with lock:
        outs = [(state["videos"][i]["folder"], state["videos"][i]["output"]) for i in state["order"]
                if state["videos"][i]["folder"] in folders and state["videos"][i].get("output")]
    outs = [(f, o) for f, o in outs if Path(o).exists()]
    if not outs:
        return None
    tmp = Path(tempfile.mkstemp(suffix=".zip", dir=CACHE)[1])
    multi = len({f for f, _ in outs}) > 1
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
        for f, o in outs:
            z.write(o, f"{Path(f).name}/{Path(o).name}" if multi else Path(o).name)
    return tmp


_prev_locks: dict[str, threading.Lock] = {}


def preview_path(vid: str) -> Path | None:
    """Bản xem trước H.264 (720p) cho trình duyệt không phát được codec gốc (vd HEVC). Tạo 1 lần, lưu tạm."""
    with lock:
        if vid not in state["videos"]:
            return None
        lk = _prev_locks.setdefault(vid, threading.Lock())
    dst = CACHE / f"prev_{_key(vid)}.mp4"
    with lk:
        if not dst.exists():
            tmp = dst.with_suffix(".tmp.mp4")
            r = ct.run(["ffmpeg", "-v", "error", "-y", "-i", vid, "-map", "0:v:0", "-map", "0:a:0?",
                        "-vf", "scale=-2:'min(720,ih)'", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(tmp)])
            if r.returncode:
                return None
            tmp.rename(dst)
    return dst


def edge_frames(vid: str, t: float, n: int = 3, width: int = 220) -> dict:
    with lock:
        fps = state["videos"][vid].get("fps") or 30
    win = (n + 2) / fps
    fr = ct.extract(Path(vid), max(0, t - win), 2 * win, width)
    before = [x for x in fr if x[0] < t - 1e-4][-n:]
    after = [x for x in fr if x[0] >= t - 1e-4][:n + 1]

    def enc(im):
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

    return {"before": [{"t": a, "img": enc(b)} for a, b in before],
            "after": [{"t": a, "img": enc(b)} for a, b in after]}


# ------------------------------------------------------------------ HTTP
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _ws(self) -> str | None:
        """Khu của trình duyệt này (web). Chưa có thì cấp mới qua cookie."""
        if not WEB:
            return None
        if getattr(self, "_wsid", None):
            return self._wsid
        m = re.search(r"(?:^|;\s*)ct_ws=([0-9a-f]{32})", self.headers.get("Cookie") or "")
        ws = m.group(1) if m else None
        if not ws or not _WS_RE.match(ws):
            ws = secrets.token_hex(16)
            self._newws = ws
        d = ws_dir(ws)
        if d.exists():
            os.utime(d)  # còn dùng -> chưa bị dọn (thư mục chỉ được tạo khi tải video lên)
        self._wsid = ws
        return ws

    def end_headers(self):
        if getattr(self, "_newws", None):
            self.send_header("Set-Cookie", f"ct_ws={self._newws}; Path=/; Max-Age={int(TTL)}; HttpOnly; SameSite=Lax")
            self._newws = None
        super().end_headers()

    def _v(self, s: str) -> str | None:
        """id video từ trình duyệt -> id thật (đã kiểm tra thuộc khu của người này)."""
        vid = from_pub(s, self._ws())
        with lock:
            return vid if vid in state["videos"] else None

    def _folder(self, s: str) -> str | None:
        f = from_pub(s, self._ws())
        with lock:
            return f if any(g["folder"] == f for g in state["groups"]) else None

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def _file(self, path: Path, ctype=None, download: str | None = None):
        size = path.stat().st_size
        ctype = ctype or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            if a:
                start = int(a)
                end = int(b) if b else size - 1
            else:
                start = size - int(b)
            end = min(end, size - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        if download:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + urllib.parse.quote(download))
        self.end_headers()
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    chunk = f.read(min(1 << 16, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _video_path(self, q, which="src") -> Path | None:
        name = self._v(q.get("v", [""])[0])
        with lock:
            if name not in state["videos"]:
                return None
            if which == "out":
                o = state["videos"][name].get("output")
                return Path(o) if o else None
            return Path(name)

    def do_GET(self):  # noqa: N802
        global last_ping
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            self._ws()
            return self._file(HERE / "ui" / "index.html", "text/html; charset=utf-8")
        if u.path == "/api/ping":
            last_ping = time.time()
            return self._json({"ok": True})
        if u.path == "/api/state":
            last_ping = time.time()
            return self._json(public_state(self._ws()))
        if u.path in ("/video", "/output"):
            p = self._video_path(q, "out" if u.path == "/output" else "src")
            if not p or not p.exists():
                return self._json({"error": "không thấy video"}, 404)
            ctype = mimetypes.guess_type(str(p))[0]
            return self._file(p, ctype if ctype and ctype.startswith("video/") else "video/mp4",
                              download=p.name if q.get("dl") else None)
        if u.path == "/api/zip":
            ws = self._ws()
            f = q.get("folder", [""])[0]
            with lock:
                folders = [self._folder(f)] if f else [g["folder"] for g in state["groups"] if _mine(g["folder"], ws)]
            folders = [x for x in folders if x]
            z = zip_outputs(folders)
            if not z:
                return self._json({"error": "Chưa có video nào đã xuất"}, 404)
            try:
                name = (Path(folders[0]).name if len(folders) == 1 else "video") + "_da_cat.zip"
                return self._file(z, "application/zip", download=name)
            finally:
                z.unlink(missing_ok=True)
        if u.path == "/preview":
            p = preview_path(self._v(q.get("v", [""])[0]) or "")
            if not p:
                return self._json({"error": "không tạo được bản xem trước"}, 404)
            return self._file(p, "video/mp4")
        if u.path == "/sprite":
            name = self._v(q.get("v", [""])[0])
            with lock:
                sp = state["videos"].get(name, {}).get("sprite")
            if not sp or not Path(sp).exists():
                return self._json({"error": "chưa có"}, 404)
            return self._file(Path(sp), "image/jpeg")
        if u.path == "/api/edge":
            name = self._v(q.get("v", [""])[0])
            t = float(q.get("t", ["0"])[0])
            n = int(q.get("n", ["3"])[0])
            with lock:
                ok = name in state["videos"]
            if not ok:
                return self._json({"error": "không thấy video"}, 404)
            return self._json(edge_frames(name, t, n))
        return self._json({"error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        u = urllib.parse.urlparse(self.path)
        if WEB:
            try:
                return self._post_web(u)
            except Exception as ex:  # noqa: BLE001
                return self._json({"error": f"{ex}" if isinstance(ex, ValueError) else f"{type(ex).__name__}: {ex}"}, 400)
        try:
            body = self._body()
            if u.path == "/api/open":
                return self._json(add_folders(body.get("folders") or [body["folder"]]))
            if u.path == "/api/pick":
                script = ('set fs to choose folder with prompt "Chọn một hoặc nhiều thư mục video '
                          '(giữ ⌘ để chọn nhiều):" with multiple selections allowed\n'
                          'set out to ""\nrepeat with f in fs\nset out to out & POSIX path of f & linefeed\n'
                          'end repeat\nreturn out')
                r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
                paths = [x for x in r.stdout.splitlines() if x.strip()]
                if r.returncode or not paths:
                    return self._json({"cancelled": True})
                return self._json(add_folders(paths))
            if u.path == "/api/clear":
                with lock:
                    state["groups"], state["videos"], state["order"] = [], {}, []
                save_session()
                return self._json(public_state())
            if u.path == "/api/remove":
                return self._json(remove_folder(body["folder"]))
            if u.path == "/api/segs":
                name = body["v"]
                segs = sorted([[round(max(0.0, float(a)), 4), round(float(b), 4)] for a, b in body["segs"] if float(b) > float(a)])
                with lock:
                    v = state["videos"][name]
                    v["segs"] = segs
                    if v["status"] == "done":
                        v["status"] = "ready"
                save_session()
                return self._json(public_state())
            if u.path == "/api/review":
                with lock:
                    state["videos"][body["v"]]["reviewed"] = bool(body.get("on", True))
                save_session()
                return self._json(public_state())
            if u.path == "/api/export":
                names = body.get("names") or [n for n in state["order"]
                                              if state["videos"][n]["status"] in ("ready", "done")]
                for n in names:
                    if state["videos"][n]["status"] in ("ready", "done", "error") and state["videos"][n].get("info"):
                        _set(n, status="exporting")
                        export_pool.submit(_export, n)
                return self._json(public_state())
            if u.path == "/api/reveal":
                with lock:
                    folders = [body["folder"]] if body.get("folder") else [g["folder"] for g in state["groups"]]
                for f in folders:
                    out = Path(f) / ct.OUT_DIRNAME
                    subprocess.run(["open", str(out if out.exists() else f)])
                return self._json({"ok": True})
        except Exception as ex:  # noqa: BLE001
            return self._json({"error": f"{type(ex).__name__}: {ex}"}, 400)
        return self._json({"error": "not found"}, 404)


    def _post_web(self, u):
        ws = self._ws()
        q = urllib.parse.parse_qs(u.query)
        if u.path == "/api/upload":
            done = upload_chunk(ws, q, self.rfile, int(self.headers.get("Content-Length") or 0))
            return self._json(public_state(ws) if done else {"ok": True})
        body = self._body()
        if u.path == "/api/clear":
            with lock:
                mine = [g["folder"] for g in state["groups"] if _mine(g["folder"], ws)]
            drop_folders(mine)
            return self._json(public_state(ws))
        if u.path == "/api/remove":
            f = self._folder(body.get("folder", ""))
            if f:
                drop_folders([f])
            return self._json(public_state(ws))
        if u.path == "/api/segs":
            name = self._v(body.get("v", ""))
            if not name:
                raise ValueError("không thấy video")
            segs = sorted([[round(max(0.0, float(a)), 4), round(float(b), 4)] for a, b in body["segs"] if float(b) > float(a)])
            with lock:
                v = state["videos"][name]
                v["segs"] = segs
                if v["status"] == "done":
                    v["status"] = "ready"
            save_session()
            return self._json(public_state(ws))
        if u.path == "/api/review":
            name = self._v(body.get("v", ""))
            if name:
                with lock:
                    state["videos"][name]["reviewed"] = bool(body.get("on", True))
                save_session()
            return self._json(public_state(ws))
        if u.path == "/api/export":
            with lock:
                names = [self._v(n) for n in body["names"]] if body.get("names") else \
                    [n for n in state["order"] if _mine(state["videos"][n]["folder"], ws)
                     and state["videos"][n]["status"] in ("ready", "done")]
                for n in filter(None, names):
                    if state["videos"][n]["status"] in ("ready", "done", "error") and state["videos"][n].get("info"):
                        state["videos"][n]["status"] = "exporting"
                        export_pool.submit(_export, n)
            return self._json(public_state(ws))
        return self._json({"error": "Không dùng được trên bản web"}, 403)


def _existing():
    try:
        info = json.loads(PORT_FILE.read_text())
        url = f"http://127.0.0.1:{info['port']}"
        urllib.request.urlopen(url + "/api/ping", timeout=1)
        return url
    except Exception:  # noqa: BLE001
        return None


def _post(url, path, obj):
    req = urllib.request.Request(url + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()


def _watchdog(server):
    while True:
        time.sleep(10)
        with lock:
            b = busy
        if b == 0 and time.time() - last_ping > IDLE_EXIT:
            server.shutdown()
            return


def main(argv):
    folders = [a for a in argv if a.strip()]
    if WEB:
        return main_web()
    url = _existing()
    if url:  # đã có giao diện đang chạy -> thêm thư mục vào đó
        if folders:
            _post(url, "/api/open", {"folders": folders})
        webbrowser.open(url)
        return 0
    server = ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("CAT_TUTORIAL_PORT", "0"))), H)
    port = server.server_address[1]
    PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    PORT_FILE.write_text(json.dumps({"port": port, "pid": os.getpid()}))
    load_session()
    if folders:
        try:
            add_folders(folders)
        except ValueError as ex:
            print(ex, flush=True)
    url = f"http://127.0.0.1:{port}"
    print(f"Giao diện: {url}", flush=True)
    if not os.environ.get("CAT_TUTORIAL_NO_OPEN"):
        webbrowser.open(url)
    threading.Thread(target=_watchdog, args=(server,), daemon=True).start()
    try:
        server.serve_forever()
    finally:
        try:
            if json.loads(PORT_FILE.read_text()).get("port") == port:
                PORT_FILE.unlink()
        except Exception:  # noqa: BLE001
            pass
    return 0


def main_web():
    port = int(os.environ.get("CAT_TUTORIAL_PORT", "8790"))
    server = ThreadingHTTPServer(("127.0.0.1", port), H)
    load_session()
    threading.Thread(target=_janitor, daemon=True).start()
    print(f"Cắt Tutorial (web) đang chạy: http://127.0.0.1:{port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    # Windows chạy ngầm (Task Scheduler) ghi log bằng cp1252 -> chữ tiếng Việt làm Python dừng. Luôn dùng UTF-8.
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    sys.exit(main(sys.argv[1:]))
