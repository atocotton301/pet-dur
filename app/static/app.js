// 이거 먹어도 돼? — 화면 로직 (빌드 없이 쓰는 바닐라 JS)
(() => {
  "use strict";
  const API = "/api";
  const EMOJI = { dog: "🐶", cat: "🐱", rabbit: "🐰", hamster: "🐹", hedgehog: "🦔", bird: "🦜" };
  const RISK = {
    danger: { dot: "🔴", text: "위험" },
    caution: { dot: "🟠", text: "주의" },
    safe: { dot: "🟢", text: "일반적으로 독성 보고가 없습니다" },
    unknown: { dot: "⚪", text: "확인된 정보 없음 · 수의사 상담 권장" },
  };
  const LEVEL = {
    avoid: { dot: "🔴", text: "함께 쓰면 안 돼요" },
    caution: { dot: "🟠", text: "함께 쓸 때 주의가 필요해요" },
    unknown: { dot: "⚪", text: "확인된 상호작용 정보 없음 · 수의사 상담 권장" },
  };
  const TYPE = { drug_ingredient: "약 성분", drug_class: "약물군", food: "음식", plant: "식물", household: "생활용품" };

  const $ = (s) => document.querySelector(s);
  const state = { species: null, speciesName: "", tray: [], lastQuery: "" };

  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? esc(u) : "#");

  function store(k, v) { try { localStorage.setItem(k, v); } catch (_) { /* 저장 불가 환경 무시 */ } }
  function load(k) { try { return localStorage.getItem(k); } catch (_) { return null; } }

  async function api(path, params) {
    const url = new URL(API + path, location.origin);
    Object.entries(params || {}).forEach(([k, v]) => url.searchParams.set(k, v));
    const res = await fetch(url);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `오류 ${res.status}`);
    return res.json();
  }

  // ---------- 종 선택 ----------
  async function initSpecies() {
    const list = await api("/species");
    const box = $("#species");
    box.innerHTML = list.map((s) =>
      `<button type="button" role="radio" aria-checked="false" data-code="${esc(s.code)}" data-name="${esc(s.name)}">
         <span class="emo" aria-hidden="true">${EMOJI[s.code] || "🐾"}</span>${esc(s.name)}</button>`).join("");
    box.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-code]");
      if (b) selectSpecies(b.dataset.code, b.dataset.name);
    });
    const saved = load("species");
    const first = list.find((s) => s.code === saved) || list[0];
    selectSpecies(first.code, first.name, true);
  }

  function selectSpecies(code, name, silent) {
    const changed = state.species && state.species !== code;
    state.species = code; state.speciesName = name; store("species", code);
    document.querySelectorAll("#species button").forEach((b) =>
      b.setAttribute("aria-checked", String(b.dataset.code === code)));
    if (changed && state.tray.length) { state.tray = []; renderTray(); }
    $("#combo-result").innerHTML = "";
    if (!silent && state.lastQuery) doSearch(state.lastQuery);
  }

  // ---------- 검색 ----------
  async function doSearch(q) {
    q = q.trim(); if (!q) return;
    state.lastQuery = q;
    const box = $("#results");
    $("#clinics").innerHTML = ""; $("#combo-result").innerHTML = "";
    box.innerHTML = `<div class="spinner">찾는 중…</div>`;
    try {
      const r = await api("/search", { q, species: state.species });
      renderResults(r);
    } catch (err) {
      box.innerHTML = `<div class="empty">검색 중 문제가 생겼어요. ${esc(err.message)}</div>`;
    }
  }

  function renderResults(r) {
    const box = $("#results");
    const parts = [];
    const total = r.substances.length + r.products.length + r.vet_products.length;
    if (!total) {
      box.innerHTML = `<div class="card r-unknown">${badge(RISK.unknown)}
        <div class="card-body"><p class="name">‘${esc(r.query)}’</p>
        <p>이 이름으로 등록된 정보를 찾지 못했어요. <strong>찾을 수 없다는 것이 안전하다는 뜻은 아닙니다.</strong>
        이미 먹었다면 동물병원에 연락하세요.</p>
        <p class="note">제품명은 포장에 적힌 대로, 성분명(예: 아세트아미노펜)이나 음식·식물 이름으로도 검색해 보세요.</p></div></div>`;
      return;
    }
    if (r.fuzzy) parts.push(`<p class="note">‘${esc(r.query)}’와 비슷한 이름으로 찾았어요.</p>`);
    if (r.substances.length) {
      parts.push(`<h3 class="section-title">${esc(state.speciesName)}에게 · 성분/음식/식물</h3>`);
      r.substances.forEach((s) => parts.push(substanceCard(s)));
    }
    if (r.products.length) {
      parts.push(`<h3 class="section-title">사람 약 제품 (${r.products.length})</h3>`);
      r.products.forEach((p) => parts.push(productCard(p)));
    }
    if (r.vet_products.length) {
      parts.push(`<h3 class="section-title">동물용 의약품</h3>`);
      parts.push(`<div class="card"><div class="card-body">
        <ul class="ing">${r.vet_products.map((v) => `<li><span>${esc(v.name)}</span><span class="muted">${esc(v.usage_type || "")}</span></li>`).join("")}</ul>
        <p class="note">${esc(r.vet_products[0].note)}</p></div></div>`);
    }
    box.innerHTML = parts.join("");
    const worst = [...r.substances.map((s) => s.risk), ...r.products.map((p) => p.overall_risk)];
    if (worst.includes("danger")) renderClinicPrompt();
  }

  const badge = (m) => `<div class="badge"><span class="dot" aria-hidden="true">${m.dot}</span><span>${esc(m.text)}</span></div>`;

  function sourcesBlock(sources) {
    if (!sources || !sources.length) return "";
    return `<details class="src"><summary>출처 ${sources.length}건 보기</summary><ol>${sources.map((s) =>
      `<li><a href="${safeUrl(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.name)}</a>
        <span class="muted">· 확인 ${esc(s.checked_on)}</span></li>`).join("")}</ol></details>`;
  }

  function reviewChip(status) {
    if (!status) return "";
    const txt = status === "감수완료" ? "수의사 감수 완료" : status === "수의사 검토중" ? "수의사 검토 중" : "수의사 감수 전";
    return `<span class="chip review">${txt}</span>`;
  }

  function list(items) { return `<ul>${items.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`; }

  function substanceCard(s) {
    const facts = [];
    if (s.risk === "unknown") {
      facts.push(`<p>${esc(state.speciesName)}에 대해 확인된 근거 자료가 아직 없어요. <strong>정보가 없다는 것이 안전하다는 뜻은 아닙니다.</strong></p>`);
    } else {
      if (s.mechanism) facts.push(`<dt>왜 그런가요?</dt><dd>${esc(s.mechanism)}</dd>`);
      if (s.symptoms.length) facts.push(`<dt>나타날 수 있는 증상</dt><dd>${list(s.symptoms)}</dd>`);
      if (s.first_aid.length) facts.push(`<dt>이렇게 하세요</dt><dd>${list(s.first_aid)}</dd>`);
    }
    const key = `s:${s.substance_id}`;
    return `<article class="card r-${esc(s.risk)}">${badge(RISK[s.risk])}
      <div class="card-body">
        <p class="name">${esc(s.name)}<small>${esc(s.name_en || "")}</small></p>
        <span class="kind">${esc(TYPE[s.type] || "")}</span>
        ${s.risk === "unknown" ? facts.join("") : `<dl class="facts">${facts.join("")}</dl>`}
        <div class="chips">${reviewChip(s.review_status)}</div>
        ${sourcesBlock(s.sources)}
      </div>
      ${addButton(key, s.name, s.type)}
    </article>`;
  }

  function productCard(p) {
    const ings = p.ingredients.map((i) =>
      `<li><span>${esc(i.raw_name)}</span><span class="lvl ${esc(i.risk)}">${RISK[i.risk].dot} ${esc(shortRisk(i.risk))}</span></li>`).join("");
    const reasons = p.ingredients.filter((i) => i.risk === "danger" || i.risk === "caution")
      .map((i) => `<dt>${esc(i.raw_name)}</dt><dd>${esc(i.mechanism || "")}${i.first_aid && i.first_aid.length ? list(i.first_aid) : ""}${sourcesBlock(i.sources)}</dd>`).join("");
    return `<article class="card r-${esc(p.overall_risk)}">${badge(RISK[p.overall_risk])}
      <div class="card-body">
        <p class="name">${esc(p.name)}</p><span class="kind">${esc(p.company || "")} · 사람 약</span>
        <ul class="ing" aria-label="성분별 판정">${ings}</ul>
        ${p.has_unknown_ingredient ? `<p class="note">⚪ 표시 성분은 ${esc(state.speciesName)}에 대해 확인된 정보가 없어요. 종합 판정은 가장 위험한 성분 기준입니다.</p>` : ""}
        ${reasons ? `<dl class="facts">${reasons}</dl>` : ""}
      </div>
      ${addButton(`p:${p.item_seq}`, p.name, "human_drug")}
    </article>`;
  }

  const shortRisk = (r) => ({ danger: "위험", caution: "주의", safe: "보고 없음", unknown: "정보 없음" }[r]);

  function addButton(key, name, type) {
    // 병용은 약끼리(또는 약+음식) 확인하는 기능이라 식물·생활용품은 담지 않는다
    if (type === "plant" || type === "household") return "";
    const on = state.tray.some((t) => t.key === key);
    return `<div class="card-actions"><button type="button" class="add-btn" aria-pressed="${on}"
      data-key="${esc(key)}" data-name="${esc(name)}">${on ? "✓ 담음" : "+ 같이 먹여도 되는지 확인"}</button></div>`;
  }

  // ---------- 병용 트레이 ----------
  function toggleTray(key, name) {
    const i = state.tray.findIndex((t) => t.key === key);
    if (i >= 0) state.tray.splice(i, 1);
    else if (state.tray.length < 10) state.tray.push({ key, name });
    renderTray();
  }

  function renderTray() {
    const tray = $("#tray");
    tray.hidden = state.tray.length === 0;
    $("#tray-items").innerHTML = state.tray.map((t) =>
      `<li><span>${esc(t.name)}</span><button type="button" aria-label="${esc(t.name)} 빼기" data-remove="${esc(t.key)}">×</button></li>`).join("");
    $("#tray-check").disabled = state.tray.length < 2;
    $("#tray-hint").textContent = state.tray.length < 2 ? "2개 이상 담으면 확인할 수 있어요" : `${state.tray.length}개 · ${state.speciesName} 기준`;
    document.querySelectorAll(".add-btn").forEach((b) => {
      const on = state.tray.some((t) => t.key === b.dataset.key);
      b.setAttribute("aria-pressed", String(on));
      b.textContent = on ? "✓ 담음" : "+ 같이 먹여도 되는지 확인";
    });
  }

  async function checkCombo() {
    const box = $("#combo-result");
    box.innerHTML = `<div class="spinner">확인하는 중…</div>`;
    box.scrollIntoView({ behavior: "smooth", block: "start" });
    try {
      const r = await api("/interactions/check", { items: state.tray.map((t) => t.key).join(","), species: state.species });
      renderCombo(r);
    } catch (err) {
      box.innerHTML = `<div class="empty">확인 중 문제가 생겼어요. ${esc(err.message)}</div>`;
    }
  }

  function renderCombo(r) {
    const pairs = r.pairs.map((p) => {
      const rules = p.matches.map((m) => `<dt>${esc(m.via[0])} + ${esc(m.via[1])}
          ${m.rule_between.join("+") !== m.via.join("+") ? `<span class="muted">(${esc(m.rule_between[0])} + ${esc(m.rule_between[1])} 규칙)</span>` : ""}</dt>
        <dd>${LEVEL[m.level].dot} ${esc(m.mechanism || "")}${m.advice ? `<p class="note">${esc(m.advice)}</p>` : ""}
          <div class="chips">${reviewChip(m.review_status)}</div>${sourcesBlock(m.sources)}</dd>`).join("");
      const dup = p.duplicate_ingredients.length
        ? `<p class="alert soft">두 가지에 같은 성분(${p.duplicate_ingredients.map(esc).join(", ")})이 들어 있어요. 함께 먹이면 같은 성분을 겹쳐 먹게 됩니다.</p>` : "";
      const unchecked = p.unchecked_ingredients.length
        ? `<p class="note">⚪ 확인된 정보가 없는 성분: ${p.unchecked_ingredients.map(esc).join(", ")}</p>` : "";
      return `<article class="card l-${esc(p.level)}">${badge(LEVEL[p.level])}
        <div class="card-body"><p class="name">${esc(p.a)} <span class="muted">+</span> ${esc(p.b)}</p>
          ${dup}${rules ? `<dl class="facts">${rules}</dl>` : `<p>${esc(state.speciesName)}에서 이 조합의 상호작용 근거를 찾지 못했어요. <strong>함께 써도 된다는 뜻은 아닙니다.</strong></p>`}
          ${unchecked}</div></article>`;
    }).join("");
    $("#combo-result").innerHTML = `<h3 class="section-title">${EMOJI[state.species] || ""} ${esc(state.speciesName)} · 같이 먹여도 될까?</h3>
      <div class="card l-${esc(r.overall_level)}">${badge(LEVEL[r.overall_level])}</div>${pairs}`;
    if (r.overall_level === "avoid") renderClinicPrompt();
  }

  // ---------- 동물병원 ----------
  function renderClinicPrompt() {
    const box = $("#clinics");
    if (box.dataset.loaded === "1" || box.innerHTML) return;
    box.innerHTML = `<div class="alert">이미 먹었다면 증상이 없어도 바로 동물병원에 연락하세요.</div>
      <button type="button" id="find-clinics" class="primary">📍 가까운 동물병원 찾기</button>
      <p class="note">위치는 가까운 병원을 찾는 데만 쓰고 저장하지 않아요.</p>`;
  }

  function findClinics() {
    const box = $("#clinics");
    if (!navigator.geolocation) { box.innerHTML = `<div class="empty">이 기기에서는 위치를 확인할 수 없어요.</div>`; return; }
    box.innerHTML = `<div class="spinner">위치를 확인하는 중…</div>`;
    navigator.geolocation.getCurrentPosition(async (pos) => {
      try {
        const r = await api("/clinics", { lat: pos.coords.latitude.toFixed(5), lng: pos.coords.longitude.toFixed(5), limit: 8 });
        renderClinics(r);
      } catch (err) {
        box.innerHTML = `<div class="empty">병원을 불러오지 못했어요. ${esc(err.message)}</div>`;
      }
    }, () => {
      box.innerHTML = `<div class="empty">위치 권한이 없어 가까운 병원을 찾지 못했어요. 지도 앱에서 ‘동물병원’을 검색해 주세요.</div>`;
    }, { enableHighAccuracy: false, timeout: 10000, maximumAge: 300000 });
  }

  function renderClinics(r) {
    const box = $("#clinics");
    box.dataset.loaded = "1";
    if (!r.clinics.length) { box.innerHTML = `<div class="empty">반경 10km 안에서 영업 중인 동물병원을 찾지 못했어요.</div>`; return; }
    box.innerHTML = `<h3 class="section-title">가까운 동물병원</h3><div class="card">${r.clinics.map((c) => `
      <div class="clinic"><div><strong>${esc(c.name)}</strong>${c.name_suggests_24h ? `<span class="tag24">24시(추정)</span>` : ""}
        <div class="meta">${esc(c.distance_km)}km · ${esc(c.address || "")}</div>${mapLinks(c.links)}</div>
        ${c.tel ? `<a class="call" href="tel:${esc(String(c.tel).replace(/[^0-9]/g, ""))}">전화</a>` : ""}</div>`).join("")}</div>
      <p class="note">${esc(r.note)}</p>`;
  }

  function mapLinks(l) {
    if (!l) return "";
    return `<div class="maplinks"><a class="naver" href="${safeUrl(l.naver)}" target="_blank" rel="noopener noreferrer">네이버 지도</a>
      <a class="kakao" href="${safeUrl(l.kakao)}" target="_blank" rel="noopener noreferrer">카카오맵</a>
      <a href="${safeUrl(l.kakao_route)}" target="_blank" rel="noopener noreferrer">길찾기</a></div>`;
  }
  window.PetUI = { esc, safeUrl, api, mapLinks };

  // ---------- 이벤트 ----------
  $("#search-form").addEventListener("submit", (e) => { e.preventDefault(); doSearch($("#q").value); });
  document.querySelector(".examples").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-q]");
    if (b) { $("#q").value = b.dataset.q; doSearch(b.dataset.q); }
  });
  document.addEventListener("click", (e) => {
    const add = e.target.closest(".add-btn");
    if (add) toggleTray(add.dataset.key, add.dataset.name);
    const rm = e.target.closest("[data-remove]");
    if (rm) { state.tray = state.tray.filter((t) => t.key !== rm.dataset.remove); renderTray(); }
    if (e.target.closest("#find-clinics")) findClinics();
  });
  $("#tray-clear").addEventListener("click", () => { state.tray = []; renderTray(); $("#combo-result").innerHTML = ""; });
  $("#tray-check").addEventListener("click", checkCombo);

  initSpecies().catch((err) => { $("#species").innerHTML = `<div class="empty">서버에 연결하지 못했어요. ${esc(err.message)}</div>`; });
})();
