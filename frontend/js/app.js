const BASE = location.origin;

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
const weight = document.getElementById("weight");
const reqKo = document.getElementById("reqKo");
const btnSchedule = document.getElementById("btnSchedule");
const btnReset = document.getElementById("btnReset");

const summary = document.getElementById("summary");
const assignmentsWrap = document.getElementById("assignmentsWrap");

const courseNameById = Object.create(null);

// API
async function apiGet(path){const u=new URL(path,BASE);const r=await fetch(u);const t=await r.text();if(!r.ok){try{const j=JSON.parse(t);throw new Error(j.detail||j.message||t);}catch{throw new Error(t);}}return JSON.parse(t);}
async function apiPost(path,body){const u=new URL(path,BASE);const r=await fetch(u,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});const t=await r.text();if(!r.ok){try{const j=JSON.parse(t);throw new Error(j.detail||j.message||t);}catch{throw new Error(t);}}return JSON.parse(t);}

// 렌더
function pickKey(row, cands){for(const k of cands) if(k in row) return k; return cands[0];}
function renderCourses(list,total=null){
  coursesWrap.innerHTML="";
  coursesInfo.textContent = total==null?`총 ${list.length}건`:`검색 결과 ${total}건`;
  if(!list.length){coursesWrap.innerHTML=`<div class="muted">결과 없음</div>`;return;}
  const idKey=pickKey(list[0],["id","course_id","교과목코드"]);
  const nameKey=pickKey(list[0],["name","교과목명","과목명"]);
  list.forEach(r=>{const id=(r[idKey]??"")+"", nm=(r[nameKey]??"")+""; if(id) courseNameById[id]=nm||courseNameById[id]||"";});
  const cols=Object.keys(list[0]||{});
  const table=document.createElement("table");
  table.innerHTML=`<thead><tr>${cols.map(c=>`<th>${c}</th>`).join("")}</tr></thead>`+
    `<tbody>${list.map(row=>`<tr>${cols.map(c=>`<td>${row[c]??""}</td>`).join("")}</tr>`).join("")}</tbody>`;
  coursesWrap.appendChild(table);
}

const START_HOUR=9; const pad=n=>String(n).padStart(2,"0");
function addMin(h,m,a){const t=h*60+m+a;return [Math.floor(t/60)%24,t%60];}
function rangeOf(block,blockMin){const s=(block-1)*blockMin;const [sh,sm]=addMin(START_HOUR,0,s);const [eh,em]=addMin(sh,sm,blockMin);return `${pad(sh)}:${pad(sm)}~${pad(eh)}:${pad(em)}`;}

function groupPretty(assignments, blockMin){
  const map=new Map();
  assignments.forEach(a=>{
    const k=`${a.course_id}__${a.day}`;
    if(!map.has(k)) map.set(k,{course_id:a.course_id, day:a.day, blocks:[], room:a.room_id});
    map.get(k).blocks.push(a.block);
  });
  const lines=[];
  for(const v of map.values()){
    v.blocks.sort((a,b)=>a-b);
    let ranges=[], s=v.blocks[0], p=v.blocks[0];
    for(let i=1;i<v.blocks.length;i++){ if(v.blocks[i]===p+1){p=v.blocks[i];} else {ranges.push([s,p]); s=p=v.blocks[i];}}
    ranges.push([s,p]);
    const nm=courseNameById[v.course_id]||v.course_id;
    const big=ranges.map(([b1,b2])=>`${rangeOf(b1,blockMin).split("~")[0]}~${rangeOf(b2,blockMin).split("~")[1]}`).join(", ");
    const small=v.blocks.map(b=>`${b} ${rangeOf(b,blockMin)}`).join("\n");
    lines.push(`${nm} (${v.day})\n${big}\n${small}`);
  }
  return lines.join("\n\n");
}

function renderAssignments(assignments, blockMin){
  assignmentsWrap.innerHTML="";
  if(!assignments?.length){assignmentsWrap.innerHTML=`<div class="muted">배정 결과가 없습니다.</div>`; return;}
  const table=document.createElement("table");
  table.innerHTML=`
  <thead><tr><th>과목</th><th>세션</th><th>요일</th><th>블록</th><th>시간</th><th>강의실</th></tr></thead>
  <tbody>
    ${assignments.map(a=>{
      const nm=courseNameById[a.course_id]||a.course_id;
      return `<tr>
        <td>${nm}</td>
        <td>${a.session_index}</td>
        <td><span class="pill">${a.day}</span></td>
        <td>${a.block}</td>
        <td>${rangeOf(a.block, blockMin)}</td>
        <td>${a.room_id}</td>
      </tr>`;
    }).join("")}
  </tbody>`;
  assignmentsWrap.appendChild(table);

  const pre=document.createElement("pre");
  pre.style.whiteSpace="pre-wrap"; pre.style.marginTop="12px";
  pre.textContent=groupPretty(assignments, blockMin);
  assignmentsWrap.appendChild(pre);
}

// 이벤트
btnAll.addEventListener("click", async ()=>{
  try{ const data=await apiGet("/courses?limit=100&offset=0"); renderCourses(data); }
  catch(e){ console.error(e); alert(`불러오기 실패: ${e.message}`); }
});
btnSearch.addEventListener("click", async ()=>{
  const kw=(q.value||"").trim(); if(!kw) return alert("키워드를 입력하세요.");
  try{ const data=await apiGet(`/search?q=${encodeURIComponent(kw)}&limit=100&offset=0`); renderCourses(data.results, data.total); }
  catch(e){ console.error(e); alert(`검색 실패: ${e.message}`); }
});
btnSchedule.addEventListener("click", async ()=>{
  try{
    const payload={};
    const reqText=(reqKo.value||"").trim();
    if(reqText){ payload.requirements_ko=reqText; }
    else{
      payload.grid_days = days.value.split(",").map(s=>s.trim().toUpperCase()).filter(Boolean);
      payload.blocks_per_day = Number(blocks.value||8);
      payload.block_minutes = Number(minutes.value||50);
      payload.hard_no_friday_evening = !!noFri.checked;
      payload.soft_prefer_morning = !!prefMorning.checked;
      payload.soft_weight = Number(weight.value||1);
    }
    payload.randomize = true; // 항상 랜덤

    const res = await apiPost("/schedule", payload);
    const s = res.summary || {};
    summary.innerHTML = `<div class="muted">과목 ${s.courses??"?"}개 · 방 ${s.rooms??"?"}개 · 강사 ${s.instructors??"?"}명 · ${Array.isArray(s.days)?s.days.join(","):""} / 일일 ${s.blocks_per_day??"?"}교시</div>`;
    renderAssignments(res.solution?.assignments||[], Number(s.block_minutes||50));
  }catch(e){
    console.error(e);
    alert(`배정 실패: ${e.message}`);
  }
});
btnReset?.addEventListener("click", ()=> location.reload());

// 초기 로드
btnAll.click();
