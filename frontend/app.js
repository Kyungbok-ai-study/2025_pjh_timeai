const BASE = location.origin; // 같은 오리진 (예: http://localhost:8000)

// 엘리먼트
const q = document.getElementById("q");
const btnSearch = document.getElementById("btnSearch");
const btnAll = document.getElementById("btnAll");
const coursesInfo = document.getElementById("coursesInfo");
const coursesWrap = document.getElementById("coursesWrap");

const days = document.getElementById("days");
const blocks = document.getElementById("blocks");
const minutes = document.getElementById("minutes");
const noFri = document.getElementById("noFri");
const prefMorning = document.getElementById("prefMorning");
const prefCompact = document.getElementById("prefCompact");
const weight = document.getElementById("weight");
const reqKo = document.getElementById("reqKo");
const btnSchedule = document.getElementById("btnSchedule");

const summary = document.getElementById("summary");
const assignmentsWrap = document.getElementById("assignmentsWrap");

// === 유틸 ===
async function apiGet(path) {
  const url = new URL(path, BASE); // 절대경로 생성
  console.debug("GET", url.href);
  const res = await fetch(url.href);
  const txt = await res.text();
  if (!res.ok) {
    try { const j = JSON.parse(txt); throw new Error(j.detail || j.message || txt); }
    catch { throw new Error(txt); }
  }
  return JSON.parse(txt);
}

async function apiPost(path, body) {
  const url = new URL(path, BASE); // 절대경로 생성
  console.debug("POST", url.href, body);
  const res = await fetch(url.href, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const txt = await res.text();
  if (!res.ok) {
    try { const j = JSON.parse(txt); throw new Error(j.detail || j.message || txt); }
    catch { throw new Error(txt); }
  }
  return JSON.parse(txt);
}

// === 렌더링 ===
function renderCourses(list, total = null) {
  coursesWrap.innerHTML = "";
  const info = total == null ? `총 ${list.length}건` : `검색 결과 ${total}건`;
  coursesInfo.textContent = info;

  if (!list.length) {
    coursesWrap.innerHTML = `<div class="muted">결과 없음</div>`;
    return;
  }

  const cols = Object.keys(list[0] || {});
  const table = document.createElement("table");
  const thead = document.createElement("thead");
  thead.innerHTML = `<tr>${cols.map(c => `<th>${c}</th>`).join("")}</tr>`;
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  list.forEach(row => {
    const tr = document.createElement("tr");
    tr.innerHTML = cols.map(c => `<td>${row[c] ?? ""}</td>`).join("");
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);
  coursesWrap.appendChild(table);
}

function renderAssignments(assignments) {
  assignmentsWrap.innerHTML = "";
  if (!assignments || !assignments.length) {
    assignmentsWrap.innerHTML = `<div class="muted">배정 결과가 없습니다.</div>`;
    return;
  }
  const table = document.createElement("table");
  table.innerHTML = `
    <thead>
      <tr><th>course_id</th><th>session</th><th>day</th><th>block</th><th>room</th></tr>
    </thead>
    <tbody>
      ${assignments.map(a => `
        <tr>
          <td>${a.course_id}</td>
          <td>${a.session_index}</td>
          <td><span class="pill">${a.day}</span></td>
          <td>${a.block}</td>
          <td>${a.room_id}</td>
        </tr>`).join("")}
    </tbody>`;
  assignmentsWrap.appendChild(table);
}

// === 이벤트 ===
btnAll.addEventListener("click", async () => {
  try {
    const data = await apiGet("/courses?limit=100&offset=0");
    renderCourses(data);
  } catch (e) {
    console.error(e);
    alert(`불러오기 실패: ${e.message}`);
  }
});

btnSearch.addEventListener("click", async () => {
  const kw = (q.value || "").trim();
  if (!kw) return alert("키워드를 입력하세요.");
  try {
    const data = await apiGet(`/search?q=${encodeURIComponent(kw)}&limit=100&offset=0`);
    renderCourses(data.results, data.total);
  } catch (e) {
    console.error(e);
    alert(`검색 실패: ${e.message}`);
  }
});

btnSchedule.addEventListener("click", async () => {
  try {
    const payload = {};
    const reqText = (reqKo.value || "").trim();

    if (reqText) {
      payload.requirements_ko = reqText;
    } else {
      payload.grid_days = days.value.split(",").map(s => s.trim()).filter(Boolean);
      payload.blocks_per_day = Number(blocks.value || 8);
      payload.block_minutes = Number(minutes.value || 50);
      payload.hard_no_friday_evening = !!noFri.checked;
      payload.soft_prefer_morning = !!prefMorning.checked;
      payload.soft_prefer_compact_days = !!prefCompact.checked;
      payload.soft_weight = Number(weight.value || 1);
    }

    const res = await apiPost("/schedule", payload);

    const s = res.summary || {};
    summary.innerHTML = `
      <div class="muted">
        과목 ${s.courses ?? "?"}개 · 방 ${s.rooms ?? "?"}개 · 강사 ${s.instructors ?? "?"}명 ·
        ${Array.isArray(s.days) ? s.days.join(",") : ""} / 일일 ${s.blocks_per_day ?? "?"}교시
      </div>`;

    renderAssignments(res.solution?.assignments || []);
  } catch (e) {
    console.error(e);
    alert(`배정 실패: ${e.message}`); // 에러 원인 그대로 표시
  }
});

// 최초 로드
btnAll.click();
