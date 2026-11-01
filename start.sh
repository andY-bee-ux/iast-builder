#!/usr/bin/env bash
# start.sh — démarre une instance d'IAST-Builder : le brain (Python) et la gateway (Node), pour un profil donné.
#
# Usage :
#   ./start.sh                     profil par défaut : ndab (YobaKoko)
#   ./start.sh afripharm           instance AfriPharm
#   ./start.sh afripharm --port 3001
#                                  autre port pour la gateway (le brain prend ce port + 5000) ;
#                                  permet de faire tourner deux instances côte à côte
#   ./start.sh --liste             profils disponibles
#   ./start.sh --verifier <profil> vérifie un profil contre le métamodèle, sans démarrer
# Arrêt : Ctrl+C
#
# Chaque profil a ses propres données : brain/data pour ndab (compatibilité avec YobaKoko v3),
# brain/data_<profil> pour les autres. Au premier démarrage d'un profil, son ontologie initiale
# y est installée automatiquement.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
BOLD="\033[1m"; RED="\033[31m"; GREEN="\033[32m"; RESET="\033[0m"
PY="brain/.venv/bin/python"

for f in brain/.venv brain/.env gateway/dist gateway/.env; do
  [ -e "$f" ] || { echo -e "${RED}$f est introuvable. Lancez d'abord ./install.sh${RESET}"; exit 1; }
done

list_profiles() {
  echo -e "${BOLD}Profils disponibles :${RESET}"
  for dir in brain/profiles/*/; do
    id=$(basename "$dir")
    [ -f "$dir/profile.json" ] || continue
    desc=$($PY -c "import json,sys; d=json.load(open(sys.argv[1])); print(d.get('agent',{}).get('nom','?'), '—', d.get('nom',''))" "$dir/profile.json")
    echo "  $id    $desc"
  done
}

# ---------- Arguments ----------
PROFILE=""; GW_PORT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --liste|--list) list_profiles; exit 0 ;;
    --verifier|--check)
      [ -n "${2:-}" ] || { echo "Usage : ./start.sh --verifier <profil>"; exit 1; }
      (cd brain && .venv/bin/python -m app.profile_check "$2"); exit $? ;;
    --port) GW_PORT="${2:?Indiquez un numéro de port}"; shift ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    -*) echo -e "${RED}Option inconnue : $1${RESET}"; exit 1 ;;
    *) PROFILE="$1" ;;
  esac
  shift
done
PROFILE=${PROFILE:-ndab}
[ -f "brain/profiles/$PROFILE/profile.json" ] || { echo -e "${RED}Profil inconnu : $PROFILE${RESET}"; list_profiles; exit 1; }

GW_PORT=${GW_PORT:-$(grep -E '^PORT=' gateway/.env 2>/dev/null | cut -d= -f2- || true)}
GW_PORT=${GW_PORT:-3000}
BRAIN_PORT=$((GW_PORT + 5000))
if [ "$PROFILE" = "ndab" ]; then DATA="data"; UPLOADS="uploads"; else DATA="data_$PROFILE"; UPLOADS="uploads_$PROFILE"; fi
AGENT=$($PY -c "import json,sys; print(json.load(open(sys.argv[1])).get('agent',{}).get('nom','IAST-Builder'))" "brain/profiles/$PROFILE/profile.json")

# ---------- Vérification du profil ----------
echo -e "${BOLD}Vérification du profil $PROFILE...${RESET}"
(cd brain && .venv/bin/python -m app.profile_check "$PROFILE") || { echo -e "${RED}Profil non conforme : démarrage annulé.${RESET}"; exit 1; }

# ---------- Ports libres ----------
# Une instance restée active (fenêtre fermée sans Ctrl+C) occuperait les mêmes ports :
# la nouvelle instance ne pourrait pas démarrer et la passerelle répondrait avec l'ancienne.
for port in "$GW_PORT" "$BRAIN_PORT"; do
  if lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
    echo -e "${RED}Le port $port est déjà occupé, sans doute par une instance restée active.${RESET}"
    echo "  Pour l'arrêter : pkill -f \"uvicorn app.main\"; pkill -f \"node dist/server.js\""
    echo "  Ou lancez cette instance sur d'autres ports : ./start.sh $PROFILE --port $((GW_PORT + 1))"
    exit 1
  fi
done

# ---------- Démarrage ----------
mkdir -p logs
export YOBAKOKO_PROFILE="$PROFILE"
export YOBAKOKO_DATA_DIR="$SCRIPT_DIR/brain/$DATA"
export YOBAKOKO_UPLOAD_DIR="$SCRIPT_DIR/brain/$UPLOADS"
(cd brain && exec .venv/bin/uvicorn app.main:app --host "${BRAIN_HOST:-127.0.0.1}" --port "$BRAIN_PORT") > "logs/$PROFILE-brain.log" 2>&1 &
BRAIN_PID=$!
(cd gateway && PORT="$GW_PORT" BRAIN_URL="http://127.0.0.1:$BRAIN_PORT" exec node dist/server.js) > "logs/$PROFILE-gateway.log" 2>&1 &
GATEWAY_PID=$!
cleanup() { echo -e "\n${BOLD}Arrêt de l'instance $AGENT...${RESET}"; kill "$BRAIN_PID" "$GATEWAY_PID" 2>/dev/null || true; wait 2>/dev/null || true; echo "Arrêté."; }
trap cleanup INT TERM

# Attente du brain (le premier démarrage peut télécharger le modèle d'embeddings).
for _ in $(seq 1 60); do
  kill -0 "$BRAIN_PID" 2>/dev/null || break
  curl -s "http://127.0.0.1:$BRAIN_PORT/health" >/dev/null 2>&1 && break
  sleep 1
done
if ! kill -0 "$BRAIN_PID" 2>/dev/null; then echo -e "${RED}Le brain s'est arrêté au démarrage. logs/$PROFILE-brain.log :${RESET}"; tail -n 30 "logs/$PROFILE-brain.log"; kill "$GATEWAY_PID" 2>/dev/null || true; exit 1; fi
# Le service qui répond doit être celui du profil demandé.
SERVED=$(curl -s "http://127.0.0.1:$BRAIN_PORT/health" | sed -n 's/.*"profile": *"\([^"]*\)".*/\1/p')
if [ "$SERVED" != "$PROFILE" ]; then
  echo -e "${RED}Le service qui répond sur le port $BRAIN_PORT sert le profil « ${SERVED:-inconnu} » et non « $PROFILE ».${RESET}"
  kill "$BRAIN_PID" "$GATEWAY_PID" 2>/dev/null || true; exit 1
fi
if ! kill -0 "$GATEWAY_PID" 2>/dev/null; then echo -e "${RED}La gateway s'est arrêtée au démarrage. logs/$PROFILE-gateway.log :${RESET}"; tail -n 30 "logs/$PROFILE-gateway.log"; kill "$BRAIN_PID" 2>/dev/null || true; exit 1; fi

echo -e "${GREEN}${BOLD}$AGENT est démarré${RESET} ${BOLD}(IAST-Builder, profil $PROFILE).${RESET}
  Conversation   : http://localhost:$GW_PORT/
  Administration : http://localhost:$GW_PORT/admin.html
  Données        : brain/$DATA
  Journaux       : logs/$PROFILE-brain.log, logs/$PROFILE-gateway.log
  Arrêt          : Ctrl+C
"
wait "$BRAIN_PID" "$GATEWAY_PID"
