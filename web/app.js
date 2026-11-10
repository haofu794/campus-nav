// Static front end: load data.json once, filter/sort in memory, save progress to localStorage.
// ~20k jobs is small enough that filtering in the browser is instant; no backend needed.

const PROGRESS_KEY = "campus-nav-progress-v1";
const STATUSES = ["", "想投", "已投递", "笔试", "面试", "Offer", "挂了", "不合适"];
const DONE = new Set(["已投递", "笔试", "面试", "Offer", "挂了", "不合适"]);
const PAGE = 60;

const state = {
  data: null, tab: "校招", q: "", direction: "", city: "", ents: new Set(),
  onlyNew: false, hideApplied: false, sort: "rec", shown: PAGE, skills: [],
  cat: "", cstatus: "", cmark: "", csort: "opened", only: null,
};

// Company directory marks (separate from per-job progress): {company: {mark, date}}
const COMPANY_KEY = "campus-nav-companies-v1";
const CMARKS = ["", "关注", "已看过", "已投递", "不考虑"];
const SCRAPED = new Set(["campus_radar", "pingan", "feishu", "beisen", "hotjob"]);
function loadMarks() {
  try { return JSON.parse(localStorage.getItem(COMPANY_KEY) || "{}"); } catch { return {}; }
}
function saveMarks(m) {
  try { localStorage.setItem(COMPANY_KEY, JSON.stringify(m)); } catch (e) { alert("保存失败：" + e.message); }
}
let marks = loadMarks();

// ---------- localStorage (wrapped: storage can throw in private mode) ----------
function loadProgress() {
  try { return JSON.parse(localStorage.getItem(PROGRESS_KEY) || "{}"); } catch { return {}; }
}
function saveProgress(p) {
  try { localStorage.setItem(PROGRESS_KEY, JSON.stringify(p)); } catch (e) { alert("保存失败：" + e.message); }
}
let progress = loadProgress();

// ---------- helpers ----------
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
function daysAgo(iso) {
  if (!iso) return Infinity;
  return (new Date(state.data.today) - new Date(iso)) / 86400000;
}
function countBy(arr, f) {
  const m = new Map();
  for (const x of arr) for (const k of [].concat(f(x))) m.set(k, (m.get(k) || 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1]);
}

// ---------- filtering ----------
function filtered() {
  const q = state.q.trim().toLowerCase();
  const mySkills = new Set(state.skills);
  let list = state.data.jobs.filter((j) => {
    if (state.tab === "mine") { if (!progress[j.id]?.status) return false; }
    else if (j.recruit !== state.tab) return false;
    if (state.only && j.src !== state.only.src) return false;
    if (state.direction && j.direction !== state.direction) return false;
    if (state.city && !j.cities.includes(state.city)) return false;
    if (state.ents.size && !state.ents.has(j.ent)) return false;
    if (state.onlyNew && daysAgo(j.first_seen) > 7) return false;
    if (state.hideApplied && state.tab !== "mine" && DONE.has(progress[j.id]?.status)) return false;
    if (q) {
      const hay = (j.company + " " + j.title + " " + j.skills.join(" ") + " " + j.cities.join(" ")).toLowerCase();
      if (!q.split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    return true;
  });
  const bySort = {
    rec: (a, b) => (a.rec ?? 1e9) - (b.rec ?? 1e9) || b.match - a.match,
    match: (a, b) => b.match - a.match,
    new: (a, b) => (b.first_seen || "").localeCompare(a.first_seen || "") || b.match - a.match,
  };
  if (state.tab === "mine") list.sort((a, b) => (progress[b.id].date || "").localeCompare(progress[a.id].date || ""));
  else list.sort(bySort[state.sort]);
  return { list, mySkills };
}

// ---------- rendering ----------
// Company avatar: first character on a colour picked from the name, so the
// same company always gets the same colour (no logo files to host).
const AVATAR_COLORS = ["#00a870", "#3370ff", "#7b61ff", "#f5631e", "#e8488b", "#14a3b8", "#c7880a", "#5b6b7f"];
function avatar(name) {
  let h = 0;
  for (const ch of name || "?") h = (h * 31 + ch.codePointAt(0)) >>> 0;
  return `<div class="avatar" style="background:${AVATAR_COLORS[h % AVATAR_COLORS.length]}">${esc((name || "?").trim()[0])}</div>`;
}
function scoreClass(m) { return m >= 75 ? "" : m >= 50 ? "mid" : "low"; }

function card(j, mySkills) {
  const p = progress[j.id] || {};
  // Skip the badge when everything is new (first run): a badge on every card means nothing.
  const s = state.data.stats;
  const isNew = daysAgo(j.first_seen) <= 7 && s.new_today < s.total;
  const opts = STATUSES.map((s) => `<option ${s === (p.status || "") ? "selected" : ""} value="${s}">${s || "标记状态"}</option>`).join("");
  const cities = j.cities.slice(0, 3).join(" / ") + (j.cities.length > 3 ? ` 等 ${j.cities.length} 城` : "");
  // Skills I have first, so the overlap is visible at a glance.
  const skills = [...j.skills].sort((a, b) => mySkills.has(b) - mySkills.has(a)).slice(0, 8);
  // Skills, city and direction are already shown above; keep only the extra signals.
  const reasons = (j.reasons || []).filter((r) => !/^(技能|城市|方向)/.test(r));
  return `<article class="job">
    ${avatar(j.company)}
    <div>
      <div class="title-row">
        <h3 class="title"><a href="${esc(j.url)}" target="_blank" rel="noopener">${esc(j.title)}</a></h3>
        ${isNew ? '<span class="badge badge-new">新</span>' : ""}
        ${p.status ? `<span class="badge badge-status">${esc(p.status)}</span>` : ""}
      </div>
      <div class="facts"><span>${esc(cities || "地点未注明")}</span><span>${esc(j.direction)}</span><span>${esc(j.recruit)}</span></div>
      <div class="company-line"><b>${esc(j.company)}</b> · ${esc(j.ent)}</div>
      <div class="tags">${skills.map((s) => `<span class="tag ${mySkills.has(s) ? "hit" : ""}">${esc(s)}</span>`).join("")}</div>
      ${reasons.length ? `<div class="reasons">${reasons.map((r) => `<span class="${r.startsWith("⚠") ? "warn" : ""}">${esc(r)}</span>`).join("")}</div>` : ""}
    </div>
    <div class="side">
      <div class="score ${scoreClass(j.match)}">${Math.round(j.match)}<small>匹配</small></div>
      <div class="actions">
        <select class="status-select ${p.status ? "set" : ""}" data-id="${esc(j.id)}" aria-label="投递状态">${opts}</select>
        <a class="btn btn-primary" href="${esc(j.url)}" target="_blank" rel="noopener">去投递</a>
      </div>
      <span class="date">${p.date ? esc(p.status + " · " + p.date) : "发现于 " + esc(j.first_seen || "-")}</span>
    </div>
  </article>`;
}

// ---------- company directory ----------
// Every company from the list, scraped or not. For sites we can't scrape
// (custom systems, Moka, WeChat-only), the 投递说明 and the entry link are
// often the fastest way in, so they're shown in full.
function coverage(c) {
  if (SCRAPED.has(c.status)) return "scraped";
  return c.status === "no_url" ? "note" : "link";
}
function filteredCompanies() {
  const q = state.q.trim().toLowerCase();
  const list = (state.data.companies || []).filter((c) => {
    if (state.cat && c.cat !== state.cat) return false;
    if (state.cstatus && coverage(c) !== state.cstatus) return false;
    if (state.ents.size && !state.ents.has(c.ent)) return false;
    const m = marks[c.company]?.mark || "";
    if (state.cmark === "__none" ? m : state.cmark && m !== state.cmark) return false;
    if (q) {
      const hay = [c.company, c.cat, c.roles, c.note, c.portal_raw].join(" ").toLowerCase();
      if (!q.split(/\s+/).every((w) => hay.includes(w))) return false;
    }
    return true;
  });
  const by = {
    opened: (a, b) => (b.opened || "").localeCompare(a.opened || "") || a.company.localeCompare(b.company, "zh"),
    jobs: (a, b) => (b.jobs_campus + b.jobs_intern) - (a.jobs_campus + a.jobs_intern),
    name: (a, b) => a.company.localeCompare(b.company, "zh"),
  };
  return list.sort(by[state.csort]);
}
function companyCard(c) {
  const m = marks[c.company] || {};
  const cov = coverage(c);
  const opts = CMARKS.map((s) => `<option ${s === (m.mark || "") ? "selected" : ""} value="${s}">${s || "标记"}</option>`).join("");
  const n = c.jobs_campus + c.jobs_intern;
  const statusText = cov !== "scraped" ? c.status_label
    : n ? `已抓取 · 校招 ${c.jobs_campus} / 实习 ${c.jobs_intern}`
    : "已接入 · 目前没有在招的校招/实习岗位";
  const entry = c.portal
    ? `<a class="btn btn-primary" href="${esc(c.portal)}" target="_blank" rel="noopener">官网投递</a>`
    : "";
  const rawExtra = c.portal_raw && c.portal_raw !== c.portal ? `<div class="linkish muted">入口备注：${esc(c.portal_raw.replace(c.portal, "").trim())}</div>` : "";
  return `<article class="company">
    ${avatar(c.company)}
    <div>
      <div class="title-row">
        <h3 class="name">${esc(c.company)}</h3>
        <span class="status ${cov === "scraped" ? "scraped" : cov === "note" ? "note-only" : ""}">${esc(statusText)}</span>
        ${m.mark ? `<span class="badge badge-status">${esc(m.mark)}</span>` : ""}
      </div>
      <div class="facts"><span>${esc(c.cat || "未分类")}</span><span>${esc(c.ent)}</span>${c.opened ? `<span>${esc(c.opened)} 开启</span>` : ""}</div>
      ${c.roles ? `<div class="roles">招聘方向：${esc(c.roles)}</div>` : ""}
      ${c.note ? `<div class="note">${esc(c.note)}</div>` : ""}
      ${rawExtra}
    </div>
    <div class="side">
      <div class="actions">
        <select class="status-select ${m.mark ? "set" : ""}" data-company-mark="${esc(c.company)}" aria-label="公司标记">${opts}</select>
        ${entry}
      </div>
      ${n ? `<button class="btn see-jobs" data-company="${esc(c.company)}" data-src="${esc(c.src || "")}" data-tab="${c.jobs_campus ? "校招" : "实习"}">查看 ${n} 个岗位</button>` : ""}
      <span class="date">${m.date ? esc(m.mark + " · " + m.date) : ""}</span>
    </div>
  </article>`;
}
function renderCompanies() {
  const list = filteredCompanies();
  const all = state.data.companies || [];
  const scraped = all.filter((c) => coverage(c) === "scraped").length;
  $("#status-bar").innerHTML = `<span>共 <b>${list.length}</b> 家公司</span><span>· 名单 ${all.length} 家，其中 ${scraped} 家可直接看到岗位，其余提供官网入口与投递说明</span>`;
  $("#list").innerHTML = list.length
    ? list.slice(0, state.shown).map(companyCard).join("")
    : '<div class="empty">没有符合条件的公司</div>';
  $("#more-wrap").style.display = list.length > state.shown ? "" : "none";
}

function render() {
  document.body.classList.toggle("view-companies", state.tab === "companies");
  $("#company-count").textContent = (state.data.companies || []).length || "";
  if (state.tab === "companies") return renderCompanies();
  const { list, mySkills } = filtered();
  const sortNote = state.tab !== "mine" && state.sort === "rec" ? "· 按匹配度推荐，同一公司的岗位会适当分散" : "";
  $("#status-bar").innerHTML = `<span>共 <b>${list.length.toLocaleString()}</b> 个岗位</span><span>${sortNote}</span>`
    + (state.only ? `<span>· 只看 ${esc(state.only.label)} <a href="#" id="clear-only">清除</a></span>` : "");
  $("#list").innerHTML = list.length
    ? list.slice(0, state.shown).map((j) => card(j, mySkills)).join("")
    : '<div class="empty">没有符合条件的岗位</div>';
  $("#more-wrap").style.display = list.length > state.shown ? "" : "none";
  $("#mine-count").textContent = Object.values(progress).filter((p) => p.status).length || "";
}

function fillFilters() {
  const jobs = state.data.jobs;
  for (const [d, n] of countBy(jobs, (j) => j.direction)) $("#direction").insertAdjacentHTML("beforeend", `<option value="${esc(d)}">${esc(d)} (${n})</option>`);
  for (const [c, n] of countBy(jobs, (j) => j.cities).slice(0, 80)) $("#city").insertAdjacentHTML("beforeend", `<option value="${esc(c)}">${esc(c)} (${n})</option>`);
  const companies = state.data.companies || [];
  const ents = new Set([...jobs.map((j) => j.ent), ...companies.map((c) => c.ent)]);
  const entCount = new Map(countBy(jobs, (j) => j.ent));
  for (const e of [...ents].sort((a, b) => (entCount.get(b) || 0) - (entCount.get(a) || 0)))
    $("#ent").insertAdjacentHTML("beforeend", `<button class="chip" data-ent="${esc(e)}">${esc(e)}</button>`);
  for (const [c, n] of countBy(companies, (c) => c.cat || "未分类")) $("#cat").insertAdjacentHTML("beforeend", `<option value="${esc(c === "未分类" ? "" : c)}">${esc(c)} (${n})</option>`);
  for (const m of CMARKS.filter(Boolean)) $("#cmark-filter").insertAdjacentHTML("beforeend", `<option value="${esc(m)}">${esc(m)}</option>`);
  const s = state.data.stats;
  // On the very first run every job is "new today", which says nothing.
  const fresh = s.new_today && s.new_today < s.total ? ` · 今日新增 ${s.new_today.toLocaleString()}` : "";
  $("#meta").textContent = `${s.total.toLocaleString()} 个岗位${fresh} · 更新于 ${state.data.generated_at}`
    + (s.failed_sources?.length ? ` · ${s.failed_sources.length} 个来源今日未更新` : "");
}

// ---------- resume upload: parse + re-score, all inside this browser ----------
// Mirrors matching/rank.py so the browser and Python give the same scores:
// same skill dictionary (shipped in data.json), same BM25, same weights, same MMR.
// Difference: data.json has no JD full text, so BM25 here runs on title + skills only.
const PROFILE_KEY = "campus-nav-profile-v1";
let skillMatchers = [];

function skillPattern(term) {
  const e = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const left = /^[a-z0-9]/.test(term) ? "(?<![a-z0-9])" : "";
  const right = /[a-z0-9]$/.test(term) ? "(?![a-z0-9+#])" : "";
  return left + e + right;
}
function extractSkills(text) {
  const low = (text || "").toLowerCase();
  return skillMatchers.filter(([, re]) => re.test(low)).map(([name]) => name);
}
async function pdfToText(file) {
  if (!window.pdfjsLib) throw new Error("PDF 解析库没加载成功（需要联网），可以先把简历文字粘贴进来");
  pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
  const pdf = await pdfjsLib.getDocument({ data: await file.arrayBuffer() }).promise;
  let out = "";
  for (let i = 1; i <= pdf.numPages; i++) {
    const content = await (await pdf.getPage(i)).getTextContent();
    out += content.items.map((x) => x.str).join(" ") + "\n";
  }
  return out;
}

function tokenize(text) {
  text = (text || "").toLowerCase();
  const tokens = text.match(/[a-z][a-z0-9+#.]*/g) || [];
  for (const run of text.match(/[一-鿿]+/g) || []) {
    if (run.length === 1) tokens.push(run);
    for (let i = 0; i < run.length - 1; i++) tokens.push(run.slice(i, i + 2));
  }
  return tokens;
}
function bm25Scores(docs, query, k1 = 1.5, b = 0.75) {
  const N = docs.length, df = new Map(), tfs = [];
  let total = 0;
  for (const d of docs) {
    const tf = new Map();
    for (const t of d) tf.set(t, (tf.get(t) || 0) + 1);
    tfs.push(tf); total += d.length;
    for (const t of tf.keys()) df.set(t, (df.get(t) || 0) + 1);
  }
  const avgdl = total / N || 1, q = [...new Set(query)];
  return tfs.map((tf, i) => {
    const norm = k1 * (1 - b + b * docs[i].length / avgdl);
    let s = 0;
    for (const t of q) {
      const f = tf.get(t); if (!f) continue;
      const n = df.get(t);
      s += Math.log((N - n + 0.5) / (n + 0.5) + 1) * f * (k1 + 1) / (f + norm);
    }
    return s;
  });
}
function rescore(skills) {
  const jobs = state.data.jobs, prefs = state.data.prefs || {};
  // The embedding channel needs the model, which only runs in Python, so a
  // browser re-score uses the no-embedding weight set, rescaled to sum to 1.
  const w = { ...(prefs.weights_no_emb || prefs.weights || { bm25: 0.35, skill: 0.35, direction: 0.2, city: 0.1 }) };
  delete w.emb;
  // Positive weights only: `avoid` is a penalty (see matching/rank.py).
  const total = Object.values(w).reduce((a, b) => a + Math.max(b, 0), 0) || 1;
  for (const k in w) w[k] /= total;
  const want = new Set(skills), dirs = new Set(prefs.directions || []), cities = new Set(prefs.cities || []);
  const raw = bm25Scores(jobs.map((j) => tokenize(j.title + " " + j.skills.join(" "))), tokenize(skills.join(" ")));
  const top = Math.max(...raw, 0);
  jobs.forEach((j, i) => {
    const hit = j.skills.filter((s) => want.has(s)).sort();
    const f = {
      bm25: top ? raw[i] / top : 0,
      skill: j.skills.length ? hit.length / (j.skills.length + 1) : 0,
      direction: dirs.has(j.direction) ? 1 : 0,
      city: !cities.size || j.cities.some((c) => cities.has(c)) ? 1 : 0,
      avoid: j.avoid || 0, // computed in Python from the JD text, which the page doesn't have
    };
    const s = Object.keys(f).reduce((a, k) => a + (w[k] || 0) * f[k], 0);
    j.match = Math.round(1000 * Math.max(0, s)) / 10;
    const warn = (j.reasons || []).find((r) => r.startsWith("⚠"));
    const cHit = j.cities.filter((c) => cities.has(c));
    j.reasons = [hit.length && "技能: " + hit.slice(0, 6).join(", "), f.direction && "方向: " + j.direction, cHit.length && "城市: " + cHit.slice(0, 3).join("/"), warn].filter(Boolean);
  });
  mmr(jobs, prefs.rec_top_n || 200);
}
function mmr(jobs, topN, pool = 600, lam = 0.7) {
  const jac = (a, b) => { const A = new Set(a), B = new Set(b); let n = 0; for (const x of A) if (B.has(x)) n++; const u = A.size + B.size - n; return u ? n / u : 0; };
  jobs.forEach((j) => (j.rec = null));
  const c = [...jobs].sort((a, b) => b.match - a.match).slice(0, pool);
  const sim = new Array(c.length).fill(0), alive = new Set(c.keys());
  for (let r = 1; r <= topN && alive.size; r++) {
    let best = -1, bestV = -Infinity;
    for (const i of alive) { const v = lam * c[i].match / 100 - (1 - lam) * sim[i]; if (v > bestV) { bestV = v; best = i; } }
    alive.delete(best); c[best].rec = r;
    for (const i of alive) {
      const s = 0.7 * (c[i].company === c[best].company) + 0.3 * jac(c[i].skills, c[best].skills);
      if (s > sim[i]) sim[i] = s;
    }
  }
}
function loadLocalProfile() {
  try { return JSON.parse(localStorage.getItem(PROFILE_KEY) || "null"); } catch { return null; }
}
function showResumeState(local) {
  $("#resume-state").textContent = local
    ? `按你的简历打分 · ${state.skills.length} 个技能 · ${local.date}`
    : `当前按示例简历排序 · 上传你的简历重新打分`;
  $("#resume-skills").value = state.skills.join(", ");
}
function initResume() {
  skillMatchers = Object.entries(state.data.skill_dict || {}).map(([name, terms]) => [name, new RegExp(terms.map(skillPattern).join("|"))]);
  const local = loadLocalProfile();
  state.skills = local ? local.skills : state.data.profile_skills;
  if (local) rescore(state.skills);
  showResumeState(local);
}
function bindResume() {
  $("#resume-file").addEventListener("change", async (e) => {
    const f = e.target.files[0]; if (!f) return;
    $("#resume-file-name").textContent = "正在读取 " + f.name + " …";
    try {
      const text = await pdfToText(f);
      $("#resume-text").value = text.trim();
      $("#resume-file-name").textContent = f.name + (text.trim() ? "" : "（没读出文字，可能是扫描版，请粘贴文字）");
      if (text.trim()) $("#resume-skills").value = extractSkills(text).join(", ");
    } catch (err) { $("#resume-file-name").textContent = "读取失败：" + err.message; }
  });
  $("#resume-extract").addEventListener("click", () => {
    const skills = extractSkills($("#resume-text").value);
    $("#resume-skills").value = skills.join(", ");
    if (!skills.length) alert("没识别出技能，可以直接在技能框里手动填写");
  });
  $("#resume-apply").addEventListener("click", () => {
    const skills = [...new Set($("#resume-skills").value.split(/[,，、\n]/).map((s) => s.trim()).filter(Boolean))];
    if (!skills.length) return alert("技能是空的，先上传简历或手动填写");
    state.skills = skills;
    const local = { skills, date: state.data.today };
    try { localStorage.setItem(PROFILE_KEY, JSON.stringify(local)); } catch {}
    rescore(skills); showResumeState(local); state.shown = PAGE; render();
  });
  $("#resume-clear").addEventListener("click", () => {
    try { localStorage.removeItem(PROFILE_KEY); } catch {}
    location.reload();  // simplest way back to the scores Python computed
  });
}

// ---------- events ----------
function bind() {
  bindResume();
  const rerender = () => { state.shown = PAGE; render(); };
  $("#tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
    state.tab = b.dataset.tab; rerender();
  });
  $("#q").addEventListener("input", (e) => { state.q = e.target.value; state.only = null; rerender(); });
  $("#status-bar").addEventListener("click", (e) => {
    if (e.target.id !== "clear-only") return;
    e.preventDefault(); state.only = null; rerender();
  });
  $("#direction").addEventListener("change", (e) => { state.direction = e.target.value; rerender(); });
  $("#city").addEventListener("change", (e) => { state.city = e.target.value; rerender(); });
  $("#sort").addEventListener("change", (e) => { state.sort = e.target.value; rerender(); });
  $("#only-new").addEventListener("change", (e) => { state.onlyNew = e.target.checked; rerender(); });
  $("#hide-applied").addEventListener("change", (e) => { state.hideApplied = e.target.checked; rerender(); });
  $("#ent").addEventListener("click", (e) => {
    const b = e.target.closest(".chip"); if (!b) return;
    const v = b.dataset.ent;
    state.ents.has(v) ? state.ents.delete(v) : state.ents.add(v);
    b.classList.toggle("on"); rerender();
  });
  $("#cat").addEventListener("change", (e) => { state.cat = e.target.value; rerender(); });
  $("#cstatus").addEventListener("change", (e) => { state.cstatus = e.target.value; rerender(); });
  $("#cmark-filter").addEventListener("change", (e) => { state.cmark = e.target.value; rerender(); });
  $("#csort").addEventListener("change", (e) => { state.csort = e.target.value; rerender(); });
  $("#list").addEventListener("click", (e) => {
    const b = e.target.closest(".see-jobs"); if (!b) return;
    // Jump to the job list filtered to this company: by its source when the
    // company name in the list differs from the job data (中国平安 -> 平安科技...),
    // otherwise by name.
    const byName = state.data.jobs.some((j) => j.company === b.dataset.company);
    if (b.dataset.src && !byName) {
      state.only = { src: b.dataset.src, label: b.dataset.company }; state.q = "";
    } else {
      state.only = null; state.q = b.dataset.company;
    }
    $("#q").value = state.q;
    state.tab = b.dataset.tab;
    document.querySelectorAll("#tabs button").forEach((x) => x.classList.toggle("active", x.dataset.tab === state.tab));
    rerender(); window.scrollTo(0, 0);
  });
  $("#more").addEventListener("click", () => { state.shown += PAGE; render(); });
  $("#list").addEventListener("change", (e) => {
    const cm = e.target.closest("select[data-company-mark]");
    if (cm) {
      const name = cm.dataset.companyMark;
      if (cm.value) marks[name] = { mark: cm.value, date: new Date().toISOString().slice(0, 10) };
      else delete marks[name];
      saveMarks(marks); render(); return;
    }
    const sel = e.target.closest("select[data-id]"); if (!sel) return;
    const id = sel.dataset.id;
    if (sel.value) progress[id] = { status: sel.value, date: new Date().toISOString().slice(0, 10) };
    else delete progress[id];
    saveProgress(progress); render();
  });
  $("#export").addEventListener("click", () => {
    const blob = new Blob([JSON.stringify({ version: 2, jobs: progress, companies: marks }, null, 2)], { type: "application/json" });
    const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `progress-${state.data.today}.json` });
    a.click(); URL.revokeObjectURL(a.href);
  });
  $("#import").addEventListener("change", async (e) => {
    const f = e.target.files[0]; if (!f) return;
    try {
      const obj = JSON.parse(await f.text());
      if (obj.version === 2) {  // new format: job progress + company marks
        progress = { ...progress, ...obj.jobs }; marks = { ...marks, ...obj.companies }; saveMarks(marks);
      } else {
        progress = { ...progress, ...obj };  // old export: job progress only
      }
      saveProgress(progress); render();
    }
    catch (err) { alert("导入失败：" + err.message); }
  });
}

fetch("data.json")
  .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
  .then((d) => { state.data = d; initResume(); fillFilters(); bind(); render(); })
  .catch((e) => {
    $("#meta").textContent = "";
    $("#list").innerHTML = `<div class="empty">读不到 data.json（${esc(e.message)}）。<br>先运行 <code>python run.py</code>，再用 <code>python -m http.server -d web 8000</code> 打开，不能直接双击 index.html。</div>`;
  });
