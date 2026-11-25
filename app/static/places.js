// 내 주변 탭: 동물병원·유치원/호텔·미용 지도와 목록, 네이버·카카오 지도 바로가기
(() => {
  "use strict";
  const { esc, safeUrl, api, mapLinks } = window.PetUI;
  const $ = (s) => document.querySelector(s);
  const DEFAULT = { lat: 37.5665, lng: 126.978 }; // 위치 권한이 없을 때: 서울시청
  const COLORS = { hospital: "#d6323a", boarding: "#2557d6", grooming: "#8b5cf6" };
  const st = { map: null, layer: null, center: null, cats: [], selected: new Set(), started: false };

  // ---------- 탭 전환 ----------
  function show(view) {
    const places = view === "places";
    $("#view-safety").hidden = places;
    $("#view-places").hidden = !places;
    $("#tab-safety").setAttribute("aria-selected", String(!places));
    $("#tab-places").setAttribute("aria-selected", String(places));
    document.body.dataset.view = view;
    if (places && !st.started) start();
    if (places && st.map) setTimeout(() => st.map.invalidateSize(), 0);
  }
  $("#tab-safety").addEventListener("click", () => show("safety"));
  $("#tab-places").addEventListener("click", () => show("places"));

  // ---------- 시작 ----------
  async function start() {
    st.started = true;
    st.cats = await api("/places/categories");
    st.cats.forEach((c) => { if (c.count) st.selected.add(c.code); });
    renderCats();
    if (window.L) {
      st.map = L.map("map", { zoomControl: true }).setView([DEFAULT.lat, DEFAULT.lng], 14);
      L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19, attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
      }).addTo(st.map);
      st.layer = L.layerGroup().addTo(st.map);
      st.map.on("moveend", () => { if (st.center) $("#search-here").hidden = false; });
    } else {
      $("#map").hidden = true; // 지도 스크립트를 못 불러와도 목록은 보여준다
    }
    locate();
  }

  function renderCats() {
    $("#place-cats").innerHTML = st.cats.map((c) =>
      `<button type="button" data-cat="${esc(c.code)}" aria-pressed="${st.selected.has(c.code)}"
         ${c.count ? "" : "disabled title=\"데이터 준비 중\""}>${esc(c.label)}<span class="cnt">${c.count ? c.count.toLocaleString() : "준비 중"}</span></button>`).join("");
  }
  $("#place-cats").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-cat]");
    if (!b) return;
    const c = b.dataset.cat;
    st.selected.has(c) ? st.selected.delete(c) : st.selected.add(c);
    renderCats();
    if (st.center) load(st.center);
  });

  // ---------- 위치 ----------
  function locate() {
    if (!navigator.geolocation) { load(DEFAULT, "위치를 확인할 수 없어 서울시청 주변을 보여드려요."); return; }
    $("#place-status").textContent = "위치를 확인하는 중…";
    navigator.geolocation.getCurrentPosition(
      (p) => load({ lat: p.coords.latitude, lng: p.coords.longitude }),
      () => load(DEFAULT, "위치 권한이 없어 서울시청 주변을 보여드려요. 지도를 움직인 뒤 ‘이 지역에서 다시 찾기’를 누르세요."),
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
  }
  $("#locate").addEventListener("click", locate);
  $("#search-here").addEventListener("click", () => {
    const c = st.map.getCenter();
    load({ lat: c.lat, lng: c.lng });
  });

  // ---------- 불러오기 ----------
  async function load(center, msg) {
    st.center = center;
    $("#search-here").hidden = true;
    const cats = [...st.selected];
    if (!cats.length) { render([], "보고 싶은 장소 종류를 골라 주세요."); return; }
    $("#place-status").textContent = msg || "주변을 찾는 중…";
    try {
      const r = await api("/places", { lat: center.lat.toFixed(5), lng: center.lng.toFixed(5), categories: cats.join(","), radius_km: 3, limit: 40 });
      render(r.places, msg);
      if (st.map) { st.map.setView([center.lat, center.lng], st.map.getZoom()); $("#search-here").hidden = true; }
    } catch (err) {
      render([], `불러오지 못했어요. ${err.message}`);
    }
  }

  function render(places, msg) {
    $("#place-status").textContent = msg || (places.length ? `반경 3km · 가까운 순 ${places.length}곳` : "반경 3km 안에 찾은 곳이 없어요.");
    if (st.layer) {
      st.layer.clearLayers();
      if (st.center) L.circleMarker([st.center.lat, st.center.lng], { radius: 6, color: "#111", fillOpacity: 1 }).addTo(st.layer);
      places.forEach((p) => {
        L.circleMarker([p.lat, p.lng], { radius: 8, color: "#fff", weight: 2, fillColor: COLORS[p.category] || "#444", fillOpacity: 0.95 })
          .bindPopup(`<strong>${esc(p.name)}</strong><br>${esc(p.category_label)} · ${esc(p.distance_km)}km${mapLinks(p.links)}`)
          .addTo(st.layer);
      });
    }
    $("#place-list").innerHTML = places.length ? `<div class="card">${places.map((p) => `
      <div class="place"><div>
        <span class="cat" style="color:${COLORS[p.category] || "inherit"}">● ${esc(p.category_label)}</span>
        <div><strong>${esc(p.name)}</strong>${p.category === "hospital" && p.name_suggests_24h ? `<span class="tag24">24시(추정)</span>` : ""}</div>
        <div class="meta">${esc(p.distance_km)}km · ${esc(p.address || "")}</div>
        ${mapLinks(p.links)}</div>
        ${p.tel ? `<a class="call" href="tel:${esc(String(p.tel).replace(/[^0-9]/g, ""))}">전화</a>` : ""}
      </div>`).join("")}</div>` : "";
  }
})();
