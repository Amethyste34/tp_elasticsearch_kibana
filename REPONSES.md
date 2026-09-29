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
 
## Partie 3 — Recherche et analyseurs
 
### Exercice 3.1 — Voir travailler un analyseur
 
**Quels mots disparaissent avec `french` ?**
Avec l'analyseur `standard`, la phrase « Les développeuses travaillaient sur l'analyse des données » donne 7 tokens : `les`, `développeuses`, `travaillaient`, `sur`, `l'analyse`, `des`, `données`. Il découpe sur les espaces et met en minuscules, sans rien supprimer.
Avec `french`, il ne reste que 4 tokens : `developeu`, `travailaient`, `analys`, `done`. Les **mots vides** `les`, `sur` et `des` ont disparu : très fréquents en français, ils n'aident pas à distinguer les documents. Les positions sont conservées (1, 2, 4, 6) : les trous correspondent aux mots supprimés, ce qui permet encore les recherches de phrase (`match_phrase`).
Les mots restants sont aussi transformés par la **racinisation** : accents retirés, doubles lettres simplifiées, terminaisons coupées (`développeuses` → `developeu`, `travaillaient` → `travailaient`, `données` → `done`). Ces racines ne sont pas de vrais mots : ce sont des clés de comparaison.
 
**Que devient `l'analyse` ?**
- Avec `standard`, `l'analyse` reste un seul token, apostrophe comprise : une recherche sur « analyse » ne le retrouverait pas.
- Avec `french`, le filtre d'**élision** supprime `l'`, puis la racinisation réduit `analyse` à `analys`. « analyse », « analyses », « l'analyse » ou « d'analyse » donnent tous le même token.
**« donnée » et « données » donnent-ils le même terme avec chaque analyseur ? Conséquence pour la recherche ?**
- `standard` : deux tokens différents, `donnée` et `données`. Une recherche sur « donnée » ne trouve pas un document qui contient « données ».
- `french` : le même token `done` dans les deux cas. Singulier et pluriel correspondent.
Conséquence : le choix de l'analyseur détermine ce qu'une recherche retrouve. Pour un texte en français, l'analyseur `french` rend la recherche tolérante aux variations grammaticales (singulier/pluriel, féminin, élisions, accents) et ignore les mots vides qui n'apportent rien au score. C'est pourquoi j'ai déclaré `"analyzer": "french"` sur `titre`, `description` et `competences.texte` dans le mapping : l'analyseur est appliqué à l'indexation **et** à la question, donc les deux côtés sont réduits aux mêmes racines.
La contrepartie : la racinisation peut rapprocher des mots sans rapport qui ont la même racine, et elle ne convient pas aux identifiants ou codes exacts, qui restent en `keyword`.

 
### Exercice 3.2 — `match` contre `term`
 
**Pourquoi les deux requêtes `term` renvoient-elles 0 résultat ? Correction ?**
Une requête `term` ne passe pas par l'analyseur : elle cherche la valeur exacte, telle quelle, dans l'index inversé.
- `{"term": {"ville": "paris"}}` → 0 résultat. `ville` est un `keyword`, stocké exactement comme dans le document : `Paris`, avec une majuscule. La comparaison est sensible à la casse, donc `paris` ne correspond à rien.
  Correction : `{"term": {"ville": "Paris"}}` → **1 492 offres**.
- `{"term": {"titre": "Data Engineer Senior"}}` → 0 résultat. `titre` est un `text` analysé en `french` : l'index ne contient que des tokens en minuscules et réduits à leur racine, un par mot, jamais la phrase complète. Aucun token n'est égal à `Data Engineer Senior`.
  Correction : viser le sous-champ `keyword`, `{"term": {"titre.brut": "Data Engineer Senior"}}` → **103 offres**.
Règle : `term` sur les champs `keyword`, numériques ou dates (valeurs exactes) ; `match` sur les champs `text` (la question est analysée comme les documents).
 
**Effet de `"operator": "and"` sur le nombre de résultats ?**
- Par défaut, `match` sur « projets bancaires » cherche les tokens `projet` **OU** `bancair` : **4 190 résultats**. Presque toutes les descriptions contiennent « projets », donc la requête ramène la majorité de l'index ; les offres qui ont les deux mots sont simplement mieux classées (score plus élevé).
- Avec `"operator": "and"`, les deux tokens sont obligatoires : **393 résultats**, uniquement les offres qui parlent de projets bancaires.
`or` favorise le rappel (on ne rate rien, mais beaucoup de bruit) ; `and` favorise la précision (moins de résultats, plus pertinents). Entre les deux, `minimum_should_match` permet d'exiger un pourcentage des mots.

 
### Exercice 3.3 — Plusieurs champs, pondération et fautes de frappe
 
**Quel paramètre rattrape la faute ?**
`"fuzziness": "AUTO"`. Sans lui, la recherche « kubernetis terraform » sur `titre`, `competences.texte` et `description` renvoie **739 offres** : « kubernetis » ne correspond à aucun token de l'index, seul « terraform » trouve des résultats.
Avec `"fuzziness": "AUTO"`, on passe à **969 offres**. Elasticsearch accepte des termes proches, mesurés en distance d'édition (nombre de lettres à ajouter, supprimer, remplacer ou inverser). En mode `AUTO`, la tolérance dépend de la longueur du mot : 0 erreur jusqu'à 2 caractères, 1 erreur de 3 à 5, 2 erreurs au-delà. « kubernetis » (10 lettres) est à une seule substitution de « kubernetes » : il le retrouve, ce qui ajoute les 230 offres qui parlent de Kubernetes sans Terraform.
La contrepartie : la recherche floue est plus coûteuse, et elle peut rapprocher des mots différents mais proches à l'écrit.
 
**Comment évolue l'ordre des résultats avec le poids sur `titre` ?**
Le nombre de résultats ne change pas (**969** avec et sans `titre^3`) : un poids ne filtre rien, il multiplie seulement la contribution d'un champ au score, et donc modifie l'ordre.
Ici, l'effet est nul en pratique : le premier résultat est le même dans les deux cas (« Architecte Cloud Lead », compétences Kubernetes, Sécurité, Terraform). La raison : les titres du corpus sont des noms de métier (« Architecte Cloud Lead », « Ingénieur DevOps Senior »…) et ne contiennent jamais « kubernetes » ni « terraform ». Le champ `titre` n'apporte aucun point au score, et multiplier zéro par 3 donne toujours zéro. Les correspondances viennent de `competences.texte` et `description`.
Le poids `titre^3` aurait un effet visible sur une recherche dont les mots apparaissent dans les titres, par exemple « architecte cloud » : les offres dont le titre contient ces mots remonteraient devant celles qui ne les citent que dans la description. Par défaut, `multi_match` (type `best_fields`) retient le score du meilleur champ pour chaque document : c'est ce score que le poids amplifie.
 
### Exercice 3.4 — Requête `bool`
 
**Comparaison des `_score` avec et sans le bloc `should` ?**
Les deux requêtes renvoient **25 offres** : `should` ne change pas le nombre de résultats. Quand un `bool` contient déjà un `must` ou un `filter`, la clause `should` n'est pas obligatoire, elle n'ajoute qu'un bonus de score.
Les 25 offres sont toutes des « Administrateur Bases de Données » (CDI, Montpellier ou Toulouse, salaire max ≥ 50 000, télétravail partiel ou total) : le mot « données » est dans leur titre.
 
- **Sans `should`** : toutes les offres ont le même score, **2,048**. Il ne vient que du `must` (le `multi_match` sur « données ») ; comme leurs titres sont presque identiques, le score ne les distingue pas. À égalité, elles sortent dans l'ordre interne de l'index : des offres avec Elasticsearch (OFF-00024, OFF-00065) et sans (OFF-00041, OFF-00072) sont mélangées.
- **Avec `should`** : les offres qui ont `Elasticsearch` dans leurs compétences passent à **4,014**, soit 2,048 + environ 1,97 de bonus apporté par le `term` sur `competences`. Elles remontent toutes en tête ; les offres sans Elasticsearch restent à 2,048 et passent derrière.
Le `should` sert donc à classer, pas à filtrer : une offre sans Elasticsearch n'est pas exclue, elle est seulement moins bien placée.
 
**Pourquoi placer les critères exacts dans `filter` plutôt que dans `must` (deux raisons) ?**
1. **Pas de score parasite.** En contexte filtre, Elasticsearch répond seulement oui ou non, sans calculer de score. Si « CDI », « Toulouse » ou « salaire ≥ 50 000 » étaient dans `must`, ils ajouteraient des points au score alors qu'ils ne mesurent pas la pertinence : toutes les offres retenues les remplissent de la même façon. Le classement doit dépendre uniquement de la recherche texte (`must`) et des bonus voulus (`should`). Ici, le score sans `should` (2,048) vient uniquement de « données ».
2. **Performance et cache.** Sans calcul de score, un filtre est moins coûteux. Surtout, son résultat (la liste des documents qui vérifient `contrat = CDI`, par exemple) peut être mis en cache et réutilisé par les requêtes suivantes, ce qui est très utile pour des critères qui reviennent souvent, comme les facettes d'un moteur de recherche.

### Exercice 3.5 — Recherche géographique
 
*(Pas de question dans l'énoncé : observations.)*
 
- La requête renvoie **340 offres** à moins de 20 km de Montpellier (43.6108, 3.8767), toutes situées à Montpellier : aucune autre ville du corpus n'est dans ce rayon, et les localisations sont générées dans un rayon d'environ 5 km autour de chaque centre-ville.
- Les résultats sont triés de la plus proche à la plus lointaine. La valeur de `sort` donne la distance en kilomètres (`"unit": "km"`) : 0,19 km pour la première offre (Développeur Java Confirmé, Cévennes Data), puis 0,22 km, 0,32 km…
- `_score` et `max_score` valent `null` : le `geo_distance` est dans un `filter` (oui/non, pas de score) et le tri se fait sur la distance, pas sur la pertinence. Elasticsearch ne calcule donc aucun score.
- Cette recherche fonctionne parce que `localisation` est déclaré en `geo_point` dans le mapping : un simple objet `{lat, lon}` en mapping dynamique aurait été indexé comme deux nombres séparés, inutilisables pour une distance.
### Exercice 3.6 — Pagination et surlignage
 
**Pourquoi `from` + `size` est-il limité à 10 000, et quelle API utiliser au-delà ?**
Avec `from` et `size`, Elasticsearch ne sait pas « sauter » directement à la page demandée : pour afficher les résultats 9 990 à 10 000, chaque shard doit calculer et trier ses `from + size` meilleurs documents, puis le nœud qui coordonne la requête fusionne toutes ces listes et jette tout ce qui précède `from`. Le coût en mémoire et en CPU augmente avec la profondeur de la page, et il est multiplié par le nombre de shards. Pour protéger le cluster, le réglage `index.max_result_window` limite `from + size` à 10 000 par défaut ; au-delà, la requête est refusée.
De toute façon, un utilisateur ne parcourt jamais des milliers de pages : cette limite concerne surtout les traitements qui veulent parcourir tous les résultats.
 
Au-delà, on utilise **`search_after`** avec un **point in time (PIT)** :
- `POST offres/_pit?keep_alive=1m` crée un instantané figé de l'index : les pages restent cohérentes même si des documents sont ajoutés ou supprimés pendant le parcours ;
- chaque requête trie sur un critère stable et unique (par exemple le score puis un identifiant) et passe dans `search_after` les valeurs `sort` du dernier résultat de la page précédente ;
- Elasticsearch reprend juste après ce document, sans recalculer les pages précédentes : le coût reste constant quelle que soit la profondeur.
Inconvénient : on ne peut plus sauter directement à la page 50, on avance page après page (pagination « page suivante »), ce qui convient aux exports, aux traitements par lots et aux défilements infinis.

---
 
## Partie 4 — Agrégations
 
### Exercice 4.1 — Offres et salaire moyen par ville
 
**Quelle ville a le salaire moyen le plus élevé ?**
**Paris**, avec un `salaire_min` moyen de **57 442 €**, nettement devant Grenoble (53 046 €) et Nantes (52 125 €). Les autres villes se tiennent entre 50 000 et 52 000 €, et Nice est dernière (49 456 €). On retrouve la majoration des salaires parisiens annoncée dans la description du jeu de données.
 
**Sur combien d'offres la moyenne est-elle réellement calculée ?**
Pas sur `doc_count`. Une agrégation `avg` ignore les documents où le champ est absent ; or `salaire_min` n'existe pas pour les alternances, stages et freelances. J'ai ajouté une agrégation `value_count` sur `salaire_min`, qui compte les documents ayant une valeur :
- sur tout l'index : **3 389 offres** ont un salaire, sur 5 000 ;
- pour Paris : la moyenne porte sur **994 offres**, alors que `doc_count` en annonce 1 492 (498 offres parisiennes sans salaire) ;
- de même pour Grenoble, 65 sur 90, et pour Nice, 79 sur 111.
Un champ absent n'est pas un zéro : s'il valait 0, la moyenne serait fortement tirée vers le bas. C'est pour cela que le générateur omet le champ plutôt que de mettre 0 ou `null`.
 
**Erreur en remplaçant `ville` par `titre`, et correction ?**
Erreur **400**, `illegal_argument_exception` : « Fielddata is disabled on [titre] ». Un champ `text` n'est pas prévu pour les agrégations et les tris : l'index inversé associe chaque token aux documents, mais pas l'inverse (document → valeur). De plus, il ne contient que des tokens analysés (`administrateur`, `bas`, `done`…) : même en activant `fielddata`, on obtiendrait des paquets par mot et non par titre, avec un coût mémoire élevé.
Correction : agréger sur le sous-champ `keyword` **`titre.brut`**, déclaré dans le mapping exactement pour cela. Les paquets correspondent alors aux titres complets.
Remarque : avec le tri par salaire moyen décroissant, les premiers paquets sont les titres « (Alternance) » et « (Stage) », dont la moyenne vaut `null` (aucune offre avec salaire). Pour obtenir un classement utile, j'ai ajouté `"query": {"exists": {"field": "salaire_min"}}` afin de n'agréger que les offres qui ont un salaire. Le champ `doc_count_error_upper_bound: -1` signale aussi qu'un tri `terms` sur une sous-agrégation est approximatif : Elasticsearch ne garantit pas l'ordre exact quand il y a plus de paquets que `size`.

### Exercice 4.2 — Publications par mois

*(Pas de question dans l'énoncé : observations.)*

Le `date_histogram` mensuel sur `date_publication` donne 6 paquets, d'avril à septembre 2026 :

| Mois | Offres | dont CDI | Alternance | CDD | Freelance | Stage |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-04 | 763 | 443 | 114 | 76 | 92 | 38 |
| 2026-05 | 865 | 476 | 127 | 105 | 103 | 54 |
| 2026-06 | 820 | 461 | 125 | 102 | 94 | 38 |
| 2026-07 | 835 | 459 | 135 | 100 | 108 | 33 |
| 2026-08 | **880** | 476 | 134 | 119 | 108 | 43 |
| 2026-09 | 837 | 460 | 119 | 112 | 108 | 38 |

- Août est le mois le plus chargé (880 offres), avril le plus faible (763) ; la publication est globalement régulière, autour de 830 offres par mois. Le total fait bien 5 000.
- La ventilation par `contrat` se fait avec une agrégation `terms` imbriquée dans le `date_histogram` : chaque mois devient un paquet, redécoupé par type de contrat. Le CDI domine chaque mois (environ 55 %), puis l'alternance ; le stage reste le plus rare.
- `"format": "yyyy-MM"` rend la clé lisible (`key_as_string`) ; `key` reste la date en millisecondes depuis 1970, utile pour un programme.

### Exercice 4.3 — Tranches de salaire et statistiques

*(Pas de question dans l'énoncé : observations.)*

Agrégation `range` sur `salaire_min` :

| Tranche | Offres |
| --- | --- |
| < 40 k | 484 |
| 40–55 k | 1 363 |
| ≥ 55 k | 1 542 |

- Le total des tranches fait **3 389** : exactement le nombre d'offres qui ont un `salaire_min` (exercice 4.1). Les offres sans salaire n'entrent dans aucune tranche.
- Dans une `range`, `from` est inclus et `to` exclu : une offre à 40 000 € exactement tombe dans « 40–55 k », pas dans « < 40 k ». Les tranches ne se chevauchent donc pas.
- Près de la moitié des offres avec salaire (1 542) proposent au moins 55 000 € de salaire minimum.

Agrégation `stats` sur `experience_annees` : en une seule agrégation, on obtient **count 5 000**, **min 0**, **max 15**, **moyenne 5,9 ans**, somme 29 564. Toutes les offres ont ce champ (count = 5 000), contrairement au salaire.

### Exercice 4.4 — Requête + agrégation

J'ai sélectionné les offres avec `"match_phrase": {"titre": "Data Engineer"}` (les deux mots doivent se suivre dans le titre) : **462 offres**, tous niveaux et contrats confondus (y compris « Data Engineer (Alternance) » et « (Stage) »).

- **5 compétences les plus demandées** (agrégation `terms` sur `competences`, `size: 5`) : **Airflow** (315), **Spark** (313), **Kafka** (312), **Python** (311), **SQL** (301). Le cœur du métier : orchestration, traitement distribué, streaming, programmation et bases de données.
- **Télétravail le plus fréquent** (`terms` sur `teletravail`, `size: 1`) : **partiel**, pour 284 offres sur 462 (61 %) ; les 178 autres (`sum_other_doc_count`) se partagent entre `aucun` et `total`.

L'agrégation sur `competences` fonctionne directement parce que le champ est un `keyword` : chaque compétence de la liste est un paquet exact, sans passer par l'analyseur.

**L'agrégation porte-t-elle sur tout l'index ou sur les résultats de la requête ?**
Seulement sur les résultats de la requête. `hits.total.value` vaut **462**, et non 5 000 : les agrégations ont été calculées sur ces 462 offres « Data Engineer » uniquement. On le vérifie aussi avec les compétences : Airflow, Spark et Kafka sont spécifiques aux métiers de la donnée ; sur tout l'index, elles ne seraient pas forcément en tête (des compétences comme Linux ou Python, communes à plusieurs métiers, pèseraient davantage).
C'est le fonctionnement général : `query` sélectionne les documents, puis `aggs` calcule ses statistiques sur cette sélection, en un seul aller-retour. C'est ce qui permet les facettes d'un moteur de recherche : après une recherche, on affiche le nombre de résultats par ville ou par contrat pour cette recherche précise. Pour obtenir un chiffre sur tout l'index dans la même requête, il faudrait une agrégation `global`.
