#!/usr/bin/env python3
"""
로컬에서 자막 + Claude 요약을 수행한 뒤 data/*.json 의 summary 필드 갱신.
Fly.io 데이터센터 IP 가 YouTube transcript/메타 fetch 를 차단하므로
로컬에서 실행 후 SFTP 로 업로드해야 함.

사용법:
  1) 환경변수 ANTHROPIC_API_KEY 설정
  2) DATA_ROOT 환경변수로 대상 디렉토리 지정 (예: tmp_prod_data)
  3) python resummarize-local.py [--force]
"""
import os, json, re, sys, subprocess, time
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.environ.get("DATA_ROOT", BASE_DIR)
DATA_DIR  = os.path.join(DATA_ROOT, "data")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5")
FORCE = "--force" in sys.argv

if not ANTHROPIC_API_KEY:
    print("ERROR: ANTHROPIC_API_KEY 환경변수가 없습니다.")
    sys.exit(1)

try:
    from youtube_transcript_api import YouTubeTranscriptApi
    from youtube_transcript_api._errors import TranscriptsDisabled, NoTranscriptFound
except ImportError:
    print("ERROR: pip install youtube-transcript-api 필요")
    sys.exit(1)
try:
    import anthropic
except ImportError:
    print("ERROR: pip install anthropic 필요")
    sys.exit(1)


def fetch_transcript(video_id):
    """자막 — ko → en → 그 외. 실패시 None."""
    for langs in (["ko"], ["en"], None):
        try:
            if hasattr(YouTubeTranscriptApi, "fetch") and not hasattr(YouTubeTranscriptApi, "get_transcript"):
                ytt = YouTubeTranscriptApi()
                fetched = ytt.fetch(video_id, languages=langs) if langs else ytt.fetch(video_id)
                data = [{"text": getattr(s, "text", "")} for s in fetched]
            else:
                data = YouTubeTranscriptApi.get_transcript(video_id, languages=langs) if langs \
                    else YouTubeTranscriptApi.get_transcript(video_id)
            text = " ".join(d.get("text", "") for d in data)
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                return text
        except (NoTranscriptFound, TranscriptsDisabled):
            if langs is None:
                return None
            continue
        except Exception:
            return None
    return None


def fetch_description(video_id):
    """yt-dlp 로 영상 description 가져오기."""
    try:
        cmd = [
            sys.executable, "-m", "yt_dlp",
            f"https://www.youtube.com/watch?v={video_id}",
            "--dump-json", "--skip-download",
            "--no-warnings", "--ignore-errors",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=30)
        for line in r.stdout.splitlines():
            try:
                info = json.loads(line)
                desc = info.get("description") or ""
                if desc:
                    return desc
            except Exception:
                continue
    except Exception:
        pass
    return None


def summarize(client, text, title, target=120):
    if not text:
        return None
    text = str(text)[:6000]
    try:
        msg = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": (
                    f"다음은 유튜브 영상의 자막 또는 설명입니다. "
                    f"영상 제목: '{title}'\n\n"
                    f"이 영상의 핵심 내용을 한국어로 약 {target}자 이내, 한 문단으로 요약해주세요. "
                    f"인사말·구독요청·광고는 제외하고 정보가 되는 부분만. 요약문만 출력하세요.\n\n"
                    f"---\n{text}\n---"
                )
            }]
        )
        out = "".join(getattr(b, "text", "") for b in msg.content).strip()
        out = out.replace("\n", " ")
        return out[:target * 2] if out else None
    except Exception as e:
        print(f"  claude error: {e}")
        return None


def process_video(client, v):
    vid = v.get("id")
    title = v.get("title", "")
    cur = v.get("summary", "")
    src_meta = v.get("summaryBy", "")
    # Claude 요약은 이미 있는 영상만 skip. heuristic/빈 값은 재처리.
    if cur and src_meta == "claude" and not FORCE:
        return False, "skipped"
    if not vid:
        return False, "no-id"

    transcript = fetch_transcript(vid)
    src = transcript
    src_kind = "transcript" if transcript else None
    if not src:
        src = fetch_description(vid)
        src_kind = "description" if src else None
    if not src:
        return False, "no-source"

    new_sum = summarize(client, src, title)
    if not new_sum:
        return False, "no-summary"

    v["summary"] = new_sum
    v["summaryBy"] = "claude"
    v["summarySource"] = src_kind  # transcript or description
    return True, src_kind


def main():
    if not os.path.isdir(DATA_DIR):
        print(f"DATA_DIR not found: {DATA_DIR}")
        return

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    total_processed = 0
    total_updated = 0

    for fname in sorted(os.listdir(DATA_DIR)):
        if not fname.endswith(".json"):
            continue
        fpath = os.path.join(DATA_DIR, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            arr = json.load(f)
        if not isinstance(arr, list):
            continue

        print(f"\n=== {fname} ({len(arr)}개) ===")
        changed = False
        for v in arr:
            cur = v.get("summary", "")
            src_meta = v.get("summaryBy", "")
            # Claude 요약은 skip. heuristic/빈 값은 재처리 대상.
            if cur and src_meta == "claude" and not FORCE:
                continue
            total_processed += 1
            ok, kind = process_video(client, v)
            vid = v.get("id", "?")
            if ok:
                total_updated += 1
                changed = True
                print(f"  ✓ {vid} ({kind}) → {(v.get('summary') or '')[:60]}")
            else:
                print(f"  ✗ {vid} ({kind})")

        if changed:
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(arr, f, ensure_ascii=False, indent=2)

    print(f"\n=== 완료: {total_updated}/{total_processed} 영상 재요약 ===")


if __name__ == "__main__":
    main()
