#!/usr/bin/env python3
"""
data/*.json 의 모든 영상 title 을 yt-dlp 로 ko locale 재fetch.
영어 번역 제목으로 저장된 영상을 한국어 원본 제목으로 교정.

사용:
  $env:DATA_ROOT = "tmp_prod_data"
  python fix-titles-local.py
"""
import os, json, sys, subprocess

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.environ.get("DATA_ROOT", BASE_DIR)
DATA_DIR  = os.path.join(DATA_ROOT, "data")

def fetch_title_ko(video_id):
    """yt-dlp 로 ko locale 메타 fetch → title 반환. 실패시 None."""
    try:
        cmd = [
            sys.executable, "-m", "yt_dlp",
            f"https://www.youtube.com/watch?v={video_id}",
            "--dump-json", "--skip-download",
            "--no-warnings", "--ignore-errors",
            "--extractor-args", "youtube:lang=ko",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=30)
        for line in r.stdout.splitlines():
            try:
                info = json.loads(line)
                if info.get("id") == video_id:
                    return info.get("title")
            except Exception:
                continue
    except Exception as e:
        print(f"  ! {video_id} fetch err: {e}")
    return None

def main():
    if not os.path.isdir(DATA_DIR):
        print(f"DATA_DIR not found: {DATA_DIR}")
        return
    total = 0
    updated = 0
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
            total += 1
            vid = v.get("id")
            if not vid:
                continue
            new_title = fetch_title_ko(vid)
            if not new_title:
                print(f"  ! {vid} title fetch failed, skip")
                continue
            old = v.get("title", "")
            if new_title != old:
                v["title"] = new_title
                changed = True
                updated += 1
                print(f"  ✓ {vid}")
                print(f"    OLD: {old[:80]}")
                print(f"    NEW: {new_title[:80]}")
            else:
                print(f"  = {vid} (unchanged)")
        if changed:
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(arr, f, ensure_ascii=False, indent=2)
    print(f"\n=== 완료: {updated}/{total} ===")

if __name__ == "__main__":
    main()
