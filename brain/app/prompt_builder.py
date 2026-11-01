"""app/prompt_builder.py — assemblage du prompt système : dossier de réponse et consignes.

Conception hybride, délibérée :
- l'ontologie (classes, règles d'attribution, répertoire) est de taille modeste et
  stable : elle entre en entier dans le dossier, comme vérité symbolique (ONT) ;
- les assertions validées par les experts (graphe des enrichissements) pertinentes
  pour la question entrent dans le dossier avec leur portée (E<n>) ;
- le corpus documentaire, volumineux, passe par la recherche par similarité :
  seuls les passages pertinents entrent dans le dossier (P<n>).

Ordre du prompt : identité et ton, DOSSIER DE RÉPONSE, règles de comportement,
charte de restitution (lissage), protocole de balises (émotion et signal), langue.

build_system_prompt renvoie aussi le Dossier (identifiants -> libellés), qui sert
au contrôle de fidélité et à la liste des sources montrée à l'usager.
"""
from __future__ import annotations

from . import enrichments, paraphrase, restitution, vectorstore
from .config import RETRIEVAL_TOP_K
from .ontology_loader import load_active, prompt_block
from .profile import active as active_profile
from . import crowdsourcing

def personas() -> dict:
    """Personnalités proposées par l'instance : celles que déclare le profil (clé « personnalites »),
    sinon les trois personnalités d'origine. Une personnalité ne change que le ton, jamais les faits."""
    declared = active_profile().raw.get("personnalites")
    if not declared:
        return PERSONAS
    return {k: {**PERSONAS.get(k, {}), **v} for k, v in declared.items()}


def default_persona() -> str:
    p = active_profile().raw.get("personnalite_par_defaut")
    available = personas()
    return p if p in available else next(iter(available))


PERSONAS = {
    "sage": {
        "label": "Sage du village",
        "label_en": "Village elder",
        "tone_fr": "Adopte le ton d'un sage de village bienveillant : chaleureux, patient, volontiers narratif, mais jamais approximatif sur les faits.",
    },
    "chercheur": {
        "label": "Chercheur",
        "label_en": "Researcher",
        "tone_fr": "Adopte un ton académique et précis, proche d'un chercheur qui présente ses résultats : structure claire, vocabulaire technique de l'ontologie assumé, peu d'effets de style.",
    },
    "guide": {
        "label": "Guide du musée",
        "label_en": "Museum guide",
        "tone_fr": "Adopte le ton d'un guide de musée accueillant un visiteur : phrases courtes, vocabulaire simple, toujours prêt à orienter vers la section suivante.",
    },
}

LANG_INSTRUCTIONS = {
    "fr": "Réponds en français, registre clair et respectueux.",
    "en": "Answer in English, clear and respectful register.",
}


def glossary_instruction() -> str | None:
    """Consigne pour la langue du glossaire déclarée par le profil (code « mb » dans l'interface)."""
    g = active_profile().glossary
    if not g or not g.get("langue"):
        return None
    langue, cle = g["langue"], g.get("cle", "glossaire")
    return (
        f"Réponds principalement en français. Chaque fois qu'un terme {langue} figure dans {cle}, "
        "utilise-le entre parenthèses à côté de sa traduction française. Ne traduis JAMAIS dans cette langue "
        "un mot absent du glossaire ; dis explicitement que ce mot n'est pas attesté et qu'une validation "
        "par un locuteur natif est nécessaire."
    )

BEHAVIOUR_RULES = """RÈGLES DE COMPORTEMENT :
1. Fonde chaque réponse sur le dossier de réponse ci-dessus, et sur lui seul.
2. N'invente jamais un fait absent du dossier, même si tu crois le connaître par ailleurs : pas de nom d'auteur
   d'une espèce, de famille, de synonyme, d'indication, de propriété, d'étude ou de référence qui n'y figure pas.
   Ne complète jamais avec tes connaissances générales. Un contenu en attente de validation n'existe pas pour toi.
   Ce que tu sais est complet pour toi : si une information manque, dis simplement que tu ne l'as pas, sans
   supposer ce qui pourrait exister ailleurs. Ne généralise jamais à partir des seules connaissances liées à la
   question : ne prétends pas qu'elles représentent tout ce que tu sais.
3. Si le dossier ne permet pas de répondre, dis-le simplement et émets un signal « lacune ».
4. Si l'usager affirme un fait contraire au dossier, ne l'adopte pas et ne le réfute pas : situe ta réponse
   (« à ma connaissance »), reconnais qu'il peut s'agir d'un usage local différent, annonce que
   son témoignage sera transmis aux experts du projet, et émets un signal « contradiction ».
5. Si l'usager affirme un fait nouveau, remercie-le, précise qu'il sera examiné par les experts avant d'être
   retenu, et émets un signal « nouveaute ».
6. Si une connaissance ne vaut que dans un contexte précis (une source, une région, une population), dis-le
   naturellement : « selon la monographie de l'OOAS », « au Sénégal », « chez l'enfant ».
7. Pour toute question hors du domaine ({domaine}), indique poliment que ce n'est pas ton domaine. Une question
   générale sur ton domaine (les entités ou les catégories que tu connais) en fait partie : réponds-y à
   partir de la vue d'ensemble.
8. Si la question porte sur une décision réelle (attribuer un nom, soigner une personne), oriente vers les experts
   humains du projet, en une phrase."""

RULE_4_COLLECT = """annonce que
   son témoignage sera transmis aux experts du projet, et émets un signal « contradiction »."""
RULE_4_NO_COLLECT = """et émets un
   signal « contradiction »."""
RULE_5_COLLECT = """5. Si l'usager affirme un fait nouveau, remercie-le, précise qu'il sera examiné par les experts avant d'être
   retenu, et émets un signal « nouveaute »."""
RULE_5_NO_COLLECT = """5. Si l'usager affirme un fait nouveau, ne l'adopte pas, remercie-le sans lui promettre de suite, et émets
   un signal « nouveaute »."""

TAG_PROTOCOL = """BALISES DE DÉBUT DE RÉPONSE — commence CHAQUE réponse par exactement deux lignes, avant tout texte :
[EMOTION:x] où x est l'une de : neutre, joyeux, pensif, solennel (joyeux pour un accueil ou une bonne nouvelle ;
pensif quand l'information est incomplète ou incertaine ; solennel pour un sujet sensible ou rituel ; neutre sinon).
[SIGNAL:none] — sauf dans l'un des quatre cas suivants, où tu écris [SIGNAL:type|question|hypothèse] :
  - lacune : la question ne trouve pas d'appui dans le dossier ;
  - contradiction : le DERNIER message de l'usager affirme un fait contraire au dossier ;
  - nouveaute : le DERNIER message de l'usager affirme un fait précis absent du dossier ;
  - ambiguite : les règles s'appliquent sans permettre de trancher.
  « question » est la question à poser aux experts du projet, formulée pour eux, en une phrase, sans nom de personne.
  « hypothèse » est le fait à vérifier en une phrase (ce que l'usager affirme, ou ta meilleure hypothèse), ou none.
  Exemple : {exemple_signal}
Ne mets jamais une simple question de l'usager dans une hypothèse. Ces balises sont retirées avant affichage :
n'en parle jamais dans le corps du texte."""


def build_system_prompt(lang: str, persona: str, user_text: str, context_text=()) -> tuple[str, restitution.Dossier]:
    """Construit le prompt système et le dossier de réponse.

    user_text    : dernier message de l'usager (recherche documentaire) ;
    context_text : messages précédents, du plus récent au plus ancien (sélection des assertions validées).
    """
    bundle = load_active()
    vocab = bundle.vocabulary
    profile = active_profile()
    available = personas()
    persona_def = available.get(persona) or available[default_persona()]
    dossier = restitution.Dossier(repertoire_blocks=set(vocab.repertoire_blocks))

    # Ontologie et règles
    dossier.facts["ONT"] = "Ontologie du projet IAST"
    for r in vocab.rules:
        short = r["id"].split("_")[0]
        dossier.facts[short] = f"Règle {short} de l'ontologie : {r.get('comment') or r.get('text')}"
    rule_ids = ", ".join(r["id"].split("_")[0] + " = " + r["id"] for r in vocab.rules)
    sections = [prompt_block(bundle)]
    if rule_ids:
        sections.append(f"Identifiants courts des règles : {rule_ids}.")

    # Vue d'ensemble de la base, pour les questions générales (« quelles espèces connais-tu ? »).
    overview = enrichments.inventory()
    if overview:
        lines = []
        for i, line in enumerate(overview, 1):
            fid = f"V{i}"
            dossier.facts[fid] = f"Vue d'ensemble : {line}"
            lines.append(f"[{fid}] {line}")
        sections.append("VUE D'ENSEMBLE DE CE QUE TU SAIS (pour les questions générales ; les détails figurent plus bas "
                        "ou te seront fournis quand la question portera sur une entité précise) :\n" + "\n".join(lines))

    # Corpus de référence du domaine, déclaré par le profil : l'agent peut orienter vers ces sources.
    corpus = profile.raw.get("ontologie", {}).get("corpus", [])
    if corpus:
        lines = []
        for i, ref in enumerate(corpus, 1):
            fid = f"C{i}"
            dossier.facts[fid] = f"Source de référence du domaine : {ref}"
            lines.append(f"[{fid}] {ref}")
        sections.append("SOURCES DE RÉFÉRENCE DU DOMAINE (tu peux y orienter la personne qui veut en savoir plus) :\n"
                        + "\n".join(lines))

    # Connaissances validées par les experts
    relevant = enrichments.relevant(user_text, context=context_text)
    if relevant:
        lines = []
        for i, a in enumerate(relevant, 1):
            fid = f"E{i}"
            text = paraphrase.assertion_text(a, vocab)
            dossier.facts[fid] = f"Connaissance validée par les experts : {text}"
            lines.append(f"[{fid}] {text}")
        sections.append("CONNAISSANCES VALIDÉES PAR LES EXPERTS (ce que tu sais ; une portée entre parenthèses "
                        "indique le contexte où la connaissance vaut) :\n" + "\n".join(lines))

    # Passages du corpus approuvé
    retrieved = vectorstore.query(user_text, RETRIEVAL_TOP_K) if user_text else []
    if retrieved:
        parts = []
        for i, r in enumerate(retrieved, 1):
            fid = f"P{i}"
            meta = r["metadata"]
            if meta.get("source_type") == "document":
                label = f"Document approuvé : {meta.get('filename')}"
            else:
                label = "Contribution communautaire approuvée"
            dossier.facts[fid] = label
            parts.append(f"[{fid}] {label}\n{r['text']}")
        sections.append("PASSAGES DU CORPUS APPROUVÉ (recherche par similarité) :\n\n" + "\n\n---\n\n".join(parts))

    agent = profile.agent
    # Consignes propres au domaine (profil) et contrainte de sûreté, s'il y en a une.
    domain_rules = list(agent.get("consignes", []))
    if profile.safety.get("consigne"):
        domain_rules.append(profile.safety["consigne"])
    rules = BEHAVIOUR_RULES.format(domaine=agent.get("domaine", "le savoir traité"))
    collecte = crowdsourcing.state()
    if not collecte["temoignages"]:
        # Recueil des témoignages désactivé : l'agent ne promet aucune transmission et ne sollicite rien.
        rules = rules.replace(RULE_4_COLLECT, RULE_4_NO_COLLECT).replace(RULE_5_COLLECT, RULE_5_NO_COLLECT)
        domain_rules.append("Le recueil des témoignages est suspendu : ne sollicite pas le savoir de l'usager, "
                            "ne l'invite pas à partager ce qu'il sait et ne lui dis pas que ses propos seront transmis aux experts.")
    if not collecte["formulaire"]:
        domain_rules.append("Le formulaire de contribution est fermé : ne propose pas à l'usager de soumettre une contribution ou un document.")
    domain_block = ("CONSIGNES PROPRES AU DOMAINE :\n" + "\n".join(f"- {c}" for c in domain_rules)) if domain_rules else ""
    lang_instruction = glossary_instruction() if lang == "mb" else None
    system = (
        f"{agent.get('identite', 'Tu es un agent conversationnel consacré à un savoir traditionnel.')} {persona_def['tone_fr']}\n\n"
        "DOSSIER DE RÉPONSE (chaque fait porte un identifiant entre crochets) :\n\n"
        + "\n\n".join(sections)
        + "\n\n" + rules
        + ("\n\n" + domain_block if domain_block else "")
        + "\n\n" + restitution.charter_for(persona)
        + "\n\n" + TAG_PROTOCOL.format(exemple_signal=agent.get("exemple_signal", "[SIGNAL:lacune|<question>|none]"))
        + "\n\n" + (lang_instruction or LANG_INSTRUCTIONS.get(lang, LANG_INSTRUCTIONS["fr"]))
    )
    return system, dossier
