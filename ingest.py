"""Partie 3a — Crée l'index `offres` avec un mapping explicite puis ingère le NDJSON en bulk.

Usage : python ingest.py [--fichier data/offres.ndjson] [--reset]
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from pathlib import Path

from elasticsearch import helpers

from es_client import INDEX, get_client

SETTINGS = {"number_of_shards": 1, "number_of_replicas": 0}

# TODO 1 : mapping validé à l'exercice 1.4
MAPPINGS = {
    "dynamic": "strict",
    "properties": {
        "id": {"type": "keyword"},
        "titre": {
            "type": "text",
            "analyzer": "french",
            "fields": {"brut": {"type": "keyword"}},
        },
        "entreprise": {"type": "keyword"},
        "description": {"type": "text", "analyzer": "french"},
        "competences": {
            "type": "keyword",
            "fields": {"texte": {"type": "text", "analyzer": "french"}},
        },
        "ville": {"type": "keyword"},
        "localisation": {"type": "geo_point"},
        "contrat": {"type": "keyword"},
        "teletravail": {"type": "keyword"},
        "experience_annees": {"type": "integer"},
        "salaire_min": {"type": "integer"},
        "salaire_max": {"type": "integer"},
        "date_publication": {"type": "date"},
    },
}


def lire_actions(fichier: Path) -> Iterator[dict]:
    """TODO 2 : générateur qui lit le fichier ligne à ligne et produit
    {"_index": INDEX, "_id": <id de l'offre>, "_source": <document>}."""
    # encoding="utf-8" : sans lui, Windows lit le fichier en cp1252 et corrompt les accents
    with fichier.open(encoding="utf-8") as f:
        for ligne in f:  # une ligne à la fois : la mémoire ne dépend pas de la taille du fichier
            ligne = ligne.strip()
            if not ligne:  # ignore les lignes vides (fin de fichier, par exemple)
                continue
            doc = json.loads(ligne)
            # _id fixé à partir de l'identifiant métier : relancer l'ingestion
            # remplace les documents au lieu de créer des doublons (idempotence)
            yield {"_index": INDEX, "_id": doc["id"], "_source": doc}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fichier", type=Path, default=Path("data/offres.ndjson"))
    parser.add_argument("--reset", action="store_true", help="supprime l'index s'il existe")
    args = parser.parse_args()

    es = get_client()
    print("Cluster :", es.info()["version"]["number"])

    # TODO 3 : si --reset, supprimer l'index (sans erreur s'il n'existe pas)
    if args.reset:
        es.indices.delete(index=INDEX, ignore_unavailable=True)
        print(f"Index '{INDEX}' supprimé (s'il existait)")

    # TODO 4 : créer l'index s'il n'existe pas, avec SETTINGS et MAPPINGS
    if not es.indices.exists(index=INDEX):
        es.indices.create(index=INDEX, settings=SETTINGS, mappings=MAPPINGS)
        print(f"Index '{INDEX}' créé")
    else:
        print(f"Index '{INDEX}' déjà présent, conservé")

    # TODO 5 : ingérer avec helpers.bulk (chunk_size=1000, raise_on_error=False), afficher les erreurs
    # raise_on_error=False : un document rejeté n'interrompt pas l'ingestion des autres ;
    # bulk renvoie alors (nombre de succès, liste des erreurs)
    nb_ok, erreurs = helpers.bulk(
        es,
        lire_actions(args.fichier),
        chunk_size=1000,
        raise_on_error=False,
    )
    print(f"{nb_ok} documents indexés, {len(erreurs)} erreurs")
    for err in erreurs[:10]:  # affiche au plus 10 erreurs pour garder une sortie lisible
        action, detail = next(iter(err.items()))
        cause = detail.get("error", {})
        print(f"  - {action} {detail.get('_id')} : {cause.get('type')} — {cause.get('reason')}")

    # TODO 6 : rafraîchir l'index puis afficher le nombre de documents (es.count)
    # refresh : rend visibles tout de suite les documents écrits, pour un comptage exact
    es.indices.refresh(index=INDEX)
    total = es.count(index=INDEX)["count"]
    print(f"{total} documents dans '{INDEX}'")


if __name__ == "__main__":
    main()
