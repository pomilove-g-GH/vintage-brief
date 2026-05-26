#!/usr/bin/env python3
"""
기존 아카이브 영상의 pubDate (업로드 날짜) 백필 스크립트
data/*.json 의 모든 영상 중 pubDate 가 비어 있거나 부정확한 항목을
yt-dlp 로 풀 메타 조회하여 'YYYY년 M월 D일' 형식으로 채워 넣는다.

실행: python backfill-dates.py
"""
import os, json, subprocess, sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
BATCH    = 10   # 한번에 yt-dlp 에 넘길 URL 갯수

def fetch_meta(video_ids):
    """video_ids 리스트를 yt-dlp 로 일괄 조회. {id: {upload_date, description}} 반환."""
    if not video_ids:
        return {}
    urls = [f"https://www.youtube.com/watch?v={vid}" for vid in video_ids]
    cmd = [
        sys.executable, "-m", "yt_dlp",
        *urls,
        "--dump-json", "--skip-download",
        "--no-warnings", "--ignore-errors",
    ]
    print(f"  yt-dlp 조회 중… ({len(video_ids)}개)")
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8", timeout=300
        )
    except subprocess.TimeoutExpired:
        print("  ⚠️  타임아웃")
        return {}

    out = {}
    for line in result.stdout.splitlines():
        try:
            info = json.loads(line)
            vid_id = info.get("id")
            if vid_id:
                out[vid_id] = info
        except Exception:
            continue
    return out

def main():
    if not os.path.isdir(DATA_DIR):
        print("data/ 디렉토리 없음")
        return

    files = [f for f in os.listdir(DATA_DIR) if f.endswith(".json")]
    if not files:
        print("data/*.json 파일 없음")
        return

    total_updated = 0
    for fname in sorted(files):
        fpath = os.path.join(DATA_DIR, fname)
        with open(fpath, "r", encoding="utf-8") as f:
            arr = json.load(f)

        if not isinstance(arr, list):
            continue

        # 날짜 누락 또는 일(day) 정보 없는 항목 수집
        need_ids = []
        for v in arr:
            pd = v.get("pubDate", "")
            if not pd or "일" not in pd:
                need_ids.append(v.get("id"))
        need_ids = [vid for vid in need_ids if vid]

        if not need_ids:
            print(f"{fname}: 모두 채워짐, 스킵")
            continue

        print(f"\n{fname}: {len(need_ids)}개 보강 필요")

        meta = {}
        for i in range(0, len(need_ids), BATCH):
            batch_ids = need_ids[i:i+BATCH]
            meta.update(fetch_meta(batch_ids))

        updated = 0
        for v in arr:
            vid = v.get("id")
            info = meta.get(vid)
            if not info:
                continue
            raw = info.get("upload_date", "")
            if raw and len(raw) == 8:
                v["pubDate"] = f"{raw[:4]}년 {int(raw[4:6])}월 {int(raw[6:8])}일"
                # summary 도 비어 있으면 채움
                if not v.get("summary"):
                    desc = info.get("description") or ""
                    if desc:
                        v["summary"] = desc.strip().split("\n")[0][:200]
                updated += 1

        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(arr, f, ensure_ascii=False, indent=2)

        print(f"  ✅ {updated}개 업데이트 완료")
        total_updated += updated

    print(f"\n=== 전체 {total_updated}개 영상 메타 보강 완료 ===")

if __name__ == "__main__":
    main()
