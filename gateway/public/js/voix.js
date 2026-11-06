// public/js/voix.js
// Volet oral (prototype) : dictée de la question et lecture de la réponse.
// Le texte reconnu suit le même chemin qu'une question tapée (/api/chat) : dossier de réponse,
// filtre de sûreté et signaux ne changent pas. Les deux moteurs sont isolés derrière
// reconnaitre() et lire() :
// - reconnaissance : enregistrement du micro dans le navigateur, transcription locale par
//   Whisper dans le brain (/api/stt). La Web Speech API de Chrome a été écartée : elle envoie
//   l'audio aux serveurs de Google et échoue dès que ce service est injoignable (erreur « network »).
// - synthèse : voix installées sur la machine (speechSynthesis), qui fonctionnent hors ligne.

window.Voix = (() => {
  const LOCALES = { fr: "fr-FR", en: "en-US" };
  // L'émotion choisie par l'agent module la voix, comme elle module l'avatar.
  const PROSODIE = {
    neutre: { rate: 1, pitch: 1 },
    joyeux: { rate: 1.05, pitch: 1.1 },
    pensif: { rate: 0.92, pitch: 0.95 },
    solennel: { rate: 0.88, pitch: 0.9 },
  };
  const TEXTES = {
    fr: { parler: "Parler", ecoute: "J'écoute… (cliquer pour terminer)", transcription: "Transcription…",
          lecture: "Lecture vocale des réponses", refus: "Accès au micro refusé.", rien: "Je n'ai rien entendu.",
          erreur: "La reconnaissance vocale a échoué." },
    en: { parler: "Speak", ecoute: "Listening… (click to finish)", transcription: "Transcribing…",
          lecture: "Read answers aloud", refus: "Microphone access denied.", rien: "I didn't hear anything.",
          erreur: "Speech recognition failed." },
  };
  // false : la transcription est placée dans la zone de saisie, l'usager la relit puis l'envoie.
  const ENVOI_AUTO = false;
  // Au-delà, l'enregistrement s'arrête de lui-même.
  const DUREE_MAX_MS = 30000;

  const micro = !!(navigator.mediaDevices && window.MediaRecorder);
  const synthese = window.speechSynthesis;
  let lang = "fr";
  let lectureActive = true;
  let enregistrement = null;

  const locale = () => LOCALES[lang] || LOCALES.fr;
  const t = (cle) => (TEXTES[lang] || TEXTES.fr)[cle];

  // ---- Synthèse ----
  // Les voix se chargent de façon asynchrone : getVoices() peut être vide au premier appel.
  // Les voix locales (installées sur la machine) sont préférées : elles fonctionnent hors ligne et
  // signalent chaque mot, ce qui permet de synchroniser les lèvres de l'avatar.
  function voixPour(loc) {
    const voix = synthese.getVoices();
    const prefixe = loc.slice(0, 2);
    const candidates = [(v) => v.lang === loc, (v) => v.lang.startsWith(prefixe)];
    for (const ok of candidates) {
      const v = voix.find((x) => ok(x) && x.localService) || voix.find(ok);
      if (v) return v;
    }
    return null;
  }

  function lire(texte, emotion) {
    if (!synthese || !lectureActive || !texte) return;
    synthese.cancel();
    const enonce = new SpeechSynthesisUtterance(texte);
    enonce.lang = locale();
    const v = voixPour(enonce.lang);
    if (v) enonce.voice = v;
    const p = PROSODIE[emotion] || PROSODIE.neutre;
    enonce.rate = p.rate;
    enonce.pitch = p.pitch;
    enonce.onstart = () => parle(true);
    enonce.onend = enonce.onerror = () => parle(false);
    enonce.onboundary = (e) => articuler(texte, e, enonce.rate);
    synthese.speak(enonce);
  }

  // L'avatar de l'en-tête et celui du dernier message remuent les lèvres pendant la lecture.
  let parlants = [];
  let minuteursBouche = [];
  function parle(actif) {
    minuteursBouche.forEach(clearTimeout);
    minuteursBouche = [];
    parlants.forEach((el) => { el.classList.remove("parle", "synchro"); el.style.removeProperty("--ouverture"); });
    parlants = [];
    if (!actif) return;
    const avatars = [document.getElementById("headerAvatar"), ...document.querySelectorAll(".msg.agent .avatar")].filter(Boolean);
    parlants = [...new Set([avatars[0], avatars[avatars.length - 1]])].filter(Boolean);
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
      flux = await navigator.mediaDevices.getUserMedia({ audio: true });
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
        data.text ? final(data.text) : erreur(t("rien"));
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
  const lectureBtn = document.createElement("button");
  lectureBtn.type = "button";
  lectureBtn.className = "voice-btn active";
  lectureBtn.textContent = "🔊";
  // Sans prise en charge par le navigateur, le bouton n'apparaît pas.
  if (micro) form.insertBefore(micBtn, sendBtn);
  if (synthese) form.insertBefore(lectureBtn, sendBtn);

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
    if (synthese) synthese.cancel();   // l'usager reprend la parole : l'agent se tait
    const placeholder = input.placeholder;
    enregistrement = await reconnaitre({
      debut: () => etatMicro("ecoute"),
      transcription: () => {
        enregistrement = null;
        etatMicro("transcription");
        input.placeholder = t("transcription");
      },
      final: (texte) => {
        etatMicro("repos");
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

  lectureBtn.addEventListener("click", () => {
    lectureActive = !lectureActive;
    lectureBtn.classList.toggle("active", lectureActive);
    if (!lectureActive && synthese) synthese.cancel();
  });

  function setLang(l) {
    lang = LOCALES[l] ? l : "fr";
    arreterEcoute();
    micBtn.title = t("parler");
    micBtn.setAttribute("aria-label", t("parler"));
    lectureBtn.title = t("lecture");
    lectureBtn.setAttribute("aria-label", t("lecture"));
  }
  setLang(lang);

  return { lire, setLang };
})();
