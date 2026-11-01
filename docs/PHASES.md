# YobaKoko v3 : guide technique des trois phases

Ce guide s'adresse à l'ingénieur qui ajuste ou étend le service brain. Chaque module Python commence par
une docstring qui explique son rôle ; ce document en donne la vue d'ensemble et les points d'entrée.

## 1. Principe directeur

L'agent n'apprend jamais seul. Toute connaissance nouvelle prend la forme d'une **assertion candidate**
(ou d'une **question d'investigation**), reçoit un **verdict formel** calculé par la couche symbolique, et
n'est visible de l'agent qu'après la **décision d'un expert**. Chaque étape est inscrite au **journal
épistémique**, qui refuse toute modification ou suppression.

## 2. Carte des modules (brain/app/)

| Module | Phase | Rôle |
| --- | --- | --- |
| `config.py` | toutes | Chemins, variables d'environnement, seuils |
| `db.py` | toutes | Schéma SQLite, migration des anciens JSON, déclencheurs d'ajout seul du journal |
| `journal.py` | 1 | Écriture et lecture du journal épistémique |
| `response_parser.py` | 1 | Balises `[EMOTION]`, `[SIGNAL]` (et `[MEMORY]` de la version précédente) |
| `investigations.py` | 1 | Signaux → questions d'investigation, regroupement, priorité, décisions, avis |
| `restitution.py` | 1 | Lissage : charte de restitution, renvois `[[...]]`, contrôle de fidélité, sources |
| `prompt_builder.py` | 1 | Dossier de réponse (ONT, R1…, REP:…, E1…, P1…) et prompt système |
| `ontology_loader.py` | 2, 3 | Ontologie active JSON/OWL, vue unifiée du vocabulaire, IRI, graphe RDFS |
| `validation.py` | 2 | Verdict : vocabulaire, SHACL (pySHACL), règles R2/R3, contradictions, questions du domaine |
| `assertions.py` | 2, 3 | Cycle de vie des assertions (pending → validated → retired…) |
| `extraction.py` | 2 | Extraction guidée par l'ontologie, rejet des citations absentes du passage |
| `paraphrase.py` | 2, 3 | Paraphrases par gabarits : ce que l'expert lit est ce qui est appliqué |
| `enrichments.py` | 3 | Graphe des enrichissements (`data/enrichments.ttl`, PROV-O), sélection pour le dossier |
| `connectors.py` | 3 | Correspondances déclaratives CSV/JSON, variantes, homonymies |
| `ontology_evolution.py` | 3 | Catalogue fermé d'opérations, formalisation par le LLM, application, versions, retour arrière |
| `vectorstore.py`, `extract_text.py`, `anthropic_client.py` | — | Recherche documentaire, extraction de texte, appels au LLM |

Routeurs (`brain/app/routers/`) : `chat.py`, `contribute.py`, `documents.py`, `admin.py` (contributions,
documents, ontologie active, statistiques), `questions.py` (phase 1), `knowledge.py` (assertions, connecteurs,
évolution, versions, enrichissements, journal).

## 3. Données (data/yobakoko.db)

| Table | Contenu |
| --- | --- |
| `contributions`, `documents` | Circuit de validation d'origine (migré des fichiers JSON) |
| `journal` | Événements horodatés, avec acteur, version de l'ontologie et charge utile JSON ; ajout seul |
| `questions`, `question_occurrences` | Questions d'investigation et extraits anonymisés de chaque signal |
| `opinions` | Avis motivés (pour, contre, réserve) sur une question, une assertion ou une évolution |
| `assertions` | Assertions candidates : énoncé, portée, provenance, verdict, statut, décision |
| `ontology_versions`, `ontology_changes` | Versions publiées (instantanés dans `data/ontology_versions/`) et propositions d'évolution |
| `import_batches` | Lots importés par les connecteurs, avec leur bilan |

Sauvegarder `brain/data/` (services arrêtés pour une copie cohérente) et `brain/uploads/` suffit à conserver
l'état complet du système.

## 4. Phase 1 en détail

**Protocole de balises.** Le modèle commence chaque réponse par :

```
[EMOTION:pensif]
[SIGNAL:contradiction|<question pour les experts>|<hypothèse ou none>]
```

Types de signal : `lacune`, `contradiction`, `nouveaute`, `ambiguite`. `routers/chat.py` transmet le signal à
`investigations.record_signal`, qui regroupe les signaux proches (cosinus d'embeddings ≥ `SIGNAL_SIMILARITY`,
ou Jaccard ≥ `SIGNAL_JACCARD` si le modèle d'embeddings est indisponible) et calcule la priorité :
`poids du type + occurrences + 2 × usagers distincts` (poids : contradiction 3, fait nouveau 2, ambiguïté 2,
lacune 1). Les usagers distincts sont comptés par une empreinte irréversible de l'identifiant aléatoire du
navigateur (`clientId`).

**Décision des experts.** L'expert rédige sa réponse en français ; `POST /api/admin/questions/{id}/formalize`
la traduit en assertions (paraphrase et verdict, rien n'est enregistré). `POST .../decide` avec
`outcome=validated` crée et valide les assertions retenues ; si l'une est en tension, la réponse est 409 avec
les « questions du domaine » à examiner, et l'expert confirme avec `confirmTension=true`.

**Lissage.** Le dossier de réponse attribue un identifiant à chaque fait ; le modèle place après chaque phrase
factuelle les identifiants qui la fondent (`[[R1,REP:BGT_16]]`). `restitution.apply_citations` vérifie les
renvois, les retire et renvoie la liste des sources à l'interface. Les anomalies (renvois inconnus, majorité
de phrases sans renvoi) sont inscrites au journal (`controle_fidelite`). `RESTITUTION_STRICT=true` retire en
outre les phrases factuelles sans renvoi.

## 5. Phase 2 en détail

**Extraction guidée** (`extraction.py`). Pour un document approuvé, bouton « Extraire les connaissances » :
le texte est découpé en passages de `EXTRACTION_CHUNK_SIZE` caractères ; pour chacun, le LLM reçoit la
description du vocabulaire (`ontology_loader.vocabulary_brief`) et produit des assertions avec citation exacte.
Une assertion dont la citation ne figure pas dans le passage est irrecevable. Les notions sans équivalent sont
enregistrées comme assertions `hors_ontologie`.

**Validation** (`validation.evaluate`), dans l'ordre :

1. Vocabulaire : prédicat et classes connus, sinon `hors_ontologie`.
2. SHACL : formes dérivées des domaines et co-domaines de l'ontologie ; les ancêtres des classes sont ajoutés
   au graphe de données. L'inférence RDFS est désactivée volontairement, car elle déduirait le type du sujet à
   partir du domaine du prédicat et neutraliserait le contrôle.
3. Règles : R2 (pas de Ndab ngon là' pour un garçon) et R3 (ligne de filiation), dans `RULE_CHECKS`.
4. Contradictions : même sujet et même prédicat qu'une assertion validée, objets disjoints selon
   `disjointures`, portées recouvrantes (`scopes_overlap`).

Pour ajouter une règle : écrire une fonction `(assertion, vocab) -> identifiant de règle | None` et l'ajouter
à `RULE_CHECKS`.

## 6. Phase 3 en détail

**Connecteurs.** Une correspondance (voir `brain/connectors/mappings/`) déclare les sujets (`field`, `column`
ou `from_list`), leurs faits (`predicate` + `field`/`column`/`value`), la portée et d'éventuels champs de texte
libre (`text_fields`, traités par l'extraction guidée). `repertoire_bangangte.json` importe le répertoire de
terrain ; `exemple_csv_ndab.json` montre le cas CSV. La classe d'une entité entre dans son IRI, pour qu'une même
forme désignant un lignage et un Ndab ne soit pas confondue ; le bilan d'import signale ces homonymies.

**Enrichissements.** `enrichments.rebuild()` régénère `data/enrichments.ttl` depuis la base à chaque
validation ou retrait : triplet direct et entité PROV-O (source, méthode, expert, date, portée).

**Évolution de l'ontologie.** Catalogue fermé (`ontology_evolution.OPERATIONS`) : `add_class`,
`add_object_property`, `add_data_property`, `add_rule`, `add_glossary_term`, `add_individual`,
`update_definition`, `add_disjointness`. Chaque opération a une traduction JSON et une traduction OWL, et une
paraphrase par gabarit. Flux : proposition en français → `formalize` (LLM) → vérification (`check_operations`)
→ paraphrase présentée → `create_change` → `apply_change` (nouvelle version, réévaluation des assertions en
attente) ou `reject_change`. `revert_change` annule la dernière évolution ; `restore_version` rétablit
n'importe quelle version en créant une nouvelle version.

Pour ajouter une opération : l'ajouter à `OPERATIONS`, à `paraphrase_op`, à `check_operations`, à `_apply_json`
et à `_apply_owl`, puis la décrire dans `FORMALIZE_SYSTEM`.

## 7. API ajoutée (préfixe /api, routes d'administration derrière la gateway)

| Méthode et chemin | Rôle |
| --- | --- |
| `POST /chat` | Réponse : `{text, emotion, sources, signal, memoryQueued}` ; corps : `messages, lang, persona, clientId` |
| `GET /admin/questions?status=open\|validated\|rejected\|all` | Questions d'investigation, par priorité |
| `GET /admin/questions/{id}` | Dossier : extraits, avis, assertions liées, décision |
| `POST /admin/questions/{id}/formalize` | `{answer}` → propositions d'assertions (rien n'est enregistré) |
| `POST /admin/questions/{id}/decide` | `{outcome, expert, notes, assertions, confirmTension}` ; 409 si tension |
| `POST /admin/questions/{id}/opinions` | `{expert, position, argument}` |
| `GET /admin/assertions?status=&verdict=&source=&batch=` | Assertions candidates |
| `POST /admin/assertions` | Assertion saisie par un expert |
| `POST /admin/assertions/{id}/decide` | `{decision: validated\|rejected\|deliberation, expert, notes, scope}` |
| `POST /admin/assertions/{id}/retire` | Retrait d'une connaissance validée |
| `POST /admin/documents/{id}/extract` | Extraction guidée (tâche de fond) |
| `GET /admin/connectors/presets`, `POST /admin/connectors/import`, `GET /admin/connectors/batches` | Connecteurs |
| `POST /admin/batches/{id}/validate-conforming` | Validation groupée des assertions conformes d'un lot |
| `POST /admin/ontology/changes/formalize`, `POST /admin/ontology/changes` | Traduction puis création d'une évolution |
| `POST /admin/ontology/changes/{id}/apply\|reject\|deliberate\|revert` | Décision sur une évolution |
| `GET /admin/ontology/versions`, `.../{v}/download`, `POST .../{v}/restore` | Versions |
| `GET /admin/enrichments.ttl` | Graphe des enrichissements |
| `GET /admin/journal`, `GET /admin/journal.jsonl` | Journal épistémique |
| `GET /admin/vocabulary` | Classes et prédicats de l'ontologie active |

## 8. Limites connues

- Un seul compte administrateur : le nom de l'expert saisi dans le panneau signe les décisions, sans
  authentification individuelle.
- Le contrôle de fidélité vérifie qu'une phrase s'appuie sur un fait du dossier, pas qu'elle en garde la nuance.
- La validation SHACL porte sur les domaines et co-domaines ; les règles d'attribution traduites en contrôles
  se limitent à R2 et R3.
- La détection des variantes repose sur la similarité des formes : elle propose, les experts décident.
- La formalisation par le LLM (réponses d'experts, évolutions) est vérifiée par le catalogue et les
  paraphrases, mais sa fidélité reste à mesurer auprès des experts.
