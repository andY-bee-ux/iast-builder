#!/usr/bin/env bash
# install.sh — installe IAST-Builder et ses instances (YobaKoko, AfriPharm) pour un lancement local
# (macOS, Linux, WSL). Le même script sert ensuite sur un serveur (voir deploy/README.md).
# Usage : ./install.sh            installation
#         ./install.sh --tests    installation, puis exécution des trois suites de tests
#
# Ce script :
#  1. choisit un Python 3.10 ou plus récent (python3.14 … python3.10, puis python3) ;
#  2. crée brain/.venv avec ce Python (et remplace un environnement trop ancien) ;
#  3. installe les dépendances des deux services et compile la gateway ;
#  4. crée les fichiers .env et y synchronise un secret interne aléatoire ;
#  5. vérifie chaque profil de domaine contre le métamodèle IAST-Builder.
# Il ne choisit PAS à votre place la clé API Anthropic ni le mot de passe administrateur.

set -euo pipefail
RUN_TESTS=0
[ "${1:-}" = "--tests" ] && RUN_TESTS=1
BOLD="\033[1m"; GREEN="\033[32m"; YELLOW="\033[33m"; RED="\033[31m"; RESET="\033[0m"
step() { echo -e "\n${BOLD}==> $1${RESET}"; }
ok()   { echo -e "${GREEN}✓${RESET} $1"; }
warn() { echo -e "${YELLOW}!${RESET} $1"; }
fail() { echo -e "${RED}✗ $1${RESET}"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ---------- 0. Prérequis ----------
step "Vérification des prérequis"
version_ok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; }
PYTHON=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && version_ok "$candidate"; then PYTHON="$candidate"; break; fi
done
[ -n "$PYTHON" ] || fail "Aucun Python 3.10 ou plus récent n'a été trouvé (le Python fourni par macOS est en 3.9).
  Installez Python 3.12 depuis python.org ou avec « brew install python@3.12 », puis relancez ./install.sh."
ok "Python retenu : $PYTHON ($($PYTHON --version))"
command -v node >/dev/null 2>&1 || fail "node est introuvable. Installez Node.js 18 ou plus récent."
ok "node trouvé ($(node -v))"
command -v npm >/dev/null 2>&1 || fail "npm est introuvable (il est normalement fourni avec Node.js)."

# ---------- 1. Secret interne ----------
step "Génération du secret interne partagé (gateway <-> brain)"
if command -v openssl >/dev/null 2>&1; then SECRET=$(openssl rand -hex 24); else SECRET=$($PYTHON -c "import secrets; print(secrets.token_hex(24))"); fi
ok "Secret généré"

# ---------- 2. Service brain ----------
step "Installation du service brain (Python)"
cd "$SCRIPT_DIR/brain"
if [ -d ".venv" ] && ! version_ok ".venv/bin/python"; then
  warn "brain/.venv utilise un Python trop ancien : il est renommé en .venv.ancien et recréé."
  rm -rf .venv.ancien && mv .venv .venv.ancien
fi
if [ ! -d ".venv" ]; then "$PYTHON" -m venv .venv; ok "Environnement virtuel créé (brain/.venv)"; else ok "Environnement virtuel existant réutilisé"; fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
deactivate
ok "Dépendances Python installées"

[ -f ".env" ] || { cp .env.example .env; ok "brain/.env créé"; }
CURRENT=$(grep '^INTERNAL_SECRET=' .env | cut -d= -f2- || true)
if [ -z "$CURRENT" ] || [ "$CURRENT" = "change-me-to-a-random-string" ]; then
  if grep -q '^INTERNAL_SECRET=' .env; then sed -i.bak "s|^INTERNAL_SECRET=.*|INTERNAL_SECRET=${SECRET}|" .env && rm -f .env.bak
  else echo "INTERNAL_SECRET=${SECRET}" >> .env; fi
  ok "INTERNAL_SECRET renseigné dans brain/.env"
else
  SECRET="$CURRENT"; warn "INTERNAL_SECRET déjà personnalisé dans brain/.env : conservé"
fi

# ---------- 3. Gateway ----------
step "Installation de la gateway (Node/TypeScript)"
cd "$SCRIPT_DIR/gateway"
npm install --silent
npm run build --silent
ok "Gateway compilée (gateway/dist/)"
[ -f ".env" ] || { cp .env.example .env; ok "gateway/.env créé"; }
if grep -q '^INTERNAL_SECRET=' .env; then sed -i.bak "s|^INTERNAL_SECRET=.*|INTERNAL_SECRET=${SECRET}|" .env && rm -f .env.bak
else echo "INTERNAL_SECRET=${SECRET}" >> .env; fi
ok "INTERNAL_SECRET synchronisé dans gateway/.env"

# ---------- 4. Profils de domaine ----------
step "Vérification des profils de domaine (métamodèle IAST-Builder)"
cd "$SCRIPT_DIR/brain"
for dir in profiles/*/; do
  id=$(basename "$dir")
  [ -f "$dir/profile.json" ] || continue
  if .venv/bin/python -m app.profile_check "$id" >/tmp/iab_check_$$.txt 2>&1; then
    ok "Profil $id conforme"
  else
    warn "Profil $id non conforme :"; cat /tmp/iab_check_$$.txt
  fi
done
rm -f /tmp/iab_check_$$.txt

# ---------- 5. Tests (facultatif) ----------
if [ "$RUN_TESTS" = "1" ]; then
  step "Exécution des tests"
  .venv/bin/pip install --quiet -r requirements-dev.txt
  PYTHON=.venv/bin/python ./run_tests.sh
fi

# ---------- 6. Résumé ----------
echo -e "\n${BOLD}${GREEN}Installation terminée.${RESET}"
echo -e "Renseignez encore :\n  1. ${BOLD}brain/.env${RESET}   → ANTHROPIC_API_KEY (clé créée dans un espace de travail de la console Anthropic)"
echo -e "  2. ${BOLD}gateway/.env${RESET} → ADMIN_PASSWORD"
echo -e "\nPuis démarrez une instance :"
echo -e "  ${BOLD}./start.sh${RESET}               YobaKoko (profil ndab, par défaut)"
echo -e "  ${BOLD}./start.sh afripharm${RESET}     AfriPharm"
echo -e "  ${BOLD}./start.sh --liste${RESET}       profils disponibles"
