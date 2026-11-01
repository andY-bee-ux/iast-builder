# Déployer IAST-Builder sur un serveur

Ce dossier contient de quoi passer du poste de travail (`./start.sh`) à un serveur Linux,
avec une instance par profil gérée par systemd et publiée derrière nginx.

## 1. Transférer le code et les données

```bash
# Depuis le poste de travail : le code, sans les environnements locaux.
rsync -av --exclude brain/.venv --exclude gateway/node_modules --exclude logs ./ serveur:/opt/iast-builder/
# Les données de chaque instance (base, versions de l'ontologie, documents), si elles existent déjà :
rsync -av brain/data/ serveur:/opt/iast-builder/brain/data/
rsync -av brain/data_afripharm/ serveur:/opt/iast-builder/brain/data_afripharm/
```

## 2. Installer sur le serveur

```bash
sudo useradd --system --home /opt/iast-builder iast
sudo chown -R iast: /opt/iast-builder
cd /opt/iast-builder && sudo -u iast ./install.sh --tests
```

Renseigner ensuite `brain/.env` (clé Anthropic) et `gateway/.env` (mot de passe d'administration).

## 3. Déclarer les instances

Un fichier par profil dans `/etc/iast-builder/`, sur le modèle de `instance.env.exemple` :

```bash
sudo mkdir -p /etc/iast-builder
sudo cp deploy/instance.env.exemple /etc/iast-builder/ndab.env        # ports 3000 / 8000
sudo cp deploy/instance.env.exemple /etc/iast-builder/afripharm.env   # à adapter : 3001 / 8001, data_afripharm
```

## 4. Démarrer avec systemd

```bash
sudo cp deploy/iast-brain@.service deploy/iast-gateway@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now iast-brain@ndab iast-gateway@ndab
sudo systemctl enable --now iast-brain@afripharm iast-gateway@afripharm
journalctl -u iast-brain@ndab -f      # journaux
```

## 5. Publier avec nginx

Adapter `nginx-iast-builder.conf` (noms de domaine, certificats), le copier dans
`/etc/nginx/sites-available/`, l'activer, puis `sudo nginx -t && sudo systemctl reload nginx`.
Seule la gateway est publiée ; le brain écoute sur 127.0.0.1 et refuse tout appel qui ne porte
pas le secret interne.

## Sauvegardes

Tout l'état d'une instance tient dans son répertoire de données (`brain/data` ou `brain/data_<profil>`) :
base SQLite (journal compris), versions de l'ontologie, index des documents, graphe des enrichissements.
Une copie régulière de ce répertoire suffit.
