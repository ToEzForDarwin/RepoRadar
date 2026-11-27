"""Repo Radar: GitHub'daki en iyi repoları konu başlıklarına göre izler.
Sadece Python standart kütüphanesi kullanır. Kullanım:
  pythonw radar.py            -> arka planda çalışır, pencereyi açar
  pythonw radar.py --no-open  -> Windows açılışında (pencere açmadan)
  python  radar.py --once     -> bir kez günceller ve çıkar
"""
import json, os, sys, time, threading, subprocess, urllib.request, urllib.parse, urllib.error, webbrowser, shutil
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
LATEST = os.path.join(DATA, "latest.json")
HISTORY = os.path.join(DATA, "history.json")
LOG = os.path.join(DATA, "radar.log")
os.makedirs(DATA, exist_ok=True)
if sys.stderr is None or sys.stdout is None:  # pythonw: konsol yok, hataları dosyaya yaz
    _f = open(os.path.join(DATA, "errors.log"), "a", encoding="utf-8", buffering=1)
    sys.stderr = sys.stderr or _f
    sys.stdout = sys.stdout or _f
_lock = threading.Lock()
status = {"running": False, "message": "", "progress": ""}


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    if sys.stdout:
        try: print(line)
        except Exception: pass


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, path)


def config():
    return load_json(os.path.join(BASE, "categories.json"), {})


TOKEN_FILE = os.path.join(DATA, "token.txt")


def get_token():
    try:
        with open(TOKEN_FILE, encoding="utf-8") as f:
            t = f.read().strip()
            if t: return t
    except OSError:
        pass
    return config().get("github_token") or os.environ.get("GITHUB_TOKEN", "")


def gh_get(path, token):
    req = urllib.request.Request("https://api.github.com" + path, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "repo-radar", "Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_mine(token):
    """Kendi hesabının repoları (gizliler dahil). Sadece okur."""
    me = gh_get("/user", token)
    repos = []
    for page in range(1, 4):
        items = gh_get(f"/user/repos?per_page=100&page={page}&sort=pushed&affiliation=owner,collaborator", token)
        repos += items
        if len(items) < 100: break
    rows = [{"repo": it["full_name"], "url": it["html_url"], "stars": it["stargazers_count"],
             "desc": (it.get("description") or "")[:300], "lang": it.get("language") or "",
             "license": (it.get("license") or {}).get("spdx_id") or "", "pushed": it.get("pushed_at") or "",
             "created": it.get("created_at") or "", "topics": (it.get("topics") or [])[:6],
             "private": it.get("private", False), "issues": it.get("open_issues_count", 0),
             "fork": it.get("fork", False)} for it in repos]
    return me.get("login", ""), rows


def search(q, token, per_page=30):
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": q, "sort": "stars", "order": "desc", "per_page": per_page})
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "repo-radar"}
    if token:
        headers["Authorization"] = "Bearer " + token
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                return json.load(r).get("items", [])
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and attempt < 2:
                log(f"GitHub sınırı, 65 sn bekleniyor ({q})")
                time.sleep(65)
                continue
            if e.code >= 500 and attempt < 2:
                time.sleep(10)
                continue
            raise
        except urllib.error.URLError:
            if attempt < 2:
                time.sleep(10); continue
            raise
    return []


def fill(q, active_only):
    now = datetime.now(timezone.utc)
    q = q.replace("{d30}", (now - timedelta(days=30)).strftime("%Y-%m-%d"))
    if active_only:
        q += " archived:false pushed:>" + (now - timedelta(days=365)).strftime("%Y-%m-%d")
    return q


def hints(r, delta7):
    """Otomatik, dürüst işaretler (insan yorumu değil)."""
    h = []
    pushed = r.get("pushed", "")
    try:
        days = (datetime.now(timezone.utc) - datetime.fromisoformat(pushed.replace("Z", "+00:00"))).days
    except ValueError:
        days = None
    if days is not None:
        if days <= 30: h.append(["ok", "Aktif (son 30 gün)"])
        elif days > 365: h.append(["bad", f"Durgun ({days // 30} aydır güncellenmiyor)"])
        elif days > 180: h.append(["warn", "Yavaşlamış (6+ ay)"])
    lic = r.get("license")
    if not lic:
        h.append(["bad", "Lisans yok: kullanmak yasal olarak riskli"])
    elif lic in ("NOASSERTION",):
        h.append(["warn", "Özel lisans: metnini oku"])
    elif lic.startswith(("AGPL", "GPL")):
        h.append(["warn", f"{lic}: kapalı kaynak üründe dikkat"])
    else:
        h.append(["ok", f"{lic}: serbest lisans"])
    if delta7 is not None and r["stars"] > 0 and delta7 >= max(200, r["stars"] * 0.05):
        h.append(["ok", f"Hızlı yükseliyor (+{delta7:,} / 7 gün)"])
    return h


PROJECTS = os.path.join(BASE, "projects.json")
_live = {"at": 0, "data": {}, "prev_runs": {}}
_live_lock = threading.Lock()


def repo_live(repo, token):
    """Bir reponun anlık durumu. Sadece okur."""
    q = urllib.parse.quote
    out = {"repo": repo, "url": f"https://github.com/{repo}"}
    try:
        info = gh_get(f"/repos/{repo}", token) if token else json.load(urllib.request.urlopen(
            urllib.request.Request(f"https://api.github.com/repos/{repo}", headers={"User-Agent": "repo-radar"}), timeout=30))
    except urllib.error.HTTPError as e:
        out["error"] = "Repo görülemiyor (gizliyse token gerekli)" if e.code in (401, 403, 404) else f"GitHub hatası {e.code}"
        return out
    out.update(pushed=info.get("pushed_at"), private=info.get("private"), branch=info.get("default_branch"))
    def safe(path):
        try: return gh_get(path, token) if token else None
        except Exception: return None
    c = safe(f"/repos/{repo}/commits?per_page=1")
    if c:
        c = c[0]
        out["commit"] = {"msg": (c["commit"]["message"] or "").split("\n")[0][:140], "date": c["commit"]["author"]["date"],
                         "author": (c.get("author") or {}).get("login") or c["commit"]["author"]["name"], "url": c["html_url"]}
    r = safe(f"/repos/{repo}/actions/runs?per_page=1")
    if r and r.get("workflow_runs"):
        w = r["workflow_runs"][0]
        out["build"] = {"name": w.get("name") or w.get("display_title"), "status": w.get("status"), "conclusion": w.get("conclusion"),
                        "date": w.get("updated_at"), "url": w.get("html_url"), "id": w.get("id"), "number": w.get("run_number")}
    prs = safe(f"/repos/{repo}/pulls?state=open&per_page=100")
    if prs is not None: out["prs"] = len(prs)
    iss = safe(f"/repos/{repo}/issues?state=open&per_page=100")
    if iss is not None: out["issues"] = len([i for i in iss if "pull_request" not in i])
    ms = safe(f"/repos/{repo}/milestones?state=open&sort=due_on&per_page=1")
    if ms:
        m = ms[0]; tot = m["open_issues"] + m["closed_issues"]
        out["milestone"] = {"title": m["title"], "done": m["closed_issues"], "total": tot,
                            "pct": round(100 * m["closed_issues"] / tot) if tot else 0, "url": m["html_url"]}
    return out


def projects_live(force=False):
    with _live_lock:
        if not force and time.time() - _live["at"] < 90:
            return _live["data"]
        token = get_token()
        data = {}
        for pr in load_json(PROJECTS, {}).get("projects", []):
            for repo in pr.get("repos", []):
                if repo not in data:
                    data[repo] = repo_live(repo, token)
        # build sonucu değişince bildirim
        for repo, d in data.items():
            b = d.get("build")
            if not b or b.get("status") != "completed": continue
            prev = _live["prev_runs"].get(repo)
            if prev and prev != b["id"] and config().get("notify", True):
                ok = b.get("conclusion") == "success"
                toast("Repo Radar", f"{repo.split('/')[-1]}: build #{b.get('number')} {'başarılı ✅' if ok else 'BAŞARISIZ ❌'}")
            _live["prev_runs"][repo] = b["id"]
        _live.update(at=time.time(), data=data)
        return data


def project_watcher():
    while True:
        try: projects_live(force=True)
        except Exception as e: log(f"Proje durumu alınamadı: {e}")
        time.sleep(300)


KEEP = {"categories.json", "projects.json"}  # kullanıcının dosyaları: güncellemede ezilmez
_upd = {"latest": None, "checked": 0}


def local_version():
    try:
        with open(os.path.join(BASE, "VERSION"), encoding="utf-8") as f: return f.read().strip()
    except OSError: return "0"


def vtuple(v):
    try: return tuple(int(x) for x in v.split("."))
    except ValueError: return (0,)


def check_update():
    repo, token = config().get("update_repo", "ToEzForDarwin/RepoRadar"), get_token()
    if not repo or not token: return None
    try:
        d = gh_get(f"/repos/{repo}/contents/VERSION", token)
        import base64
        v = base64.b64decode(d["content"]).decode().strip()
        _upd.update(latest=v, checked=time.time())
        return v
    except Exception as e:
        log(f"Güncelleme kontrolü başarısız: {e}")
        return None


def apply_update():
    import zipfile, io
    repo, token = config().get("update_repo", "ToEzForDarwin/RepoRadar"), get_token()
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/zipball", headers={
        "User-Agent": "repo-radar", "Authorization": "Bearer " + token})
    with urllib.request.urlopen(req, timeout=60) as r:
        z = zipfile.ZipFile(io.BytesIO(r.read()))
    n = 0
    for name in z.namelist():
        rel = name.split("/", 1)[1] if "/" in name else ""
        if not rel or rel.endswith("/") or rel.startswith(("data/", ".")) or "/" in rel or ".." in rel: continue
        if rel in KEEP and os.path.exists(os.path.join(BASE, rel)): continue
        with open(os.path.join(BASE, rel), "wb") as f: f.write(z.read(name))
        n += 1
    log(f"Güncellendi: {n} dosya, yeniden başlatılıyor")
    exe = sys.executable
    args = [a for a in sys.argv[1:] if a not in ("--no-open", "--after-update")]
    subprocess.Popen([exe, os.path.join(BASE, "radar.py"), "--no-open", "--after-update"] + args,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    os._exit(0)


def refresh():
    if not _lock.acquire(blocking=False):
        return False
    status.update(running=True, message="Güncelleniyor...")
    try:
        cfg = config()
        token = get_token()
        gap = 2.2 if token else 6.5  # GitHub arama sınırı: tokensız 10/dk
        top_n = int(cfg.get("top_n", 20))
        prev = load_json(LATEST, {})
        hist = load_json(HISTORY, {})
        today = datetime.now().strftime("%Y-%m-%d")
        cats_out = []
        cats = cfg.get("categories", [])
        total_q = sum(len(c["queries"]) for c in cats)
        done = 0
        for c in cats:
            seen = {}
            for q in c["queries"]:
                done += 1
                status["progress"] = f"{done}/{total_q}: {c['name']}"
                try:
                    items = search(fill(q, c.get("active_only", True)), token)
                except Exception as e:
                    log(f"Sorgu hatası {q}: {e}")
                    items = []
                for it in items:
                    seen[it["full_name"]] = {
                        "repo": it["full_name"], "url": it["html_url"], "stars": it["stargazers_count"],
                        "desc": (it.get("description") or "")[:300], "lang": it.get("language") or "",
                        "license": (it.get("license") or {}).get("spdx_id") or "",
                        "pushed": it.get("pushed_at") or "", "created": it.get("created_at") or "",
                        "topics": (it.get("topics") or [])[:6]}
                time.sleep(gap)
            rows = sorted(seen.values(), key=lambda r: -r["stars"])[:top_n]
            if not rows:  # sorgu başarısızsa eski listeyi koru
                rows = next((pc["rows"] for pc in prev.get("categories", []) if pc["id"] == c["id"]), [])
            cats_out.append({"id": c["id"], "name": c["name"], "rows": rows})
        if not any(c["rows"] for c in cats_out):
            status["message"] = "Güncelleme başarısız (internet veya GitHub sınırı). Eski veri gösteriliyor."
            log(status["message"])
            return False
        # geçmiş ve 7 günlük değişim
        cutoff = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        for c in cats_out:
            for r in c["rows"]:
                h = hist.setdefault(r["repo"], {})
                h[today] = r["stars"]
        for k in list(hist):
            hist[k] = {d: s for d, s in hist[k].items() if d >= cutoff}
            if not hist[k]: del hist[k]
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        for c in cats_out:
            for r in c["rows"]:
                past = [d for d in hist.get(r["repo"], {}) if d <= week_ago]
                older = sorted(hist.get(r["repo"], {}))
                base = hist[r["repo"]][max(past)] if past else (hist[r["repo"]][older[0]] if older and older[0] != today else None)
                r["delta7"] = r["stars"] - base if base is not None else None
                r["delta_since"] = (max(past) if past else (older[0] if older and older[0] != today else None))
                r["hints"] = hints(r, r["delta7"])
        # yeni girenler
        prev_sets = {c["id"]: {r["repo"] for r in c.get("rows", [])} for c in prev.get("categories", [])}
        news = []
        for c in cats_out:
            if c["id"] in prev_sets:
                for r in c["rows"]:
                    if r["repo"] not in prev_sets[c["id"]]:
                        r["new"] = True
                        news.append((c["name"], r))
        mine, login = None, ""
        if token:
            status["progress"] = "Kendi repoların"
            try:
                login, rows = fetch_mine(token)
                old = {r["repo"]: r["stars"] for r in prev.get("mine", {}).get("rows", [])}
                for r in rows:
                    r["delta_prev"] = r["stars"] - old[r["repo"]] if r["repo"] in old else None
                mine = {"id": "benim", "name": "Benim repolarım", "login": login, "rows": rows}
                gained = [r for r in rows if (r["delta_prev"] or 0) > 0]
                if gained and cfg.get("notify", True):
                    g = max(gained, key=lambda r: r["delta_prev"])
                    toast("Repo Radar", f"Repon {g['repo']} +{g['delta_prev']} yıldız aldı (★ {g['stars']:,})")
            except Exception as e:
                log(f"Kendi repoların alınamadı: {e}")
                mine = prev.get("mine")
        out = {"updated": datetime.now().isoformat(timespec="seconds"), "categories": cats_out, "mine": mine}
        save_json(LATEST, out)
        save_json(HISTORY, hist)
        status["message"] = f"Güncellendi: {datetime.now():%d.%m %H:%M}"
        log(f"Güncellendi, {len(news)} yeni giriş")
        if news and cfg.get("notify", True):
            first = news[0]
            more = f" (+{len(news) - 1} başka)" if len(news) > 1 else ""
            toast("Repo Radar", f"{first[0]}: {first[1]['repo']} listeye girdi (★ {first[1]['stars']:,}){more}")
        return True
    finally:
        status.update(running=False, progress="")
        _lock.release()


def toast(title, text):
    if os.name != "nt":
        log(f"[bildirim] {title}: {text}")
        return
    esc = lambda s: (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                     .replace('"', "&quot;").replace("'", "''"))
    ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
          "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null;"
          f"$x = New-Object Windows.Data.Xml.Dom.XmlDocument; $x.LoadXml('<toast><visual><binding template=\"ToastGeneric\"><text>{esc(title)}</text><text>{esc(text)}</text></binding></visual></toast>');"
          "$app='{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe';"
          "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($x))")
    try:
        subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                       timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        log(f"Bildirim gösterilemedi: {e}")


def scheduler():
    while True:
        hours = float(config().get("refresh_hours", 6))
        last = load_json(LATEST, {}).get("updated")
        age = (datetime.now() - datetime.fromisoformat(last)).total_seconds() / 3600 if last else 1e9
        if age >= hours:
            try: refresh()
            except Exception as e: log(f"Güncelleme hatası: {e}")
        time.sleep(300)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def send(self, code, body, ctype):
        b = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def local_only(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            self.send(403, "yasak", "text/plain"); return False
        return True

    def do_GET(self):
        try:
            self._get()
        except Exception:
            import traceback
            log("Sayfa hatası " + self.path + ": " + traceback.format_exc())
            try: self.send(500, "Repo Radar hata verdi. Ayrıntı: data\\radar.log", "text/plain; charset=utf-8")
            except Exception: pass

    def _get(self):
        if not self.local_only(): return
        if self.path in ("/", "/index.html"):
            with open(os.path.join(BASE, "index.html"), encoding="utf-8") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        if self.path == "/api/data":
            d = load_json(LATEST, {"categories": []})
            d["notes"] = load_json(os.path.join(BASE, "notes.json"), {}).get("notes", {})
            d["status"] = status
            d["has_token"] = bool(get_token())
            if time.time() - _upd["checked"] > 3600: threading.Thread(target=check_update, daemon=True).start()
            d["version"] = local_version()
            d["update"] = _upd["latest"] if _upd["latest"] and vtuple(_upd["latest"]) > vtuple(local_version()) else None
            d["projects"] = load_json(PROJECTS, {})
            return self.send(200, json.dumps(d, ensure_ascii=False), "application/json; charset=utf-8")
        if self.path.startswith("/api/projects"):
            return self.send(200, json.dumps({"live": projects_live(force="force" in self.path),
                                              "at": datetime.fromtimestamp(_live["at"]).isoformat(timespec="seconds")},
                                             ensure_ascii=False), "application/json; charset=utf-8")
        if self.path == "/api/status":
            return self.send(200, json.dumps(status, ensure_ascii=False), "application/json; charset=utf-8")
        self.send(404, "yok", "text/plain")

    def do_POST(self):
        if not self.local_only(): return
        if self.path == "/api/token" and self.headers.get("X-Radar") == "1":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                token = json.loads(self.rfile.read(min(n, 10000)) or b"{}").get("token", "").strip()
                if not token:
                    if os.path.exists(TOKEN_FILE): os.remove(TOKEN_FILE)
                    return self.send(200, json.dumps({"ok": True, "login": ""}), "application/json")
                login = gh_get("/user", token).get("login", "")
                with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                    f.write(token)
                threading.Thread(target=refresh, daemon=True).start()
                return self.send(200, json.dumps({"ok": True, "login": login}), "application/json")
            except Exception as e:
                return self.send(400, json.dumps({"ok": False, "error": "Token geçersiz veya GitHub'a ulaşılamadı."}, ensure_ascii=False), "application/json")
        if self.path == "/api/project-edit" and self.headers.get("X-Radar") == "1":
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(n, 20000)) or b"{}")
            pj = load_json(PROJECTS, {"projects": []})
            i = body.get("index")
            if not isinstance(i, int) or not 0 <= i < len(pj["projects"]):
                return self.send(400, "{}", "application/json")
            for k in ("status", "next", "progress"):
                if k in body:
                    v = body[k]
                    if k == "progress":
                        try: v = max(0, min(100, int(v)))
                        except (TypeError, ValueError): continue
                    else:
                        v = str(v)[:500]
                    pj["projects"][i][k] = v
            save_json(PROJECTS, pj)
            return self.send(200, json.dumps({"ok": True}), "application/json")
        if self.path == "/api/update" and self.headers.get("X-Radar") == "1":
            self.send(202, "{}", "application/json")
            threading.Timer(0.5, apply_update).start()
            return
        if self.path == "/api/refresh" and self.headers.get("X-Radar") == "1":
            threading.Thread(target=refresh, daemon=True).start()
            return self.send(202, "{}", "application/json")
        self.send(404, "yok", "text/plain")


def screen_area():
    """Windows'ta görev çubuğu hariç ekran alanı (sol, üst, sağ, alt)."""
    if os.name != "nt":
        return (0, 0, 1920, 1040)
    import ctypes, ctypes.wintypes
    r = ctypes.wintypes.RECT()
    ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA
    return (r.left, r.top, r.right, r.bottom)


def open_window(port):
    url = f"http://127.0.0.1:{port}/"
    w = int(config().get("widget_width", 440))
    left, top, right, bottom = screen_area()
    prof = os.path.join(DATA, "edge-profile")  # ayrı profil: konum/boyut her seferinde uygulanır
    for exe in ("msedge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        path = shutil.which(exe) or (exe if os.path.exists(exe) else None)
        if path:
            subprocess.Popen([path, f"--app={url}", f"--user-data-dir={prof}", "--no-first-run",
                              f"--window-size={w},{bottom - top}", f"--window-position={right - w},{top}"])
            return
    webbrowser.open(url)


def make_icon_image():
    from PIL import Image, ImageDraw
    s = 64
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, s - 2, s - 2), fill=(47, 111, 222, 255))
    for r in (22, 14):
        d.ellipse((s/2 - r, s/2 - r, s/2 + r, s/2 + r), outline=(255, 255, 255, 230), width=3)
    d.line((s/2, s/2, s/2 + 20, s/2 - 16), fill=(255, 255, 255, 255), width=4)
    d.ellipse((s/2 - 4, s/2 - 4, s/2 + 4, s/2 + 4), fill=(255, 255, 255, 255))
    return img


def run_tray(port, server):
    """Bildirim alanı simgesi. pystray yoksa False döner."""
    try:
        import pystray
        img = make_icon_image()
    except Exception as e:
        log(f"Bildirim alanı simgesi yok ({e}). 'pip install pystray pillow' ile eklenir.")
        return False

    def quit_app(icon, item):
        icon.stop()
        threading.Thread(target=server.shutdown, daemon=True).start()

    menu = pystray.Menu(
        pystray.MenuItem("Repo Radar'ı aç", lambda i, it: open_window(port), default=True),
        pystray.MenuItem("Şimdi yenile", lambda i, it: threading.Thread(target=refresh, daemon=True).start()),
        pystray.MenuItem("Çıkış", quit_app))
    pystray.Icon("RepoRadar", img, "Repo Radar", menu).run()
    return True


def is_ours(port):
    """O portta gerçekten Repo Radar mı çalışıyor?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=3) as r:
            return "running" in json.load(r)
    except Exception:
        return False


def main():
    cfg = config()
    base_port = int(cfg.get("port", 8765))
    if "--once" in sys.argv:
        refresh(); return
    if "--after-update" in sys.argv:
        time.sleep(3)  # eski sürümün kapanmasını bekle
    server, port = None, None
    for p in range(base_port, base_port + 15):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", p), Handler)
            port = p
            break
        except OSError:
            if is_ours(p):  # zaten çalışıyor: sadece pencereyi aç
                if "--no-open" not in sys.argv: open_window(p)
                return
            log(f"Port {p} başka bir program tarafından kullanılıyor, sonrakine geçiliyor")
    if server is None:
        log("Boş port bulunamadı"); return
    threading.Thread(target=scheduler, daemon=True).start()
    threading.Thread(target=project_watcher, daemon=True).start()
    if "--no-open" not in sys.argv:
        threading.Timer(0.8, open_window, args=[port]).start()
    log(f"Repo Radar çalışıyor: http://127.0.0.1:{port}/")
    if "--no-tray" in sys.argv:
        server.serve_forever(); return
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    if not run_tray(port, server):
        t.join()


if __name__ == "__main__":
    main()
