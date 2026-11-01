#!/usr/bin/env bash
# Exécute les quatre suites de tests : métamodèle, YobaKoko, AfriPharm, toponymie (instance de référence). Chaque profil tourne dans son propre processus,
# car le profil actif est fixé pour la durée d'un processus.
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-.venv/bin/python}
$PY -m pytest -q tests/metamodele
$PY -m pytest -q tests/ndab
$PY -m pytest -q tests/afripharm
$PY -m pytest -q tests/toponymie
