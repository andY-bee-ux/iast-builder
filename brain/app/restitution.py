"""app/restitution.py — lissage des réponses : dossier de réponse, restitution, contrôle de fidélité.

L'ancrage ontologique garantit l'exactitude des réponses, pas leur lisibilité.
Le traitement d'une question comprend donc trois temps :

1. Dossier de réponse (couche symbolique, construit par prompt_builder.py) : les
   faits pertinents, chacun avec un identifiant :
       ONT        l'ontologie du projet
       R1, R2...  règles d'attribution
       REP:<bloc> bloc du répertoire de terrain (ex. REP:BGT_16)
       E<n>       assertion validée par les experts (graphe des enrichissements)
       P<n>       passage d'un document ou d'une contribution approuvés
2. Restitution (couche neuronale) : le LLM reformule le dossier pour l'usager selon
   la charte CHARTER_POPULAR (ou CHARTER_SCHOLARLY pour la personnalité « chercheur »),
   en plaçant après chaque phrase factuelle les identifiants qui la fondent : [[R1,E3]].
3. Contrôle de fidélité (couche symbolique, apply_citations) : chaque renvoi doit
   désigner un fait du dossier ; les renvois sont retirés avant l'affichage et
   servent à constituer la liste des sources consultable par l'usager.
   En mode strict (RESTITUTION_STRICT=true), les phrases déclaratives sans renvoi
   sont retirées ; sinon, les anomalies sont seulement inscrites au journal.

Limite assumée : le contrôle vérifie qu'une phrase s'appuie sur un fait du
dossier, pas qu'elle en rend exactement la nuance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import journal
from .config import RESTITUTION_STRICT
from .profile import active as active_profile
from .text_utils import split_sentences

CITE_RE = re.compile(r"\s*\[\[([^\[\]]{1,200})\]\]")
# Renvois mal écrits par le modèle : « [[E1][E5]] », « [E1] », « [[E1, E5]] ». Normalisés avant l'analyse,
# puis tout reste de renvoi vers le dossier est retiré du texte affiché.
_JOINED_RE = re.compile(r"\[\[([^\[\]]{1,200})\]\[([^\[\]]{1,200})\]\]")
_DOSSIER_ID = r"(?:ONT|REP:[^\]\s,;]+|[CERPV]\d+)"
_LEFTOVER_RE = re.compile(r"\s*\[+\s*" + _DOSSIER_ID + r"(?:\s*[\],;\[]+\s*" + _DOSSIER_ID + r")*\s*\]+")


_RULE_RE = re.compile(r"^\s*([-*_]\s*){3,}$")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*")
_QUOTE_RE = re.compile(r"^\s{0,3}>\s?")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+")
_EMPHASIS_RE = re.compile(r"(\*{1,3}|_{2,3})(?=\S)(.+?)(?<=\S)\1")


_DOSSIER_PHRASES = [
    (re.compile(r"\s+(?:dans|selon)\s+(?:mon|le|ce)\s+dossier(?:\s+de\s+réponse)?(?:\s+actuel)?(?=[\s.,;!?])", re.I), ""),
    (re.compile(r"\b(?:selon|d'après|d’après)\s+(?:le|ce|mon)\s+dossier(?:\s+de\s+réponse)?\s*,?\s*", re.I), "à ma connaissance, "),
    (re.compile(r"\b(?:le|ce|mon)\s+dossier(?:\s+de\s+réponse)?\s+(?:confirme|indique|précise|mentionne|montre|dit|établit)\s+(?:que|qu')\s*", re.I),
     "à ma connaissance, "),
]


def first_person(text: str) -> str:
    """Remplace les formules qui évoquent le dossier par « à ma connaissance », et rétablit la majuscule
    en début de phrase."""
    for pattern, repl in _DOSSIER_PHRASES:
        text = pattern.sub(repl, text)
    return re.sub(r"(^|[.!?…]\s+|\n\s*)à ma connaissance", lambda m: m.group(1) + "À ma connaissance", text)


def plain_text(text: str) -> str:
    """Rend le texte lisible tel qu'il est affiché : retire les séparateurs, les titres, les citations
    en retrait et l'emphase Markdown (astérisques), garde les listes sous forme de puces simples, et
    resserre les lignes vides. Appliqué en dernier, après le contrôle des renvois et de sûreté."""
    lines = []
    for line in text.split("\n"):
        if _RULE_RE.match(line):
            continue
        line = _HEADING_RE.sub("", line)
        line = _QUOTE_RE.sub("", line)
        line = _BULLET_RE.sub("• ", line)
        previous = None
        while previous != line:
            previous, line = line, _EMPHASIS_RE.sub(r"\2", line)
        line = line.replace("`", "")
        lines.append(line.rstrip())
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    # Espace manquante entre deux phrases (« Rubiaceae.Ce nom »), souvent laissée par le retrait des renvois.
    out = re.sub(r"([a-zàâäéèêëîïôöùûüç\)»])([.!?…])([A-ZÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ«])", r"\1\2 \3", out)
    out = re.sub(r"([?!…])([A-ZÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ«])", r"\1 \2", out)
    return first_person(out.strip())


def normalize_citations(text: str) -> str:
    previous = None
    while previous != text:
        previous, text = text, _JOINED_RE.sub(r"[[\1]][[\2]]", text)
    return text

CONVERSATION_RULE = """CONVERSATION — la réponse doit se lire d'un coup d'œil, comme un échange de vive voix :
1. Par défaut, réponds en deux à quatre phrases (une centaine de mots au plus). Commence par l'essentiel.
2. Parle en ton nom, directement : affirme ce que tu sais sans formule d'introduction. Réserve « à ma
   connaissance » ou « je n'ai pas d'information sur » aux moments où tu signales une limite, et ne commence pas
   deux réponses de suite par la même tournure. N'évoque jamais le dossier, les sources qui t'ont été fournies,
   leurs identifiants ni la manière dont tu disposes de ces informations : les sources restent consultables sous
   ta réponse.
3. S'il te reste des choses que tu sais et que tu n'as pas dites (des usages, des précautions, des noms, une
   source), termine par une courte relance qui les propose. C'est toujours le cas quand ta réponse se contente de
   nommer des entités dont tu connais davantage. Exemple : « Ce nom désigne deux espèces, A et B. Voulez-vous
   connaître l'usage rapporté pour A ? » Si tu as tout dit, ne relance pas. Une seule question à la fois.
4. Si la question porte sur plusieurs entités, par exemple un nom qui désigne plusieurs choses distinctes,
   nomme-les toutes et dis l'essentiel de chacune en une phrase, au lieu de demander laquelle intéresse la personne.
5. Si la personne demande des détails, une liste ou une explication complète, donne-les : la brièveté vaut par
   défaut, jamais contre sa demande.
6. Texte simple : pas de titres, pas de séparateurs, pas d'astérisques ; une liste seulement si elle est demandée
   ou vraiment nécessaire.
7. Ponctuation simple, qui se lit bien à voix haute : n'emploie pas le tiret long (—) ni le tiret moyen (–) pour
   enchaîner ou encadrer une idée. Mets à la place une virgule, deux-points ou une nouvelle phrase, selon le sens."""

CHARTER_POPULAR = """RESTITUTION — tu t'adresses à un membre de la communauté ou à un visiteur, pas à un chercheur :
1. Pars de la personne et de ce qu'elle cherche à comprendre.
2. Emploie le vocabulaire de la vie courante, par exemple : {exemples}. Tu peux citer un terme du glossaire, une
   fois, en l'expliquant.
3. Tais la mécanique : jamais d'identifiant de bloc, de numéro de règle, de nom de liste, de classe ou de relation
   de l'ontologie dans le texte.
4. Si une information reste incertaine ou n'est pas encore validée, dis-le brièvement, une seule fois (par ex.
   « {incertitude} ») ; inutile de le répéter à chaque réponse.
5. N'ajoute rien que tu ne saches pas."""

CHARTER_SCHOLARLY = """RESTITUTION — ton interlocuteur est un spécialiste : tu peux employer le vocabulaire technique du
domaine, préciser le niveau de preuve et les conditions de validité d'une information. N'ajoute rien que tu ne
saches pas. Tu peux aller jusqu'à six phrases quand la précision l'exige."""

CITATION_RULE = """RENVOIS (techniques, invisibles pour l'usager) : après chaque phrase qui exprime un fait, ajoute entre doubles crochets les
identifiants des faits du dossier qui la fondent, par exemple [[R1]] ou [[REP:BGT_16,E3]]. Ces renvois sont retirés
avant l'affichage et servent à montrer les sources à l'usager. Les formules de politesse et les questions n'en ont
pas besoin. N'emploie que des identifiants présents dans le dossier."""


def charter_for(persona: str) -> str:
    if persona == "chercheur":
        return CHARTER_SCHOLARLY + "\n\n" + CONVERSATION_RULE + "\n\n" + CITATION_RULE
    restit = active_profile().raw.get("restitution", {})
    examples = restit.get("exemples") or ["des mots de tous les jours plutôt que les termes techniques de l'ontologie"]
    uncertainty = restit.get("incertitude") or "ce point n'a pas encore été vérifié par les experts du projet"
    return (CHARTER_POPULAR.replace("{exemples}", " ; ".join(examples)).replace("{incertitude}", uncertainty)
            + "\n\n" + CONVERSATION_RULE + "\n\n" + CITATION_RULE)


# ---------------------------------------------------------------------------
# Contrôle de sûreté (profils à risque élevé)
# ---------------------------------------------------------------------------
@dataclass
class SafetyResult:
    text: str
    removed: list[str]                                   # identifiants des contraintes déclenchées
    sentences: list[str] = field(default_factory=list)   # phrases retirées, pour le journal
    emptied: bool = False                                # tout le contenu informatif a été retiré


SAFETY_FALLBACK = ("Je ne peux pas vous répondre sous cette forme : ma réponse comportait des indications de dose "
                   "ou de traitement que je ne donne pas.")


def apply_safety(text: str) -> SafetyResult:
    """Retire de la restitution toute phrase qui enfreint une contrainte de sûreté du profil
    (motifs déclarés dans profile.json, clé « surete »), puis ajoute le message de sûreté du
    profil. La vérification est symbolique : elle ne dépend pas de la bonne volonté du modèle.
    Les phrases retirées sont renvoyées pour le journal. Si le retrait ne laisse aucune phrase
    informative (seulement une relance), la réponse est remplacée par une explication honnête,
    plutôt que par une question posée sans réponse."""
    patterns = active_profile().safety_patterns()
    if not patterns:
        return SafetyResult(text, [])
    removed: list[str] = []
    removed_sentences: list[str] = []
    kept_informative = 0
    out_paragraphs = []
    for para in text.split("\n"):
        kept = []
        for sent in split_sentences(para) if para.strip() else []:
            hit = [cid for cid, pat in patterns if pat.search(sent)]
            if hit:
                removed.extend(hit)
                removed_sentences.append(sent.strip())
                continue
            kept.append(sent)
            if not sent.strip().endswith("?"):
                kept_informative += 1
        out_paragraphs.append(" ".join(kept))
    if not removed:
        return SafetyResult(text, [])
    message = active_profile().safety.get("message", "")
    if kept_informative == 0:
        final = (SAFETY_FALLBACK + ("\n\n" + message if message else "")).strip()
        return SafetyResult(final, sorted(set(removed)), removed_sentences, emptied=True)
    final = "\n".join(out_paragraphs).strip()
    if message:
        final = (final + "\n\n" + message).strip()
    return SafetyResult(final, sorted(set(removed)), removed_sentences)


@dataclass
class Dossier:
    """Faits disponibles pour une réponse : identifiant -> libellé lisible (pour la liste des sources)."""
    facts: dict[str, str] = field(default_factory=dict)
    repertoire_blocks: set[str] = field(default_factory=set)

    def label(self, fid: str) -> str | None:
        if fid in self.facts:
            return self.facts[fid]
        if fid.startswith("REP:") and fid[4:] in self.repertoire_blocks:
            return f"Répertoire de terrain, bloc {fid[4:]}"
        return None


@dataclass
class RestitutionResult:
    text: str
    sources: list[dict]
    unknown_ids: list[str]
    unsupported_sentences: int
    sentences: int
    removed_sentences: int


def apply_citations(text: str, dossier: Dossier) -> RestitutionResult:
    sources: dict[str, str] = {}
    unknown: list[str] = []
    unsupported = removed = 0
    # Les paragraphes sont traités un par un pour conserver la mise en forme du texte.
    paragraphs = normalize_citations(text).split("\n")
    out_paragraphs = []
    total = 0
    for para in paragraphs:
        # Un renvoi placé juste après le point final est ramené avant lui, pour rester
        # attaché à sa phrase : « ... Bangangté. [[REP:BGT_16]] » -> « ... Bangangté [[REP:BGT_16]]. »
        para = re.sub(r"([.!?…])\s*((?:\[\[[^\[\]]+\]\]\s*)+)", lambda m: " " + m.group(2).strip() + m.group(1), para)
        if not para.strip():
            out_paragraphs.append(para)
            continue
        kept = []
        for sent in split_sentences(para):
            total += 1
            ids = []
            for m in CITE_RE.finditer(sent):
                ids.extend(x.strip() for x in m.group(1).split(",") if x.strip())
            clean = CITE_RE.sub("", sent).strip()
            valid = False
            for fid in ids:
                label = dossier.label(fid)
                if label:
                    sources.setdefault(fid, label)
                    valid = True
                else:
                    unknown.append(fid)
            if not valid and not clean.endswith("?"):
                unsupported += 1
                if RESTITUTION_STRICT and ids == [] and len(clean.split()) > 6:
                    removed += 1
                    continue
            kept.append(clean)
        out_paragraphs.append(" ".join(kept))
    final = "\n".join(out_paragraphs).strip()
    # Nettoyage d'éventuels renvois mal formés restés dans le texte.
    final = re.sub(r"\[\[[^\]]*\]\]", "", final)
    final = _LEFTOVER_RE.sub("", final).strip()
    return RestitutionResult(final, [{"id": k, "label": v} for k, v in sources.items()], unknown, unsupported, total, removed)


def log_anomalies(result: RestitutionResult) -> None:
    """Inscrit au journal les restitutions suspectes : renvois inconnus, ou majorité
    de phrases factuelles sans renvoi (au moins trois phrases)."""
    if result.unknown_ids or (result.sentences >= 3 and result.unsupported_sentences / result.sentences > 0.5):
        journal.append("controle_fidelite", "conversation", None, "systeme", {
            "unknown_ids": result.unknown_ids, "unsupported": result.unsupported_sentences,
            "sentences": result.sentences, "removed": result.removed_sentences,
        })
