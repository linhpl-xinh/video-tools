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


def public_state() -> dict:
    with lock:
        vids = [{k: state["videos"][i].get(k) for k in (
            "id", "name", "folder", "status", "segs", "auto_segs", "note", "duration", "fps", "error",
            "output", "sprite_n", "exported_segs", "reviewed")} for i in state["order"]]
        return {"groups": [dict(g) for g in state["groups"]], "videos": vids,
                "out_dirname": ct.OUT_DIRNAME, "backend": ct.BACKEND}


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

    def _file(self, path: Path, ctype=None):
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
        name = q.get("v", [""])[0]
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
            return self._file(HERE / "ui" / "index.html", "text/html; charset=utf-8")
        if u.path == "/api/ping":
            last_ping = time.time()
            return self._json({"ok": True})
        if u.path == "/api/state":
            last_ping = time.time()
            return self._json(public_state())
        if u.path in ("/video", "/output"):
            p = self._video_path(q, "out" if u.path == "/output" else "src")
            if not p or not p.exists():
                return self._json({"error": "không thấy video"}, 404)
            ctype = mimetypes.guess_type(str(p))[0]
            return self._file(p, ctype if ctype and ctype.startswith("video/") else "video/mp4")
        if u.path == "/preview":
            p = preview_path(q.get("v", [""])[0])
            if not p:
                return self._json({"error": "không tạo được bản xem trước"}, 404)
            return self._file(p, "video/mp4")
        if u.path == "/sprite":
            name = q.get("v", [""])[0]
            with lock:
                sp = state["videos"].get(name, {}).get("sprite")
            if not sp or not Path(sp).exists():
                return self._json({"error": "chưa có"}, 404)
            return self._file(Path(sp), "image/jpeg")
        if u.path == "/api/edge":
            name = q.get("v", [""])[0]
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


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
