# Vintage Daily Digest

빈티지 의류 관련 유튜브 영상 큐레이션 사이트. Flask + yt-dlp 기반.

## 기능

- 4개 주제 카테고리(창업 팁 / 사장 인터뷰 / 도매 사입 정보 / 빈티지샵 탐방)
- 업데이트 버튼 클릭 시 yt-dlp 로 새 영상 5개 자동 큐레이션
- 좋아요(사용자별) · 휴지통(공유) · 영구삭제 · 카테고리 간 이동
- 로그인/회원가입 (첫 가입자 자동 admin)
- 역할 기반 UI: anonymous / user / admin

## 로컬 실행

```bash
pip install -r requirements.txt
python server.py
```

http://localhost:4322 접속.

## 배포 (Fly.io — 권장)

### 사전 준비
1. Fly.io 계정 (https://fly.io) — 신용카드 등록 필요 (사용량 없으면 청구 0)
2. flyctl CLI 설치:
   - Windows PowerShell: `iwr https://fly.io/install.ps1 -useb | iex`
   - 또는 https://fly.io/docs/flyctl/install/

### 배포 절차
```powershell
# 1. 로그인
fly auth login

# 2. 앱 생성 (대화형 — 기본값 그대로 Y, 단 fly.toml 덮어쓰기는 N 으로!)
fly launch --no-deploy
#   - "Would you like to copy its configuration to the new app?" → Y
#   - app 이름 → vintage-brief (이미 있으면 다른 이름)
#   - region → nrt (Tokyo)
#   - postgres / redis → N
#   - deploy now? → N

# 3. 영구 볼륨 생성 (1GB, 무료 한도 내)
fly volumes create vintage_data --size 1 --region nrt

# 4. 배포
fly deploy

# 5. URL 확인
fly status
```

배포 완료 후 `https://vintage-brief.fly.dev` (이름 다르면 그에 맞춰) 접속.

### 비용
Fly.io 무료 한도:
- shared-cpu-1x VM 3개
- 영구 볼륨 3GB
- 아웃바운드 트래픽 160GB/월
- 대시 보드 https://fly.io/dashboard 에서 사용량 확인

본 앱은 VM 1개 + 1GB 볼륨이라 무료 한도 내. 트래픽 적으면 청구 0원.

`auto_stop_machines = "stop"` 설정으로 유휴 시 자동 정지 → 첫 접속 시 ~5초 콜드 스타트.

## 배포 (Render.com — 대안)

### 사전 준비
- Render 계정 (https://render.com)
- 본 저장소가 GitHub 에 있어야 함

### Blueprint 로 한 번에 배포
1. Render 대시보드 → New → Blueprint
2. GitHub 저장소 연결 → `vintage-brief` 선택
3. `render.yaml` 자동 감지 → Apply
4. 디스크 1GB(`/var/data`) 가 자동 마운트되고 Starter 플랜으로 배포됨

### 수동 배포
1. New → Web Service → 본 저장소 선택
2. 설정:
   - Runtime: Python 3
   - Build: `pip install -r requirements.txt`
   - Start: `gunicorn server:app --workers 2 --threads 2 --timeout 180 --bind 0.0.0.0:$PORT`
3. Disks 탭 → Add Disk
   - Name: `vintage-disk`
   - Mount Path: `/var/data`
   - Size: 1 GB
4. Environment 탭 → 추가:
   - `DATA_ROOT` = `/var/data`
   - `RENDER` = `true`
5. Deploy

### 비용
- Starter 플랜 약 $7/월 + Disk 1GB 약 $0.25/월

### 첫 사용
1. 배포 완료 후 `https://vintage-brief.onrender.com` (혹은 부여된 URL) 접속
2. 우상단 "로그인" → "회원가입" 탭 → ID + 비밀번호 입력 → 첫 가입자가 자동으로 admin
3. 이후 다른 사람이 가입하면 일반 user 권한

## 데이터 구조

영구 디스크(`DATA_ROOT`) 에 저장되는 것들:
- `data/<topic>.json` — 토픽별 큐레이션된 영상 목록
- `users.json` — 사용자 계정 (비밀번호는 해시)
- `likes/<user_id>.json` — 사용자별 좋아요
- `_state/trash.json` — 휴지통
- `_state/permdel.json` — 영구 삭제 차단 목록
- `.flask-secret` — 세션 키

## 스택
- Backend: Flask + werkzeug (세션) + gunicorn
- Search: yt-dlp (서브프로세스)
- Frontend: vanilla JS, no build step
- Storage: 파일 기반 (영구 디스크)
