const $ = (id) => document.getElementById(id);
let currentId = null;
let pollTimer = null;

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function show(id, v = true) { $(id).classList.toggle("hidden", !v); }

async function loadHistory() {
  try {
    const items = await api("/api/history");
    const el = $("history");
    el.innerHTML = "";
    items.slice(0, 12).forEach((h) => {
      const b = document.createElement("button");
      b.textContent = h.query.slice(0, 40);
      b.onclick = () => openResult(h.id);
      el.appendChild(b);
    });
  } catch (e) {}
}

async function openResult(id) {
  currentId = id;
  show("statusPanel", false);
  const data = await api(`/api/search/${id}`);
  renderResult(data);
}

function renderResult(data) {
  show("results", true);
  $("summary").textContent = data.summary || "Sem resumo disponível.";
  const gallery = $("gallery");
  gallery.innerHTML = "";
  (data.images || []).forEach((im) => {
    const card = document.createElement("div");
    card.className = "card";
    const img = document.createElement("img");
    img.src = im.thumb_url || im.local_url;
    img.onclick = () => openModal(im.local_url);
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.innerHTML = `
      <span class="badge">${im.classification}</span>
      <span class="badge">${Math.round((im.relevance || 0) * 100)}%</span>
      <div>${im.verification_status}</div>
      <a class="small-btn download" href="/api/images/${im.id}/file" download>Baixar</a>
    `;
    card.appendChild(img);
    card.appendChild(meta);
    gallery.appendChild(card);
  });

  const facts = $("facts");
  facts.innerHTML = "";
  (data.facts || []).forEach((f) => {
    const div = document.createElement("div");
    div.className = "fact";
    div.innerHTML = `<div class="key">${escapeHtml(f.key)}</div><div>${escapeHtml(f.value)}</div><div class="conf">${f.confidence} · ${f.status}</div>`;
    facts.appendChild(div);
  });

  $("reliability").textContent = JSON.stringify(data.reliability || {}, null, 2);
  const sources = $("sources");
  sources.innerHTML = "";
  (data.sources || []).forEach((s) => {
    const li = document.createElement("li");
    li.innerHTML = `<a href="${s.url}" target="_blank" rel="noopener">${escapeHtml(s.title || s.url)}</a> <span class="badge">${s.provider || ""}</span>`;
    sources.appendChild(li);
  });

  $("downloadAll").onclick = () => { window.location.href = `/api/downloads/zip?search_id=${data.id}`; };
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]));
}

function openModal(src) {
  $("modalImg").src = src;
  show("modal", true);
}
$("modalClose").onclick = () => show("modal", false);
$("modal").onclick = (e) => { if (e.target.id === "modal") show("modal", false); };

$("copySummary").onclick = async () => {
  try { await navigator.clipboard.writeText($("summary").textContent); } catch (e) {}
};

$("searchForm").onsubmit = async (e) => {
  e.preventDefault();
  const query = $("queryInput").value.trim();
  if (!query) return;
  const deep = $("deepToggle").checked;
  $("searchBtn").disabled = true;
  show("results", false);
  show("statusPanel", true);
  try {
    const res = await api("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, deep }),
    });
    currentId = res.id;
    pollStatus();
  } catch (err) {
    $("statusMessage").textContent = "Erro ao iniciar pesquisa.";
    $("searchBtn").disabled = false;
  }
};

function pollStatus() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(async () => {
    if (!currentId) return;
    try {
      const st = await api(`/api/search/${currentId}/status`);
      $("stageText").textContent = st.stage;
      $("progressText").textContent = st.progress + "%";
      $("progressBar").style.width = st.progress + "%";
      $("statusMessage").textContent = st.message || "";
      if (st.status === "completed" || st.status === "failed") {
        clearInterval(pollTimer);
        pollTimer = null;
        $("searchBtn").disabled = false;
        const data = await api(`/api/search/${currentId}`);
        renderResult(data);
        loadHistory();
      }
    } catch (e) {}
  }, 2000);
}

loadHistory();