"""Bonus TP2 — Tester la règle d'alerte « plus de 50 réponses 5xx en 5 minutes ».

Injecte 60 événements 503 datés de MAINTENANT dans le data stream logs-web-default,
pour que la règle (qui ne regarde que les 5 dernières minutes) puisse se déclencher.

Usage : python test_alerte.py            -> injecte 60 événements de test
        python test_alerte.py --nettoyer -> supprime les événements de test

Les événements portent l'étiquette "test_alerte" pour pouvoir les retrouver et les supprimer.
Ils sont datés d'aujourd'hui : ils n'apparaissent pas dans le tableau de bord réglé
sur la période du 23 au 30 septembre.
"""

import sys
from datetime import datetime, timezone

from elasticsearch import helpers

from es_client import get_client

DATA_STREAM = "logs-web-default"
NB_EVENEMENTS = 60

es = get_client()

if "--nettoyer" in sys.argv:
    # Suppression exceptionnelle dans un data stream : _delete_by_query est autorisé
    reponse = es.delete_by_query(
        index=DATA_STREAM,
        query={"term": {"tags": "test_alerte"}},
        refresh=True,
    )
    print(f"{reponse['deleted']} événements de test supprimés")
    sys.exit(0)

maintenant = datetime.now(timezone.utc).isoformat()

actions = [
    {
        "_op_type": "create",  # un data stream n'accepte que l'action create
        "_index": DATA_STREAM,
        "_source": {
            "@timestamp": maintenant,
            "source": {"address": "192.0.2.1"},
            "http": {
                "request": {"method": "GET"},
                "response": {"status_code": 503},
            },
            "url": {"original": "/api/offres?test=alerte"},
            "tags": ["test_alerte"],
        },
    }
    for _ in range(NB_EVENEMENTS)
]

succes, erreurs = helpers.bulk(es, actions, raise_on_error=False, refresh=True)
print(f"{succes} événements 503 injectés à {maintenant} ({len(erreurs)} erreurs)")
for e in erreurs[:3]:
    print("  -", e)
