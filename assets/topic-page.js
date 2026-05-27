/* =============================================================
   Vintage Daily Digest — 토픽 페이지 공용 로직 (topic-page.js)
   -------------------------------------------------------------
   각 토픽 페이지(`pages/<topic-id>.html`)에서 사용한다.
   사전 조건:
     - 부모 페이지가 `manifest.js`를 먼저 로드해 `window.DIGEST_MANIFEST`가 있다.
     - HTML 안에서 `window.TOPIC_ID = "<id>"` 가 설정돼 있다.
   기능:
     - 토픽 메타(설명·키워드·채널) 렌더
     - 누적 아카이브(data/<id>.json) 렌더 + 페이지네이션(10/page)
     - 휴지통/영구삭제 상태(localStorage) 필터링·관리
     - "업데이트" 버튼 (5개 신규 큐레이션 트리거 — 백엔드 미연결 stub)
   ============================================================= */
(function () {
  "use strict";

  // ===== 상수 =====
  var PAGE_SIZE = 10;

  // 부모(iframe URL) 에서 role/uid 수신
  var urlParams = new URLSearchParams(location.search);
  var ROLE = urlParams.get("role") || "anonymous";
  var UID  = urlParams.get("uid")  || "";

  var topicId = window.TOPIC_ID;
  if (!topicId) { console.error("TOPIC_ID not set"); return; }

  var manifest = window.DIGEST_MANIFEST;
  if (!manifest || !manifest.topics) { console.error("manifest missing"); return; }

  var topic = null;
  for (var i = 0; i < manifest.topics.length; i++) {
    if (manifest.topics[i].id === topicId) { topic = manifest.topics[i]; break; }
  }
  if (!topic) { console.error("topic not found in manifest: " + topicId); return; }

  // ===== 좋아요 (서버 기반) =====
  function isLiked(vid) {
    for (var i = 0; i < state.likes.length; i++) {
      if (state.likes[i].topic === topicId && state.likes[i].videoId === vid) return true;
    }
    return false;
  }
  function loadLikes() {
    if (ROLE === "anonymous") { state.likes = []; return Promise.resolve(); }
    return fetch("/api/likes", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (d) { state.likes = Array.isArray(d) ? d : []; })
      .catch(function () { state.likes = []; });
  }
  function toggleLike(vid, btn) {
    if (ROLE === "anonymous") return;
    var v = null;
    for (var i = 0; i < state.archive.length; i++) if (state.archive[i].id === vid) { v = state.archive[i]; break; }
    if (!v) return;
    var already = isLiked(vid);
    if (already) {
      fetch("/api/likes/" + encodeURIComponent(vid) + "?topic=" + encodeURIComponent(topicId),
            { method: "DELETE", credentials: "same-origin" })
        .then(function () {
          state.likes = state.likes.filter(function (l) { return !(l.topic === topicId && l.videoId === vid); });
          if (btn) { btn.textContent = "🤍"; btn.classList.remove("liked"); }
          toast("좋아요가 취소되었습니다.");
          try { window.parent.postMessage({ type: "vintage-likes-changed" }, "*"); } catch (e) {}
        });
    } else {
      fetch("/api/likes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ topic: topicId, video: v })
      }).then(function () {
        state.likes.unshift({ topic: topicId, videoId: vid, likedAt: Date.now(), video: v });
        if (btn) { btn.textContent = "❤️"; btn.classList.add("liked"); }
        toast("좋아요를 눌렀습니다!", "success");
        try { window.parent.postMessage({ type: "vintage-likes-changed" }, "*"); } catch (e) {}
      });
    }
  }

  // ===== 상태 =====
  var LS_SORT = "vintage-sort";
  var LS_SORT_DIR = "vintage-sort-dir";  // {addedAt, pubDate, channel} → 'asc'|'desc'
  var defaultSort = "addedAt";
  var sortDirMap = { addedAt: "desc", pubDate: "desc", channel: "asc" };
  try {
    var saved = localStorage.getItem(LS_SORT);
    if (saved === "addedAt" || saved === "pubDate" || saved === "channel") defaultSort = saved;
    var savedDir = JSON.parse(localStorage.getItem(LS_SORT_DIR) || "null");
    if (savedDir && typeof savedDir === "object") {
      ["addedAt", "pubDate", "channel"].forEach(function (k) {
        if (savedDir[k] === "asc" || savedDir[k] === "desc") sortDirMap[k] = savedDir[k];
      });
    }
  } catch (e) {}
  var state = { archive: [], page: 1, selected: {}, sort: defaultSort, likes: [] };

  function curDir() { return sortDirMap[state.sort] || "desc"; }
  function setDir(d) {
    sortDirMap[state.sort] = d;
    try { localStorage.setItem(LS_SORT_DIR, JSON.stringify(sortDirMap)); } catch (e) {}
  }

  // pubDate "YYYY년 M월 D일" → 비교 가능 정수
  function pubDateNum(s) {
    if (!s) return 0;
    var m = s.match(/(\d{4})년\s*(\d{1,2})월(?:\s*(\d{1,2})일)?/);
    if (!m) return 0;
    var y = parseInt(m[1], 10) || 0;
    var mo = parseInt(m[2], 10) || 0;
    var d = parseInt(m[3] || "0", 10) || 0;
    return y * 10000 + mo * 100 + d;
  }
  function sortArchive(arr) {
    var s = state.sort;
    var dir = curDir();
    var mul = (dir === "asc") ? 1 : -1;
    var copy = arr.slice();
    if (s === "pubDate") {
      copy.sort(function (a, b) { return mul * (pubDateNum(a.pubDate) - pubDateNum(b.pubDate)); });
    } else if (s === "channel") {
      copy.sort(function (a, b) { return mul * (a.channel || "").localeCompare(b.channel || "", "ko"); });
    } else {
      copy.sort(function (a, b) {
        if (a.addedAt && b.addedAt) return mul * a.addedAt.localeCompare(b.addedAt);
        return 0;
      });
    }
    return copy;
  }

  // 정렬별 방향 라벨
  var DIR_LABELS = {
    addedAt: { asc: "오래된 순",  desc: "최신순" },
    pubDate: { asc: "오래된 순",  desc: "최신순" },
    channel: { asc: "ㄱ→ㅎ",      desc: "ㅎ→ㄱ" }
  };

  // ===== 데이터 페치 =====
  function loadArchive() {
    return fetch("../" + topic.dataFile + "?ts=" + Date.now(), { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .catch(function (e) { console.warn("data load failed:", e); return []; });
  }

  // ===== 렌더: 메타 =====
  function renderMeta() {
    var host = document.getElementById("topicMeta");
    if (!host) return;
    var kwHtml = (topic.keywords || []).map(function (k) {
      return '<span class="tag">' + escapeHtml(k) + '</span>';
    }).join("");
    var chHtml = (topic.channels || []).map(function (c) {
      return '<span class="tag tag-primary">' + escapeHtml(c) + '</span>';
    }).join("");
    host.innerHTML =
      '<details class="topic-meta">' +
        '<summary>📋 토픽 정보 · 검색 키워드 · 유관 채널</summary>' +
        '<div class="meta-body">' +
          '<p>' + escapeHtml(topic.description || "") + '</p>' +
          '<div class="meta-row"><span class="meta-label">키워드</span><div class="meta-chips">' + kwHtml + '</div></div>' +
          '<div class="meta-row"><span class="meta-label">유관 채널</span><div class="meta-chips">' + chHtml + '</div></div>' +
        '</div>' +
      '</details>';
  }

  // ===== 렌더: 컨트롤 =====
  function renderControls(visibleCount) {
    var host = document.getElementById("topicControls");
    if (!host) return;
    var sortVal = state.sort;
    var updateBtnHtml = (ROLE === "admin")
      ? ('<button class="update-btn" id="updateBtn" type="button">' +
           '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">' +
             '<path d="M21 12a9 9 0 1 1-3-6.7"/><polyline points="21 4 21 10 15 10"/>' +
           '</svg>' +
           '<span class="btn-label">업데이트 (영상 5개 추가)</span>' +
         '</button>')
      : "";
    host.innerHTML =
      updateBtnHtml +
      '<div class="topic-counts">현재 아카이브 <strong>' + visibleCount + '</strong>개 (총 ' + state.archive.length + '개)</div>' +
      '<div class="spacer"></div>' +
      '<label class="sort-control">정렬: ' +
        '<select id="sortSelect">' +
          '<option value="addedAt"' + (sortVal === "addedAt" ? " selected" : "") + '>추가한 순</option>' +
          '<option value="pubDate"' + (sortVal === "pubDate" ? " selected" : "") + '>업로드 순</option>' +
          '<option value="channel"' + (sortVal === "channel" ? " selected" : "") + '>유튜버 이름순</option>' +
        '</select>' +
        '<button class="sort-dir-btn" id="sortDirBtn" type="button" title="정렬 방향 전환">' +
          (curDir() === "asc" ? "↑" : "↓") + ' <span>' + DIR_LABELS[sortVal][curDir()] + '</span>' +
        '</button>' +
      '</label>';

    var ub = document.getElementById("updateBtn");
    if (ub) ub.addEventListener("click", onUpdateClick);
    document.getElementById("sortSelect").addEventListener("change", function (ev) {
      state.sort = ev.target.value;
      try { localStorage.setItem(LS_SORT, state.sort); } catch (e) {}
      state.page = 1;
      renderList();
    });
    document.getElementById("sortDirBtn").addEventListener("click", function () {
      setDir(curDir() === "asc" ? "desc" : "asc");
      state.page = 1;
      renderList();
    });
  }

  // ===== 렌더: 영상 카드 =====
  function visibleArchive() {
    // 서버에서 이미 휴지통/영구삭제 영상은 data/<topic>.json 에서 제거됨
    return state.archive.slice();
  }
  function renderList() {
    var visible = sortArchive(visibleArchive());
    renderControls(visible.length);

    var host = document.getElementById("videoList");
    var pager = document.getElementById("pager");
    if (!host) return;

    if (!visible.length) {
      host.innerHTML =
        '<div class="empty-state">' +
          '<h3>아직 큐레이션된 영상이 없습니다</h3>' +
          '<p>위 "업데이트" 버튼을 눌러 첫 5개 영상을 받아보세요.</p>' +
        '</div>';
      if (pager) pager.innerHTML = "";
      return;
    }

    var totalPages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
    if (state.page > totalPages) state.page = totalPages;
    var start = (state.page - 1) * PAGE_SIZE;
    var slice = visible.slice(start, start + PAGE_SIZE);

    host.innerHTML = slice.map(function (v, idx) {
      var rank = start + idx + 1;
      var pubDateHtml = v.pubDate ? '<span class="video-date">영상: ' + escapeHtml(v.pubDate) + '</span>' : '';
      var addedHtml = ''; // addedAt 은 데이터로만 보관, 화면에는 표시하지 않음
      var checkBtnHtml = (ROLE === "admin")
        ? '<button class="card-check-btn js-check' + (state.selected[v.id] ? ' checked' : '') + '" type="button" title="선택" aria-label="선택">✓</button>'
        : '';
      var likeBtnHtml = (ROLE !== "anonymous")
        ? '<button class="card-like-btn js-like' + (isLiked(v.id) ? ' liked' : '') + '" type="button" title="좋아요" aria-label="좋아요">' + (isLiked(v.id) ? '❤️' : '🤍') + '</button>'
        : '';
      var trashBtnHtml = (ROLE === "admin")
        ? '<button class="card-trash-btn js-trash" type="button" title="휴지통으로 이동" aria-label="휴지통으로 이동">🗑️</button>'
        : '';
      return (
        '<article class="video-card reveal in' + (state.selected[v.id] ? ' selected-card' : '') + '" data-delay="0" data-vid="' + escapeAttr(v.id) + '">' +
          checkBtnHtml + likeBtnHtml + trashBtnHtml +
          '<a class="video-thumb" href="' + escapeAttr(v.url) + '" target="_blank" rel="noopener">' +
            '<img src="https://img.youtube.com/vi/' + escapeAttr(v.id) + '/hqdefault.jpg" onerror="this.classList.add(\'thumb-error\')" alt="">' +
            '<span class="thumb-rank">#' + rank + '</span>' +
            '<span class="thumb-play" aria-hidden="true"><svg width="16" height="16" viewBox="0 0 24 24" fill="#fff"><path d="M8 5v14l11-7z"/></svg></span>' +
          '</a>' +
          '<div class="video-body">' +
            '<div class="video-meta">' +
              '<span class="channel-badge">' + escapeHtml(v.channel) + '</span>' +
              pubDateHtml + addedHtml +
            '</div>' +
            '<h3><a class="video-title-link" href="' + escapeAttr(v.url) + '" target="_blank" rel="noopener">' + escapeHtml(v.title) + '</a></h3>' +
            '<p>' + escapeHtml(v.summary || "") + '</p>' +
          '</div>' +
        '</article>'
      );
    }).join("");

    // 카드 휴지통 버튼 바인딩
    var btns = host.querySelectorAll(".js-trash");
    for (var b = 0; b < btns.length; b++) {
      btns[b].addEventListener("click", function (ev) {
        var card = ev.currentTarget.closest("[data-vid]");
        if (!card) return;
        var vid = card.getAttribute("data-vid");
        onTrashClick(vid);
      });
    }
    // 카드 좋아요 버튼 바인딩
    var likeBtns = host.querySelectorAll(".js-like");
    for (var lb = 0; lb < likeBtns.length; lb++) {
      likeBtns[lb].addEventListener("click", function (ev) {
        var card = ev.currentTarget.closest("[data-vid]");
        if (!card) return;
        toggleLike(card.getAttribute("data-vid"), ev.currentTarget);
      });
      // hover 시 이모지 🤍 → ❤️ 로 교체 (단 .liked 상태가 아닐 때만)
      likeBtns[lb].addEventListener("mouseenter", function (ev) {
        var b = ev.currentTarget;
        if (!b.classList.contains("liked")) b.textContent = "❤️";
      });
      likeBtns[lb].addEventListener("mouseleave", function (ev) {
        var b = ev.currentTarget;
        if (!b.classList.contains("liked")) b.textContent = "🤍";
      });
    }

    // 카드 체크 버튼 바인딩
    var checkBtns = host.querySelectorAll(".js-check");
    for (var cb = 0; cb < checkBtns.length; cb++) {
      checkBtns[cb].addEventListener("click", function (ev) {
        var card = ev.currentTarget.closest("[data-vid]");
        if (!card) return;
        var vid = card.getAttribute("data-vid");
        if (state.selected[vid]) {
          delete state.selected[vid];
          card.classList.remove("selected-card");
          ev.currentTarget.classList.remove("checked");
        } else {
          state.selected[vid] = true;
          card.classList.add("selected-card");
          ev.currentTarget.classList.add("checked");
        }
        renderMoveBar();
      });
    }

    renderPager(totalPages);
  }

  // ===== 이동 액션바 =====
  function renderMoveBar() {
    var existing = document.getElementById("moveBar");
    var count = Object.keys(state.selected).length;
    if (!count) {
      if (existing) existing.parentNode.removeChild(existing);
      return;
    }

    // 사이드바와 동일 순서 + 넘버링 (vintage-topic-order localStorage)
    var savedOrder = null;
    try {
      var raw = localStorage.getItem("vintage-topic-order");
      var parsed = raw ? JSON.parse(raw) : null;
      if (Array.isArray(parsed)) savedOrder = parsed;
    } catch (e) {}
    var ordered = manifest.topics.slice();
    if (savedOrder) {
      ordered.sort(function (a, b) {
        var ai = savedOrder.indexOf(a.id), bi = savedOrder.indexOf(b.id);
        if (ai === -1 && bi === -1) return 0;
        if (ai === -1) return 1;
        if (bi === -1) return -1;
        return ai - bi;
      });
    }
    var optionsHtml = ordered.map(function (t, i) {
      if (t.id === topicId) return "";
      var num = (i + 1 < 10 ? "0" : "") + (i + 1);
      return '<option value="' + t.id + '">' + num + '. ' + t.label + '</option>';
    }).join("");
    optionsHtml += '<option value="__trash__">🗑️ 휴지통으로 이동</option>';

    if (!existing) {
      existing = document.createElement("div");
      existing.id = "moveBar";
      existing.className = "move-bar";
      document.body.appendChild(existing);
    }
    existing.innerHTML =
      '<span class="move-bar-count">' + count + '개 선택됨</span>' +
      '<select id="moveTarget">' + optionsHtml + '</select>' +
      '<button class="move-bar-btn do-move" id="doMoveBtn">이동</button>' +
      '<button class="move-bar-btn do-cancel" id="doCancelBtn">취소</button>';

    document.getElementById("doMoveBtn").addEventListener("click", onMoveClick);
    document.getElementById("doCancelBtn").addEventListener("click", function () {
      state.selected = {};
      renderList();
    });
  }

  function onMoveClick() {
    var target = document.getElementById("moveTarget").value;
    if (!target) return;
    var videoIds = Object.keys(state.selected);
    if (!videoIds.length) return;

    var finish = function (msg, kind) {
      state.selected = {};
      var bar = document.getElementById("moveBar");
      if (bar) bar.parentNode.removeChild(bar);
      toast(msg, kind);
      try { window.parent.postMessage({ type: "vintage-trash-changed" }, "*"); } catch (e) {}
      loadArchive().then(function (newData) {
        state.archive = Array.isArray(newData) ? newData : [];
        state.page = 1;
        renderList();
      });
    };

    // 일괄 휴지통 이동 — 각 영상별 POST /api/trash 병렬 호출
    if (target === "__trash__") {
      Promise.all(videoIds.map(function (vid) {
        return fetch("/api/trash", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ topic: topicId, videoId: vid })
        }).then(function (r) { return r.ok; });
      })).then(function (results) {
        var ok = results.filter(function (x) { return x; }).length;
        finish(ok + "개 영상을 휴지통으로 이동했습니다.", "success");
      }).catch(function () {
        toast("휴지통 이동 실패.", "error");
      });
      return;
    }

    // 다른 토픽으로 이동
    fetch("/api/move", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ fromTopic: topicId, toTopic: target, videoIds: videoIds })
    })
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(function (data) {
      finish(data.moved + "개 영상을 이동했습니다.", "success");
    })
    .catch(function () {
      toast("이동 실패 — 서버 응답 확인.", "error");
    });
  }

  // ===== 렌더: 페이지네이션 =====
  function renderPager(total) {
    var host = document.getElementById("pager");
    if (!host) return;
    if (total <= 1) { host.innerHTML = ""; return; }

    var cur = state.page;
    var html = '';
    html += '<button class="pg-btn" type="button" data-go="' + (cur - 1) + '"' + (cur === 1 ? ' disabled' : '') + '>‹ 이전</button>';

    // 페이지 번호 (최대 7개)
    var pages = pageWindow(cur, total, 7);
    pages.forEach(function (p) {
      if (p === "…") html += '<span class="pg-ellipsis">…</span>';
      else html += '<button class="pg-btn' + (p === cur ? ' active' : '') + '" type="button" data-go="' + p + '">' + p + '</button>';
    });

    html += '<button class="pg-btn" type="button" data-go="' + (cur + 1) + '"' + (cur === total ? ' disabled' : '') + '>다음 ›</button>';
    host.innerHTML = html;

    var btns = host.querySelectorAll("button[data-go]");
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener("click", function (ev) {
        var go = parseInt(ev.currentTarget.getAttribute("data-go"), 10);
        if (!isNaN(go) && go >= 1 && go <= total) {
          state.page = go;
          renderList();
          window.scrollTo({ top: 0, behavior: "smooth" });
        }
      });
    }
  }
  function pageWindow(cur, total, max) {
    if (total <= max) {
      var arr = [];
      for (var i = 1; i <= total; i++) arr.push(i);
      return arr;
    }
    // 항상 1, total 포함
    var out = [];
    var left = Math.max(2, cur - 2);
    var right = Math.min(total - 1, cur + 2);
    out.push(1);
    if (left > 2) out.push("…");
    for (var p = left; p <= right; p++) out.push(p);
    if (right < total - 1) out.push("…");
    out.push(total);
    return out;
  }

  // ===== 이벤트 =====
  function onTrashClick(vid) {
    if (ROLE !== "admin") return;
    var v = null;
    for (var i = 0; i < state.archive.length; i++) if (state.archive[i].id === vid) { v = state.archive[i]; break; }
    if (!v) return;
    if (!confirm('"' + v.title + '" 영상을 휴지통으로 옮기시겠습니까?')) return;
    fetch("/api/trash", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ topic: topicId, videoId: vid })
    })
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(function () {
      toast("휴지통으로 이동했습니다.");
      try { window.parent.postMessage({ type: "vintage-trash-changed" }, "*"); } catch (e) {}
      loadArchive().then(function (newData) {
        state.archive = Array.isArray(newData) ? newData : [];
        renderList();
      });
    })
    .catch(function () { toast("실패했습니다.", "error"); });
  }

  function onUpdateClick() {
    if (ROLE !== "admin") return;
    var btn = document.getElementById("updateBtn");
    if (!btn) return;
    btn.classList.add("is-loading");
    btn.disabled = true;
    btn.querySelector(".btn-label").textContent = "검색 중…";

    var excludeIds = state.archive.map(function (v) { return v.id; });
    var likedChannels = state.likes
      .filter(function (l) { return l.topic === topicId; })
      .map(function (l) { return l.video && l.video.channel; })
      .filter(function (c, i, arr) { return c && arr.indexOf(c) === i; });

    fetch("/api/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({
        topicId:       topicId,
        keywords:      topic.keywords  || [],
        channels:      topic.channels  || [],
        excludeIds:    excludeIds,
        likedChannels: likedChannels
      })
    })
    .then(function (r) {
      if (r.status === 403) throw new Error("admin only");
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    })
    .then(function (data) {
      btn.classList.remove("is-loading");
      btn.disabled = false;
      btn.querySelector(".btn-label").textContent = "업데이트 (영상 5개 추가)";
      if (data.added > 0) {
        toast(data.added + "개 영상이 추가되었습니다!", "success");
        loadArchive().then(function (newData) {
          state.archive = Array.isArray(newData) ? newData : [];
          state.page = 1;
          renderList();
        });
      } else {
        toast("새 영상을 찾지 못했습니다.", "error");
      }
    })
    .catch(function (e) {
      btn.classList.remove("is-loading");
      btn.disabled = false;
      btn.querySelector(".btn-label").textContent = "업데이트 (영상 5개 추가)";
      toast(e && e.message === "admin only" ? "관리자만 사용할 수 있습니다." : "서버 연결 실패.", "error");
    });
  }

  // ===== 토스트 =====
  function toast(msg, kind) {
    var host = document.getElementById("toastHost");
    if (!host) { host = document.createElement("div"); host.id = "toastHost"; host.className = "toast-host"; document.body.appendChild(host); }
    var el = document.createElement("div");
    el.className = "toast" + (kind ? " " + kind : " success");
    el.textContent = msg;
    host.appendChild(el);
    setTimeout(function () { el.style.opacity = "0"; el.style.transition = "opacity 0.3s"; }, 2400);
    setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 2800);
  }

  // ===== 이스케이프 =====
  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function escapeAttr(s) { return escapeHtml(s); }

  // ===== 헤더(히어로) 렌더 =====
  function renderHero() {
    var pillEl = document.getElementById("heroPill");
    var emojiEl = document.getElementById("heroEmoji");
    var titleEl = document.getElementById("heroTitle");
    var subEl = document.getElementById("heroSub");

    // 사이드바와 동일한 순서 → 현재 토픽 번호 계산
    var savedOrder = null;
    try {
      var raw = localStorage.getItem("vintage-topic-order");
      var parsed = raw ? JSON.parse(raw) : null;
      if (Array.isArray(parsed)) savedOrder = parsed;
    } catch (e) {}
    var ordered = manifest.topics.slice();
    if (savedOrder) {
      ordered.sort(function (a, b) {
        var ai = savedOrder.indexOf(a.id), bi = savedOrder.indexOf(b.id);
        if (ai === -1 && bi === -1) return 0;
        if (ai === -1) return 1;
        if (bi === -1) return -1;
        return ai - bi;
      });
    }
    var idx = -1;
    for (var i = 0; i < ordered.length; i++) if (ordered[i].id === topicId) { idx = i; break; }
    var heroNum = idx >= 0 ? ((idx + 1 < 10 ? "0" : "") + (idx + 1)) : "??";

    if (pillEl) pillEl.textContent = topic.label + " 큐레이션";
    if (emojiEl) { emojiEl.textContent = heroNum + "."; emojiEl.classList.add("hero-num"); }
    if (titleEl) titleEl.textContent = topic.label;
    if (subEl) subEl.textContent = (topic.description || "").split(".")[0] + ".";
    document.title = topic.label + " — Vintage Daily Digest";
  }

  // ===== 초기화 =====
  function init() {
    renderHero();
    renderMeta();
    Promise.all([loadArchive(), loadLikes()]).then(function (results) {
      state.archive = Array.isArray(results[0]) ? results[0] : [];
      renderList();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
