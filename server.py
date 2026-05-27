#!/usr/bin/env python3
"""
Vintage Daily Digest — 로컬 개발 서버
정적 파일 서빙 + 업데이트 API (/api/update)

실행: python server.py
접속: http://localhost:4322
"""
import os, json, subprocess, datetime, re, sys, secrets, functools, shutil

# 자막 + LLM 요약 (옵션 — 의존 모듈 없거나 키 없으면 자동 비활성)
try:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
    YT_TRANS_OK = True
except Exception:
    YT_TRANS_OK = False
try:
    import anthropic
    ANTHROPIC_OK = True
except Exception:
    ANTHROPIC_OK = False
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5")

# 한글 우선 + 의미 있는 라인 추출 (해외 채널 대비 fallback 포함)
_HANGUL_RE = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")

def _meaningful(line):
    """URL/해시태그/멘션/이모지만 있는 줄 제외 — 알파벳·한글 5자 이상이어야 함."""
    if not line:
        return False
    cnt = sum(1 for c in line if c.isalpha() or '가' <= c <= '힣')
    return cnt >= 5

def _accumulate(lines, start_idx, target_len=120, hard_max=200):
    """start_idx 부터 의미 있는 라인들을 이어붙여 target_len 도달까지 누적.
       다음 의미 없는 줄(해시태그/URL/멘션 etc.) 만나면 중단."""
    parts = []
    total = 0
    for i in range(start_idx, len(lines)):
        line = lines[i]
        if not _meaningful(line):
            if parts:
                break  # 의미 있는 단락 끝
            continue   # 시작 전 잡음 스킵
        parts.append(line)
        total += len(line)
        if total >= target_len:
            break
    out = " ".join(parts)
    return out[:hard_max]

def pick_summary(desc, max_len=200):
    if not desc:
        return ""
    lines = [l.strip() for l in str(desc).split("\n") if l.strip()]
    # 1순위: 한글 + 의미 있는 첫 줄에서 시작해 단락 누적
    for i, line in enumerate(lines):
        if _HANGUL_RE.search(line) and _meaningful(line):
            return _accumulate(lines, i, hard_max=max_len)
    # 2순위: 한글 포함 줄 그대로
    for line in lines:
        if _HANGUL_RE.search(line):
            return line[:max_len]
    # 3순위: 외국어라도 의미 있는 첫 줄에서 시작해 단락 누적
    for i, line in enumerate(lines):
        if _meaningful(line):
            return _accumulate(lines, i, hard_max=max_len)
    # 4순위: 그냥 첫 줄
    return (lines[0] if lines else "")[:max_len]


def _fetch_one(video_id, langs):
    """youtube-transcript-api 호출 (구/신 API 자동 감지)."""
    # 신 API (1.x): YouTubeTranscriptApi().fetch(...)
    if hasattr(YouTubeTranscriptApi, "fetch") and not hasattr(YouTubeTranscriptApi, "get_transcript"):
        ytt = YouTubeTranscriptApi()
        fetched = ytt.fetch(video_id, languages=langs) if langs else ytt.fetch(video_id)
        return [{"text": getattr(s, "text", "")} for s in fetched]
    # 구 API (0.x): classmethod get_transcript
    if langs:
        return YouTubeTranscriptApi.get_transcript(video_id, languages=langs)
    return YouTubeTranscriptApi.get_transcript(video_id)

def fetch_transcript(video_id):
    """YouTube 자막 — 한국어 우선 → 영어 → 그 외. 실패시 None."""
    if not YT_TRANS_OK or not video_id:
        return None
    for langs in (["ko"], ["en"], None):
        try:
            data = _fetch_one(video_id, langs)
            text = " ".join(d.get("text", "") for d in data)
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                return text
        except (NoTranscriptFound, TranscriptsDisabled):
            if langs is None:
                return None
            continue
        except Exception as e:
            print(f"[transcript] {video_id} error: {e}", flush=True)
            return None
    return None


def summarize_with_claude(text, title="", target_chars=120):
    """Claude Haiku 로 핵심 내용 한국어 요약. 실패시 None."""
    if not ANTHROPIC_OK or not ANTHROPIC_API_KEY or not text:
        return None
    text = str(text)[:6000]
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    f"다음은 유튜브 영상의 자막 또는 설명입니다. "
                    f"영상 제목: '{title}'\n\n"
                    f"이 영상의 핵심 내용을 한국어로 약 {target_chars}자 이내, 한 문단으로 요약해주세요. "
                    f"인사말·구독요청·광고는 제외하고 정보가 되는 부분만. 요약문만 출력하세요.\n\n"
                    f"---\n{text}\n---"
                )
            }]
        )
        out = "".join(getattr(b, "text", "") for b in msg.content).strip()
        out = out.replace("\n", " ")
        return out[:target_chars * 2] if out else None
    except Exception as e:
        print(f"[claude] error: {e}", flush=True)
        return None


def build_smart_summary(video_id, title, fallback_desc):
    """자막 → Claude 요약 → 실패시 description → Claude → 실패시 pick_summary.
    반환: (summary_text, source_kind) — source_kind in {claude_transcript, claude_description, heuristic, ''}"""
    transcript = fetch_transcript(video_id)
    if transcript:
        s = summarize_with_claude(transcript, title)
        if s:
            return s, "claude_transcript"
    if fallback_desc:
        s = summarize_with_claude(fallback_desc, title)
        if s:
            return s, "claude_description"
    return pick_summary(fallback_desc or ""), ("heuristic" if fallback_desc else "")


from flask import Flask, request, jsonify, send_from_directory, session
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
# DATA_ROOT — 영구 저장 위치 (Render Disk 등). 미설정 시 BASE_DIR 사용.
DATA_ROOT = os.environ.get("DATA_ROOT", BASE_DIR)
USERS_FP  = os.path.join(DATA_ROOT, "users.json")
LIKES_DIR = os.path.join(DATA_ROOT, "likes")
STATE_DIR = os.path.join(DATA_ROOT, "_state")
TRASH_FP  = os.path.join(STATE_DIR, "trash.json")
PERMDEL_FP= os.path.join(STATE_DIR, "permdel.json")
SECRET_FP = os.path.join(DATA_ROOT, ".flask-secret")
DATA_DIR  = os.path.join(DATA_ROOT, "data")

os.makedirs(DATA_ROOT, exist_ok=True)
os.makedirs(LIKES_DIR, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)

# 첫 실행 / 새 디스크 — 시드 데이터 복사
_seed_data = os.path.join(BASE_DIR, "data")
if not os.path.exists(DATA_DIR) and os.path.exists(_seed_data):
    shutil.copytree(_seed_data, DATA_DIR)
os.makedirs(DATA_DIR, exist_ok=True)

# Persistent secret key
if os.path.exists(SECRET_FP):
    with open(SECRET_FP, "rb") as f:
        _secret = f.read()
else:
    _secret = secrets.token_bytes(32)
    with open(SECRET_FP, "wb") as f:
        f.write(_secret)

app = Flask(__name__)
app.secret_key = _secret
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# 프로덕션(HTTPS) 에서는 secure cookie
if (os.environ.get("FLASK_ENV") == "production"
        or os.environ.get("RENDER") == "true"
        or os.environ.get("FLY_APP_NAME")):
    app.config["SESSION_COOKIE_SECURE"] = True


# ───────────────────────────────────────────────
# 사용자/세션 헬퍼
# ───────────────────────────────────────────────
def _read_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def read_users():    return _read_json(USERS_FP, [])
def write_users(v): _write_json(USERS_FP, v)
def read_trash():   return _read_json(TRASH_FP, [])
def write_trash(v): _write_json(TRASH_FP, v)
def read_permdel(): return _read_json(PERMDEL_FP, {})
def write_permdel(v): _write_json(PERMDEL_FP, v)

def user_likes_path(uid): return os.path.join(LIKES_DIR, f"{uid}.json")
def read_user_likes(uid): return _read_json(user_likes_path(uid), [])
def write_user_likes(uid, v): _write_json(user_likes_path(uid), v)

def find_user_by_id(uid):
    for u in read_users():
        if u.get("id") == uid:
            return u
    return None

def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    return find_user_by_id(uid)

def current_role():
    u = current_user()
    return u.get("role") if u else "anonymous"

def admin_only(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        if current_role() != "admin":
            return jsonify({"error": "admin only"}), 403
        return fn(*a, **kw)
    return wrapper

def login_required(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        if not current_user():
            return jsonify({"error": "login required"}), 401
        return fn(*a, **kw)
    return wrapper


# ───────────────────────────────────────────────
# 정적 파일 서빙
# ───────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "index.html")

@app.route("/data/<path:path>")
def serve_data(path):
    # 동적 데이터는 DATA_DIR(영구 디스크) 에서 제공
    resp = send_from_directory(DATA_DIR, path)
    resp.headers["Cache-Control"] = "no-store"
    return resp

@app.route("/<path:path>")
def static_files(path):
    full = os.path.join(BASE_DIR, path.replace("/", os.sep))
    if os.path.isdir(full):
        return send_from_directory(full, "index.html")
    resp = send_from_directory(BASE_DIR, path)
    # JS/JSON 캐시 방지
    if path.endswith((".js", ".json")):
        resp.headers["Cache-Control"] = "no-store"
    return resp


# ───────────────────────────────────────────────
# /api/update  POST
# body: { topicId, keywords, channels, excludeIds }
# ───────────────────────────────────────────────
# ───────────────────────────────────────────────
# 인증
# ───────────────────────────────────────────────
@app.route("/api/me", methods=["GET"])
def api_me():
    u = current_user()
    if not u:
        return jsonify({"role": "anonymous"})
    return jsonify({"id": u["id"], "role": u.get("role", "user")})

@app.route("/api/signup", methods=["POST"])
def api_signup():
    body = request.get_json(force=True)
    uid = (body.get("id") or "").strip()
    pw  = body.get("password") or ""
    if not uid or not pw:
        return jsonify({"error": "ID와 비밀번호를 입력해 주세요."}), 400
    if len(uid) < 2 or len(uid) > 32:
        return jsonify({"error": "ID는 2~32자."}), 400
    if len(pw) < 4:
        return jsonify({"error": "비밀번호는 4자 이상."}), 400
    users = read_users()
    if any(u.get("id") == uid for u in users):
        return jsonify({"error": "이미 존재하는 ID."}), 409
    role = "admin" if not users else "user"  # 첫 가입자 자동 admin
    users.append({
        "id":            uid,
        "password_hash": generate_password_hash(pw),
        "role":          role,
        "created_at":    datetime.datetime.now().isoformat(timespec="seconds"),
    })
    write_users(users)
    session["user_id"] = uid
    return jsonify({"id": uid, "role": role})

@app.route("/api/login", methods=["POST"])
def api_login():
    body = request.get_json(force=True)
    uid = (body.get("id") or "").strip()
    pw  = body.get("password") or ""
    u = find_user_by_id(uid)
    if not u or not check_password_hash(u.get("password_hash", ""), pw):
        return jsonify({"error": "ID 또는 비밀번호가 올바르지 않습니다."}), 401
    session["user_id"] = uid
    return jsonify({"id": uid, "role": u.get("role", "user")})

@app.route("/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


# ───────────────────────────────────────────────
# 좋아요 (사용자 본인 데이터)
# ───────────────────────────────────────────────
@app.route("/api/likes", methods=["GET"])
@login_required
def api_likes_get():
    u = current_user()
    return jsonify(read_user_likes(u["id"]))

@app.route("/api/likes", methods=["POST"])
@login_required
def api_likes_add():
    u = current_user()
    body = request.get_json(force=True)
    topic = body.get("topic")
    video = body.get("video") or {}
    vid = video.get("id")
    if not topic or not vid:
        return jsonify({"error": "topic + video.id 필수"}), 400
    likes = read_user_likes(u["id"])
    likes = [l for l in likes if not (l.get("topic") == topic and l.get("videoId") == vid)]
    likes.insert(0, {
        "topic":    topic,
        "videoId":  vid,
        "likedAt":  int(datetime.datetime.now().timestamp() * 1000),
        "video":    video,
    })
    write_user_likes(u["id"], likes)
    return jsonify({"ok": True, "count": len(likes)})

@app.route("/api/likes/<vid>", methods=["DELETE"])
@login_required
def api_likes_remove(vid):
    u = current_user()
    topic = request.args.get("topic", "")
    likes = read_user_likes(u["id"])
    likes2 = [l for l in likes
              if not (l.get("videoId") == vid and (not topic or l.get("topic") == topic))]
    write_user_likes(u["id"], likes2)
    return jsonify({"ok": True, "count": len(likes2)})

@app.route("/api/likes/clear", methods=["POST"])
@login_required
def api_likes_clear():
    u = current_user()
    write_user_likes(u["id"], [])
    return jsonify({"ok": True})


# ───────────────────────────────────────────────
# 휴지통 (admin 전용 — 모든 방문자에게 공유)
# ───────────────────────────────────────────────
@app.route("/api/trash", methods=["GET"])
def api_trash_get():
    # 보기는 admin 만
    if current_role() != "admin":
        return jsonify([])
    return jsonify(read_trash())

@app.route("/api/trash", methods=["POST"])
@admin_only
def api_trash_move():
    body = request.get_json(force=True)
    topic_id = body.get("topic")
    vid = body.get("videoId")
    if not topic_id or not vid:
        return jsonify({"error": "topic + videoId 필수"}), 400
    data_path = os.path.join(DATA_DIR, f"{topic_id}.json")
    arr = _read_json(data_path, [])
    moved = None
    rest = []
    for v in arr:
        if v.get("id") == vid and not moved:
            moved = v
        else:
            rest.append(v)
    if not moved:
        return jsonify({"error": "원본 토픽에서 영상을 찾을 수 없습니다."}), 404
    _write_json(data_path, rest)
    trash = read_trash()
    trash.insert(0, {
        "topic":     topic_id,
        "videoId":   vid,
        "trashedAt": int(datetime.datetime.now().timestamp() * 1000),
        "video":     moved,
    })
    write_trash(trash)
    return jsonify({"ok": True})

@app.route("/api/restore", methods=["POST"])
@admin_only
def api_restore():
    body = request.get_json(force=True)
    vid = body.get("videoId")
    topic = body.get("topic", "")
    trash = read_trash()
    item = None
    rest = []
    for t in trash:
        if (not item) and t.get("videoId") == vid and (not topic or t.get("topic") == topic):
            item = t
        else:
            rest.append(t)
    if not item:
        return jsonify({"error": "휴지통에서 영상을 찾을 수 없습니다."}), 404
    write_trash(rest)
    data_path = os.path.join(DATA_DIR, f"{item['topic']}.json")
    arr = _read_json(data_path, [])
    arr.insert(0, item["video"])
    _write_json(data_path, arr)
    return jsonify({"ok": True})

@app.route("/api/permdel", methods=["POST"])
@admin_only
def api_permdel():
    body = request.get_json(force=True)
    vid = body.get("videoId")
    topic = body.get("topic", "")
    trash = read_trash()
    rest  = []
    found_topic = topic
    for t in trash:
        if t.get("videoId") == vid and (not topic or t.get("topic") == topic):
            found_topic = t.get("topic", topic)
            continue
        rest.append(t)
    write_trash(rest)
    pd = read_permdel()
    if found_topic:
        if found_topic not in pd:
            pd[found_topic] = []
        if vid not in pd[found_topic]:
            pd[found_topic].append(vid)
    write_permdel(pd)
    return jsonify({"ok": True})

@app.route("/api/trash/empty", methods=["POST"])
@admin_only
def api_trash_empty():
    write_trash([])
    return jsonify({"ok": True})


@app.route("/api/update", methods=["POST"])
@admin_only
def api_update():
    body = request.get_json(force=True)
    topic_id   = body.get("topicId", "")
    keywords   = body.get("keywords", [])
    channels   = body.get("channels", [])
    exclude    = set(body.get("excludeIds", []))

    if not topic_id:
        return jsonify({"error": "topicId required"}), 400

    # 교차 토픽 중복 방지 — 모든 토픽 JSON 의 영상 ID 를 exclude 에 합침
    if os.path.isdir(DATA_DIR):
        for fname in os.listdir(DATA_DIR):
            if not fname.endswith(".json"):
                continue
            try:
                with open(os.path.join(DATA_DIR, fname), "r", encoding="utf-8") as f:
                    arr = json.load(f)
                if isinstance(arr, list):
                    for v in arr:
                        vid = v.get("id") if isinstance(v, dict) else None
                        if vid:
                            exclude.add(vid)
            except Exception:
                continue
    # 휴지통 + 영구삭제 ID 도 제외
    for t in read_trash():
        vid = t.get("videoId")
        if vid:
            exclude.add(vid)
    pd = read_permdel()
    for _tid, ids in (pd.items() if isinstance(pd, dict) else []):
        for v in ids or []:
            exclude.add(v)

    # 검색 쿼리 조합 (키워드 앞 3개 + 채널명 1개 순차 시도)
    liked_channels = body.get("likedChannels", [])

    queries = []
    # 좋아요 채널 우선 검색
    for ch in liked_channels[:3]:
        queries.append(ch + " " + (keywords[0] if keywords else "빈티지"))
    # 일반 키워드 검색
    if keywords:
        queries.append(" ".join(keywords[:3]))
    if len(keywords) > 3:
        queries.append(" ".join(keywords[3:6]))
    for ch in channels[:2]:
        queries.append(ch + " " + (keywords[0] if keywords else ""))

    found = []
    seen  = set(exclude)

    for query in queries:
        if len(found) >= 5:
            break
        try:
            cmd = [
                sys.executable, "-m", "yt_dlp",
                f"ytsearch30:{query}",
                "--flat-playlist",
                "--dump-json",
                "--no-warnings",
                "--ignore-errors",
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8", timeout=40
            )
            for line in result.stdout.splitlines():
                if len(found) >= 5:
                    break
                try:
                    info = json.loads(line)
                    vid_id = info.get("id", "")
                    if not vid_id or vid_id in seen:
                        continue
                    # 짧은 영상(60초 미만) 제외
                    dur = info.get("duration") or 0
                    if dur and dur < 60:
                        continue
                    # 날짜 포맷 YYYYMMDD → YYYY년 M월
                    raw_date = info.get("upload_date", "")
                    pub_date = ""
                    if raw_date and len(raw_date) == 8:
                        pub_date = f"{raw_date[:4]}년 {int(raw_date[4:6])}월"

                    found.append({
                        "id":       vid_id,
                        "title":    info.get("title", ""),
                        "channel":  info.get("channel") or info.get("uploader", ""),
                        "summary":  "",          # flat-playlist 에선 description 없음
                        "url":      f"https://www.youtube.com/watch?v={vid_id}",
                        "pubDate":  pub_date,
                        "addedAt":  datetime.date.today().isoformat(),
                    })
                    seen.add(vid_id)
                except Exception:
                    continue
        except subprocess.TimeoutExpired:
            continue
        except Exception:
            continue

    if not found:
        return jsonify({"added": 0, "videos": [], "message": "새 영상 없음"}), 200

    # 풀 메타 보강 — 정확한 upload_date 확보 (단일 배치 yt-dlp 호출)
    try:
        urls = [v["url"] for v in found]
        enrich_cmd = [
            sys.executable, "-m", "yt_dlp",
            *urls,
            "--dump-json", "--skip-download",
            "--no-warnings", "--ignore-errors",
        ]
        enrich_result = subprocess.run(
            enrich_cmd, capture_output=True, text=True, encoding="utf-8", timeout=120
        )
        by_id = {}
        for line in enrich_result.stdout.splitlines():
            try:
                info = json.loads(line)
                vid_id = info.get("id")
                if vid_id:
                    by_id[vid_id] = info
            except Exception:
                continue
        for v in found:
            info = by_id.get(v["id"])
            if not info:
                continue
            raw_date = info.get("upload_date", "")
            if raw_date and len(raw_date) == 8:
                v["pubDate"] = f"{raw_date[:4]}년 {int(raw_date[4:6])}월 {int(raw_date[6:8])}일"
            desc = info.get("description") or ""
            if not v.get("summary"):
                # 자막 + Claude 요약 우선, 실패시 description 기반 휴리스틱
                smart, src_kind = build_smart_summary(v["id"], v.get("title", ""), desc)
                if smart:
                    v["summary"] = smart
                    v["summaryBy"] = "claude" if src_kind.startswith("claude") else "heuristic"
                    v["summarySource"] = src_kind
    except Exception:
        pass

    # data/<topic-id>.json 업데이트 (새 영상 앞에 추가)
    data_path = os.path.join(DATA_DIR, f"{topic_id}.json")
    existing = []
    if os.path.exists(data_path):
        try:
            with open(data_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = []

    merged = found + existing
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    return jsonify({"added": len(found), "videos": found})


@app.route("/api/admin/resummarize", methods=["POST"])
@admin_only
def api_resummarize():
    """모든 아카이브 영상을 자막+Claude 로 재요약. 시간 소요 큼.
       body: {topic?: <id> 특정 토픽만, force?: bool 빈 게 아닌 것도 덮어쓰기}"""
    body = request.get_json(force=True) or {}
    only_topic = body.get("topic")
    force = bool(body.get("force"))

    if not (ANTHROPIC_OK and ANTHROPIC_API_KEY):
        return jsonify({"error": "ANTHROPIC_API_KEY 미설정 또는 anthropic 모듈 없음"}), 503

    results = {"processed": 0, "updated": 0, "failed_files": []}
    if not os.path.isdir(DATA_DIR):
        return jsonify(results)

    for fname in sorted(os.listdir(DATA_DIR)):
        if not fname.endswith(".json"):
            continue
        tid = fname[:-5]
        if only_topic and tid != only_topic:
            continue
        fpath = os.path.join(DATA_DIR, fname)
        try:
            arr = _read_json(fpath, [])
            if not isinstance(arr, list):
                continue
            changed = False
            for v in arr:
                vid = v.get("id")
                if not vid:
                    continue
                cur = v.get("summary", "")
                if cur and not force:
                    continue
                results["processed"] += 1
                title = v.get("title", "")
                # 1) 자막 시도
                transcript = fetch_transcript(vid)
                new_sum = None
                if transcript:
                    new_sum = summarize_with_claude(transcript, title)
                    if new_sum:
                        print(f"[resum] {vid} via transcript ({len(transcript)} chars)", flush=True)
                # 2) 자막 실패 시 — yt-dlp 로 description 가져와 시도
                if not new_sum:
                    try:
                        cmd = [
                            sys.executable, "-m", "yt_dlp",
                            f"https://www.youtube.com/watch?v={vid}",
                            "--dump-json", "--skip-download",
                            "--no-warnings", "--ignore-errors",
                        ]
                        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=30)
                        for line in r.stdout.splitlines():
                            try:
                                info = json.loads(line)
                                desc = info.get("description") or ""
                                if desc:
                                    new_sum = summarize_with_claude(desc, title)
                                    if new_sum:
                                        print(f"[resum] {vid} via description ({len(desc)} chars)", flush=True)
                                    break
                            except Exception:
                                continue
                    except Exception as e:
                        print(f"[resum] {vid} ytdlp error: {e}", flush=True)
                if new_sum:
                    v["summary"] = new_sum
                    v["summaryBy"] = "claude"
                    changed = True
                    results["updated"] += 1
                else:
                    print(f"[resum] {vid} no summary produced", flush=True)
            if changed:
                _write_json(fpath, arr)
        except Exception as e:
            print(f"[resummarize] {fname} error: {e}", flush=True)
            results["failed_files"].append(fname)

    return jsonify(results)


@app.route("/api/move", methods=["POST"])
@admin_only
def api_move():
    body = request.get_json(force=True)
    from_topic = body.get("fromTopic", "")
    to_topic   = body.get("toTopic", "")
    video_ids  = set(body.get("videoIds", []))

    if not from_topic or not to_topic or not video_ids:
        return jsonify({"error": "fromTopic, toTopic, videoIds required"}), 400
    if from_topic == to_topic:
        return jsonify({"error": "same topic"}), 400

    def read_json(path):
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def write_json(path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    from_path = os.path.join(DATA_DIR, f"{from_topic}.json")
    to_path   = os.path.join(DATA_DIR, f"{to_topic}.json")

    from_data = read_json(from_path)
    to_data   = read_json(to_path)

    moved   = [v for v in from_data if v.get("id") in video_ids]
    stayed  = [v for v in from_data if v.get("id") not in video_ids]

    if not moved:
        return jsonify({"error": "videos not found in source topic"}), 404

    write_json(from_path, stayed)
    write_json(to_path, moved + to_data)

    return jsonify({"moved": len(moved)})


if __name__ == "__main__":
    print("=" * 50)
    print("  Vintage Daily Digest — 로컬 서버")
    print("  http://localhost:4322")
    print("=" * 50)
    app.run(host="0.0.0.0", port=4322, debug=False)
