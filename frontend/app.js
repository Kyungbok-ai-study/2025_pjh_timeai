const API = ""; // 같은 출처(127.0.0.1:8000)에서 서빙, 상대경로 사용

function render(rows){
  const thead=document.querySelector("#tbl thead");
  const tbody=document.querySelector("#tbl tbody");
  thead.innerHTML=""; tbody.innerHTML="";
  if(!rows.length){ thead.innerHTML="<tr><th>No data</th></tr>"; return; }
  const cols=Object.keys(rows[0]);
  thead.innerHTML="<tr>"+cols.map(c=>`<th>${c}</th>`).join("")+"</tr>";
  rows.forEach(r=>{
    const tr=document.createElement("tr");
    tr.innerHTML=cols.map(c=>`<td>${r[c] ?? ""}</td>`).join("");
    tbody.appendChild(tr);
  });
}

async function loadAll(){
  const res = await fetch(`${API}/courses?limit=100`);
  const data = await res.json();
  document.getElementById("meta").textContent = `표시: ${data.length}건`;
  render(data);
}

async function doSearch(){
  const q = document.getElementById("q").value.trim();
  if(!q){ loadAll(); return; }
  const res = await fetch(`${API}/search?q=${encodeURIComponent(q)}&limit=100`);
  const data = await res.json();
  document.getElementById("meta").textContent = `검색결과: ${data.total}건`;
  render(data.results);
}

window.addEventListener("DOMContentLoaded", loadAll);
