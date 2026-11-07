// public/js/voix.js
// Volet oral (prototype) : dictée de la question et lecture de la réponse.
// Le texte reconnu suit le même chemin qu'une question tapée (/api/chat) : dossier de réponse,
// filtre de sûreté et signaux ne changent pas. Les deux moteurs sont isolés derrière
// reconnaitre() et jouer() :
// - reconnaissance : enregistrement du micro dans le navigateur, transcription locale par
//   Whisper dans le brain (/api/stt). La Web Speech API de Chrome a été écartée : elle envoie
//   l'audio aux serveurs de Google et échoue dès que ce service est injoignable (erreur « network »).
// - synthèse : voix du navigateur (speechSynthesis). Les voix « naturelles » (neuronales) sont
//   préférées quand elles existent ; l'usager peut en choisir une autre dans les réglages.

window.Voix = (() => {
  const LOCALES = { fr: "fr-FR", en: "en-US" };
  // L'émotion choisie par l'agent module la voix, comme elle module l'avatar. Les écarts restent
  // faibles : une hauteur trop modifiée rend la voix plus artificielle.
  const PROSODIE = {
    neutre: { rate: 1, pitch: 1 },
    joyeux: { rate: 1.04, pitch: 1.04 },
    pensif: { rate: 0.95, pitch: 0.98 },
    solennel: { rate: 0.92, pitch: 0.96 },
  };
  const VITESSES = [0.85, 1, 1.15, 1.3];
  const TEXTES = {
    fr: { parler: "Parler", ecoute: "J'écoute… (cliquer pour terminer)", transcription: "Transcription…",
          reglages: "Réglages de la voix", auto: "Lire les réponses automatiquement", voix: "Voix", vitesse: "Vitesse",
          essayer: "Essayer", essai: "Bonjour, je suis votre guide. Posez-moi une question quand vous voulez.",
          enLigne: "en ligne", aucune: "Aucune voix française installée",
          ecouter: "Écouter", pause: "Pause", reprendre: "Reprendre", recommencer: "Recommencer", arreter: "Arrêter",
          refus: "Accès au micro refusé.", rien: "Je n'ai rien entendu.", erreur: "La reconnaissance vocale a échoué." },
    en: { parler: "Speak", ecoute: "Listening… (click to finish)", transcription: "Transcribing…",
          reglages: "Voice settings", auto: "Read answers aloud automatically", voix: "Voice", vitesse: "Speed",
          essayer: "Try it", essai: "Hello, I am your guide. Ask me a question whenever you like.",
          enLigne: "online", aucune: "No English voice installed",
          ecouter: "Listen", pause: "Pause", reprendre: "Resume", recommencer: "Start over", arreter: "Stop",
          refus: "Microphone access denied.", rien: "I didn't hear anything.", erreur: "Speech recognition failed." },
  };
  const ICONES = {
    lire: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg>',
    pause: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 5h4v14H6zM14 5h4v14h-4z"/></svg>',
    recommencer: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5V1.5L7 6l5 4.5V7a5 5 0 1 1-5 5H5a7 7 0 1 0 7-7z"/></svg>',
    arreter: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.5 6.5h11v11h-11z"/></svg>',
  };
  // false : la transcription est placée dans la zone de saisie, l'usager la relit puis l'envoie.
  const ENVOI_AUTO = false;
  // Au-delà, l'enregistrement s'arrête de lui-même.
  const DUREE_MAX_MS = 30000;
  // Prototype : affiche sous la barre de saisie le moteur qui a transcrit la question et son temps
  // (utile pour comparer Whisper et ElevenLabs). Mettre false pour une démonstration publique.
  const AFFICHER_MOTEUR = true;
  const NOMS_MOTEURS = { scribe_v2: "ElevenLabs Scribe v2" };

  const micro = !!(navigator.mediaDevices && window.MediaRecorder);
  const synthese = window.speechSynthesis;
  let lang = "fr";
  let enregistrement = null;

  const locale = () => LOCALES[lang] || LOCALES.fr;
  const t = (cle) => (TEXTES[lang] || TEXTES.fr)[cle];

  // ---- Réglages, mémorisés dans ce navigateur (confort seulement : sans stockage, valeurs par défaut) ----
  const CLE = "iast-voix";
  const reglages = { auto: true, vitesse: 1, voix: {} };   // voix : { fr: nom, en: nom }
  try { Object.assign(reglages, JSON.parse(localStorage.getItem(CLE)) || {}); } catch (e) { /* stockage indisponible */ }
  const sauver = () => { try { localStorage.setItem(CLE, JSON.stringify(reglages)); } catch (e) { /* idem */ } };

  // ---- Choix de la voix ----
  // Les voix neuronales (« Natural » dans Edge, « Google » dans Chrome) ont une intonation bien plus
  // humaine que les anciennes voix de Windows (Hortense, Paul…). Elles passent par un service en ligne :
  // le texte de la réponse (jamais la voix de l'usager) est alors envoyé à Microsoft ou Google.
  // Les voix se chargent de façon asynchrone : getVoices() peut être vide au premier appel.
  const qualite = (v) => (/natural|neural/i.test(v.name) ? 8 : 0) + (/online/i.test(v.name) ? 4 : 0) + (/google/i.test(v.name) ? 3 : 0);
  function voixDisponibles() {
    if (!synthese) return [];
    return synthese.getVoices()
      .filter((v) => v.lang.toLowerCase().replace("_", "-").startsWith(lang))
      .sort((a, b) => qualite(b) - qualite(a) || (b.lang === locale()) - (a.lang === locale()) || a.name.localeCompare(b.name));
  }
  function voixPour() {
    const liste = voixDisponibles();
    return liste.find((v) => v.name === reglages.voix[lang]) || liste[0] || null;
  }

  // ---- Lecture ----
  // La réponse est lue phrase par phrase : les pauses entre phrases sonnent plus naturelles, la pause
  // et la reprise fonctionnent dans tous les navigateurs (on reprend au début de la phrase en cours),
  // et Chrome ne coupe plus les longues réponses au bout d'une quinzaine de secondes.
  const phrases = (texte) => texte.split(/(?<=[.!?…»:])\s+|\n+/).map((s) => s.replace(/^•\s*/, "").trim()).filter(Boolean);

  let lecture = null;         // { barre, morceaux, i, emotion, enPause }
  let derniereBarre = null;

  function jouer(texte, emotion, barre) {
    if (!synthese || !texte) return;
    arreter();
    lecture = { barre, morceaux: phrases(texte), i: 0, emotion, enPause: false };
    etatBarre(barre, "lecture");
    suivante(lecture);
  }

  function suivante(l) {
    if (lecture !== l || l.enPause) return;
    if (l.i >= l.morceaux.length) return fin(l);
    const morceau = l.morceaux[l.i];
    const enonce = new SpeechSynthesisUtterance(morceau);
    enonce.lang = locale();
    const v = voixPour();
    if (v) { enonce.voice = v; enonce.lang = v.lang; }
    const p = PROSODIE[l.emotion] || PROSODIE.neutre;
    enonce.rate = p.rate * reglages.vitesse;
    enonce.pitch = p.pitch;
    enonce.onstart = () => { if (lecture === l) parle(true); };
    enonce.onboundary = (e) => { if (lecture === l) articuler(morceau, e, enonce.rate); };
    // Une annulation (pause, arrêt, autre lecture) déclenche aussi ces événements : on les ignore alors.
    enonce.onend = enonce.onerror = () => {
      if (lecture !== l || l.enPause) return;
      parle(false);
      l.i++;
      suivante(l);
    };
    synthese.speak(enonce);
  }

  function fin(l) {
    lecture = null;
    parle(false);
    etatBarre(l.barre, "repos");
  }

  function pause() {
    if (!lecture) return;
    lecture.enPause = true;
    synthese.cancel();
    parle(false);
    etatBarre(lecture.barre, "pause");
  }

  function reprendre() {
    if (!lecture) return;
    lecture.enPause = false;
    etatBarre(lecture.barre, "lecture");
    suivante(lecture);
  }

  function arreter() {
    const l = lecture;
    lecture = null;
    if (synthese) synthese.cancel();
    parle(false);
    if (l) etatBarre(l.barre, "repos");
  }

  // Appelé par app.js à chaque nouvelle réponse : lecture seulement si l'usager l'a laissée activée.
  function lire(texte, emotion) {
    if (!reglages.auto) return;
    const barre = derniereBarre && derniereBarre._audio.texte === texte ? derniereBarre : null;
    jouer(texte, emotion, barre);
  }

  // ---- Barre de lecture sous chaque réponse ----
  function barre(texte, emotion) {
    if (!synthese || !texte) return null;
    const el = document.createElement("div");
    el.className = "audio-barre";
    el._audio = { texte, emotion };
    const bouton = (cls) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "audio-btn " + cls;
      el.appendChild(b);
      return b;
    };
    const lirePause = bouton("audio-lire");
    const recommencer = bouton("audio-recommencer");
    const stop = bouton("audio-arreter");
    recommencer.innerHTML = ICONES.recommencer;
    stop.innerHTML = ICONES.arreter;
    const actif = () => lecture && lecture.barre === el;
    lirePause.addEventListener("click", () => {
      if (!actif()) return jouer(texte, emotion, el);
      lecture.enPause ? reprendre() : pause();
    });
    recommencer.addEventListener("click", () => jouer(texte, emotion, el));
    stop.addEventListener("click", () => actif() && arreter());
    derniereBarre = el;
    etatBarre(el, "repos");
    return el;
  }

  function etatBarre(el, etat) {
    if (!el) return;
    el.dataset.etat = etat;
    const [lirePause, recommencer, stop] = el.children;
    lirePause.innerHTML = etat === "lecture" ? ICONES.pause : ICONES.lire;
    const titres = [[lirePause, etat === "lecture" ? "pause" : etat === "pause" ? "reprendre" : "ecouter"],
                    [recommencer, "recommencer"], [stop, "arreter"]];
    titres.forEach(([b, cle]) => { b.title = t(cle); b.setAttribute("aria-label", t(cle)); });
    stop.disabled = etat === "repos";
  }

  // ---- Avatar : l'avatar de l'en-tête et celui du message lu remuent les lèvres ----
  let parlants = [];
  let minuteursBouche = [];
  function parle(actif) {
    minuteursBouche.forEach(clearTimeout);
    minuteursBouche = [];
    parlants.forEach((el) => { el.classList.remove("parle", "synchro"); el.style.removeProperty("--ouverture"); });
    parlants = [];
    if (!actif) return;
    const msg = lecture && lecture.barre && lecture.barre.closest(".msg");
    const avatarMsg = msg ? msg.querySelector(".avatar") : [...document.querySelectorAll(".msg.agent .avatar")].pop();
    parlants = [...new Set([document.getElementById("headerAvatar"), avatarMsg])].filter(Boolean);
    parlants.forEach((el) => el.classList.add("parle"));
  }

  // Synchronisation des lèvres : la synthèse signale le début de chaque mot (événement « boundary ») ;
  // la bouche s'ouvre et se referme environ une fois par syllabe, puis reste presque close entre les mots.
  // Sans ces signaux (certaines voix ne les émettent pas), l'animation régulière du CSS sert de repli.
  const ouvrir = (v) => parlants.forEach((el) => { el.classList.add("synchro"); el.style.setProperty("--ouverture", v); });
  function articuler(texte, e, debit) {
    if (e.name && e.name !== "word") return;
    const mot = e.charLength ? texte.substr(e.charIndex, e.charLength) : (texte.slice(e.charIndex).match(/^\S+/) || [""])[0];
    const syllabes = Math.max(1, (mot.match(/[aeiouyàâäéèêëîïôöûùü]+/gi) || []).length);
    const duree = Math.min(600, Math.max(120, mot.length * 62 / (debit || 1)));
    const pas = duree / syllabes;
    minuteursBouche.forEach(clearTimeout);
    minuteursBouche = [];
    for (let i = 0; i < syllabes; i++) {
      minuteursBouche.push(setTimeout(() => ouvrir((0.55 + Math.random() * 0.45).toFixed(2)), i * pas));
      minuteursBouche.push(setTimeout(() => ouvrir(0.15), i * pas + pas * 0.6));
    }
  }

  // ---- Reconnaissance ----
  // Enregistre jusqu'à arreter() (ou DUREE_MAX_MS), puis envoie l'audio à /api/stt.
  async function reconnaitre({ debut, transcription, final, erreur }) {
    let flux;
    try {
      // Traitements du navigateur : moins de bruit de fond et d'écho, volume ajusté pour une voix éloignée.
      flux = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
      });
    } catch (e) {
      erreur(e.name === "NotAllowedError" ? t("refus") : `${t("erreur")} (${e.name})`);
      return null;
    }
    const rec = new MediaRecorder(flux);
    const morceaux = [];
    rec.ondataavailable = (e) => { if (e.data.size) morceaux.push(e.data); };
    rec.onstop = async () => {
      clearTimeout(minuteur);
      flux.getTracks().forEach((piste) => piste.stop());
      const audio = new Blob(morceaux, { type: rec.mimeType || "audio/webm" });
      if (!audio.size) return erreur(t("rien"));
      transcription();
      const fd = new FormData();
      fd.append("file", audio, "question.webm");
      fd.append("lang", lang);
      try {
        const res = await fetch("/api/stt", { method: "POST", body: fd });
        const data = await res.json();
        if (!res.ok) return erreur(data.detail || data.error || t("erreur"));
        if (data.moteur) console.info(`[voix] transcription ${data.moteur} en ${data.temps} s : ${data.text}`);
        data.text ? final(data.text, data) : erreur(t("rien"));
      } catch (e) {
        erreur(t("erreur"));
      }
    };
    const minuteur = setTimeout(() => rec.state === "recording" && rec.stop(), DUREE_MAX_MS);
    rec.start();
    debut();
    return { arreter: () => rec.state === "recording" && rec.stop() };
  }

  // ---- Interface ----
  const form = document.getElementById("form");
  const input = document.getElementById("input");
  const sendBtn = document.getElementById("sendBtn");

  const micBtn = document.createElement("button");
  micBtn.type = "button";
  micBtn.className = "voice-btn";
  micBtn.textContent = "🎤";
  const reglagesBtn = document.createElement("button");
  reglagesBtn.type = "button";
  reglagesBtn.className = "voice-btn";
  reglagesBtn.textContent = "🔊";
  reglagesBtn.setAttribute("aria-haspopup", "true");
  reglagesBtn.setAttribute("aria-expanded", "false");
  // Sans prise en charge par le navigateur, le bouton n'apparaît pas.
  if (micro) form.insertBefore(micBtn, sendBtn);

  // Indication du moteur de transcription, sous la barre de saisie ; effacée à l'envoi.
  const infoMoteur = document.createElement("div");
  infoMoteur.className = "stt-info";
  infoMoteur.hidden = true;
  if (micro && AFFICHER_MOTEUR) form.after(infoMoteur);
  function montrerMoteur(data) {
    if (!AFFICHER_MOTEUR || !data || !data.moteur) return;
    const nom = NOMS_MOTEURS[data.moteur] || data.moteur.replace(/^whisper-/, "Whisper ") + " (local)";
    const temps = String(data.temps).replace(".", lang === "fr" ? "," : ".");
    infoMoteur.textContent = `🎤 ${lang === "fr" ? "Transcrit par" : "Transcribed by"} ${nom} · ${temps} s`;
    infoMoteur.hidden = false;
  }
  form.addEventListener("submit", () => { infoMoteur.hidden = true; });
  if (synthese) form.insertBefore(reglagesBtn, sendBtn);

  // Panneau de réglages, ouvert par le bouton 🔊.
  const panneau = document.createElement("div");
  panneau.className = "voix-reglages";
  panneau.hidden = true;
  panneau.innerHTML = `
    <p class="voix-titre"></p>
    <label class="voix-auto"><input type="checkbox"> <span></span></label>
    <label class="voix-champ"><span class="voix-etiquette"></span><select class="voix-choix"></select></label>
    <label class="voix-champ"><span class="voix-etiquette"></span><select class="voix-vitesse"></select></label>
    <button type="button" class="voix-essai"></button>`;
  if (synthese) form.appendChild(panneau);
  const [autoCase, choixVoix, choixVitesse, essaiBtn] =
    ["input", ".voix-choix", ".voix-vitesse", ".voix-essai"].map((s) => panneau.querySelector(s));
  VITESSES.forEach((v) => choixVitesse.add(new Option(`${v}×`.replace(".", lang === "fr" ? "," : "."), v)));

  function remplirVoix() {
    const liste = voixDisponibles();
    const choisie = voixPour();
    choixVoix.innerHTML = "";
    liste.forEach((v) => {
      const nom = v.name.replace(/^(Microsoft|Google)\s+/, "").replace(/\s+-\s+.*$/, "");
      choixVoix.add(new Option(`${nom} (${v.lang})${v.localService ? "" : " · " + t("enLigne")}`, v.name, false, v === choisie));
    });
    if (!liste.length) choixVoix.add(new Option(t("aucune"), ""));
    choixVoix.disabled = !liste.length;
  }

  function textesPanneau() {
    panneau.querySelector(".voix-titre").textContent = t("reglages");
    panneau.querySelector(".voix-auto span").textContent = t("auto");
    const [eVoix, eVitesse] = panneau.querySelectorAll(".voix-etiquette");
    eVoix.textContent = t("voix");
    eVitesse.textContent = t("vitesse");
    essaiBtn.textContent = "▶ " + t("essayer");
    autoCase.checked = reglages.auto;
    choixVitesse.value = String(reglages.vitesse);
    [...choixVitesse.options].forEach((o) => { o.text = `${o.value}×`.replace(".", lang === "fr" ? "," : "."); });
    remplirVoix();
  }

  function ouvrirPanneau(ouvert) {
    panneau.hidden = !ouvert;
    reglagesBtn.setAttribute("aria-expanded", String(ouvert));
    reglagesBtn.classList.toggle("ouvert", ouvert);
    if (ouvert) textesPanneau();
  }

  reglagesBtn.addEventListener("click", () => ouvrirPanneau(panneau.hidden));
  document.addEventListener("click", (e) => {
    if (!panneau.hidden && !panneau.contains(e.target) && e.target !== reglagesBtn) ouvrirPanneau(false);
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !panneau.hidden) ouvrirPanneau(false); });

  autoCase.addEventListener("change", () => {
    reglages.auto = autoCase.checked;
    reglagesBtn.classList.toggle("active", reglages.auto);
    if (!reglages.auto) arreter();
    sauver();
  });
  choixVoix.addEventListener("change", () => { reglages.voix[lang] = choixVoix.value; sauver(); });
  choixVitesse.addEventListener("change", () => { reglages.vitesse = Number(choixVitesse.value); sauver(); });
  essaiBtn.addEventListener("click", () => jouer(t("essai"), "neutre", null));
  if (synthese) synthese.addEventListener?.("voiceschanged", () => { if (!panneau.hidden) remplirVoix(); });
  reglagesBtn.classList.toggle("active", reglages.auto);

  function etatMicro(etat) {
    micBtn.classList.toggle("listening", etat === "ecoute");
    micBtn.disabled = etat === "transcription";
    micBtn.title = etat === "ecoute" ? t("ecoute") : t("parler");
  }

  function arreterEcoute() {
    if (enregistrement) enregistrement.arreter();
  }

  micBtn.addEventListener("click", async () => {
    if (enregistrement) return arreterEcoute();
    arreter();   // l'usager reprend la parole : l'agent se tait
    const placeholder = input.placeholder;
    enregistrement = await reconnaitre({
      debut: () => etatMicro("ecoute"),
      transcription: () => {
        enregistrement = null;
        etatMicro("transcription");
        input.placeholder = t("transcription");
      },
      final: (texte, data) => {
        etatMicro("repos");
        montrerMoteur(data);
        input.placeholder = placeholder;
        input.value = texte;
        input.dispatchEvent(new Event("input"));   // la zone s'agrandit pour montrer toute la transcription
        input.focus();
        if (ENVOI_AUTO) form.requestSubmit();
      },
      erreur: (message) => {
        enregistrement = null;
        etatMicro("repos");
        input.placeholder = message;
      },
    });
  });

  function setLang(l) {
    lang = LOCALES[l] ? l : "fr";
    arreterEcoute();
    arreter();
    micBtn.title = t("parler");
    micBtn.setAttribute("aria-label", t("parler"));
    reglagesBtn.title = t("reglages");
    reglagesBtn.setAttribute("aria-label", t("reglages"));
    document.querySelectorAll(".audio-barre").forEach((el) => etatBarre(el, el.dataset.etat || "repos"));
    if (!panneau.hidden) textesPanneau();
  }
  setLang(lang);

  return { lire, barre, arreter, setLang };
})();
