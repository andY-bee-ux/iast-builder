# IAST-Builder

IAST-Builder (*Intelligence artificielle et savoirs traditionnels*) is a neuro-symbolic framework for building
conversational agents that document traditional knowledge under community validation. A domain-independent
engine executes a declarative **domain profile** that conforms to a two-level **metamodel** (OWL meta-ontology
and SHACL invariants). This repository accompanies the article:

> Nkambou, R. *IAST-Builder: generalising a conversational agent into a neuro-symbolic metamodel for
> community-validated traditional knowledge.* Submitted to *Data & Knowledge Engineering*.

## Contents

| Path | Content |
| --- | --- |
| `brain/app/` | Engine (Python, FastAPI): extraction, formal validation, answer dossier, epistemic log, ontology evolution |
| `brain/app/profile_check.py` | Profile checker: invariants IP1 to IP8 and consistency with the domain ontology |
| `brain/app/audit.py` | Audit of the system state against invariants IE1 to IE4 |
| `brain/metamodele/` | Metamodel: OWL meta-ontology and SHACL shapes of the invariants |
| `brain/profiles/ndab/` | YobaKoko profile (Ndab praise names, Ndé, Cameroon) |
| `brain/profiles/afripharm/` | AfriPharm profile (West African pharmacopoeia) and its demonstration set |
| `brain/profiles/toponymie/` | Reference instance (customary toponymy, fictitious corpus) |
| `brain/tests/` | Four test suites: metamodel, ndab, afripharm, toponymie |
| `brain/evaluation/` | Code, data and results of the evaluation (Section 10 of the article), protocol of the future study |
| `gateway/` | Web interface and gateway (Node.js, TypeScript) |

## Installation

Requirements: Python 3.11 or later, Node.js 18 or later, and an Anthropic API key for the language model.

```bash
git clone https://github.com/nkambou/iast-builder.git
cd iast-builder
python3 -m venv venv && . venv/bin/activate
pip install -r brain/requirements.txt
(cd gateway && npm install && npm run build)
cp brain/.env.example brain/.env      # set ANTHROPIC_API_KEY
cp gateway/.env.example gateway/.env  # set ADMIN_PASSWORD
```

Start an instance (each profile uses its own data directory):

```bash
./start.sh afripharm --port 3001   # http://localhost:3001
./start.sh toponymie --port 3002   # http://localhost:3002
./start.sh ndab                    # http://localhost:3000 (field data not distributed, see below)
```

## Tests

```bash
cd brain && ./run_tests.sh
```

The tests replace the language model and the embedding model with test components, so they need neither a
network connection nor an API key.

## Reproducing the evaluation

All commands are run from `brain/`; none calls the language model. Results are written to
`brain/evaluation/resultats/`, which also contains the results reported in the article.

| Part of the article | Command |
| --- | --- |
| 10.1 Detection of faulty profiles (mutation analysis) | `python -m evaluation.mutation` |
| 10.2 Guarantees at execution (5 batches, seeds 1 to 5) | `python -m evaluation.proprietes <profile> 20 50 <seed>` then `python evaluation/agreger.py` |
| 10.2 Precision and recall of the safety filter | `python -m evaluation.surete evaluation/motifs_affines.json` |
| 10.3 Instantiation of a third domain | `python -m evaluation.instanciation_reference` |

The last command records the engine fingerprint at the beginning and at the end of the run, together with the
repository version, and reports whether the engine was modified. Details: `brain/evaluation/README.md`.

## Instantiating a new domain

1. Create `brain/profiles/<id>/` with an initial ontology (`ontologie_initiale.json`) derived from a reference
   corpus, a profile (`profile.json`) and, if needed, mappings for data sources (`correspondances/`).
   The toponymy profile is the smallest complete example.
2. Check the profile: `python -m app.profile_check <id>`. The messages name the invariant or the
   inconsistency to correct.
3. Start the instance: `./start.sh <id> --port <port>`.

The metamodel, the variation points and the conditions of reuse are described in `brain/metamodele/README.md`.

## Data

- **AfriPharm.** The demonstration set (`brain/profiles/afripharm/donnees/`) contains facts taken from the cited
  sources (names, parts, uses, precautions), without the text of the OOAS monographs or any dose value. It has
  not been validated by domain experts and is not a pharmacological knowledge base.
- **Toponymy.** The corpus is fictitious.
- **YobaKoko.** The field data of the Bangangté paramount chiefdom concern families and lineages and are not
  distributed. Access requires the agreement of the communities concerned and of the project partners. The
  test fixture `brain/tests/ndab/fixtures/repertoire_extrait.json` has the same structure but invented names.

## Licence

See `LICENSE`.

## Acknowledgements

IAST project (Artificial Intelligence and Traditional Knowledge), Université du Québec à Montréal and
Université de Dschang, with the support of the Fonds de recherche du Québec (FRQ) and the Agence universitaire
de la Francophonie (AUF).
