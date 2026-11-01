# Évaluation d'IAST-Builder

Trois volets, exécutables depuis `brain/` :

| Volet | Question | Commande | Résultats |
| --- | --- | --- | --- |
| 1 | La vérification de conformité détecte-t-elle les profils défectueux ? | `python -m evaluation.mutation` | `resultats/mutation.csv`, `mutation.json` |
| 2 | Les garanties tiennent-elles à l'exécution ? | `python -m evaluation.proprietes <profil> <séquences> <opérations> <graine>` puis `python evaluation/agreger.py` | `resultats/proprietes_*.json`, `proprietes_synthese.json` |
| 2 (sûreté) | Quels sont la précision et le rappel du filtre de sûreté ? | `python -m evaluation.surete evaluation/motifs_affines.json` | `resultats/surete.json` |
| 3 | Le cadre se réutilise-t-il dans un troisième domaine (toponymie coutumière) sans modification du moteur ? | `python evaluation/verifier_reference.py` (chaque passage du vérificateur), puis `python -m evaluation.instanciation_reference` | `resultats/instanciation_reference.json`, `instanciation_reference_verifications.jsonl` |
| Étude future | Quel effort l'instanciation demande-t-elle à des personnes qui découvrent le cadre ? (prévue après le déploiement de YobaKoko et d'AfriPharm) | Protocole : `etude/protocole.md` ; carnet : `python -m evaluation.etude.carnet` ; analyse : `python -m evaluation.etude.analyse` | `etude/resultats_*.{csv,md}` |

Les volets 1 et 2 n'appellent ni le modèle de langage ni un service externe. Les lots du volet 2 utilisés
dans l'article : 5 lots de 20 séquences de 50 opérations par profil, graines 1 à 5.
