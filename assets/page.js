/* =============================================================
   AI Daily Digest — 콘텐츠 페이지 공용 스크립트 (page.js)
   -------------------------------------------------------------
   - 셸(index.html) iframe 안에서 열릴 때: ?theme= 파라미터 +
     부모 창의 postMessage 로 다크/라이트 테마를 동기화.
   - 단독으로 열릴 때: localStorage 또는 OS 설정을 따름.
   - 카드/섹션 스크롤 등장 애니메이션.
   ============================================================= */
(function () {
  "use strict";

  /* ---- 테마 결정 ---- */
  function applyTheme(t) {
    if (t !== "light" && t !== "dark") return;
    document.documentElement.classList.remove("theme-dark", "theme-light");
    document.documentElement.classList.add("theme-" + t);
  }

  var params = new URLSearchParams(window.location.search);
  var fromUrl = params.get("theme");
  var fromStore = null;
  try { fromStore = localStorage.getItem("digest-theme"); } catch (e) {}

  applyTheme(fromUrl || fromStore || "dark");

  /* ---- 부모 셸에서 테마 변경 메시지 수신 ---- */
  window.addEventListener("message", function (ev) {
    var d = ev.data;
    if (d && d.type === "digest-theme" && d.theme) applyTheme(d.theme);
  });

  /* ---- 스크롤 등장 애니메이션 ----
     IntersectionObserver 는 빠른 점프 스크롤 시 중간 요소를 놓치므로
     매 스크롤마다 화면에 들어온 요소를 전수 검사하는 방식을 쓴다. */
  function initReveal() {
    var items = Array.prototype.slice.call(document.querySelectorAll(".reveal"));
    if (!items.length) return;

    function show(el) {
      if (el.classList.contains("in")) return;
      var delay = parseInt(el.getAttribute("data-delay") || "0", 10);
      setTimeout(function () { el.classList.add("in"); }, delay);
    }
    function sweep() {
      var vh = window.innerHeight || document.documentElement.clientHeight;
      for (var i = 0; i < items.length; i++) {
        if (!items[i].classList.contains("in") &&
            items[i].getBoundingClientRect().top < vh * 0.92) {
          show(items[i]);
        }
      }
    }
    var ticking = false;
    function onScroll() {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(function () { sweep(); ticking = false; });
    }
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    sweep();
    /* 안전망: 어떤 경우에도 콘텐츠가 영구히 숨겨지지 않도록 */
    setTimeout(function () {
      items.forEach(function (el) { el.classList.add("in"); });
    }, 3500);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initReveal);
  } else {
    initReveal();
  }
})();
