// public/js/app.js
// Client de conversation d'IAST-Builder ,ne parle qu'aux routes /api/* ; la clé Anthropic
// never reaches the browser.

// ---- Avatar ----
// Personnage illustré : son expression suit l'émotion choisie par l'agent, il cligne des yeux et
// remue les lèvres pendant la lecture vocale (classe « parle », posée par js/voix.js). Sa tenue reste
// volontairement neutre : couleurs et motif sont des paramètres, qu'un profil peut déclarer sous
// interface.avatar ({peau, cheveux, tenue, motif, fond}) après validation par les experts du domaine.
const AVATAR = { peau: "#8D5A3B", cheveux: "#2B1D16", tenue: "#E9B63B", motif: "#2F7D4F", fond: "#FBF1E3" };

const EXPRESSIONS = {
  neutre: {
    yeux: '<ellipse cx="80" cy="96" rx="6" ry="7" fill="#2B1D16"/><ellipse cx="120" cy="96" rx="6" ry="7" fill="#2B1D16"/><circle cx="82" cy="94" r="2" fill="#fff"/><circle cx="122" cy="94" r="2" fill="#fff"/>',
    sourcils: '<path d="M70 82 Q80 77 90 81" /><path d="M110 81 Q120 77 130 82" />',
    bouche: '<path d="M88 124 Q100 132 112 124" stroke="#6B2F26" stroke-width="3.5" fill="none" stroke-linecap="round"/>',
  },
  joyeux: {
    yeux: '<path d="M72 98 Q80 88 88 98" stroke="#2B1D16" stroke-width="4" fill="none" stroke-linecap="round"/><path d="M112 98 Q120 88 128 98" stroke="#2B1D16" stroke-width="4" fill="none" stroke-linecap="round"/>',
    sourcils: '<path d="M70 79 Q80 72 90 77" /><path d="M110 77 Q120 72 130 79" />',
    bouche: '<path d="M84 120 Q100 140 116 120 Z" fill="#6B2F26"/><path d="M89 121 Q100 126 111 121" fill="#fff"/>',
  },
  pensif: {
    yeux: '<ellipse cx="80" cy="97" rx="6" ry="6" fill="#2B1D16"/><ellipse cx="120" cy="97" rx="6" ry="6" fill="#2B1D16"/><circle cx="83" cy="93" r="2" fill="#fff"/><circle cx="123" cy="93" r="2" fill="#fff"/>',
    sourcils: '<path d="M70 80 Q80 74 90 79" /><path d="M110 83 Q120 81 130 84" />',
    bouche: '<path d="M92 127 Q101 124 110 126" stroke="#6B2F26" stroke-width="3.5" fill="none" stroke-linecap="round"/>',
  },
  solennel: {
    yeux: '<path d="M73 97 Q80 101 87 97" stroke="#2B1D16" stroke-width="4" fill="none" stroke-linecap="round"/><path d="M113 97 Q120 101 127 97" stroke="#2B1D16" stroke-width="4" fill="none" stroke-linecap="round"/>',
    sourcils: '<path d="M70 84 L90 83" /><path d="M110 83 L130 84" />',
    bouche: '<path d="M90 126 L110 126" stroke="#6B2F26" stroke-width="3.5" fill="none" stroke-linecap="round"/>',
  },
};

let avatarCount = 0;
function avatarSVG(emotion) {
  const e = EXPRESSIONS[emotion] || EXPRESSIONS.neutre;
  const a = AVATAR;
  const clip = `avatar-clip-${++avatarCount}`;
  return `<svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg" role="img" aria-hidden="true">
    <defs><clipPath id="${clip}"><circle cx="100" cy="100" r="100"/></clipPath></defs>
    <g clip-path="url(#${clip})">
      <rect width="200" height="200" fill="${a.fond}"/>
      <path d="M30 210 Q32 160 72 148 L128 148 Q168 160 170 210 Z" fill="${a.tenue}"/>
      <path d="M78 148 L100 172 L122 148" fill="${a.peau}"/>
      <path d="M74 150 L100 176 L126 150" stroke="${a.motif}" stroke-width="5" fill="none" stroke-linejoin="round"/>
      <path d="M52 190 l8 -10 l8 10 l8 -10 l8 10 M116 190 l8 -10 l8 10 l8 -10 l8 10" stroke="${a.motif}" stroke-width="4" fill="none" stroke-linejoin="round"/>
      <rect x="86" y="126" width="28" height="28" rx="10" fill="${a.peau}"/>
      <ellipse cx="54" cy="100" rx="9" ry="12" fill="${a.peau}"/>
      <ellipse cx="146" cy="100" rx="9" ry="12" fill="${a.peau}"/>
      <ellipse cx="100" cy="98" rx="46" ry="50" fill="${a.peau}"/>
      <path d="M54 92 Q52 44 100 42 Q148 44 146 92 Q140 66 100 62 Q60 66 54 92 Z" fill="${a.cheveux}"/>
      <ellipse cx="70" cy="112" rx="8" ry="5" fill="#E07A5F" opacity="0.35"/>
      <ellipse cx="130" cy="112" rx="8" ry="5" fill="#E07A5F" opacity="0.35"/>
      <g class="avatar-yeux">${e.yeux}</g>
      <g stroke="${a.cheveux}" stroke-width="4" fill="none" stroke-linecap="round">${e.sourcils}</g>
      <path d="M97 102 Q100 112 104 108" stroke="#5E3A26" stroke-width="3" fill="none" stroke-linecap="round" opacity="0.6"/>
      <g class="avatar-bouche">${e.bouche}</g>
      <ellipse class="avatar-bouche-parle" display="none" cx="100" cy="126" rx="10" ry="7" fill="#6B2F26"/>
    </g>
  </svg>`;
}

// Textes de l'interface communs à toutes les instances. Les textes propres à un domaine (sous-titre,
// suggestions, accueil, langues supplémentaires, outils) viennent du profil actif ; {agent} est remplacé
// par le nom de l'agent.
const UI = {
  "fr": {
    "send": "Envoyer",
    "you": "Vous",
    "contribTextTab": "Écrire",
    "contribDocTab": "Joindre un document",
    "contribTextLabel": "Ce que vous savez (l'équipe du projet le vérifiera avant que {agent} l'utilise)",
    "contribTypeLabel": "Type",
    "contribNameLabel": "Votre nom (facultatif)",
    "contribSubmit": "Partager",
    "contribDocFile": "Fichier (.txt, .md, .csv, .json, .docx, .pdf)",
    "contribDocNote": "Un mot pour l'équipe (facultatif)",
    "contribDocSubmit": "Envoyer le document",
    "contribSuccess": "Merci ! L'équipe du projet va examiner votre contribution.",
    "personaLabel": "Style de réponse",
    "subtitle": "",
    "placeholder": "Posez votre question…",
    "suggestions": [],
    "typing": "{agent} réfléchit…",
    "error": "{agent} n'a pas pu répondre pour le moment. Réessayez dans un instant.",
    "contribToggle": "Vous savez quelque chose ? Partagez-le avec {agent}",
    "heroTitre": "Bonjour ! Je suis {agent}.",
    "etapesTitre": "Comment ça marche",
    "etapes": [
      "Posez votre question, en l'écrivant ou à voix haute avec le micro.",
      "{agent} répond uniquement à partir de connaissances vérifiées par des experts, et cite ses sources.",
      "Vous savez quelque chose qu'il ignore ? <a href=\"#\" class=\"lien-contrib\">Partagez-le</a> : l'équipe du projet l'examinera."
    ]
  },
  "en": {
    "send": "Send",
    "you": "You",
    "contribTextTab": "Write",
    "contribDocTab": "Attach a document",
    "contribTextLabel": "What you know (the project team will review it before {agent} uses it)",
    "contribTypeLabel": "Type",
    "contribNameLabel": "Your name (optional)",
    "contribSubmit": "Share",
    "contribDocFile": "File (.txt, .md, .csv, .json, .docx, .pdf)",
    "contribDocNote": "A note for the team (optional)",
    "contribDocSubmit": "Send document",
    "contribSuccess": "Thank you! The project team will review your contribution.",
    "personaLabel": "Answer style",
    "subtitle": "",
    "placeholder": "Ask your question…",
    "suggestions": [],
    "typing": "{agent} is thinking…",
    "error": "{agent} couldn't answer right now. Please try again in a moment.",
    "contribToggle": "Know something? Share it with {agent}",
    "heroTitre": "Hello! I'm {agent}.",
    "etapesTitre": "How it works",
    "etapes": [
      "Ask your question, by typing it or out loud with the microphone.",
      "{agent} answers only from knowledge checked by experts, and cites its sources.",
      "Know something it doesn't? <a href=\"#\" class=\"lien-contrib\">Share it</a>: the project team will review it."
    ]
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
  fr: { sources: "Voir les sources", signal: "Merci ! Votre témoignage a été transmis aux experts du projet.",
        lacune: "Bonne question : elle a été transmise aux experts du projet." },
  en: { sources: "See sources", signal: "Thank you! Your testimony has been passed on to the project's experts.",
        lacune: "Good question: it has been passed on to the project's experts." },
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
  // Barre de lecture (écouter, pause, recommencer, arrêter), fournie par voix.js.
  if (role === "agent" && window.Voix) {
    const barre = Voix.barre(text, emotion);
    if (barre) content.appendChild(barre);
  }
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
  if (window.Voix) Voix.setLang(currentLang);
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
  document.getElementById("heroTitre").textContent = ui("heroTitre");
  const etapes = (UI[currentLang] || UI.fr).etapes || UI.fr.etapes;
  document.getElementById("etapes").innerHTML = `<li class="etapes-titre">${ui("etapesTitre")}</li>`
    + etapes.map((e) => `<li>${fill(e)}</li>`).join("");
  if (WELCOMES[currentLang]) {
    WELCOME = WELCOMES[currentLang];
    // Tant que la conversation n'a pas commencé, l'accueil est réaffiché dans la nouvelle langue.
    if (history.length === 0 && chat) { chat.innerHTML = ""; addMessage("agent", WELCOME, "joyeux"); }
  }
  document.getElementById("heroTexte").textContent = WELCOME;
}

document.getElementById("personaSelect").addEventListener("change", (e) => (currentPersona = e.target.value));

async function askAgent(userText) {
  document.body.classList.remove("conversation-vide");
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
      addMessage("agent", data.error || ui("error"), "pensif");
      history.pop();
      return;
    }
    history.push({ role: "assistant", content: data.text });
    addMessage("agent", data.text, data.emotion, { sources: data.sources, signal: data.signal });
    document.getElementById("headerAvatar").innerHTML = avatarSVG(data.emotion);
    if (window.Voix) Voix.lire(data.text, data.emotion);
  } catch (err) {
    typing.style.display = "none";
    addMessage("agent", ui("error"), "pensif");
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
  ajusterHauteur();
  askAgent(text);
});

// La zone de saisie s'agrandit avec son contenu (question longue, transcription vocale) ;
// au-delà de sa hauteur maximale (CSS), elle défile.
function ajusterHauteur() {
  input.style.height = "auto";
  input.style.height = input.scrollHeight + 4 + "px";
}
input.addEventListener("input", ajusterHauteur);

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
const contribPanel = document.getElementById("contribPanel");
// Le panneau n'apparaît que sur demande (lien « Partagez-le » de la barre latérale) ; le refermer le masque.
contribToggle.addEventListener("click", () => {
  const open = contribBody.style.display !== "none";
  contribBody.style.display = open ? "none" : "block";
  contribToggle.classList.toggle("open", !open);
  if (open) contribPanel.classList.remove("visible");
});
document.getElementById("etapes").addEventListener("click", (e) => {
  if (!e.target.closest(".lien-contrib")) return;
  e.preventDefault();
  contribPanel.classList.add("visible");
  contribBody.style.display = "block";
  contribToggle.classList.add("open");
  contribPanel.scrollIntoView({ behavior: "smooth", block: "center" });
  document.getElementById("contribContent").focus({ preventScroll: true });
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
  if (itf.avatar && typeof itf.avatar === "object") Object.assign(AVATAR, itf.avatar);
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
// Palette de l'interface : « foret » par défaut ; une autre peut être essayée dans l'adresse (?theme=sable | lagune | savane).
const THEME = new URLSearchParams(location.search).get("theme") || "foret";
if (THEME !== "sable") document.body.dataset.theme = THEME;
(async () => {
  try {
    const res = await fetch("/api/profile");
    if (res.ok) applyProfile(await res.json());
  } catch (e) {
    // Sans réponse du service, l'interface garde les textes par défaut.
  }
  document.getElementById("headerAvatar").innerHTML = avatarSVG("joyeux");
  // Tant que rien n'a été demandé, accueil, suggestions et saisie sont regroupés au centre de l'écran.
  if (history.length === 0) document.body.classList.add("conversation-vide");
  applyLang("fr");
  if (!chat.children.length) addMessage("agent", WELCOME, "joyeux");
  renderSuggestions();
})();
