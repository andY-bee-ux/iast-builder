// public/js/app.js
// Client de conversation d'IAST-Builder — ne parle qu'aux routes /api/* ; la clé Anthropic
// never reaches the browser.

const EMOTIONS = {
  neutre: {
    eyes: '<circle cx="82" cy="119" r="8" fill="#E0BD70" opacity="0.3"/><circle cx="118" cy="119" r="8" fill="#E0BD70" opacity="0.3"/><circle cx="82" cy="119" r="4.5" fill="#E0BD70"/><circle cx="118" cy="119" r="4.5" fill="#E0BD70"/>',
    mouth: '<rect x="84" y="139" width="32" height="3" rx="1.5" fill="#C99A3E" opacity="0.8"/>',
  },
  joyeux: {
    eyes: '<path d="M74 119 Q82 108 90 119" stroke="#E0BD70" stroke-width="4" fill="none" stroke-linecap="round"/><path d="M110 119 Q118 108 126 119" stroke="#E0BD70" stroke-width="4" fill="none" stroke-linecap="round"/>',
    mouth: '<path d="M80 138 Q100 152 120 138" stroke="#E0BD70" stroke-width="4" fill="none" stroke-linecap="round"/>',
  },
  pensif: {
    eyes: '<rect x="75" y="117" width="14" height="4" rx="2" fill="#E0BD70"/><rect x="111" y="117" width="14" height="4" rx="2" fill="#E0BD70"/><path d="M72 108 Q82 103 92 107" stroke="#E0BD70" stroke-width="2" fill="none" opacity="0.6"/>',
    mouth: '<rect x="92" y="140" width="12" height="3" rx="1.5" fill="#C99A3E" opacity="0.7"/>',
  },
  solennel: {
    eyes: '<circle cx="82" cy="119" r="7" fill="#E0BD70" opacity="0.85"/><circle cx="118" cy="119" r="7" fill="#E0BD70" opacity="0.85"/><line x1="72" y1="106" x2="92" y2="106" stroke="#E0BD70" stroke-width="2.5" opacity="0.7"/><line x1="108" y1="106" x2="128" y2="106" stroke="#E0BD70" stroke-width="2.5" opacity="0.7"/>',
    mouth: '<rect x="86" y="140" width="28" height="2.5" rx="1.25" fill="#C99A3E" opacity="0.9"/>',
  },
};

function avatarSVG(emotion) {
  const e = EMOTIONS[emotion] || EMOTIONS.neutre;
  return `<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
    <defs><clipPath id="roundClip"><circle cx="100" cy="100" r="98"/></clipPath></defs>
    <g clip-path="url(#roundClip)">
      <rect x="0" y="0" width="200" height="200" fill="#1F2A44"/>
      <circle cx="100" cy="115" r="72" fill="#8A5A20"/>
      <rect x="62" y="94" width="76" height="54" rx="10" fill="#12201A"/>
      ${e.eyes}
      ${e.mouth}
      <ellipse cx="100" cy="98" rx="58" ry="11" fill="#A6472C"/>
      <path d="M100 26 L58 92 L142 92 Z" fill="#B8874A"/>
      <line x1="76" y1="76" x2="124" y2="76" stroke="#8A5A20" stroke-width="2" opacity="0.6"/>
      <line x1="84" y1="60" x2="116" y2="60" stroke="#8A5A20" stroke-width="2" opacity="0.6"/>
      <path d="M52 172 L72 172 L82 184 L72 196 L52 196 L62 184 Z" fill="#F3ECDA"/>
      <path d="M82 172 L102 172 L112 184 L102 196 L82 196 L92 184 Z" fill="#232C68"/>
      <path d="M112 172 L132 172 L142 184 L132 196 L112 196 L122 184 Z" fill="#F3ECDA"/>
      <path d="M142 172 L162 172 L172 184 L162 196 L142 196 L152 184 Z" fill="#232C68"/>
    </g>
    <circle cx="100" cy="100" r="98" fill="none" stroke="#C99A3E" stroke-width="3"/>
  </svg>`;
}

// Textes de l'interface communs à toutes les instances. Les textes propres à un domaine (sous-titre,
// suggestions, accueil, langues supplémentaires, outils) viennent du profil actif ; {agent} est remplacé
// par le nom de l'agent.
const UI = {
  "fr": {
    "send": "Envoyer",
    "you": "Vous",
    "contribTextTab": "Proposer une information",
    "contribDocTab": "Soumettre un document",
    "contribTextLabel": "Votre information (sera examinée par un administrateur avant d'être utilisée)",
    "contribTypeLabel": "Type",
    "contribNameLabel": "Votre nom (optionnel)",
    "contribSubmit": "Envoyer la proposition",
    "contribDocFile": "Fichier (.txt, .md, .csv, .json, .docx, .pdf)",
    "contribDocNote": "Note pour l'administrateur (optionnel)",
    "contribDocSubmit": "Envoyer le document",
    "contribSuccess": "Merci — en attente de validation par un administrateur.",
    "personaLabel": "Personnalité",
    "subtitle": "",
    "placeholder": "Posez votre question…",
    "suggestions": [],
    "typing": "{agent} réfléchit…",
    "error": "{agent} n'a pas pu répondre. Vérifiez que le serveur est démarré et que la clé API est configurée.",
    "contribToggle": "Enrichir la connaissance de {agent}"
  },
  "en": {
    "send": "Send",
    "you": "You",
    "contribTextTab": "Suggest information",
    "contribDocTab": "Submit a document",
    "contribTextLabel": "Your information (reviewed by an administrator before use)",
    "contribTypeLabel": "Type",
    "contribNameLabel": "Your name (optional)",
    "contribSubmit": "Send suggestion",
    "contribDocFile": "File (.txt, .md, .csv, .json, .docx, .pdf)",
    "contribDocNote": "Note for the administrator (optional)",
    "contribDocSubmit": "Send document",
    "contribSuccess": "Thank you — pending administrator review.",
    "personaLabel": "Persona",
    "subtitle": "",
    "placeholder": "Ask your question…",
    "suggestions": [],
    "typing": "{agent} is thinking…",
    "error": "{agent} could not respond. Check that the server is running and the API key is configured.",
    "contribToggle": "Help expand {agent}'s knowledge"
  }
};

function fill(text) { return (text || "").split("{agent}").join(AGENT_NAME); }
function ui(key) { return fill((UI[currentLang] || UI.fr)[key] ?? UI.fr[key]); }

let currentLang = "fr";
let currentPersona = "sage";
let history = [];

const chat = document.getElementById("chat");
const form = document.getElementById("form");
const input = document.getElementById("input");
const sendBtn = document.getElementById("sendBtn");
const typing = document.getElementById("typing");
const suggestionsEl = document.getElementById("suggestions");

// Identifiant aléatoire du navigateur, conservé localement. Il ne contient aucune
// information personnelle ; le service l'utilise seulement, sous forme d'empreinte
// irréversible, pour compter les usagers distincts qui soulèvent une même question.
function getClientId() {
  try {
    let id = localStorage.getItem("yobakoko_client_id");
    if (!id) {
      id = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2) + Date.now());
      localStorage.setItem("yobakoko_client_id", id);
    }
    return id;
  } catch (e) {
    return null;
  }
}
const CLIENT_ID = getClientId();

const SOURCE_UI = {
  fr: { sources: "D'où viennent ces informations ?", signal: "Votre témoignage a été transmis aux experts du projet, qui l'examineront.",
        lacune: "Cette question a été signalée aux experts du projet." },
  en: { sources: "Where does this information come from?", signal: "Your testimony has been passed on to the project's experts for review.",
        lacune: "This question has been reported to the project's experts." },
  mb: { sources: "D'où viennent ces informations ?", signal: "Votre témoignage a été transmis aux experts du projet, qui l'examineront.",
        lacune: "Cette question a été signalée aux experts du projet." },
};

function addMessage(role, text, emotion, extra) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  if (role === "agent") {
    const avatar = document.createElement("span");
    avatar.className = "avatar";
    avatar.innerHTML = avatarSVG(emotion || "neutre");
    div.appendChild(avatar);
  }
  const content = document.createElement("div");
  content.className = "content";
  const label = document.createElement("span");
  label.className = "label";
  label.textContent = role === "user" ? UI[currentLang].you : AGENT_NAME;
  content.appendChild(label);
  const body = document.createElement("span");
  body.textContent = text;
  content.appendChild(body);
  // Sources du dossier de réponse (lissage : le texte les tait, l'usager peut les consulter).
  if (role === "agent" && extra && extra.sources && extra.sources.length) {
    const det = document.createElement("details");
    det.className = "msg-sources";
    const sum = document.createElement("summary");
    sum.textContent = (SOURCE_UI[currentLang] || SOURCE_UI.fr).sources;
    det.appendChild(sum);
    const ul = document.createElement("ul");
    extra.sources.forEach((src) => {
      const li = document.createElement("li");
      li.textContent = src.label;
      ul.appendChild(li);
    });
    det.appendChild(ul);
    content.appendChild(det);
  }
  // La mention n'apparaît qu'une fois par question dans la conversation, avec une formulation adaptée :
  // un témoignage (fait nouveau, contradiction) est transmis ; une lacune ou une ambiguïté est signalée.
  if (role === "agent" && extra && extra.signal && !NOTIFIED.has(extra.signal.questionId)) {
    NOTIFIED.add(extra.signal.questionId);
    const note = document.createElement("div");
    note.className = "msg-signal";
    const ui = SOURCE_UI[currentLang] || SOURCE_UI.fr;
    note.textContent = ["nouveaute", "contradiction"].includes(extra.signal.type) ? ui.signal : ui.lacune;
    content.appendChild(note);
  }
  if (role === "agent") {
    div.appendChild(content);
  } else {
    div.appendChild(label);
    div.appendChild(body);
  }
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function renderSuggestions() {
  suggestionsEl.innerHTML = "";
  UI[currentLang].suggestions.forEach((s) => {
    const chip = document.createElement("button");
    chip.className = "chip";
    chip.type = "button";
    chip.textContent = s;
    chip.onclick = () => {
      input.value = s;
      form.requestSubmit();
    };
    suggestionsEl.appendChild(chip);
  });
}

function applyLang(lang) {
  currentLang = UI[lang] ? lang : "fr";
  document.querySelectorAll(".lang-btn").forEach((b) => b.classList.toggle("active", b.dataset.lang === lang));
  document.getElementById("subtitleText").textContent = ui("subtitle");
  input.placeholder = ui("placeholder");
  sendBtn.textContent = ui("send");
  typing.textContent = ui("typing");
  document.getElementById("contribToggleLabel").textContent = ui("contribToggle");
  document.getElementById("contribTextTabBtn").textContent = ui("contribTextTab");
  document.getElementById("contribDocTabBtn").textContent = ui("contribDocTab");
  document.getElementById("contribTextLabel").textContent = ui("contribTextLabel");
  document.getElementById("contribNameLabel1").textContent = ui("contribNameLabel");
  document.getElementById("contribNameLabel2").textContent = ui("contribNameLabel");
  document.getElementById("contribSubmitBtn").textContent = ui("contribSubmit");
  document.getElementById("contribDocFileLabel").textContent = ui("contribDocFile");
  document.getElementById("contribDocNoteLabel").textContent = ui("contribDocNote");
  document.getElementById("contribDocSubmitBtn").textContent = ui("contribDocSubmit");
  document.getElementById("personaLabel").textContent = ui("personaLabel");
  renderTools();
  renderSuggestions();
  // En-tête, personnalités et accueil dans la langue choisie.
  const eb = document.querySelector(".eyebrow");
  if (eb && EYEBROWS[currentLang] !== undefined) eb.textContent = EYEBROWS[currentLang];
  const personaSel = document.getElementById("personaSelect");
  if (personaSel) PERSONAS.forEach((p) => {
    const opt = personaSel.querySelector(`option[value="${p.id}"]`);
    if (opt) opt.textContent = (currentLang === "fr" ? p.label : p[`label_${currentLang}`]) || p.label;
  });
  if (WELCOMES[currentLang]) {
    WELCOME = WELCOMES[currentLang];
    // Tant que la conversation n'a pas commencé, l'accueil est réaffiché dans la nouvelle langue.
    if (history.length === 0 && chat) { chat.innerHTML = ""; addMessage("agent", WELCOME, "joyeux"); }
  }
}

document.getElementById("personaSelect").addEventListener("change", (e) => (currentPersona = e.target.value));

async function askAgent(userText) {
  history.push({ role: "user", content: userText });
  typing.style.display = "block";
  chat.scrollTop = chat.scrollHeight;
  sendBtn.disabled = true;
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history, lang: currentLang, persona: currentPersona, clientId: CLIENT_ID }),
    });
    const data = await response.json();
    typing.style.display = "none";
    if (!response.ok) {
      addMessage("agent", data.error || UI[currentLang].error, "pensif");
      history.pop();
      return;
    }
    history.push({ role: "assistant", content: data.text });
    addMessage("agent", data.text, data.emotion, { sources: data.sources, signal: data.signal });
  } catch (err) {
    typing.style.display = "none";
    addMessage("agent", UI[currentLang].error, "pensif");
    history.pop();
  } finally {
    sendBtn.disabled = false;
  }
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  addMessage("user", text);
  input.value = "";
  askAgent(text);
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

// ---- Outils déclarés par le profil ----
// Un outil est un petit formulaire dont les champs et la consigne sont déclarés par le profil (clé
// interface.outils). La consigne, complétée par les valeurs saisies, est envoyée à l'agent comme une question.
let TOOLS = [];
function loc(v) { return typeof v === "string" ? v : (v && (v[currentLang] || v.fr || Object.values(v)[0])) || ""; }
function renderTools() {
  const box = document.getElementById("toolsContainer");
  if (!box) return;
  box.innerHTML = TOOLS.map((t, i) => `
    <div class="infer-panel">
      <button type="button" class="infer-toggle" data-tool="${i}"><span>${fill(loc(t.titre))}</span><span class="chev">▾</span></button>
      <div class="infer-body" id="toolBody${i}" style="display:none;">
        <div class="infer-grid">${(t.champs || []).map((c) => `
          <label class="infer-field"><span>${loc(c.libelle)}</span>${c.type === "choix"
            ? `<select data-field="${c.id}">${(c.options || []).map((o) => `<option value="${o.valeur}">${loc(o.libelle)}</option>`).join("")}</select>`
            : `<input type="text" data-field="${c.id}" placeholder="${c.exemple || ""}">`}</label>`).join("")}
        </div>
        <button type="button" class="infer-submit" data-submit="${i}">${fill(loc(t.bouton))}</button>
      </div>
    </div>`).join("");
  box.querySelectorAll("[data-tool]").forEach((btn) => btn.addEventListener("click", () => {
    const body = document.getElementById(`toolBody${btn.dataset.tool}`);
    const open = body.style.display !== "none";
    body.style.display = open ? "none" : "block";
    btn.classList.toggle("open", !open);
  }));
  box.querySelectorAll("[data-submit]").forEach((btn) => btn.addEventListener("click", () => {
    const t = TOOLS[Number(btn.dataset.submit)];
    const panel = btn.closest(".infer-panel");
    let msg = t.consigne || "";
    (t.champs || []).forEach((c) => {
      const el = panel.querySelector(`[data-field="${c.id}"]`);
      const val = (el && el.value.trim()) || t.vide || "";
      msg = msg.split(`{${c.id}}`).join(val);
    });
    addMessage("user", msg);
    askAgent(msg);
  }));
}

// ---- Contribution panel ----
const contribToggle = document.getElementById("contribToggle");
const contribBody = document.getElementById("contribBody");
contribToggle.addEventListener("click", () => {
  const open = contribBody.style.display !== "none";
  contribBody.style.display = open ? "none" : "block";
  contribToggle.classList.toggle("open", !open);
});
document.querySelectorAll(".contrib-tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".contrib-tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    const target = tab.dataset.target;
    document.getElementById("contribTextPane").style.display = target === "text" ? "block" : "none";
    document.getElementById("contribDocPane").style.display = target === "doc" ? "block" : "none";
  });
});
document.getElementById("contribSubmitBtn").addEventListener("click", async () => {
  const content = document.getElementById("contribContent").value.trim();
  const type = document.getElementById("contribType").value;
  const submittedBy = document.getElementById("contribName1").value.trim();
  const statusEl = document.getElementById("contribTextStatus");
  if (content.length < 5) {
    statusEl.textContent = "…";
    return;
  }
  const res = await fetch("/api/contribute", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content, type, submittedBy }),
  });
  const data = await res.json();
  statusEl.textContent = res.ok ? UI[currentLang].contribSuccess : data.error;
  if (res.ok) document.getElementById("contribContent").value = "";
});
document.getElementById("contribDocSubmitBtn").addEventListener("click", async () => {
  const fileInput = document.getElementById("contribFile");
  const statusEl = document.getElementById("contribDocStatus");
  if (!fileInput.files[0]) {
    statusEl.textContent = "…";
    return;
  }
  const fd = new FormData();
  fd.append("file", fileInput.files[0]);
  fd.append("submittedBy", document.getElementById("contribName2").value.trim());
  fd.append("note", document.getElementById("contribDocNote").value.trim());
  statusEl.textContent = "…";
  const res = await fetch("/api/documents", { method: "POST", body: fd });
  const data = await res.json();
  statusEl.textContent = res.ok ? data.message : data.error;
  if (res.ok) fileInput.value = "";
});

// ---- profil de domaine ----
// Le moteur IAST-Builder sert plusieurs domaines. Le profil actif (GET /api/profile) fournit le nom de
// l'agent, les textes propres au domaine, les langues proposées et les outils particuliers.
let AGENT_NAME = "Agent";
const NOTIFIED = new Set();   // questions déjà signalées dans cette conversation
let WELCOME = "Bienvenue.";
// Accueil et en-tête par langue, lus dans le profil ; à défaut, la version française.
const WELCOMES = {}, EYEBROWS = {};
let PERSONAS = [];

function applyProfile(profile) {
  if (!profile || !profile.interface) return;
  const itf = profile.interface;
  if (profile.agent) AGENT_NAME = profile.agent;
  // Langues déclarées par le profil ; une langue sans textes de base reprend ceux du français.
  const langs = (itf.langues || ["fr"]).map((l) => (typeof l === "string" ? { code: l, libelle: l } : l));
  langs.forEach(({ code }) => {
    if (!UI[code]) UI[code] = { ...UI.fr };
    const o = itf[code] || {};
    if (o.sousTitre) UI[code].subtitle = o.sousTitre;
    if (o.placeholder) UI[code].placeholder = o.placeholder;
    if (o.suggestions) UI[code].suggestions = o.suggestions;
  });
  const bar = document.getElementById("langButtons");
  if (bar) {
    bar.innerHTML = langs.length > 1 ? langs.map((l, i) => `<button class="lang-btn${i === 0 ? " active" : ""}" data-lang="${l.code}">${l.libelle}</button>`).join("") : "";
    bar.querySelectorAll(".lang-btn").forEach((b) => b.addEventListener("click", () => applyLang(b.dataset.lang)));
  }
  const fr = itf.fr || {};
  document.title = fr.titre || AGENT_NAME;
  const h = document.querySelector("header h1") || document.querySelector("h1");
  if (h) h.textContent = fr.titre || AGENT_NAME;
  if (fr.accueil) WELCOME = fr.accueil;
  langs.forEach(({ code }) => {
    const o = itf[code] || {};
    WELCOMES[code] = o.accueil || fr.accueil || WELCOME;
    EYEBROWS[code] = o.eyebrow || fr.eyebrow || "";
  });
  // Outils déclarés par le profil (formulaires dont les champs et la consigne sont décrits dans le profil).
  TOOLS = (itf.outils || []).filter((t) => t && typeof t === "object");
  // Personnalités déclarées par le profil, et personnalité par défaut.
  const personaSel = document.getElementById("personaSelect");
  if (personaSel && Array.isArray(profile.personnalites) && profile.personnalites.length) {
    personaSel.innerHTML = "";
    PERSONAS = profile.personnalites;
    profile.personnalites.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.id; opt.textContent = p.label;
      personaSel.appendChild(opt);
    });
    personaSel.value = profile.personnalite_par_defaut || profile.personnalites[0].id;
    currentPersona = personaSel.value;
  }
  // Collecte communautaire : le formulaire disparaît lorsqu'il est fermé par les experts.
  const panel = document.getElementById("contribPanel");
  if (panel && profile.collecte) panel.style.display = profile.collecte.formulaire ? "" : "none";
  // Types de contributions déclarés par le profil.
  const sel = document.getElementById("contribType");
  if (sel && Array.isArray(profile.contributions) && profile.contributions.length) {
    sel.innerHTML = "";
    profile.contributions.forEach((t) => {
      const opt = document.createElement("option");
      opt.value = t.id;
      opt.textContent = t.libelle || t.id;
      sel.appendChild(opt);
    });
  }
}

// ---- init ----
document.getElementById("headerAvatar").innerHTML = avatarSVG("neutre");
(async () => {
  try {
    const res = await fetch("/api/profile");
    if (res.ok) applyProfile(await res.json());
  } catch (e) {
    // Sans réponse du service, l'interface garde les textes par défaut.
  }
  applyLang("fr");
  if (!chat.children.length) addMessage("agent", WELCOME, "joyeux");
  renderSuggestions();
})();
