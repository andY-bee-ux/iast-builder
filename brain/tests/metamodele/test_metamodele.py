"""Conformité des profils au métamodèle IAST-Builder, sans démarrer le moteur."""
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app import profile_check  # noqa: E402
from app.profile import Profile, load_profile  # noqa: E402


def test_both_profiles_conform():
    assert profile_check.check("ndab") == []
    assert profile_check.check("afripharm") == []


def test_incomplete_profile_is_refused():
    p = load_profile("afripharm")
    raw = copy.deepcopy(p.raw)
    raw["surete"]["contraintes"] = []          # risque élevé sans contrainte de sûreté (IP5)
    raw["acces"]["niveau_diffusion_agent"] = "inconnu"   # niveau non déclaré (IP4)
    raw.pop("autorite")                        # pas d'autorité de validation (IP2)
    issues = profile_check.check_invariants(Profile("essai", raw, p.directory))
    assert any(i.startswith("IP2") for i in issues)
    assert any(i.startswith("IP4") for i in issues)
    assert any(i.startswith("IP5") for i in issues)


def test_inconsistent_profile_is_refused():
    p = load_profile("ndab")
    raw = copy.deepcopy(p.raw)
    raw["regles"][0]["si"]["predicat"] = ["predicatInexistant"]
    issues = profile_check.check_consistency(Profile("essai", raw, p.directory))
    assert any("predicatInexistant" in i for i in issues)


def test_ontology_must_declare_its_corpus():
    p = load_profile("afripharm")
    raw = copy.deepcopy(p.raw)
    raw["ontologie"].pop("corpus")
    raw["ontologie"]["origine"] = "inconnue"
    issues = profile_check.check_invariants(Profile("essai", raw, p.directory))
    assert sum(i.startswith("IP1") for i in issues) == 2


def test_profile_must_declare_collection_defaults():
    p = load_profile("ndab")
    raw = copy.deepcopy(p.raw)
    raw.pop("collecte")
    issues = profile_check.check_invariants(Profile("essai", raw, p.directory))
    assert sum(i.startswith("IP8") for i in issues) == 3


def test_data_directory_bound_to_its_profile(tmp_path):
    """Un répertoire de données rattaché à un profil refuse d'en servir un autre ; un répertoire
    ancien sans marque, contenant l'ontologie d'un autre domaine, est refusé lui aussi."""
    import json as _json
    import pytest
    from app import instance

    ndab, afri = load_profile("ndab"), load_profile("afripharm")
    ndab_classes = {c["id"] for c in _json.loads(ndab.ontology_file.read_text(encoding="utf-8"))["classes"]}
    d1 = tmp_path / "neuf"; d1.mkdir()
    assert instance.check_or_bind(afri, d1, None) == "rattache"
    assert instance.check_or_bind(afri, d1, None) == "verifie"
    with pytest.raises(instance.InstanceMismatch, match="appartient au profil « afripharm »"):
        instance.check_or_bind(ndab, d1, None)
    d2 = tmp_path / "ancien"; d2.mkdir()
    with pytest.raises(instance.InstanceMismatch, match="ne correspond pas au profil « afripharm »"):
        instance.check_or_bind(afri, d2, ndab_classes)
    d3 = tmp_path / "ancien_ndab"; d3.mkdir()
    assert instance.check_or_bind(ndab, d3, ndab_classes) == "marque_ajoutee"


def test_ontology_identifiers_must_be_iri_safe(tmp_path):
    """Un identifiant d'ontologie avec espace ou apostrophe est refusé avant le démarrage."""
    import json as _json, shutil
    p = load_profile("afripharm")
    d = tmp_path / "afripharm"; shutil.copytree(p.directory, d)
    onto = _json.loads((d / "ontologie_initiale.json").read_text(encoding="utf-8"))
    onto["individus_seed"].append({"id": "cours d'eau", "classe": "PartieDePlante", "label": "cours d'eau"})
    (d / "ontologie_initiale.json").write_text(_json.dumps(onto, ensure_ascii=False), encoding="utf-8")
    issues = profile_check.check_consistency(Profile("afripharm", p.raw, d))
    assert any("Identifiant de individu invalide : « cours d'eau »" in i for i in issues)
