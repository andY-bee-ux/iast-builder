# Protocole d'une étude future d'instanciation d'IAST-Builder auprès de nouveaux utilisateurs

Étude prévue après le déploiement de YobaKoko et d'AfriPharm, à un horizon d'un à deux ans. Le protocole et le carnet
d'étude sont prêts ; l'instanciation du même domaine par l'équipe du projet (evaluation/instanciation_reference.py)
en fournit le point de comparaison.

## 1. Objectif et questions

Mesurer l'effort nécessaire pour instancier IAST-Builder dans un nouveau domaine de savoir traditionnel,
par des personnes qui n'ont pas participé à son développement, en ne s'appuyant que sur la documentation
et les profils existants.

- **Q1. Coût.** Combien de temps faut-il pour obtenir une instance conforme et fonctionnelle, et quelles
  étapes concentrent l'effort ?
- **Q2. Guidage.** Les messages du vérificateur suffisent-ils à corriger un profil défectueux ? Combien
  d'allers-retours sont nécessaires avant la conformité ?
- **Q3. Généricité.** L'instanciation se fait-elle sans modifier le code du moteur ?
- **Q4. Utilisabilité perçue.** Comment les participants jugent-ils l'outil (score SUS) et ses choix de
  conception (items propres à l'étude) ?

## 2. Plan

Étude descriptive d'utilisabilité, à petit effectif (3 à 5 participants), chaque participant réalisant la
même tâche individuellement. Ce plan ne vise pas une inférence statistique ; il fournit des mesures
d'effort, des observations sur les obstacles et un retour qualitatif, ce qu'attend une évaluation
d'instanciation de cadre.

## 3. Participants

- **Nombre** : 3 à 5.
- **Critères d'inclusion** : formation de deuxième ou troisième cycle en informatique, en sciences de
  l'information ou dans une discipline voisine ; capacité à lire et modifier un fichier JSON.
- **Critère d'exclusion** : avoir contribué au développement d'IAST-Builder, de YobaKoko ou d'AfriPharm.
- **Recrutement** : invitation au sein du CRIA et des programmes de cycles supérieurs de l'UQAM.
- **Codes** : chaque participant reçoit un code (P01, P02...) ; aucun nom n'est enregistré par le carnet.

## 4. Éthique

L'étude fait intervenir des personnes : vérifier auprès du CIEREH si elle relève d'une modification du
certificat 2026-8058 ou d'une demande distincte, avant toute séance. Le formulaire d'information et de
consentement (section 10) est remis et signé avant la séance. La participation est volontaire ; le
participant peut se retirer à tout moment, et ses données sont alors supprimées. Les données sont
enregistrées sur le poste de l'étude, sous code, puis transférées sur un espace sécurisé de l'UQAM.

## 5. Matériel

- Un ordinateur par participant, avec IAST-Builder installé (`./install.sh`) et une clé API valide.
- Le corpus de la tâche : `brain/evaluation/etude/corpus/toponymie_illustrative.json` (données fictives
  de toponymie coutumière : variantes graphiques, homonymie entre un cours d'eau et un quartier, lieux
  sacrés à diffusion restreinte).
- La documentation : `brain/metamodele/README.md`, et les profils `ndab` et `afripharm` comme modèles.
- Les consignes : `brain/evaluation/etude/consignes_participant.md`.
- Le carnet d'étude : `.venv/bin/python -m evaluation.etude.carnet`, puis http://localhost:3900.

## 6. Déroulement (environ 3 heures au maximum)

1. **Accueil (10 min).** Présentation de l'étude, signature du consentement, attribution du code.
2. **Démarrage du carnet (5 min).** Le participant saisit son code et son profil (formation, expérience
   des ontologies, familiarité avec JSON).
3. **Tâche (150 min au maximum).** Les sept étapes des consignes : prise en main, ontologie initiale,
   profil, règles, correspondance, vérification et démarrage, import. Le participant chronomètre chaque
   étape dans le carnet, vérifie son profil autant qu'il le souhaite et note ses difficultés au fil de l'eau.
   L'animateur n'intervient que pour un blocage technique sans rapport avec la tâche (panne, réseau), et
   le consigne. Au-delà de 150 minutes, la séance s'arrête et l'état atteint est enregistré.
4. **Questionnaire (10 min).** Dans le carnet : SUS (10 items), six items propres à l'étude, trois questions ouvertes.
5. **Entretien (10 min, facultatif).** Retour libre sur les difficultés notées ; l'animateur prend des notes sous le code du participant.

## 7. Mesures

| Mesure | Recueil | Question |
| --- | --- | --- |
| Temps actif par étape et temps total | Carnet (début, pause, fin de chaque étape) | Q1 |
| Nombre de vérifications ; vérifications et temps avant le premier profil conforme | Carnet (bouton de vérification) | Q2 |
| Problèmes signalés, par invariant | Carnet (texte des messages du vérificateur) | Q2 |
| Intégrité du moteur | Empreinte du code au début et à la fin de la séance | Q3 |
| Taille de ce qui a été produit : lignes du profil, de l'ontologie, des correspondances ; classes, relations, dimensions, règles | Carnet (mesures finales) | Q1, Q3 |
| Réussite : instance démarrée, import réalisé | Observation de l'animateur, journal de l'instance | Q1 |
| Difficultés notées, par étape | Carnet | Q1, Q2 |
| Score SUS (0 à 100) | Questionnaire | Q4 |
| Items S1 à S6 (1 à 5) | Questionnaire | Q2, Q4 |
| Réponses ouvertes et entretien | Questionnaire, notes | Q1 à Q4 |

## 8. Analyse

- `python -m evaluation.etude.analyse` produit le tableau par participant (`resultats_participants.csv`)
  et la synthèse (`resultats_synthese.md`) : moyenne, médiane, minimum et maximum de chaque mesure.
- Le score SUS se lit au regard de la valeur de référence usuelle de 68 (Bangor et al., 2008).
- Les difficultés et les réponses ouvertes font l'objet d'un codage thématique par deux codeurs, qui
  rattachent chaque difficulté à une étape et à un élément du cadre (ontologie, portée, règles, accès,
  correspondances, documentation, messages du vérificateur).
- Point de comparaison : la taille de ce qui a été produit par chaque participant est rapportée à celle du
  moteur commun (environ 3 600 lignes, 33 modules) et à celle des profils de référence (YobaKoko, AfriPharm).

## 9. Menaces à la validité

- **Effectif réduit** : les résultats sont descriptifs et ne se généralisent pas statistiquement.
- **Corpus fictif** : la tâche reproduit des phénomènes réels de la toponymie coutumière, mais pas sa complexité ;
  l'étude mesure l'effort d'instanciation, non la qualité d'une ontologie de toponymie.
- **Profil des participants** : des étudiants de cycles supérieurs ne sont pas les futurs administrateurs d'une
  instance réelle ; leur familiarité avec l'informatique peut minorer l'effort.
- **Effet d'apprentissage par imitation** : les profils existants servent de modèles, ce qui correspond à l'usage
  attendu du cadre mais facilite la tâche.

## 10. Formulaire d'information et de consentement (modèle à adapter)

> **Titre de l'étude** : Évaluation de l'instanciation du cadre IAST-Builder pour un nouveau domaine de savoir traditionnel.
> **Chercheur responsable** : Roger Nkambou, Département d'informatique, UQAM.
>
> **Objectif.** Mesurer l'effort nécessaire pour adapter un outil logiciel à un nouveau domaine. C'est l'outil qui est évalué, non vous.
>
> **Ce que l'on vous demande.** Réaliser une tâche d'instanciation sur ordinateur (au plus 150 minutes), noter vos difficultés,
> puis remplir un questionnaire (10 minutes) et, si vous le souhaitez, participer à un court entretien (10 minutes).
>
> **Données recueillies.** Temps passé par étape, résultats des vérifications automatiques, difficultés notées, réponses au
> questionnaire, fichiers produits. Aucune donnée d'identification n'est enregistrée par l'outil : vous êtes désigné par un code.
>
> **Confidentialité.** Les données sont conservées sur un espace sécurisé de l'UQAM pendant [durée], puis détruites. Les résultats
> sont publiés sous forme agrégée, sans possibilité de vous identifier.
>
> **Participation volontaire.** Vous pouvez refuser de participer ou vous retirer à tout moment, sans avoir à vous justifier et sans
> conséquence ; vos données sont alors supprimées.
>
> **Risques et avantages.** Aucun risque prévisible au-delà de la fatigue liée à une tâche sur ordinateur. Vous contribuez à
> l'amélioration d'un outil destiné à la sauvegarde des savoirs traditionnels. [Compensation éventuelle.]
>
> **Contacts.** Chercheur responsable : [courriel]. Questions sur vos droits : Comité institutionnel d'éthique de la recherche avec des
> êtres humains (CIEREH) de l'UQAM, [coordonnées].
>
> Je déclare avoir lu ce formulaire, avoir obtenu des réponses à mes questions et accepter de participer.
> Code du participant : ______  Signature : ______  Date : ______

## Références

Bangor, A., Kortum, P. T. et Miller, J. T. (2008). An empirical evaluation of the System Usability Scale.
*International Journal of Human-Computer Interaction*, 24(6), 574–594.

Brooke, J. (1996). SUS: A quick and dirty usability scale. Dans P. W. Jordan et al. (dir.), *Usability Evaluation in Industry* (p. 189–194). Taylor & Francis.

Gronier, G. et Baudet, A. (2021). Psychometric evaluation of the F-SUS: Creation and validation of the French version of the
System Usability Scale. *International Journal of Human-Computer Interaction*, 37(16), 1571–1582.
