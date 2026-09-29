"""Mini-défi — moteur de recherche d'offres en ligne de commande.

Attendu :
  python search.py "développeur python"
  python search.py "données spark" --ville Lyon --contrat CDI --salaire-min 45000
  python search.py "kubernetes" --autour "43.6108,3.8767" --rayon 50km --teletravail partiel
"""

from __future__ import annotations

import argparse

from es_client import INDEX, get_client

# Balises du surlignage : lisibles dans un terminal (au lieu de <em>...</em>)
DEBUT_SURLIGNE = "«"
FIN_SURLIGNE = "»"

# Elasticsearch refuse from + size au-delà de 10 000 (index.max_result_window)
MAX_RESULTATS = 10_000


def lire_point(autour: str) -> dict:
    """Convertit "43.6108,3.8767" en {"lat": 43.6108, "lon": 3.8767}."""
    try:
        lat, lon = (float(x) for x in autour.split(","))
    except ValueError:
        raise SystemExit(f'--autour attend "lat,lon" (ex. "43.6108,3.8767"), reçu : {autour!r}')
    return {"lat": lat, "lon": lon}


def construire_requete(args: argparse.Namespace) -> dict:
    """Requête bool
    - must   : multi_match sur titre (x3), competences.texte (x2), description, tolérant aux fautes
    - filter : ville, contrat, teletravail (term), salaire_max >= --salaire-min (range),
               distance autour d'un point (geo_distance) si --autour est fourni
    """
    # must : la recherche texte, la seule partie qui calcule le score
    must = [
        {
            "multi_match": {
                "query": args.texte,
                "fields": ["titre^3", "competences.texte^2", "description"],
                "fuzziness": "AUTO",  # rattrape les fautes de frappe (kubernetis -> kubernetes)
            }
        }
    ]

    # filter : critères exacts, oui/non, sans effet sur le score et mis en cache
    filtres = []
    if args.ville:
        filtres.append({"term": {"ville": args.ville}})
    if args.contrat:
        filtres.append({"term": {"contrat": args.contrat}})
    if args.teletravail:
        filtres.append({"term": {"teletravail": args.teletravail}})
    if args.salaire_min is not None:
        # offres dont le haut de la fourchette atteint le salaire souhaité ;
        # les offres sans salaire (alternance, stage, freelance) sont exclues
        filtres.append({"range": {"salaire_max": {"gte": args.salaire_min}}})
    if args.autour:
        filtres.append(
            {"geo_distance": {"distance": args.rayon, "localisation": lire_point(args.autour)}}
        )

    return {"bool": {"must": must, "filter": filtres}}


def formater_salaire(source: dict) -> str:
    """Fourchette de salaire, ou mention explicite quand le champ est absent."""
    if "salaire_min" not in source:
        return "salaire non communiqué"
    return f"{source['salaire_min']:,} – {source['salaire_max']:,} €".replace(",", " ")


def afficher_facette(nom: str, agg: dict) -> None:
    valeurs = ", ".join(f"{b['key']} ({b['doc_count']})" for b in agg["buckets"])
    print(f"  {nom:<12} {valeurs or '—'}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("texte")
    p.add_argument("--ville")
    p.add_argument("--contrat", choices=["CDI", "CDD", "Alternance", "Freelance", "Stage"])
    p.add_argument("--teletravail", choices=["aucun", "partiel", "total"])
    p.add_argument("--salaire-min", type=int)
    p.add_argument("--autour", help="lat,lon")
    p.add_argument("--rayon", default="30km")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--taille", type=int, default=10)
    args = p.parse_args()

    # Pagination : page 1 -> from 0, page 2 -> from taille, etc.
    if args.page < 1 or args.taille < 1:
        raise SystemExit("--page et --taille doivent être supérieurs ou égaux à 1")
    debut = (args.page - 1) * args.taille
    if debut + args.taille > MAX_RESULTATS:
        raise SystemExit(
            f"Pagination limitée à {MAX_RESULTATS} résultats (from + size) : "
            "au-delà, il faudrait search_after avec un point in time"
        )

    # Tri : pertinence d'abord ; avec --autour, la distance départage et s'affiche
    tri: list = ["_score"]
    if args.autour:
        tri.append(
            {"_geo_distance": {"localisation": lire_point(args.autour), "order": "asc", "unit": "km"}}
        )

    es = get_client()
    reponse = es.search(
        index=INDEX,
        query=construire_requete(args),
        from_=debut,
        size=args.taille,
        sort=tri,
        source=["titre", "entreprise", "ville", "contrat", "teletravail", "salaire_min", "salaire_max"],
        highlight={
            "pre_tags": [DEBUT_SURLIGNE],
            "post_tags": [FIN_SURLIGNE],
            # titre en plus de description : un mot trouvé seulement dans le titre
            # ne produirait sinon aucun extrait (constaté à l'exercice 3.6)
            "fields": {
                "description": {"fragment_size": 150, "number_of_fragments": 1},
                "titre": {"number_of_fragments": 0},  # 0 = le titre entier
            },
        },
        # Facettes : calculées sur les résultats de la recherche, pas sur tout l'index
        aggs={
            "villes": {"terms": {"field": "ville", "size": 12}},
            "contrats": {"terms": {"field": "contrat", "size": 5}},
            "competences": {"terms": {"field": "competences", "size": 10}},
        },
    )

    total = reponse["hits"]["total"]["value"]
    resultats = reponse["hits"]["hits"]
    nb_pages = max(1, -(-total // args.taille))  # division arrondie au supérieur

    print(f'\n{total} offre(s) pour « {args.texte} » — page {args.page}/{nb_pages}\n')
    if not resultats:
        print("Aucun résultat sur cette page.")

    for rang, hit in enumerate(resultats, start=debut + 1):
        src = hit["_source"]
        surligne = hit.get("highlight", {})
        titre = surligne.get("titre", [src["titre"]])[0]
        distance = f" — {hit['sort'][1]:.1f} km" if args.autour else ""

        print(f"{rang:>3}. [{hit['_score']:.2f}] {titre}")
        print(
            f"     {src['entreprise']} — {src['ville']}{distance} — {src['contrat']}"
            f" — télétravail {src['teletravail']} — {formater_salaire(src)}"
        )
        if "description" in surligne:
            print(f"     … {surligne['description'][0]} …")
        print()

    aggs = reponse["aggregations"]
    print("Facettes :")
    afficher_facette("Ville", aggs["villes"])
    afficher_facette("Contrat", aggs["contrats"])
    afficher_facette("Compétences", aggs["competences"])


if __name__ == "__main__":
    main()
