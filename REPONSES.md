# TP Elasticsearch — Réponses aux questions
 
## Exercice 0 — Vérifier l'accès au cluster
 
**Les réponses sont-elles identiques d'un outil à l'autre ?**
Oui. Kibana Dev Tools et curl renvoient le même contenu (nœud `es01`, cluster `tp-eisi`, même `cluster_uuid`, version 9.5.4). Les deux outils interrogent la même API REST ; seule la mise en forme du JSON diffère légèrement.
 
**Quel code HTTP sans authentification, et que dit le message d'erreur ?**
Code **401** (non authentifié). Elasticsearch renvoie une `security_exception` : « missing authentication credentials for REST request [/] ».
Avec un mauvais mot de passe, le code est aussi 401 mais le message diffère : « unable to authenticate user [elastic] ». Dans le premier cas les identifiants manquent, dans le second ils sont faux.
 
**Pourquoi Kibana n'a-t-il pas besoin du mot de passe à chaque requête ?**
Je me suis connectée une fois à Kibana, qui conserve ma session. Kibana transmet lui-même mes identifiants à Elasticsearch pour chaque requête envoyée depuis Dev Tools.
 
---
 
## Partie 1 — Concepts, CRUD et mapping
 
### Exercice 1.1 — Explorer le cluster
 
**Quelle version tourne ?**
9.5.4 (champ `version.number` de `GET /`).
 
**Combien de nœuds ?**
Un seul nœud, `es01` (`GET _cat/nodes?v`). Il porte l'étoile dans la colonne `master` : c'est lui qui dirige le cluster. Sa colonne `node.role` (`cdfhilmrstw`) montre qu'il cumule tous les rôles (données, master, ingestion…), ce qui est normal pour un nœud unique de laboratoire.
 
**Pourquoi voit-on des index commençant par un point ?**
Ce sont des index système, créés automatiquement par Elasticsearch et Kibana pour leur propre fonctionnement : `.security-7` stocke les utilisateurs et les rôles, les index `.kibana_…` la configuration de Kibana, `.kibana_task_manager…` et `.internal.alerts…` les tâches de fond et les alertes. Ils sont masqués par défaut ; on ne les voit qu'avec `expand_wildcards=all`. Je n'ai encore créé aucun index à moi, donc toute la liste est interne.
Ils ont tous `rep 0` (aucune réplique), ce qui explique que le cluster soit vert avec un seul nœud.
 
### Exercice 1.2 — CRUD
 
**Comment évolue `_version` ?**
`_version` compte les écritures sur un même document :
- `PUT essai/_doc/1` → version 1, `result: created` (code 201) ;
- `POST essai/_update/1` → version 2, `result: updated` ; le `GET` suivant montre que le champ `contrat: CDI` a été ajouté sans effacer `titre` ni `ville` (mise à jour partielle, fusion des champs) ;
- `DELETE essai/_doc/1` → version 3, `result: deleted`. La suppression est elle aussi une écriture et incrémente la version.
Les lectures (`GET`) ne changent pas la version. En parallèle, `_seq_no` augmente de 1 à chaque écriture dans le shard, tous documents confondus (0, 1, 2, 3).
 
**Quel identifiant reçoit le document créé par `POST essai/_doc` ?**
Un identifiant aléatoire généré par Elasticsearch : `jXms7KABo-WI-xxS2rv6`. Avec `POST` sans id, Elasticsearch choisit l'`_id` ; avec `PUT index/_doc/<id>`, c'est moi qui le fixe.
 
**L'index `essai` existait-il avant le premier `PUT` ?**
Non. Il n'apparaissait pas dans `_cat/indices` à l'exercice 1.1. Elasticsearch l'a créé automatiquement au premier document reçu, avec un mapping déduit (dynamique) et les réglages par défaut.
Conséquence visible : `_shards.total` vaut 2 mais `successful` vaut 1. Par défaut un index a 1 réplique ; sur un nœud unique elle ne peut être placée nulle part, donc l'index `essai` (et le cluster) passent en jaune.

### Exercice 1.3 — Les pièges du mapping dynamique
 
**Quel type reçoit `salaire` ? Et `publication` ?**
`GET essai2/_mapping` montre que :
- `salaire` est de type `text`, avec un sous-champ `salaire.keyword` de type `keyword`. La valeur `"45000"` était entre guillemets : Elasticsearch a vu une chaîne, pas un nombre. C'est le traitement par défaut de toute chaîne en mapping dynamique (`text` pour la recherche + `keyword` pour le tri et les agrégations, ignoré au-delà de 256 caractères).
- `publication` est de type `date` : la détection automatique des dates a reconnu le format `AAAA-MM-JJ`, même entre guillemets.
- `actif` est de type `text` + `keyword`, et non `boolean` : Elasticsearch ne convertit pas la chaîne `"true"` en booléen.
La détection est donc incohérente : une chaîne qui ressemble à une date devient une date, mais une chaîne qui ressemble à un nombre ou à un booléen reste du texte.
 
**Pourquoi le document 2 est-il accepté ?**
Le type de `salaire` a été fixé à `text` par le premier document, et un type ne change plus ensuite. Quand le document 2 arrive avec le nombre `52000`, Elasticsearch le convertit en chaîne `"52000"` pour l'indexer dans le champ `text` : aucune erreur. Le `_source` garde bien `52000`, mais ce qui est indexé et interrogeable est du texte.
 
**Conséquence pour un tri ou un filtre `salaire > 50000` ?**
Les salaires sont comparés comme des chaînes, pas comme des nombres :
- un filtre `range` sur `salaire` (champ `text`) ne fait pas de comparaison numérique ; sur `salaire.keyword`, la comparaison est alphabétique, caractère par caractère : `"100000"` est plus petit que `"50000"` (parce que `1` < `5`), et `"9000"` plus grand que `"50000"` ;
- un tri donne donc un ordre faux, et une agrégation `avg` est impossible sur ce champ.
Pour corriger, il faut recréer l'index avec un mapping explicite (`salaire` en `integer`) puis réindexer les documents : c'est l'intérêt de déclarer le mapping dès la création (exercice 1.4).

### Exercice 1.4 — Mapping explicite de l'index `offres`
 
**Mes choix de types**
 
| Champ | Type | Pourquoi |
| --- | --- | --- |
| `id`, `entreprise`, `ville`, `contrat`, `teletravail` | `keyword` | Valeurs exactes : filtres et facettes |
| `titre` | `text` (analyseur `french`) + sous-champ `brut` en `keyword` | Recherche plein texte en français, et tri/facette sur la valeur brute |
| `description` | `text` (analyseur `french`) | Recherche plein texte uniquement |
| `competences` | `keyword` + sous-champ `texte` en `text` (`french`) | Chaque compétence est une étiquette exacte (filtre, facette), mais on veut aussi la retrouver en recherche plein texte. Un `keyword` accepte une liste sans déclaration particulière |
| `localisation` | `geo_point` | Recherche par distance |
| `experience_annees`, `salaire_min`, `salaire_max` | `integer` | Intervalles et moyennes : il faut une comparaison numérique (voir le piège de l'exercice 1.3) |
| `date_publication` | `date` | Filtres par date, histogramme mensuel |
 
Réglages de l'index : 1 shard, 0 réplique (nœud unique, l'index reste vert) et `"dynamic": "strict"`.
 
**Quelle erreur obtient-on avec `champ_inconnu` ?**
Code **400** (requête invalide), avec une `strict_dynamic_mapping_exception` : le mapping est en mode strict, l'ajout dynamique du champ `champ_inconnu` n'est pas autorisé. Le document est refusé en entier, rien n'est écrit dans l'index.
 
**Pourquoi est-ce une bonne pratique en production ?**
- **Qualité des données** : une faute de frappe dans un nom de champ (`vile` au lieu de `ville`) ou un champ inattendu envoyé par une application provoque une erreur visible tout de suite, au lieu de créer silencieusement un nouveau champ que personne n'interroge.
- **Pas de mauvais types devinés** : comme vu à l'exercice 1.3, le mapping dynamique peut choisir un type faux (un salaire en `text`), et ce type ne peut plus être changé sans recréer l'index et réindexer.
- **Maîtrise de la taille du mapping** : sans verrou, des données mal formées peuvent créer des centaines de champs (« explosion du mapping »), ce qui consomme de la mémoire et ralentit le cluster.
Le mapping devient un contrat : les documents doivent respecter le schéma déclaré, comme une table SQL.
 
---
 
## Partie 2 — Ingestion en Python
 
### Exercice 2.2 — Idempotence et identifiants
 
**Le nombre de documents a-t-il doublé ?**
Non. Après une première ingestion avec `--reset` (5 000 documents), j'ai relancé `python ingest.py` sans `--reset` : le script a conservé l'index existant, a de nouveau envoyé 5 000 documents sans erreur, et le comptage final est toujours **5 000**. Les documents ont été remplacés, pas ajoutés : l'ingestion est idempotente.
 
**Pourquoi fixer `_id` à partir du champ `id` est-il essentiel ?**
Dans `lire_actions()`, chaque action a `"_id": doc["id"]` (par exemple `OFF-00002`). L'action `index` du bulk fonctionne alors comme un `PUT offres/_doc/OFF-00002` : si un document avec cet `_id` existe déjà, il est remplacé (sa `_version` augmente), sinon il est créé. Un même identifiant métier donne donc toujours le même document dans l'index.
C'est ce qui permet de relancer le script sans risque : après une panne au milieu de l'ingestion, une correction des données source ou une mise à jour quotidienne, on réexécute simplement le script et l'index reflète la source, sans doublons.
 
**Que se passerait-il avec des identifiants générés par Elasticsearch ?**
Sans `_id` fourni, chaque document reçoit un identifiant aléatoire (comme `jXms7KABo-WI-xxS2rv6` à l'exercice 1.2). Elasticsearch ne peut pas savoir qu'une offre a déjà été indexée : chaque relance crée 5 000 nouveaux documents. Après deux exécutions, l'index contiendrait 10 000 documents, chaque offre en double ; les recherches afficheraient deux fois les mêmes résultats et les agrégations (comptages par ville, moyennes) seraient faussées. Il faudrait alors vider et recharger l'index à chaque fois.
 
### Exercice 2.3 — Provoquer une erreur de mapping
 
**Le lot entier est-il rejeté ou seulement ce document ?**
Seulement ce document. J'ai ajouté à la fin de `data/offres.ndjson` une offre `OFF-99999` avec un champ `"prime": 3000` absent du mapping, puis relancé `python ingest.py`. Sortie :
 
```
5000 documents indexés, 1 erreurs
  - index OFF-99999 : strict_dynamic_mapping_exception — mapping set to strict, dynamic introduction of [prime] within [_doc] is not allowed
5000 documents dans 'offres'
```
 
Le fichier contenait 5 001 lignes : les 5 000 offres valides ont été indexées, seule `OFF-99999` a été refusée à cause du mapping `strict`. Ce document faisait partie du dernier paquet de 1 000 (`chunk_size=1000`) ; les 999 autres documents de ce paquet sont bien passés. L'API `_bulk` n'est pas transactionnelle : elle renvoie un statut par opération, et un échec n'annule pas les autres.
 
**Intérêt de `raise_on_error=False` pour un pipeline ?**
Avec la valeur par défaut (`True`), `helpers.bulk` lève une exception `BulkIndexError` dès qu'un paquet contient une erreur : le script s'arrête, la suite du fichier n'est pas envoyée, et on ne sait pas facilement ce qui a été chargé ou non.
Avec `raise_on_error=False`, le pipeline va jusqu'au bout : un document mal formé parmi des milliers ne bloque pas l'ingestion des autres. `helpers.bulk` renvoie le nombre de succès et la liste détaillée des erreurs (identifiant du document, type et raison de l'erreur), que mon script affiche. On peut ensuite les journaliser, les mettre de côté pour correction et les réinjecter plus tard. Comme l'ingestion est idempotente, relancer après correction ne crée pas de doublons.
La contrepartie : il faut vérifier et surveiller ces erreurs, sinon des données peuvent manquer sans que personne ne s'en aperçoive.
 
---
