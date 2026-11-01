# IAST-Builder : métamodèle du cadre neuro-symbolique collaboratif

Ce dossier formalise le cadre générique dont YobaKoko est une instance. Il comprend :

- `iast-builder-metamodele.ttl` : la méta-ontologie OWL, qui définit les concepts du cadre à deux niveaux.
  Le niveau du profil décrit ce qu'il faut déclarer pour instancier le cadre dans un domaine ;
  le niveau de l'exécution décrit les objets que le moteur manipule quel que soit le domaine.
- `iast-builder-invariants.ttl` : les invariants du cadre, exprimés en SHACL.

## Invariants

| Code | Énoncé | Vérification |
| --- | --- | --- |
| IP1 | Un profil utilise exactement une ontologie de domaine, qui déclare l'origine de son corpus de référence (terrain, documentaire ou mixte) et en cite les sources | SHACL, au chargement du profil |
| IP2 | Un profil désigne une autorité de validation, et une seule | SHACL, au chargement du profil |
| IP3 | Un profil déclare au moins une dimension de portée | SHACL, au chargement du profil |
| IP4 | Un profil déclare ses niveaux d'accès et fixe le niveau de diffusion de l'agent parmi eux | SHACL, au chargement du profil |
| IP5 | Un profil à risque élevé déclare au moins une contrainte de sûreté et au moins deux niveaux d'accès | SHACL, au chargement du profil |
| IP6 | Toute règle contrôlée, règle d'accès ou contrainte de sûreté est identifiée et décrite ; une contrainte de sûreté porte au moins un motif vérifiable | SHACL, au chargement du profil |
| IP7 | Tout composant neuronal est sans état : il n'est jamais ré-entraîné par ce qu'il traite | SHACL, au chargement du profil |
| IP8 | Un profil déclare, pour chacun des trois modes de collecte communautaire (témoignages, formulaire, lacunes), s'il est actif par défaut | SHACL, au chargement du profil |
| IE1 | Toute assertion validée procède d'une décision prise par un expert | SHACL, par l'audit |
| IE2 | Toute assertion porte sa provenance, son verdict et son niveau d'accès | SHACL, par l'audit |
| IE3 | Toute version de l'ontologie a un numéro et un motif, et désigne sa version précédente | SHACL, par l'audit |
| IE4 | Tout événement du journal nomme son acteur, son type et la version de l'ontologie en vigueur | SHACL, par l'audit |
| IE-C1 | Aucune assertion non validée, ni au-delà du niveau de diffusion de l'agent, n'entre dans le dossier de réponse | Par construction ; tests |
| IE-C2 | Aucun événement du journal ne peut être modifié ni supprimé | Par construction (déclencheurs SQL) ; tests |
| IE-C3 | Aucun réglage de la collecte ne modifie le circuit de validation ; tout changement de réglage est inscrit au journal avec son auteur | Par construction ; tests |
| IE-C4 | Un répertoire de données ne sert qu'un seul profil de domaine | Par construction (marque du répertoire, contrôle de l'ontologie présente) ; tests |
| IE-C5 | Un même fichier n'est importé qu'une fois avec une même correspondance ; l'annulation d'un lot ne laisse aucune de ses connaissances active, sans rien effacer du journal | Par construction ; tests |

## Outils

- `python -m app.profile_check <profil>` (depuis `brain/`) : conformité d'un profil aux invariants IP1 à IP8
  et cohérence de ses termes avec l'ontologie du domaine. Le service refuse de démarrer avec un profil non conforme.
- `python -m app.audit` ou `GET /api/admin/audit` : conformité de l'état du système aux invariants IE1 à IE4.

## Points de variation

Un profil de domaine (`brain/profiles/<id>/profile.json`) instancie les points de variation suivants :
identité et consignes de l'agent, ontologie initiale et espace de noms, dimensions de portée, règles
contrôlées, niveaux d'accès et règles d'accès, niveau de risque et contraintes de sûreté, relation de
variante et relation de désignation, glossaire, exemples de restitution, types de contributions,
textes et outils de l'interface, autorité de validation, modes de collecte communautaire actifs par défaut. Un profil peut ajouter des contraintes de
données propres au domaine (`formes.ttl`) et des correspondances de connecteurs (`correspondances/`).

## Instancier le cadre pour un nouveau domaine

1. Constituer l'ontologie initiale à partir d'un corpus de référence (collecte de terrain, pharmacopée, dictionnaire, répertoire), en JSON (schéma du projet) ou en OWL, et en déclarer l'origine et les sources dans le profil.
2. Créer `brain/profiles/<id>/profile.json` sur le modèle des profils `ndab` et `afripharm`.
3. Traduire en règles contrôlées les règles du domaine qui appellent l'examen d'un expert.
4. Déclarer les niveaux d'accès et, pour un domaine à risque élevé, les contraintes de sûreté.
5. Écrire les correspondances des sources de données disponibles.
6. Vérifier le profil : `python -m app.profile_check <id>`.
7. Démarrer avec `YOBAKOKO_PROFILE=<id>` et un répertoire de données propre (`YOBAKOKO_DATA_DIR`).

## Conditions de réutilisation

Le cadre convient à un savoir qui réunit les conditions suivantes : une autorité communautaire
identifiable et disposée à valider ; une variation légitime des connaissances selon des contextes
que l'on peut nommer (les dimensions de portée) ; un corpus de référence, de terrain ou documentaire,
pour constituer l'ontologie initiale ; une capacité d'examen des experts proportionnée au volume attendu des
contributions ; un cadre éthique de consentement et de partage des avantages. Il ne convient pas
à un savoir dont une restitution erronée aurait des conséquences immédiates graves sans qu'une
contrainte de sûreté vérifiable puisse les prévenir, ni à un domaine où la délibération experte
serait incompatible avec les délais d'usage.

## Collecte communautaire

Trois modes de collecte sont réglables séparément : le recueil des témoignages en conversation, le
formulaire de contribution et le signalement des lacunes aux experts. Le profil en déclare la valeur par
défaut (clé `collecte`) ; un expert peut les suspendre ou les rétablir dans l'onglet Contributions du
panneau d'administration, en indiquant un motif. Quand le recueil des témoignages est suspendu, l'agent
ne sollicite plus le savoir des usagers et n'annonce aucune transmission ; les signaux correspondants ne
sont pas transmis, seul leur type est journalisé. YobaKoko active les trois modes ; AfriPharm n'active que
le signalement des lacunes, le recueil de savoirs thérapeutiques auprès du public relevant du consentement
préalable prévu par le Protocole de Nagoya.
