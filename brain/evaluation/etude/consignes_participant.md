# Étude d'instanciation d'IAST-Builder : consignes aux participants

Merci de participer à cette étude. Elle ne vous évalue pas : elle évalue l'outil, et en particulier
l'effort nécessaire pour l'adapter à un nouveau savoir traditionnel. Les difficultés que vous
rencontrerez sont précisément ce que nous cherchons à connaître.

## Votre tâche

Instancier IAST-Builder pour un troisième domaine, la **toponymie coutumière**, à partir du corpus
fourni (`corpus/toponymie_illustrative.json`, données fictives). À la fin, un agent conversationnel
consacré aux noms de lieux doit démarrer et accueillir l'import du corpus.

Vous disposez de la documentation (`brain/metamodele/README.md`) et des deux profils existants
(`brain/profiles/ndab` et `brain/profiles/afripharm`), que vous pouvez consulter et imiter.
**Vous ne devez pas modifier le code du moteur** (`brain/app/`, `gateway/`).

## Le carnet d'étude

Toute l'étude se déroule avec le carnet, ouvert dans votre navigateur :

```bash
cd iast-builder/brain
.venv/bin/python -m evaluation.etude.carnet
```

puis ouvrir http://localhost:3900. Le carnet enregistre automatiquement vos temps et vos
vérifications. Pour chaque étape : cliquez **Commencer**, travaillez, puis cliquez **Terminer**.
Vous pouvez faire une pause à tout moment. Le bouton **Vérifier mon profil** lance le vérificateur
du métamodèle ; utilisez-le aussi souvent que vous le souhaitez. Notez dans le carnet toute difficulté,
même brève, au moment où vous la rencontrez.

## Les étapes

1. **Prise en main.** Lire la documentation et parcourir les deux profils existants.
2. **Ontologie initiale.** Créer `brain/profiles/toponymie/ontologie_initiale.json` : les classes
   (lieu, nom de lieu, type de lieu, chefferie, informateur...) et les relations utiles, à partir du corpus.
3. **Profil.** Créer `brain/profiles/toponymie/profile.json` : agent, ontologie et corpus de référence,
   autorité de validation, dimensions de portée, niveaux d'accès, sûreté, collecte communautaire.
4. **Règles.** Déclarer au moins une règle contrôlée et une règle d'accès qui vous semblent pertinentes
   pour ce domaine (par exemple pour les bois sacrés).
5. **Correspondance.** Écrire la correspondance qui importe le corpus
   (`brain/profiles/toponymie/correspondances/`), avec la détection des variantes.
6. **Vérification et démarrage.** Obtenir un profil conforme, puis démarrer l'instance :
   `./start.sh toponymie --port 3002`.
7. **Import.** Dans le panneau d'administration (http://localhost:3002/admin.html), importer le corpus
   et examiner le bilan : variantes, homonymies ou polysémies, niveaux d'accès.

À la fin, remplissez le questionnaire du carnet (environ 10 minutes).
