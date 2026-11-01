// public/js/admin.js — panneau d'administration d'une instance d'IAST-Builder.
//
// Onglets :
//   Questions des usagers      phase 1 : questions d'investigation, décision des experts
//   Connaissances proposées    phases 2 et 3 : assertions candidates et leur verdict formel
//   Ontologie                  phase 3 : évolutions en langage naturel, versions, import initial
//   Connecteurs                phase 3 : import CSV/JSON par correspondance déclarative
//   Contributions, Documents   circuit de validation existant (+ extraction guidée des documents)
//   Journal                    journal épistémique en ajout seul
//
// Toutes les décisions sont signées du nom saisi dans « Vous êtes », inscrit au journal.

let token = sessionStorage.getItem("yobakoko_admin_token") || null;
const formalized = {};        // propositions d'assertions par question (réponse d'expert traduite)
let pendingChange = null;     // évolution traduite, en attente de soumission
let batchFilter = null;       // filtre des assertions par lot d'import

// ---------------------------------------------------------------------------
// Outils
// ---------------------------------------------------------------------------
function authHeaders() {
  return { Authorization: "Bearer " + token };
}

async function api(method, path, body) {
  const init = { method, headers: { ...authHeaders() } };
  if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const res = await fetch(path, init);
  if (res.status === 401) {
    doLogout();
    throw new Error("Session expirée");
  }
  let data = null;
  try { data = await res.json(); } catch (e) { data = null; }
  return { ok: res.ok, status: res.status, data };
}

const apiGet = async (path) => (await api("GET", path)).data;

function errorText(r) {
  if (!r.data) return "Erreur " + r.status;
  return r.data.detail || r.data.error || JSON.stringify(r.data);
}

function expert() {
  const name = document.getElementById("expertName").value.trim();
  if (!name) {
    alert("Indiquez votre nom dans le champ « Vous êtes » : chaque décision est signée et inscrite au journal.");
    throw new Error("Nom de l'expert manquant");
  }
  sessionStorage.setItem("yobakoko_expert", name);
  return name;
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

const LABELS = {
  pending: "en attente", approved: "approuvé", rejected: "rejeté", validated: "validé", deliberation: "en délibération",
  retired: "retiré", open: "à traiter", complement: "complément demandé", proposed: "proposée", applied: "appliquée",
  reverted: "annulée", running: "en cours", done: "terminé", failed: "échec", annule: "annulé",
  lacune: "lacune", contradiction: "contradiction", nouveaute: "fait nouveau", ambiguite: "ambiguïté",
  conforme: "conforme", en_tension: "en conflit", hors_ontologie: "hors ontologie",
};

function statusPill(status) {
  return `<span class="status-pill status-${status}">${LABELS[status] || status}</span>`;
}

function badge(kind) {
  return `<span class="badge ${kind}">${LABELS[kind] || kind}</span>`;
}

function fmtDate(iso) {
  return iso ? new Date(iso).toLocaleString("fr-FR") : "";
}

async function downloadFile(path, filename) {
  const res = await fetch(path, { headers: authHeaders() });
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

// ---------------------------------------------------------------------------
// Connexion et navigation
// ---------------------------------------------------------------------------
async function doLogin() {
  const password = document.getElementById("loginPassword").value;
  const errEl = document.getElementById("loginError");
  errEl.textContent = "";
  try {
    const res = await fetch("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    const data = await res.json();
    if (!res.ok) {
      errEl.textContent = data.error || "Erreur de connexion.";
      return;
    }
    token = data.token;
    sessionStorage.setItem("yobakoko_admin_token", token);
    showDashboard();
  } catch (err) {
    errEl.textContent = "Impossible de contacter le serveur.";
  }
}

async function doLogout() {
  try {
    await fetch("/api/admin/logout", { method: "POST", headers: authHeaders() });
  } catch (err) {}
  token = null;
  sessionStorage.removeItem("yobakoko_admin_token");
  document.getElementById("dashboardView").style.display = "none";
  document.getElementById("loginView").style.display = "block";
}

const LOADERS = {
  questions: () => loadQuestions(),
  assertions: () => loadAssertions(),
  ontology: () => { loadOntology(); loadChanges(); loadVersions(); },
  connectors: () => { loadPresets(); loadBatches(); },
  contributions: () => loadContributions(),
  documents: () => loadDocuments(),
  journal: () => loadJournal(),
};

function openTab(name) {
  document.querySelectorAll(".admin-tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".admin-panel").forEach((p) => p.classList.toggle("active", p.id === "panel-" + name));
  LOADERS[name]();
  loadStats();
}

document.querySelectorAll(".admin-tab").forEach((tab) => tab.addEventListener("click", () => openTab(tab.dataset.tab)));

function showDashboard() {
  document.getElementById("loginView").style.display = "none";
  document.getElementById("dashboardView").style.display = "block";
  document.getElementById("expertName").value = sessionStorage.getItem("yobakoko_expert") || "";
  openTab("questions");
}

async function loadStats() {
  const s = await apiGet("/api/admin/stats");
  if (!s) return;
  const q = s.questions || {};
  const a = s.assertions || {};
  const open = (q.open || 0) + (q.complement || 0) + (q.deliberation || 0);
  document.getElementById("statsBar").innerHTML =
    `<span>Questions à traiter : <b>${open}</b></span>` +
    `<span>Connaissances en attente : <b>${(a.pending || 0) + (a.deliberation || 0)}</b></span>` +
    `<span>Connaissances validées : <b>${a.validated || 0}</b></span>` +
    `<span>Passages indexés : <b>${s.vectorCount}</b></span>` +
    `<span>Version de l'ontologie : <b>${s.ontologyVersion ?? "?"}</b></span>`;
}

// ---------------------------------------------------------------------------
// Phase 1 : questions d'investigation
// ---------------------------------------------------------------------------
async function loadQuestions() {
  const status = document.getElementById("qStatus").value;
  const list = await apiGet("/api/admin/questions?status=" + status);
  const el = document.getElementById("questionsList");
  if (!list || list.length === 0) {
    el.innerHTML = '<div class="empty-state">Aucune question pour le moment.</div>';
    return;
  }
  el.innerHTML = list.map((q) => `
    <div class="admin-card" id="q-${q.id}">
      <div class="meta">${badge(q.signal_type)} n° ${q.id} · priorité ${q.priority.toFixed(1)} · ${q.occurrences} occurrence(s),
        ${q.distinct_clients} usager(s) distinct(s) · ${fmtDate(q.updated_at)} · ${statusPill(q.status)}</div>
      <div class="body-text"><b>${escapeHtml(q.question)}</b></div>
      ${q.hypothesis ? `<div class="meta">Hypothèse de l'agent : ${escapeHtml(q.hypothesis)}</div>` : ""}
      <div class="actions"><button class="btn-admin ghost" onclick="toggleDossier(${q.id})">Ouvrir le dossier</button></div>
      <div class="dossier" id="dossier-${q.id}" style="display:none;"></div>
    </div>`).join("");
}

async function toggleDossier(qid) {
  const el = document.getElementById("dossier-" + qid);
  if (el.style.display === "block") {
    el.style.display = "none";
    return;
  }
  el.style.display = "block";
  await renderDossier(qid);
}

async function renderDossier(qid) {
  const q = await apiGet("/api/admin/questions/" + qid);
  const el = document.getElementById("dossier-" + qid);
  const decided = ["validated", "rejected"].includes(q.status);
  el.innerHTML = `
    <h4>Ce que l'agent savait</h4><div class="meta">${escapeHtml(q.agent_knowledge || "—")}</div>
    <h4>Extraits anonymisés des échanges</h4>
    ${q.occurrences_list.map((o) => `<div class="excerpt">« ${escapeHtml(o.excerpt)} » — ${fmtDate(o.created_at)}</div>`).join("")}
    ${q.opinions.length ? `<h4>Avis des experts</h4>` + q.opinions.map((o) =>
      `<div class="meta">${escapeHtml(o.expert)} : <b>${escapeHtml(o.position)}</b> — ${escapeHtml(o.argument || "")}</div>`).join("") : ""}
    ${q.assertions.length ? `<h4>Connaissances retenues</h4>` + q.assertions.map((a) =>
      `<div class="paraphrase">${escapeHtml(a.paraphrase)} ${statusPill(a.status)}</div>`).join("") : ""}
    ${q.decision ? `<div class="meta">Décision : ${escapeHtml(LABELS[q.decision.outcome] || q.decision.outcome)} par ${escapeHtml(q.decision.expert)}
      ${q.decision.notes ? "— " + escapeHtml(q.decision.notes) : ""}</div>` : ""}
    ${decided ? "" : `
      <h4>Votre réponse, en français courant</h4>
      <textarea class="wide-text" id="answer-${qid}" placeholder="Ex. : votre réponse, en français courant, avec le contexte où elle vaut."></textarea>
      <div class="actions">
        <button class="btn-admin" onclick="formalizeAnswer(${qid})">Traduire ma réponse</button>
        <button class="btn-admin danger" onclick="decideQuestion(${qid}, 'rejected')">Rejeter</button>
        <button class="btn-admin ghost" onclick="decideQuestion(${qid}, 'complement')">Demander un complément</button>
        <button class="btn-admin ghost" onclick="decideQuestion(${qid}, 'deliberation')">Ouvrir une délibération</button>
        <span class="ontology-status" id="qstatus-${qid}"></span>
      </div>
      <div id="proposals-${qid}"></div>
      <h4>Déposer un avis (délibération)</h4>
      <div class="actions">
        <select id="pos-${qid}"><option value="pour">pour</option><option value="contre">contre</option><option value="reserve">réserve</option></select>
        <input type="text" id="arg-${qid}" placeholder="Argument">
        <button class="btn-admin ghost" onclick="addOpinion(${qid})">Déposer</button>
      </div>`}
  `;
}

async function formalizeAnswer(qid) {
  const answer = document.getElementById("answer-" + qid).value.trim();
  const st = document.getElementById("qstatus-" + qid);
  if (!answer) { st.textContent = "Rédigez d'abord votre réponse."; return; }
  st.textContent = "Traduction en cours…";
  const r = await api("POST", `/api/admin/questions/${qid}/formalize`, { answer });
  if (!r.ok) { st.textContent = errorText(r); return; }
  st.textContent = "";
  formalized[qid] = r.data.propositions;
  const el = document.getElementById("proposals-" + qid);
  if (!r.data.propositions.length) {
    el.innerHTML = `<div class="problems">Aucune connaissance n'a pu être tirée de la réponse.</div>`;
    return;
  }
  el.innerHTML = `<h4>Voici ce qui sera retenu (cochez ce que vous validez)</h4>` +
    r.data.propositions.map((p, i) => `
      <div class="proposal"><input type="checkbox" id="prop-${qid}-${i}" checked>
        <div><div class="paraphrase">${escapeHtml(p.paraphrase)}</div>${badge(p.verdict)}
        ${p.questions_domaine.map((d) => `<div class="domain-q">${escapeHtml(d)}</div>`).join("")}</div></div>`).join("") +
    (r.data.hors_ontologie && r.data.hors_ontologie.length ? `<div class="problems">Notions absentes de l'ontologie : ` +
      r.data.hors_ontologie.map((t) => escapeHtml(t.term)).join(", ") + ` (proposez une évolution depuis l'onglet Ontologie).</div>` : "") +
    (r.data.commentaire ? `<div class="meta">${escapeHtml(r.data.commentaire)}</div>` : "") +
    `<div class="actions"><button class="btn-admin" onclick="validateSelection(${qid}, false)">Valider la sélection</button></div>
     <div id="tension-${qid}"></div>`;
}

async function validateSelection(qid, confirmTension) {
  const selected = (formalized[qid] || []).filter((_, i) => document.getElementById(`prop-${qid}-${i}`)?.checked).map((p) => p.assertion);
  if (!selected.length) { alert("Aucune connaissance sélectionnée."); return; }
  const notes = document.getElementById("answer-" + qid).value.trim();
  const r = await api("POST", `/api/admin/questions/${qid}/decide`,
    { outcome: "validated", expert: expert(), notes, assertions: selected, confirmTension });
  if (r.status === 409) {
    document.getElementById("tension-" + qid).innerHTML = `<h4>Avant de valider</h4>` +
      r.data.tensions.map((t) => `<div class="paraphrase">${escapeHtml(t.paraphrase)}</div>` +
        (t.details.questions_domaine || []).map((d) => `<div class="domain-q">${escapeHtml(d)}</div>`).join("")).join("") +
      `<div class="actions"><button class="btn-admin" onclick="validateSelection(${qid}, true)">Confirmer en connaissance de cause</button></div>`;
    return;
  }
  if (!r.ok) { alert(errorText(r)); return; }
  loadQuestions();
  loadStats();
}

async function decideQuestion(qid, outcome) {
  const notes = document.getElementById("answer-" + qid)?.value.trim() || null;
  if (outcome === "rejected" && !notes) { alert("Indiquez le motif du rejet dans le champ de réponse."); return; }
  const r = await api("POST", `/api/admin/questions/${qid}/decide`, { outcome, expert: expert(), notes });
  if (!r.ok) { alert(errorText(r)); return; }
  loadQuestions();
  loadStats();
}

async function addOpinion(qid) {
  const r = await api("POST", `/api/admin/questions/${qid}/opinions`, {
    expert: expert(), position: document.getElementById("pos-" + qid).value, argument: document.getElementById("arg-" + qid).value,
  });
  if (!r.ok) { alert(errorText(r)); return; }
  renderDossier(qid);
}

// ---------------------------------------------------------------------------
// Phases 2 et 3 : assertions candidates
// ---------------------------------------------------------------------------
async function loadAssertions() {
  const params = new URLSearchParams({ status: document.getElementById("aStatus").value });
  const verdict = document.getElementById("aVerdict").value;
  const source = document.getElementById("aSource").value;
  if (verdict) params.set("verdict", verdict);
  if (source) params.set("source", source);
  if (batchFilter) params.set("batch", batchFilter);
  const list = await apiGet("/api/admin/assertions?" + params.toString());
  const el = document.getElementById("assertionsList");
  const banner = batchFilter
    ? `<div class="meta">Lot d'import n° ${batchFilter} · <a href="#" onclick="batchFilter=null; loadAssertions(); return false;">voir toutes les sources</a></div>`
    : "";
  if (!list || !list.length) {
    el.innerHTML = banner + '<div class="empty-state">Aucune connaissance dans cette sélection.</div>';
    return;
  }
  el.innerHTML = banner + list.map((a) => {
    const d = a.verdict_details || {};
    const open = ["pending", "deliberation"].includes(a.status);
    const term = d.term
      ? `<div class="domain-q">Notion absente de l'ontologie : « ${escapeHtml(d.term.term)} »${d.term.justification ? " — " + escapeHtml(d.term.justification) : ""}</div>`
      : (d.questions_domaine || []).map((q) => `<div class="domain-q">${escapeHtml(q)}</div>`).join("");
    return `
    <div class="admin-card">
      <div class="meta">${badge(a.verdict)} n° ${a.id} · ${escapeHtml(a.method)} · ${escapeHtml(a.source_ref || a.source_type)}
        ${a.confidence != null ? "· confiance " + a.confidence : ""} · ${statusPill(a.status)}</div>
      <div class="body-text">${a.verdict === "hors_ontologie" ? escapeHtml(a.subject) : escapeHtml(a.paraphrase)}</div>
      ${a.citation ? `<div class="excerpt">Source : « ${escapeHtml(a.citation)} »</div>` : ""}
      ${term}
      ${a.decided_by ? `<div class="meta">Décision : ${escapeHtml(a.decided_by)}${a.decision_notes ? " — " + escapeHtml(a.decision_notes) : ""}</div>` : ""}
      <div class="actions">
        ${open ? `<input type="text" id="anote-${a.id}" placeholder="Note (motif, précision de portée…)">
          ${a.verdict !== "hors_ontologie" ? `<button class="btn-admin" onclick="decideAssertion(${a.id}, 'validated')">Valider</button>` : ""}
          <button class="btn-admin danger" onclick="decideAssertion(${a.id}, 'rejected')">Rejeter</button>
          ${a.status === "pending" ? `<button class="btn-admin ghost" onclick="decideAssertion(${a.id}, 'deliberation')">Délibérer</button>` : ""}` : ""}
        ${a.verdict === "hors_ontologie" && open ? `<button class="btn-admin ghost" onclick="proposeFromAssertion(${a.id})">Proposer une évolution de l'ontologie</button>` : ""}
        ${a.status === "validated" ? `<input type="text" id="anote-${a.id}" placeholder="Motif du retrait">
          <button class="btn-admin danger" onclick="retireAssertion(${a.id})">Retirer</button>` : ""}
      </div>
    </div>`;
  }).join("");
}

async function decideAssertion(id, decision) {
  const notes = document.getElementById("anote-" + id)?.value.trim() || null;
  const r = await api("POST", `/api/admin/assertions/${id}/decide`, { decision, expert: expert(), notes });
  if (!r.ok) { alert(errorText(r)); return; }
  loadAssertions();
  loadStats();
}

async function retireAssertion(id) {
  const notes = document.getElementById("anote-" + id)?.value.trim() || null;
  if (!notes) { alert("Indiquez le motif du retrait."); return; }
  const r = await api("POST", `/api/admin/assertions/${id}/retire`, { expert: expert(), notes });
  if (!r.ok) { alert(errorText(r)); return; }
  loadAssertions();
}

async function proposeFromAssertion(id) {
  const a = await apiGet("/api/admin/assertions/" + id);
  const t = (a.verdict_details && a.verdict_details.term) || { term: a.subject };
  openTab("ontology");
  const box = document.getElementById("changeProposal");
  box.value = `Ajouter à l'ontologie la notion « ${t.term} ».` + (t.justification ? ` ${t.justification}` : "") +
    (a.citation ? ` (Source : « ${a.citation} »)` : "");
  box.dataset.origin = "assertion:" + id;
  box.focus();
}

// ---------------------------------------------------------------------------
// Ontologie : fichier actif, évolutions, versions
// ---------------------------------------------------------------------------
let currentOntologyFormat = "json";

async function loadOntology() {
  const data = await apiGet("/api/admin/ontology");
  if (!data) return;
  currentOntologyFormat = data.format || "json";
  document.getElementById("ontologyText").value = data.content || "";
  document.getElementById("ontologyFormatPill").textContent = currentOntologyFormat === "owl" ? "Format : OWL (Turtle)" : "Format : JSON";
  document.getElementById("ontologyVersionPill").textContent = "Version " + (data.version ?? "?");
  document.getElementById("ontologyStatus").textContent = "";
}

async function saveOntology() {
  const statusEl = document.getElementById("ontologyStatus");
  const content = document.getElementById("ontologyText").value;
  if (currentOntologyFormat === "json") {
    try { JSON.parse(content); } catch (err) { statusEl.textContent = "JSON invalide : " + err.message; return; }
  }
  const r = await api("PUT", "/api/admin/ontology", { format: currentOntologyFormat, content, expert: expert() });
  statusEl.textContent = r.ok ? `Enregistré : version ${r.data.version} (sauvegarde : ${r.data.backup || "aucune"})` : errorText(r);
  if (r.ok) { loadOntology(); loadVersions(); }
}

document.getElementById("ontologyUploadInput").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  const statusEl = document.getElementById("ontologyUploadStatus");
  if (!file) return;
  statusEl.textContent = "Import en cours…";
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch("/api/admin/ontology/upload", { method: "POST", headers: authHeaders(), body: fd });
  const data = await res.json();
  statusEl.textContent = res.ok ? `Importée : format ${data.format}, version ${data.version}` : (data.detail || data.error);
  e.target.value = "";
  if (res.ok) { loadOntology(); loadVersions(); }
});

async function formalizeChange() {
  const proposal = document.getElementById("changeProposal").value.trim();
  const st = document.getElementById("changeStatus");
  if (!proposal) { st.textContent = "Décrivez d'abord l'évolution."; return; }
  st.textContent = "Traduction en cours…";
  const r = await api("POST", "/api/admin/ontology/changes/formalize", { proposal });
  st.textContent = "";
  const el = document.getElementById("changePreview");
  if (!r.ok) { el.innerHTML = `<div class="problems">${escapeHtml(errorText(r))}</div>`; return; }
  if (r.data.problems.length) {
    pendingChange = null;
    el.innerHTML = `<div class="problems">La proposition ne peut pas être appliquée telle quelle :<br>${r.data.problems.map(escapeHtml).join("<br>")}
      <br>Reformulez-la, par exemple en précisant la catégorie existante à laquelle rattacher la nouvelle notion.</div>`;
    return;
  }
  pendingChange = { proposal, operations: r.data.operations, origin: document.getElementById("changeProposal").dataset.origin || "manuel" };
  el.innerHTML = `<h4>Voici exactement ce qui sera appliqué</h4><div class="paraphrase">${escapeHtml(r.data.paraphrase)}</div>
    ${r.data.commentaire ? `<div class="meta">${escapeHtml(r.data.commentaire)}</div>` : ""}
    <div class="actions"><button class="btn-admin" onclick="submitChange()">Soumettre la proposition</button></div>`;
}

async function submitChange() {
  if (!pendingChange) return;
  const r = await api("POST", "/api/admin/ontology/changes", { ...pendingChange, expert: expert() });
  if (!r.ok) { alert(errorText(r)); return; }
  pendingChange = null;
  const box = document.getElementById("changeProposal");
  document.getElementById("changePreview").innerHTML = "";
  box.value = "";
  delete box.dataset.origin;
  loadChanges();
}

async function loadChanges() {
  const list = await apiGet("/api/admin/ontology/changes");
  const el = document.getElementById("changesList");
  if (!list || !list.length) { el.innerHTML = '<div class="empty-state">Aucune évolution proposée.</div>'; return; }
  el.innerHTML = list.map((c) => `
    <div class="admin-card">
      <div class="meta">n° ${c.id} · ${fmtDate(c.created_at)} · origine : ${escapeHtml(c.origin || "manuel")} · ${statusPill(c.status)}
        ${c.applied_version ? "· version " + c.applied_version : ""} ${c.decided_by ? "· " + escapeHtml(c.decided_by) : ""}</div>
      <div class="meta">Proposition : ${escapeHtml(c.proposal_text)}</div>
      <div class="paraphrase">${escapeHtml(c.paraphrase)}</div>
      <div class="actions">
        ${["proposed", "deliberation"].includes(c.status) ? `
          <input type="text" id="cnote-${c.id}" placeholder="Note">
          <button class="btn-admin" onclick="changeAction(${c.id}, 'apply')">Appliquer</button>
          <button class="btn-admin danger" onclick="changeAction(${c.id}, 'reject')">Rejeter</button>
          ${c.status === "proposed" ? `<button class="btn-admin ghost" onclick="changeAction(${c.id}, 'deliberate')">Délibérer</button>` : ""}` : ""}
        ${c.status === "applied" ? `<button class="btn-admin ghost" onclick="changeAction(${c.id}, 'revert')">Annuler cette évolution</button>` : ""}
      </div>
    </div>`).join("");
}

async function changeAction(id, action) {
  if (action === "revert" && !confirm("Annuler cette évolution rétablit la version précédente de l'ontologie. Continuer ?")) return;
  const notes = document.getElementById("cnote-" + id)?.value.trim() || null;
  const r = await api("POST", `/api/admin/ontology/changes/${id}/${action}`, { expert: expert(), notes });
  if (!r.ok) { alert(errorText(r)); return; }
  if (action === "apply" && r.data.reevaluated_assertions) {
    alert(`Évolution appliquée. ${r.data.reevaluated_assertions} connaissance(s) en attente ont changé de verdict.`);
  }
  loadChanges(); loadVersions(); loadOntology(); loadStats();
}

async function loadVersions() {
  const list = await apiGet("/api/admin/ontology/versions");
  const el = document.getElementById("versionsList");
  if (!list || !list.length) { el.innerHTML = '<div class="empty-state">Aucune version.</div>'; return; }
  el.innerHTML = list.map((v, i) => `
    <div class="journal-row"><b>Version ${v.version}</b> · ${fmtDate(v.created_at)} · ${v.format} · ${escapeHtml(v.reason)}
      · <a href="#" onclick="downloadFile('/api/admin/ontology/versions/${v.version}/download', '${v.file}'); return false;">télécharger</a>
      ${i > 0 ? ` · <a href="#" onclick="restoreVersion(${v.version}); return false;">rétablir</a>` : " · version active"}</div>`).join("");
}

async function restoreVersion(version) {
  if (!confirm(`Rétablir le contenu de la version ${version} ? Une nouvelle version sera créée ; rien n'est effacé.`)) return;
  const r = await api("POST", `/api/admin/ontology/versions/${version}/restore`, { expert: expert() });
  if (!r.ok) { alert(errorText(r)); return; }
  loadVersions(); loadOntology(); loadChanges();
}

function downloadEnrichments() {
  downloadFile("/api/admin/enrichments.ttl", "enrichments.ttl");
}

// ---------------------------------------------------------------------------
// Phase 3 : connecteurs
// ---------------------------------------------------------------------------
async function loadPresets() {
  const list = await apiGet("/api/admin/connectors/presets");
  const sel = document.getElementById("connectorPreset");
  const current = sel.value;
  sel.innerHTML = `<option value="">Correspondance personnalisée (ci-dessous)</option>` +
    (list || []).map((p) => `<option value="${escapeHtml(p.name)}">${escapeHtml(p.name)} — ${escapeHtml(p.description)}</option>`).join("");
  sel.value = current;
}

async function showPreset() {
  const name = document.getElementById("connectorPreset").value;
  document.getElementById("connectorMapping").value = name
    ? JSON.stringify(await apiGet("/api/admin/connectors/presets/" + encodeURIComponent(name)), null, 2) : "";
}

async function importConnector() {
  const file = document.getElementById("connectorFile").files[0];
  const st = document.getElementById("connectorStatus");
  if (!file) { st.textContent = "Choisissez un fichier."; return; }
  const preset = document.getElementById("connectorPreset").value;
  const fd = new FormData();
  fd.append("file", file);
  fd.append("preset", preset);
  fd.append("mapping", preset ? "" : document.getElementById("connectorMapping").value);
  st.textContent = "Envoi…";
  const res = await fetch("/api/admin/connectors/import", { method: "POST", headers: authHeaders(), body: fd });
  const data = await res.json();
  st.textContent = res.ok ? data.message : (data.detail || data.error);
  if (res.ok) pollBatches();
}

function pollBatches(n = 0) {
  loadBatches().then((running) => { if (running && n < 60) setTimeout(() => pollBatches(n + 1), 2000); });
}

async function loadBatches() {
  const list = await apiGet("/api/admin/connectors/batches");
  const el = document.getElementById("batchesList");
  if (!list || !list.length) { el.innerHTML = '<div class="empty-state">Aucun import.</div>'; return false; }
  el.innerHTML = `<div class="actions"><button class="btn-admin ghost" onclick="deduplicate()">Retirer les connaissances en double</button></div>` + list.map((b) => {
    const r = b.report || {};
    const homs = (r.homonymes || []).map((h) =>
      `<div class="domain-q">Même forme pour des entités de natures différentes : ` +
      Object.entries(h.formes || {}).map(([cls, f]) => `« ${escapeHtml(f)} » (${escapeHtml(cls)})`).join(", ") + `</div>`).join("")
      + (r.polysemies || []).map((p) => `<div class="domain-q">Un même nom pour plusieurs entités : « ${escapeHtml(p.forme)} » désigne `
          + p.entites.map((e) => `« ${escapeHtml(e)} »`).join(" et ") + `</div>`).join("");
    return `
    <div class="admin-card">
      <div class="meta">Lot n° ${b.id} · ${escapeHtml(b.filename)} · ${b.connector} · ${fmtDate(b.created_at)} · ${statusPill(b.status)}</div>
      ${b.status === "done" ? `<div class="body-text">${r.records} enregistrement(s), ${r.assertions} connaissance(s) proposée(s),
        ${r.variants} variante(s) graphique(s) signalée(s)${r.extraction ? `, ${r.extraction.created} extraite(s) des champs libres` : ""}.</div>` : ""}
      ${homs}
      ${(r.errors || []).length ? `<div class="problems">${r.errors.map(escapeHtml).join("<br>")}</div>` : ""}
      ${b.status === "done" ? `<div class="actions">
        <button class="btn-admin ghost" onclick="viewBatch(${b.id})">Voir les connaissances du lot</button>
        <button class="btn-admin" onclick="validateBatch(${b.id})">Valider les connaissances conformes du lot</button>
        <button class="btn-admin ghost" onclick="cancelBatch(${b.id})">Annuler ce lot</button></div>` : ""}
    </div>`;
  }).join("");
  return list.some((b) => b.status === "running");
}

function viewBatch(id) {
  batchFilter = id;
  document.getElementById("aStatus").value = "all";
  document.getElementById("aSource").value = "";
  openTab("assertions");
}

async function cancelBatch(id) {
  if (!expert()) { alert("Inscrivez d'abord votre nom dans le champ « Vous êtes »."); return; }
  const motif = prompt("Annuler ce lot ? Ses connaissances en attente seront rejetées et celles déjà validées retirées ; rien n'est effacé du journal.\n\nMotif (par exemple : import en double) :", "Import en double");
  if (motif === null) return;
  const r = await api("POST", `/api/admin/batches/${id}/cancel`, { expert: expert(), motif });
  if (!r.ok) { alert(errorText(r)); return; }
  alert(`Lot n° ${id} annulé : ${r.data.rejetees} connaissance(s) rejetée(s), ${r.data.retirees} retirée(s).`);
  loadBatches(); loadStats();
}

async function deduplicate() {
  if (!expert()) { alert("Inscrivez d'abord votre nom dans le champ « Vous êtes »."); return; }
  if (!confirm("Retirer les connaissances en double (même sujet, relation, objet et portée) ? La plus ancienne est conservée.")) return;
  const r = await api("POST", "/api/admin/assertions/deduplicate", { expert: expert() });
  if (!r.ok) { alert(errorText(r)); return; }
  alert(`${r.data.retirees} doublon(s) retiré(s), ${r.data.rejetees} rejeté(s).`);
  loadBatches(); loadStats();
}

async function validateBatch(id) {
  if (!confirm("Valider toutes les connaissances CONFORMES et en attente de ce lot ? Celles en conflit ou hors ontologie restent à examiner une par une.")) return;
  const r = await api("POST", `/api/admin/batches/${id}/validate-conforming`, { expert: expert() });
  if (!r.ok) { alert(errorText(r)); return; }
  alert(`${r.data.validated} connaissance(s) validée(s).`);
  loadStats();
}

// ---------------------------------------------------------------------------
// Contributions et documents
// ---------------------------------------------------------------------------
// ---- collecte communautaire ----
// Trois modes réglables séparément ; la valeur par défaut vient du profil de domaine.
// Chaque changement est signé par l'expert et inscrit au journal avec son motif.
async function collecteCard() {
  const c = await apiGet("/api/admin/collecte");
  if (!c) return "";
  const rows = Object.keys(c.libelles).map((mode) => {
    const on = c.etat[mode];
    const def = c.defauts[mode] ? "actif" : "inactif";
    return `<div class="collecte-row">
      <label><input type="checkbox" id="coll-${mode}" ${on ? "checked" : ""} onchange="toggleCollecte('${mode}')">
        <strong>${escapeHtml(c.libelles[mode])}</strong></label>
      <span class="meta">${on ? "actif" : "suspendu"} · défaut du profil : ${def}</span></div>`;
  }).join("");
  return `<div class="admin-card collecte-card">
    <div class="meta"><strong>Collecte communautaire</strong></div>
    <p class="panel-intro">Suspendre un mode n'affecte pas la validation : ce qui a déjà été recueilli reste soumis aux experts.
      Quand le recueil des témoignages est suspendu, l'agent ne sollicite plus le savoir des usagers et n'annonce aucune transmission.</p>
    ${rows}
    <div class="actions"><input type="text" id="collMotif" placeholder="Motif du changement (inscrit au journal)"></div>
  </div>`;
}

async function toggleCollecte(mode) {
  const box = document.getElementById(`coll-${mode}`);
  const r = await api("PUT", "/api/admin/collecte", {
    mode, actif: box.checked, expert: expert(), motif: document.getElementById("collMotif")?.value || null,
  });
  if (!r.ok) { alert(errorText(r)); box.checked = !box.checked; }
  loadContributions();
}

async function loadContributions() {
  const list = await apiGet("/api/admin/contributions");
  const panel = document.getElementById("panel-contributions");
  const header = await collecteCard();
  if (!list || !list.length) { panel.innerHTML = header + '<div class="empty-state">Aucune contribution pour le moment.</div>'; return; }
  panel.innerHTML = header + list.slice().reverse().map((c) => `
    <div class="admin-card">
      <div class="meta">#${c.id} · ${escapeHtml(c.type)} · ${fmtDate(c.createdAt)} · ${escapeHtml(c.submittedBy || "anonyme")}
        ${c.questionId ? `· liée à la question n° ${c.questionId}` : ""} · ${statusPill(c.status)}</div>
      <div class="body-text">${escapeHtml(c.content)}</div>
      ${c.reviewedNotes ? `<div class="meta">Note : ${escapeHtml(c.reviewedNotes)}</div>` : ""}
      ${c.status === "pending" ? `<div class="actions">
        <input type="text" placeholder="Note (optionnel)" id="note-c-${c.id}">
        <button class="btn-admin" onclick="reviewContribution(${c.id}, 'approved')">Approuver</button>
        <button class="btn-admin danger" onclick="reviewContribution(${c.id}, 'rejected')">Rejeter</button></div>` : ""}
    </div>`).join("");
}

async function reviewContribution(id, decision) {
  const notes = document.getElementById(`note-c-${id}`)?.value || "";
  const r = await api("POST", `/api/admin/contributions/${id}/review`, { decision, notes, expert: expert() });
  if (!r.ok) alert(errorText(r));
  loadContributions();
}

async function loadDocuments() {
  const list = await apiGet("/api/admin/documents");
  const panel = document.getElementById("panel-documents");
  if (!list || !list.length) { panel.innerHTML = '<div class="empty-state">Aucun document pour le moment.</div>'; return; }
  panel.innerHTML = list.slice().reverse().map((d) => {
    let extraction = "";
    if (d.assertionExtraction) {
      const det = d.assertionExtractionDetail ? JSON.parse(d.assertionExtractionDetail) : {};
      extraction = `<div class="meta">Extraction des connaissances : ${statusPill(d.assertionExtraction)}
        ${d.assertionExtraction === "done" ? `${det.created} connaissance(s), ${det.hors_ontologie} notion(s) hors ontologie, ${det.irrecevables} irrecevable(s)` : ""}
        ${det.error ? escapeHtml(det.error) : ""}</div>`;
    }
    return `
    <div class="admin-card">
      <div class="meta">#${d.id} · ${escapeHtml(d.filename)} · ${(d.sizeBytes / 1024).toFixed(1)} Ko · ${fmtDate(d.createdAt)} ·
        ${escapeHtml(d.submittedBy || "anonyme")} · ${statusPill(d.status)} ${d.chunksIndexed != null ? "· " + d.chunksIndexed + " passage(s) indexé(s)" : ""}</div>
      ${d.note ? `<div class="meta">Note : ${escapeHtml(d.note)}</div>` : ""}
      <div class="body-text">${escapeHtml(d.textPreview) || "(texte non extrait)"}${d.textPreview && d.textPreview.length >= 240 ? "…" : ""}</div>
      ${d.extractionError ? `<div class="problems">Erreur d'extraction du texte : ${escapeHtml(d.extractionError)}</div>` : ""}
      ${extraction}
      <div class="actions">
        ${d.status === "pending" ? `<input type="text" placeholder="Note (optionnel)" id="note-d-${d.id}">
          <button class="btn-admin" onclick="reviewDocument(${d.id}, 'approved')">Approuver</button>
          <button class="btn-admin danger" onclick="reviewDocument(${d.id}, 'rejected')">Rejeter</button>` : ""}
        ${d.status === "approved" && d.assertionExtraction !== "running" ? `<button class="btn-admin ghost" onclick="extractDocument(${d.id})">
          ${d.assertionExtraction ? "Relancer l'extraction des connaissances" : "Extraire les connaissances"}</button>` : ""}
      </div>
    </div>`;
  }).join("");
}

async function reviewDocument(id, decision) {
  const notes = document.getElementById(`note-d-${id}`)?.value || "";
  const r = await api("POST", `/api/admin/documents/${id}/review`, { decision, notes, expert: expert() });
  if (!r.ok) alert(errorText(r));
  loadDocuments();
}

async function extractDocument(id) {
  const r = await api("POST", `/api/admin/documents/${id}/extract`, {});
  if (!r.ok) { alert(errorText(r)); return; }
  const poll = (n) => setTimeout(async () => {
    const docs = await apiGet("/api/admin/documents");
    await loadDocuments();
    if (docs.find((d) => d.id === id)?.assertionExtraction === "running" && n < 90) poll(n + 1);
  }, 2000);
  loadDocuments();
  poll(0);
}

// ---------------------------------------------------------------------------
// Journal
// ---------------------------------------------------------------------------
async function loadJournal() {
  const subject = document.getElementById("jSubject").value;
  const list = await apiGet("/api/admin/journal?limit=300" + (subject ? "&subject_type=" + subject : ""));
  const el = document.getElementById("journalList");
  if (!list || !list.length) { el.innerHTML = '<div class="empty-state">Journal vide.</div>'; return; }
  el.innerHTML = list.map((e) => `
    <div class="journal-row">${fmtDate(e.ts)} · <b>${escapeHtml(e.event_type)}</b> · ${escapeHtml(e.subject_type)}
      ${e.subject_id ? "n° " + escapeHtml(e.subject_id) : ""} · ${escapeHtml(e.actor)} · ontologie v${e.ontology_version ?? "?"}
      <div>${escapeHtml(JSON.stringify(e.payload)).slice(0, 400)}</div></div>`).join("");
}

function downloadJournal() {
  downloadFile("/api/admin/journal.jsonl", "journal_yobakoko.jsonl");
}

if (token) showDashboard();

// Nom de l'instance (YobaKoko, AfriPharm...) dans le titre de l'administration, lu dans le profil actif.
fetch("/api/profile").then((r) => r.ok ? r.json() : null).then((p) => {
  if (!p || !p.agent) return;
  const title = p.agent + " — Administration";
  document.title = title;
  document.querySelectorAll("h1").forEach((h) => { if (h.textContent.includes("Administration")) h.textContent = title; });
}).catch(() => {});
