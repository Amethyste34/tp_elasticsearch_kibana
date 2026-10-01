# TP2 — Ingestion et analyse de logs avec Logstash : réponses
 
Suite du TP « Introduction à Elasticsearch », branche `tp2`.
Stack : Elasticsearch, Kibana et Logstash 9.5.4 sous Docker Compose.
 
## Mise en place
 
Le kit a été copié à la racine du dépôt : `docker-compose.override.yml` à côté de `docker-compose.yml`, dossier `logstash/` (configuration et pipelines), `data/generate_access_logs.py`.
 
Avant de commencer, l'index `offres` a dû être recréé avec `python ingest.py` (les données du cluster avaient été réinitialisées). Vérification : `GET offres/_count` renvoie 5 000 documents, et le mapping est bien en `"dynamic": "strict"`.
 
Un rôle `logstash_writer` et un utilisateur `logstash_internal` ont été créés (requêtes dans `requetes/logstash.txt`). Le mot de passe est stocké uniquement dans `.env`, ignoré par Git.
 
Vérifications du compte :
 
- `GET _security/_authenticate` avec `logstash_internal` renvoie bien l'utilisateur, son rôle `logstash_writer` et `"enabled": true` : l'authentification fonctionne.
- `GET offres/_count` avec ce même compte renvoie une **erreur 403** (`security_exception`, action `indices:data/read/search` non autorisée). Ce n'est pas une erreur 401 : l'utilisateur est reconnu, mais il n'a pas le droit de lire. Le rôle n'accorde que l'écriture, ce qui est voulu.
Le service `logstash` est rattaché au profil Compose `logstash` (`profiles: ["logstash"]`) : `docker compose up -d` ne le démarre pas, il faut le nommer explicitement (`docker compose up -d logstash`). Cela permet de garder la stack du TP d'introduction inchangée par défaut.
 
**Pourquoi ne pas utiliser le compte `elastic` pour Logstash ?**
 
`elastic` est le superutilisateur du cluster : il peut tout faire, y compris supprimer des index, créer des utilisateurs ou modifier la sécurité. Si ses identifiants fuitaient (fichier de configuration, journal, conteneur compromis), l'attaquant aurait le contrôle total du cluster.
 
Le compte `logstash_internal` applique le **principe du moindre privilège** : il ne peut qu'écrire dans `offres` et `logs-web-*`, superviser le cluster et gérer les modèles d'index. Le test ci-dessus le montre : même avec ses identifiants, on ne peut pas lire le contenu de l'index `offres`.
 
Autres avantages : on peut désactiver ou changer le mot de passe de ce compte sans impacter les autres usages, et les journaux d'audit identifient clairement les actions faites par Logstash.
 
**Que se passerait-il si le pipeline `web` tentait d'écrire dans `logs-generic-default` ?**
 
L'écriture serait **refusée par Elasticsearch avec une erreur 403** : le rôle `logstash_writer` n'a de privilèges que sur `offres` et sur le motif `logs-web-*`, auquel `logs-generic-default` ne correspond pas. Les événements ne seraient pas indexés.
 
C'est un garde-fou utile : une erreur de configuration dans un pipeline ne peut pas aller écrire dans d'autres index ou data streams.
 
**Pourquoi le mot de passe est-il transmis par variable d'environnement plutôt qu'écrit dans les fichiers `.conf` ?**
 
Les fichiers `.conf` sont **versionnés dans Git** : un mot de passe écrit dedans serait publié sur GitHub, et il resterait dans l'historique des commits même après avoir été retiré du fichier.
 
Le fichier `.env` est ignoré par Git. Docker Compose y lit `LOGSTASH_INTERNAL_PASSWORD` et le transmet au conteneur, et les pipelines y font référence avec `${LOGSTASH_INTERNAL_PASSWORD}`. Le secret reste ainsi **hors du code**.
 
Cela permet aussi d'utiliser un mot de passe différent selon l'environnement (poste de développement, recette, production) sans modifier les fichiers de configuration.
 
## Exercice 0 — Premier pipeline
 
Pipeline lancé : `input { stdin { } } output { stdout { codec => rubydebug } }`. Événement obtenu en tapant « Bonjour Logstash » :
 
```ruby
{
         "event" => { "original" => "Bonjour Logstash" },
    "@timestamp" => 2026-10-01T09:17:00.948702944Z,
          "host" => { "hostname" => "e44cdd9f6b84" },
      "@version" => "1",
       "message" => "Bonjour Logstash"
}
```
 
Avec le filtre `mutate { uppercase => ["message"] }`, en tapant « salut logstash » :
 
```ruby
{
    "@timestamp" => 2026-10-01T09:20:55.401854591Z,
          "host" => { "hostname" => "6432512eb8c1" },
         "event" => { "original" => "salut logstash" },
      "@version" => "1",
       "message" => "SALUT LOGSTASH"
}
```
 
Le filtre a modifié `message`, mais **pas `event.original`** : ce champ conserve le texte brut tel qu'il a été reçu, ce qui permet de retrouver la donnée d'origine quelles que soient les transformations appliquées ensuite. On remarque aussi que `host.hostname` a changé entre les deux essais : chaque `docker compose run --rm` crée un nouveau conteneur, avec un nouvel identifiant.
 
**Quels champs Logstash a-t-il ajoutés à votre phrase ?**
 
Seul le texte a été saisi ; Logstash l'a placé dans `message` et a ajouté :
 
- `@timestamp` : la date et l'heure de l'événement, présent sur tout événement Logstash ;
- `@version` : la version du format d'événement (`"1"`) ;
- `event.original` : une copie du texte brut reçu (nommage ECS) ;
- `host.hostname` : le nom de la machine qui a produit l'événement, ici l'identifiant du conteneur Docker et non le nom du poste.
**Que contient `@timestamp` : l'heure de quoi ?**
 
L'heure à laquelle **Logstash a reçu la ligne**, c'est-à-dire le moment où la touche Entrée a été pressée. Elle est exprimée en **UTC** (suffixe `Z`) : `09:17` UTC correspond à `11:17` heure de Paris.
 
Ce n'est donc pas l'heure d'un fait décrit dans le message. Pour des logs, c'est un problème : tous les événements d'un fichier lu d'un coup sembleraient s'être produits au même moment. Le filtre `date` (partie 3) corrige cela en remplaçant `@timestamp` par la date contenue dans la ligne de log.
 
**À quoi sert l'option `--path.data /tmp/essai` ?**
 
Le dossier de données de Logstash contient son état : files d'attente persistées, dead letter queue, sincedb, identifiant du nœud. Logstash y pose un **verrou** : deux instances ne peuvent pas utiliser le même dossier, la seconde refuse de démarrer.
 
Le service `logstash` du TP utilise le dossier par défaut `/usr/share/logstash/data`. En donnant un dossier distinct à ce Logstash éphémère, on évite le conflit avec le service principal et on ne modifie pas son état. Comme le conteneur est lancé avec `--rm`, ce dossier temporaire disparaît avec lui.

## Partie 1 — Recharger les offres avec Logstash
 
Le pipeline `logstash/pipeline/offres.conf` a été fourni complet ; nous l'avons commenté (repères TODO 1 à 6) pour expliquer chaque réglage.
 
### Exercice 1.1 — Vérifier la syntaxe
 
`--config.test_and_exit` renvoie `Config Validation Result: OK`.
 
### Exercice 1.2 — Premier lancement
 
Pour observer l'erreur prévue par l'énoncé, le filtre `mutate` (TODO 6) a été mis en commentaire avant le lancement. État de départ : `OFF-00002` en `_version: 1` (index recréé par `ingest.py`).
 
Extrait des journaux de Logstash (une ligne par document refusé) :
 
```text
[WARN ][logstash.outputs.elasticsearch][offres] Could not index event to Elasticsearch.
{status: 400, action: ["index", {_id: "OFF-00004", _index: "offres"}, {"@version" => "1", …,
 "host" => {"name" => "f669bf633d74"}, "log" => {"file" => {"path" => "/data/offres.ndjson"}},
 "event" => {"original" => "…"}, "@timestamp" => 2026-10-01T11:50:32.028865737Z}],
 response: {"index" => {"status" => 400, "error" => {"type" => "strict_dynamic_mapping_exception",
 "reason" => "[1:13] mapping set to strict, dynamic introduction of [@version] within [_doc] is not allowed"}}}}
```
 
Dans Dev Tools : `GET offres/_count` → 5000, `GET offres/_doc/OFF-00002` → `_version: 1`.
 
**Les documents sont-ils indexés ?**
 
Non. Le `_count` reste à 5 000, mais ces documents sont ceux chargés auparavant par `ingest.py`. La preuve que Logstash n'a rien écrit : `OFF-00002` est toujours en `_version: 1`. Si Logstash l'avait réécrit, sa version serait passée à 2.
 
**Quelle erreur, avec quel code HTTP et quel type d'exception ?**
 
Pour chaque document, Elasticsearch répond **400 (Bad Request)** avec une **`strict_dynamic_mapping_exception`**. Le code 400 indique une erreur du côté de la requête : réessayer à l'identique ne changerait rien. Logstash journalise donc l'erreur (`Could not index event`) et **abandonne** le document.
 
**Quels noms de champs sont cités ?**
 
Le message cite **`@version`** : `dynamic introduction of [@version] within [_doc] is not allowed`. Elasticsearch s'arrête au premier champ inconnu rencontré (position `[1:13]` dans le JSON envoyé). Mais l'événement affiché dans le journal montre que Logstash a ajouté d'autres champs, absents du mapping eux aussi : `@timestamp`, `host` (`host.name`), `log` (`log.file.path`, le fichier lu) et `event` (`event.original`, la ligne JSON brute). Chacun aurait provoqué le même refus.
 
**Lien avec `"dynamic": "strict"` (TP d'introduction, ex. 1.4)**
 
Le mapping de `offres` est en `"dynamic": "strict"` : seuls les 13 champs déclarés sont acceptés, et **tout champ inconnu fait rejeter le document entier**. C'est le même mécanisme qu'au TP d'introduction avec le champ `prime` de `OFF-99999`. Ici, les champs inconnus ne viennent pas des données, mais des **métadonnées ajoutées automatiquement par Logstash** (vues à l'exercice 0). Le mapping strict joue son rôle de garde-fou : il empêche que des champs techniques non prévus viennent polluer le schéma des offres.
 
### Exercice 1.3 — Corriger
 
Le filtre `mutate` a été rétabli : il supprime `@timestamp`, `@version`, `event`, `log` et `host` avant l'envoi. Syntaxe validée, puis `docker compose restart logstash`.
 
Résultats :
 
- `docker compose logs --since 2m logstash | grep -c "Could not index"` → **0** erreur d'indexation ;
- `GET offres/_count` → **5000** ;
- `GET offres/_doc/OFF-00002` → **`_version: 2`**, `_seq_no: 5001`.
**Le nombre de documents a-t-il changé ? Et le `_version` de `OFF-00002` ? Pourquoi ?**
 
Le nombre de documents **n'a pas changé** : toujours 5 000. En revanche, `OFF-00002` est passé de `_version: 1` à **`_version: 2`** : Logstash a bien réécrit le document.
 
C'est l'effet de `document_id => "%{id}"` : chaque offre est envoyée avec son identifiant métier comme `_id`. Les 5 000 `_id` existaient déjà (chargés par `ingest.py`), donc l'action `index` a **remplacé** chaque document au lieu d'en créer un nouveau. Elasticsearch incrémente alors le `_version` du document. Le `_seq_no` (numéro d'opération sur le shard) passe de 1 à 5001 : les 5 000 premières opérations venaient d'`ingest.py`, celle-ci est une nouvelle écriture.
 
L'ingestion est donc **idempotente** : la rejouer donne le même état final, sans doublon. On remarque aussi que l'ordre des champs dans `_source` a changé (Logstash ne conserve pas l'ordre du JSON d'origine), ce qui n'a aucune incidence.
 
**Pourquoi supprimer ces champs plutôt qu'assouplir le mapping de l'index ?**
 
- Ces champs n'ont **aucun sens métier** pour une offre d'emploi : la date de lecture par Logstash, le nom du conteneur, le chemin du fichier ou la ligne JSON brute ne décrivent pas l'offre. Ils alourdiraient chaque document et le stockage.
- Le mapping strict est un **contrat** sur le schéma des offres, partagé par tous les producteurs (`ingest.py`, Logstash, une future API). L'assouplir pour un outil ouvrirait la porte à n'importe quel champ imprévu, y compris des fautes de frappe ou des données erronées, qui passeraient alors inaperçues.
- Corriger à la source, dans le pipeline, garde le problème là où il est créé : c'est Logstash qui ajoute ces champs, c'est donc à lui de les retirer.
**Pourquoi l'index `offres` doit-il exister avant le premier démarrage de Logstash ?**
 
Avec `manage_template => false`, Logstash n'installe aucun modèle d'index. Si `offres` n'existait pas, le premier document envoyé ferait **créer l'index automatiquement** (le rôle `logstash_writer` a le privilège `create_index`), avec un **mapping dynamique** deviné par Elasticsearch à partir des valeurs :
 
- plus de `"dynamic": "strict"` : n'importe quel champ serait accepté ;
- `titre`, `description` en `text` avec l'analyseur standard, sans l'analyseur `french` ;
- `localisation` deviné comme un objet de deux nombres et non comme un `geo_point` : plus de recherche géographique ni de carte ;
- `ville`, `contrat` en `text` + sous-champ `.keyword`, au lieu de `keyword` directement.
Le mapping d'un champ ne pouvant plus être modifié une fois créé, il faudrait supprimer l'index et tout réindexer. C'est pourquoi l'index et son mapping explicite doivent être créés **avant** l'ingestion (ici par `ingest.py`, ou par le `PUT offres` du TP d'introduction).

### Exercice 1.4 — Relancer
 
Nouveau `docker compose restart logstash`, puis vérifications :
 
- `GET offres/_count` → **5000** ;
- `GET offres/_doc/OFF-00002` → **`_version: 3`**, `_seq_no: 10314` ;
- journal de lecture (`file_completed_log_path`) :
```bash
$ docker compose exec logstash cat /usr/share/logstash/data/offres_lus.log
/data/offres.ndjson
/data/offres.ndjson
/data/offres.ndjson
```
 
**Combien de fois le fichier a-t-il été lu ?**
 
**Trois fois**, une fois par démarrage de Logstash : à l'exercice 1.2 (lecture complète, mais les 5 000 documents ont été refusés par Elasticsearch), à l'exercice 1.3 et à l'exercice 1.4. Avec `sincedb_path => "/dev/null"`, Logstash ne mémorise pas sa position : à chaque démarrage, il considère le fichier comme nouveau et le relit en entier.
 
À chaque relecture réussie, les 5 000 documents sont réécrits avec le même `_id` : le nombre reste à 5 000 et le `_version` augmente de 1 (2 après l'exercice 1.3, 3 après l'exercice 1.4). Le `_seq_no` de `OFF-00002`, passé de 5001 à 10314, confirme les 5 000 nouvelles opérations d'écriture sur le shard.
 
**Que se passerait-il avec la sincedb par défaut au lieu de `/dev/null` ?**
 
Logstash enregistrerait dans sa sincedb (dans son dossier de données, le volume `lsdata`, qui survit aux redémarrages) que `offres.ndjson` a été **lu jusqu'au bout**. Aux démarrages suivants, il ne le relirait pas : rien ne serait envoyé et `OFF-00002` resterait en `_version: 2`. Seules des lignes ajoutées à la fin du fichier, ou un nouveau fichier, seraient traitées.
 
C'est le comportement voulu en production (ne pas tout renvoyer à chaque redémarrage). Mais dans notre cas, il aurait posé un problème dès l'exercice 1.3 : la lecture de l'exercice 1.2, dont tous les documents ont été refusés, aurait été mémorisée comme terminée. Après correction du pipeline, le fichier n'aurait **pas été relu**, et les offres n'auraient jamais été chargées par Logstash. Il aurait fallu supprimer la sincedb pour forcer la relecture.
 
**Et si `document_id` n'était pas renseigné ?**
 
Elasticsearch générerait un **`_id` aléatoire** pour chaque document reçu. Chaque relecture créerait donc 5 000 **nouveaux** documents au lieu de remplacer les existants : 10 000 documents après l'exercice 1.3 (les 5 000 d'`ingest.py` plus 5 000 copies), 15 000 après l'exercice 1.4. Chaque offre existerait en plusieurs exemplaires, ce qui fausserait les comptages, les agrégations et les résultats de recherche. On ne pourrait pas non plus retrouver une offre par `GET offres/_doc/OFF-00002`.
 
Le `document_id` métier, combiné à l'action `index`, rend l'ingestion **idempotente** : on peut relancer Logstash autant de fois qu'on veut, l'index reflète toujours le contenu du fichier, sans doublon.
 
## Partie 2 — Superviser et fiabiliser
 
### Exercice 2.1 — Superviser
 
Requêtes sur l'API de supervision de Logstash (port 9600) : `/?pretty`, `/_node/pipelines?pretty` et `/_node/stats/pipelines/offres?pretty`.
 
Extrait des statistiques du pipeline `offres` :
 
| Élément | Valeur |
| --- | --- |
| `events.in` / `filtered` / `out` | 5000 / 5000 / 5000 |
| `events.duration_in_millis` (pipeline) | 12 987 |
| Entrée `file` : `out` | 5000 |
| Filtre `mutate` : `duration_in_millis` | 703 |
| Sortie `elasticsearch` : `duration_in_millis` | 12 240 |
| Sortie `elasticsearch` : requêtes `_bulk` | 43, toutes en 200 ; 5000 documents en succès |
| File d'attente | `memory`, 0 événement en attente |
| `dead_letter_queue_enabled` | `false` |
 
**Combien de pipelines sont chargés, avec combien de workers chacun ?**
 
**Deux pipelines**, `offres` et `web`, ceux déclarés dans `pipelines.yml`. Chacun a **12 workers** (valeur par défaut : le nombre de cœurs processeur vus par le conteneur), traite les événements par lots de **125** (`batch_size`) et attend au plus **50 ms** pour compléter un lot (`batch_delay`). L'état général de Logstash est `green`.
 
**Que valent `in`, `filtered` et `out` pour `offres`, et que représentent-ils ?**
 
Les trois valent **5000** :
 
- `in` : événements entrés dans le pipeline (lus par l'entrée `file`) ;
- `filtered` : événements passés par l'étape des filtres ;
- `out` : événements transmis aux sorties.
Ces compteurs sont **remis à zéro à chaque démarrage** de Logstash : ils correspondent à la seule lecture de l'exercice 1.4, et non aux trois lectures du fichier. L'égalité des trois valeurs montre qu'aucun événement n'a été perdu ni supprimé (`drop`) en route. Côté sortie, `documents.successes: 5000` et 43 requêtes `_bulk` toutes en réponse 200 confirment qu'Elasticsearch a accepté tous les documents.
 
Attention : `out` compte les événements remis à la sortie, pas les documents acceptés par Elasticsearch. À l'exercice 1.2, `out` aurait aussi valu 5000, alors que tous les documents avaient été refusés. Pour cela, il faut regarder `documents.successes` et les codes de réponse de la sortie `elasticsearch`.
 
**Quel plugin du pipeline consomme le plus de temps ?**
 
La **sortie `elasticsearch`**, avec **12 240 ms** sur un total de 12 987 ms pour le pipeline, soit environ 94 %. Le filtre `mutate` ne prend que 703 ms (environ 0,14 ms par événement). C'est logique : supprimer quelques champs se fait en mémoire, alors que la sortie attend la réponse d'Elasticsearch pour chaque requête `_bulk` (envoi réseau, indexation, analyse des champs `text` avec l'analyseur `french`, écriture sur disque).
 
Ces durées sont du temps cumulé sur l'ensemble des workers, pas du temps écoulé : le pipeline a en réalité traité les 5 000 offres en quelques secondes. C'est donc la sortie qu'il faudrait optimiser en priorité (taille des lots, nombre de workers, performance du cluster).
 
### Exercice 2.2 — Isoler les documents rejetés
 
Mise en œuvre :
 
1. Ajout de `DEAD_LETTER_QUEUE_ENABLE=true` dans l'environnement du service `logstash` (`docker-compose.override.yml`) : la ligne n'existait pas dans le kit, elle a été ajoutée. Conteneur recréé avec `docker compose up -d logstash`.
2. Chemin de l'entrée `file` élargi à `/data/offres*.ndjson` dans `offres.conf`.
3. Création de `data/offres_test.ndjson` : une seule offre, copie de la dernière ligne de `offres.ndjson`, avec `"id": "OFF-99999"` et un champ `"prime": 3000` absent du mapping.
4. `docker compose restart logstash`.
Vérifications :
 
- l'API de Logstash indique `"dead_letter_queue_enabled" : true` pour les deux pipelines, chacun avec son propre dossier (`…/dead_letter_queue/offres` et `…/dead_letter_queue/web`) ;
- contenu de la DLQ :
```text
/usr/share/logstash/data/dead_letter_queue/offres:
-rw-r--r-- 1 logstash root 2165 Oct  1 12:37 1.log
-rw-r--r-- 1 logstash root 2164 Oct  1 12:39 2.log
-rw-r--r-- 1 logstash root    1 Oct  1 12:39 3.log.tmp
```
 
- `GET offres/_doc/OFF-99999` → `"found": false` (404) ; `GET offres/_count` → 5000.
La DLQ contient **deux** exemplaires de `OFF-99999` : en mode `read`, Logstash a repéré le nouveau fichier `offres_test.ndjson` dès sa création (12:37 UTC), puis l'a relu au redémarrage (12:39 UTC), la sincedb étant désactivée. Les fichiers `.tmp` de 1 octet sont les segments en cours d'écriture, encore vides.
 
Relecture de la DLQ avec un second Logstash éphémère (entrée `dead_letter_queue`, `pipeline_id => "offres"`, `commit_offsets => false`). Extrait de l'un des deux événements :
 
```ruby
{
                   "id" => "OFF-99999",
                "prime" => 3000,
                "ville" => "Nice",
                "titre" => "Développeur Java Junior",
                  …
            "@metadata" => {
                     "path" => "/data/offres_test.ndjson",
        "dead_letter_queue" => {
            "plugin_type" => "elasticsearch",
              "plugin_id" => "61c7b428…",
             "entry_time" => 2026-10-01T12:37:50.568024443Z,
                 "reason" => "Could not index event to Elasticsearch. status: 400, action: [\"index\",
                              {_id: \"OFF-99999\", _index: \"offres\"}, {…}], response: {\"index\" =>
                              {\"status\" => 400, \"error\" => {\"type\" => \"strict_dynamic_mapping_exception\",
                              \"reason\" => \"[1:480] mapping set to strict, dynamic introduction of [prime]
                              within [_doc] is not allowed\"}}}"
        }
    }
}
```
 
**Le document `OFF-99999` est-il dans l'index ? Où se trouve-t-il ?**
 
Non : `GET offres/_doc/OFF-99999` renvoie `"found": false`, et le compte reste à 5 000. Les 5 000 offres valides ont été indexées normalement : le document refusé n'a rien bloqué.
 
Il se trouve dans la **dead letter queue** du pipeline `offres`, sur le disque de Logstash : `/usr/share/logstash/data/dead_letter_queue/offres/` (fichiers `1.log` et `2.log`). Ce dossier est dans le volume Docker `lsdata` : il survit aux redémarrages et à la recréation du conteneur.
 
**Quelle raison de refus est enregistrée dans `[@metadata][dead_letter_queue]` ?**
 
Une erreur **400** de type **`strict_dynamic_mapping_exception`** : `mapping set to strict, dynamic introduction of [prime] within [_doc] is not allowed`. Le champ `prime` n'existe pas dans le mapping strict de `offres`.
 
Cette fois, c'est bien `prime` qui est cité, et non `@version` comme à l'exercice 1.2 : le filtre `mutate` a retiré les champs ajoutés par Logstash, il ne reste que le champ métier imprévu. La DLQ conserve aussi :
 
- `entry_time` : l'heure du refus ;
- `plugin_type` et `plugin_id` : le plugin qui a rejeté l'événement (la sortie `elasticsearch`) ;
- `[@metadata][path]` : le fichier source (`/data/offres_test.ndjson`) ;
- l'**événement complet**, tel qu'il a été envoyé à Elasticsearch, et la requête `_bulk` exacte dans `reason`.
**Comparaison avec `raise_on_error=False` dans `ingest.py` : qu'apporte la DLQ en plus ?**
 
Les deux approches ont un point commun : un document invalide ne bloque pas le reste de l'ingestion. Mais avec `raise_on_error=False`, `ingest.py` se contentait d'**afficher** l'erreur dans la console : une fois le terminal fermé, il ne restait aucune trace exploitable, et pour corriger il fallait retrouver la ligne dans le fichier source.
 
La DLQ apporte en plus :
 
- la **conservation** : le document refusé et la raison du refus sont écrits sur disque, ils survivent aux redémarrages ;
- le **contexte complet** : l'événement tel qu'il était après les filtres, l'heure, le plugin en cause, le fichier d'origine ;
- l'**indépendance vis-à-vis de la source** : on peut corriger même si le fichier source a été supprimé, déplacé ou réécrit entre-temps (rotation de logs, fichier supprimé après lecture…) ;
- la **réinjection automatisable** : l'entrée `dead_letter_queue` permet d'écrire un pipeline Logstash qui relit, corrige et renvoie les documents, au lieu d'un traitement manuel ;
- la **supervision** : la taille de la DLQ peut être surveillée, et une DLQ qui grossit signale un problème de données.
Sans DLQ, Logstash perd le document refusé et ne laisse qu'une ligne d'avertissement dans son journal, comme à l'exercice 1.2.
 
**Comment corriger et réinjecter ce document, en trois étapes ?**
 
1. **Analyser** : relire la DLQ (comme ci-dessus) pour identifier la cause, ici le champ `prime` absent du mapping, et décider de la correction avec le métier.
2. **Corriger** : deux options selon la décision.
   - Si la prime ne doit pas être stockée : écrire un pipeline de reprise qui lit la DLQ (`input { dead_letter_queue { pipeline_id => "offres" commit_offsets => true } }`) et supprime le champ (`mutate { remove_field => ["prime", "@timestamp", "@version"] }`).
   - Si la prime est une information utile : l'ajouter au mapping (`PUT offres/_mapping` avec `"prime": { "type": "integer" }` ; ajouter un champ est autorisé, contrairement à modifier un champ existant), puis relire la DLQ sans modifier le document.
3. **Réinjecter et vérifier** : envoyer le résultat avec la même sortie `elasticsearch` (`index => "offres"`, `document_id => "%{id}"`), puis contrôler avec `GET offres/_doc/OFF-99999` et `GET offres/_count` (5001). Grâce au `document_id` métier, les deux exemplaires présents dans la DLQ aboutissent au même document, sans doublon. Avec `commit_offsets => true`, les entrées traitées sont marquées comme lues et ne seront pas retraitées ; on peut ensuite purger la DLQ.
Le fichier `data/offres_test.ndjson` a ensuite été supprimé.
 
### Exercice 2.3 — Pourquoi deux pipelines ?
 
**Si `pipelines.yml` n'était pas monté, combien de pipelines Logstash chargerait-il ?**
 
**Un seul**, nommé `main`. L'image Docker charge alors tous les fichiers du dossier `/usr/share/logstash/pipeline/` et les **concatène** en un seul pipeline : les entrées, les filtres et les sorties de `offres.conf` et de `web.conf` sont mis bout à bout.
 
**Que deviendrait une offre lue dans `offres.ndjson` ? Et une ligne de log d'accès ?**
 
Dans un pipeline unique, chaque événement passe par **tous** les filtres et est envoyé à **toutes** les sorties, quelle que soit l'entrée qui l'a lu (sauf à ajouter des conditions partout).
 
- Une **offre** serait envoyée à la fois dans l'index `offres` (correct) et dans le data stream `logs-web-default`, où elle n'a rien à faire : elle polluerait les logs web et fausserait les statistiques de trafic. Elle passerait aussi par les filtres des logs (`grok`, `date`, `useragent`), inutilement.
- Une **ligne de log** serait envoyée dans `logs-web-default` (correct), mais aussi dans l'index `offres`, où elle serait **refusée** par le mapping strict (champs `message`, `source`, `http`, `url`… inconnus) : 20 700 erreurs 400, perdues ou entassées dans la DLQ. Pire, le filtre `mutate` de `offres.conf` lui retirerait `@timestamp` : elle ne pourrait plus être datée correctement, alors qu'un data stream exige ce champ.
**Deux autres avantages à isoler les pipelines**
 
- **Isolation des pannes** : si Elasticsearch refuse ou ralentit les écritures d'un flux (index bloqué, mapping en erreur), seul ce pipeline est freiné ; l'autre continue de fonctionner normalement. Dans un pipeline unique, une sortie bloquée bloque tout.
- **Réglages indépendants** : chaque pipeline a ses propres workers, taille de lots, type de file d'attente (mémoire ou persistée) et sa propre DLQ (on l'a vu : un dossier par pipeline). On peut par exemple persister la file des logs sans ralentir le rechargement des offres.
- **Supervision et maintenance séparées** : l'API de supervision donne des compteurs par pipeline (`in`, `out`, durées), ce qui permet de savoir immédiatement quel flux pose problème. Chaque pipeline peut aussi être modifié et rechargé sans toucher à l'autre, et chaque fichier reste court et lisible.
### Exercice 2.4 — Ne rien perdre (réflexion)
 
**Logstash est arrêté brutalement pendant la lecture d'un gros fichier. Avec la file en mémoire, que deviennent les événements lus mais pas encore envoyés ?**
 
Ils sont **perdus**. La file en mémoire (`queue.type: memory`, valeur par défaut, visible dans l'API : `"queue" : { "type" : "memory" }`) disparaît avec le processus. Tous les événements déjà lus par l'entrée mais pas encore confirmés par Elasticsearch, qu'ils attendent dans la file, en cours de filtrage ou dans une requête `_bulk` sans réponse, n'existent plus nulle part dans Logstash.
 
Le risque est aggravé par la sincedb : l'entrée `file` y enregistre régulièrement sa position de lecture. Au redémarrage, elle reprend après la dernière position enregistrée, et les lignes lues avant l'arrêt mais jamais envoyées ne sont pas relues. Dans notre labo, la sincedb à `/dev/null` masque ce problème, puisque le fichier entier est relu à chaque démarrage.
 
**Quel réglage change ce comportement, et quelle garantie obtient-on ?**
 
La **file persistée** : `queue.type: persisted` (sous Docker, variable d'environnement `QUEUE_TYPE=persisted`), réglable par pipeline dans `pipelines.yml`. Les événements sont écrits sur disque dès leur réception, avant d'être confirmés à l'entrée, et ne sont retirés de la file qu'une fois acceptés par les sorties. Après un arrêt brutal, Logstash reprend les événements restés dans la file et les renvoie.
 
On obtient une garantie de livraison **« au moins une fois »** (*at-least-once*) : aucun événement n'est perdu, mais certains peuvent être envoyés **deux fois**. C'est le cas d'un lot qu'Elasticsearch a indexé juste avant l'arrêt, mais dont Logstash n'a pas eu le temps d'enregistrer la confirmation : il sera renvoyé au redémarrage. La contrepartie est un débit un peu plus faible et de l'espace disque à prévoir.
 
**Pourquoi le `document_id` de la partie 1 devient-il alors indispensable ?**
 
Parce qu'il transforme les doublons possibles en **remplacements**. Un événement renvoyé après le redémarrage porte le même identifiant métier (`OFF-xxxxx`) : l'action `index` réécrit le même document, seul le `_version` augmente, comme on l'a observé aux exercices 1.3 et 1.4. Sans `document_id`, chaque renvoi créerait un nouveau document avec un `_id` aléatoire, donc des offres en double dans l'index.
 
File persistée et `_id` métier se complètent : la première garantit qu'on ne **perd** rien, le second qu'on ne **duplique** rien. Ensemble, ils donnent l'équivalent d'un traitement « exactement une fois » sur le résultat final.
