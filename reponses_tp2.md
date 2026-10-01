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
 
## Partie 3 — Transformer les logs d'accès
 
### Exercice 3.2 — Mettre au point le motif
 
Le pipeline `logstash/pipeline/web.conf` a été fourni complet (`grok`, `date`, `useragent`, extraction de l'identifiant d'offre, sortie vers le data stream).
 
Logs générés avec `python data/generate_access_logs.py` : 20 700 lignes, première ligne :
 
```text
203.0.113.123 - - [23/Sep/2026:00:00:39 +0200] "GET /offres/OFF-01468 HTTP/1.1" 200 43686 "https://jobs.example.org/recherche" "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36"
```
 
`data/access.log` a été ajouté au `.gitignore` (il se régénère et ne doit pas être versionné).
 
Résultat dans Kibana, **Dev Tools → Grok Debugger**, avec le motif `%{COMBINEDAPACHELOG}` :
 
```json
{
  "request": "/offres/OFF-01468",
  "agent": "\"Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Mobile Safari/537.36\"",
  "auth": "-",
  "ident": "-",
  "verb": "GET",
  "referrer": "\"https://jobs.example.org/recherche\"",
  "response": "200",
  "bytes": "43686",
  "clientip": "203.0.113.123",
  "httpversion": "1.1",
  "timestamp": "23/Sep/2026:00:00:39 +0200"
}
```
 
**Quels champs sont extraits ?**
 
Onze champs : adresse du client, identité et utilisateur (ici `-`), date, méthode, URL, version HTTP, code de réponse, taille de la réponse, page d'origine et navigateur.
 
Le Grok Debugger de Kibana utilise la version **historique (legacy)** des motifs, d'avant ECS : les noms obtenus (`clientip`, `verb`, `request`…) ne sont pas ceux de l'énoncé. Logstash 9 fonctionne en mode ECS par défaut (`pipeline.ecs_compatibility: v8`, visible dans ses journaux) : dans le pipeline, le même `%{COMBINEDAPACHELOG}` produit les noms ECS.
 
| Grok Debugger (legacy) | Logstash (ECS) |
| --- | --- |
| `clientip` | `source.address` |
| `ident`, `auth` | `apache.access.user.identity`, `user.name` |
| `timestamp` | `timestamp` |
| `verb` | `http.request.method` |
| `request` | `url.original` |
| `httpversion` | `http.version` |
| `response` | `http.response.status_code` |
| `bytes` | `http.response.body.bytes` |
| `referrer` | `http.request.referrer` |
| `agent` | `user_agent.original` |
 
**Sous quel type apparaît `http.response.status_code` ?**
 
Dans le Grok Debugger, le code de réponse apparaît comme une **chaîne de caractères** (`"response": "200"`, entre guillemets), de même que la taille (`"bytes": "43686"`). Grok extrait du texte, et la version legacy ne fait aucune conversion. On remarque aussi que `referrer` et `agent` conservent leurs guillemets d'origine.
 
La version ECS du motif, utilisée par Logstash, convertit le code de réponse et la taille en **entiers** et retire les guillemets. C'est à vérifier dans le mapping du data stream (exercice 3.4).
 
**Pourquoi `timestamp` doit-il encore être traité ?**
 
Parce que c'est un simple **texte** au format Apache (`23/Sep/2026:00:00:39 +0200`), pas une date exploitable. Grok ne fait que le découper. Sans le filtre `date`, `@timestamp` resterait l'heure de **lecture** de la ligne par Logstash (comme à l'exercice 0) : les 20 700 requêtes, réparties sur 7 jours, sembleraient toutes avoir eu lieu à la même minute, et il serait impossible d'analyser le trafic dans le temps.
 
Le filtre `date` de `web.conf` analyse ce texte avec le format `dd/MMM/yyyy:HH:mm:ss Z` et écrit le résultat dans `@timestamp`, en tenant compte du fuseau `+0200`. L'option `locale => "en"` est nécessaire car le mois est écrit en anglais (`Sep`). Le champ texte `timestamp` est ensuite supprimé (`remove_field`), puisqu'il fait double emploi.
 
**Motif qui extrait `OFF-01468` de l'URL `/offres/OFF-01468/postuler`**
 
Aucun motif prédéfini ne reconnaît le format des identifiants d'offre : on déclare un motif personnalisé `OFFRE_ID`.
 
- Données : `/offres/OFF-01468/postuler`
- Modèle personnalisé : `OFFRE_ID OFF-[0-9]{5}` (`OFF-` suivi de 5 chiffres)
- Modèle Grok : `^/offres/%{OFFRE_ID:offre_id}` (l'URL doit commencer par `/offres/`, la suite est rangée dans `offre_id` ; `/postuler` est ignoré)
Résultat :
 
```json
{
  "offre_id": "OFF-01468"
}
```
 
C'est le motif utilisé dans `web.conf`, appliqué uniquement aux URL qui commencent par `/offres/OFF-`, avec le résultat rangé dans le champ ECS `labels.offre_id` :
 
```text
if [url][original] =~ /^\/offres\/OFF-/ {
  grok {
    pattern_definitions => { "OFFRE_ID" => "OFF-[0-9]{5}" }
    match => { "[url][original]" => "^/offres/%{OFFRE_ID:[labels][offre_id]}" }
  }
}
```

### Exercice 3.3 — Compléter `web.conf`
 
Le pipeline étant fourni, nous avons vérifié sa syntaxe (`--config.test_and_exit` : `Config Validation Result: OK`), puis démarré Logstash (`docker compose up -d logstash`).
 
Statistiques du pipeline `web` une fois la lecture terminée (`/_node/stats/pipelines/web`) :
 
```text
"events" : { "in" : 20700, "filtered" : 20700, "out" : 20700, "duration_in_millis" : 103851 }
```
 
Les 20 700 lignes ont toutes traversé le pipeline. Le temps cumulé (environ 104 s de travail réparti sur les workers) est bien supérieur à celui du pipeline `offres` (environ 13 s pour 5 000 offres) : `grok` (expressions régulières), `date` et surtout `useragent` (analyse de la chaîne du navigateur) sont des filtres plus coûteux qu'un simple `mutate`.
 
### Exercice 3.4 — Vérifier le data stream
 
Résultats dans Dev Tools :
 
| Requête | Résultat |
| --- | --- |
| `GET _data_stream/logs-web-default` | 1 backing index `.ds-logs-web-default-2026.10.01-000001`, modèle `logs`, politique ILM `logs`, `index_mode: logsdb`, `status: YELLOW` |
| `GET logs-web-default/_count` | **20 700** |
| `_count` avec `tags: _grokparsefailure` | **0** |
| Premier événement (tri par `@timestamp` croissant) | `"@timestamp": "2026-09-22T22:00:39.000Z"` |
| `_mapping/field/http.response.status_code` | `"type": "long"` |
| `_settings` (`index.mode`) | `"mode": "logsdb"` |
 
Premier événement (extrait du `_source`) :
 
```json
{
  "@timestamp": "2026-09-22T22:00:39.000Z",
  "source": { "address": "203.0.113.123" },
  "http": {
    "request": { "method": "GET", "referrer": "https://jobs.example.org/recherche" },
    "response": { "status_code": 200, "body": { "bytes": 43686 } },
    "version": "1.1"
  },
  "url": { "original": "/offres/OFF-01468" },
  "labels": { "offre_id": "OFF-01468" },
  "user_agent": {
    "original": "Mozilla/5.0 (Linux; Android 15; Pixel 9) …",
    "name": "Chrome Mobile", "version": "140.0.0.0",
    "os": { "name": "Android", "version": "15", "full": "Android 15" },
    "device": { "name": "Pixel 9" }
  },
  "data_stream": { "type": "logs", "dataset": "web", "namespace": "default" },
  "log": { "file": { "path": "/data/access.log" } },
  "event": {}
}
```
 
Tous les traitements du pipeline sont visibles : champs ECS extraits par `grok` (code de réponse et taille en nombres, sans guillemets), `@timestamp` issu de la ligne de log, navigateur décomposé par `useragent` (nom, version, système, appareil), identifiant d'offre dans `labels.offre_id`, et `event.original` supprimé (l'objet `event` est resté vide). Le champ `data_stream` a été ajouté par la sortie `elasticsearch`.
 
**Combien de documents, et combien d'échecs de `grok` ?**
 
**20 700 documents**, autant que de lignes dans `access.log`, et **0 échec** de `grok` (aucun document avec l'étiquette `_grokparsefailure`). Toutes les lignes ont été reconnues par `%{COMBINEDAPACHELOG}`.
 
Le fichier a été généré sous Windows et ses lignes se terminent par `\r\n` : le champ `message` conserve le `\r` final. Cela ne gêne pas `grok`, car le motif n'est pas ancré en fin de ligne : le dernier champ (`user_agent.original`) est délimité par ses guillemets.
 
**Quel est le nom de l'index caché qui contient les données, et que signifie chaque partie de ce nom ?**
 
`.ds-logs-web-default-2026.10.01-000001` :
 
- **`.ds-`** : préfixe des *backing indices* de data stream ; le point initial en fait un index caché, qu'on n'interroge pas directement mais via le nom du data stream ;
- **`logs-web-default`** : le nom du data stream, lui-même construit sur le modèle `<type>-<dataset>-<namespace>` : type `logs`, jeu de données `web`, espace de noms `default` ;
- **`2026.10.01`** : la date de **création** du backing index (aujourd'hui), et non la date des événements qu'il contient (23 au 29 septembre) ;
- **`000001`** : le numéro de **génération**. À chaque *rollover* (déclenché par la politique ILM `logs` selon la taille ou l'âge de l'index), un nouveau backing index `…-000002` est créé et devient l'index d'écriture ; les anciens restent interrogeables puis sont supprimés à la fin de la durée de conservation.
**Le premier événement est-il daté du 23/09/2026 à 00:00:39 (+02:00), soit 22:00:39 UTC la veille ?**
 
**Oui** : `"@timestamp": "2026-09-22T22:00:39.000Z"`. La ligne de log indique `23/Sep/2026:00:00:39 +0200`, soit 00:00:39 heure de Paris le 23 septembre, c'est-à-dire 22:00:39 **UTC** le 22 septembre. Elasticsearch stocke toutes les dates en UTC (suffixe `Z`) ; Kibana les réaffiche dans le fuseau du navigateur. Le filtre `date` a donc bien remplacé l'heure de lecture par l'heure réelle de la requête, en tenant compte du fuseau.
 
**Quel type a reçu `http.response.status_code`, et pourquoi est-ce important pour la suite ?**
 
Le type **`long`** (entier), défini par les mappings ECS du modèle `logs` et cohérent avec la valeur envoyée par Logstash (`200`, sans guillemets).
 
C'est indispensable pour l'enquête et le tableau de bord, qui reposent sur des **comparaisons numériques** : `http.response.status_code >= 500` en KQL, `WHERE http.response.status_code >= 500` en ES|QL, la formule de taux d'erreur `count(kql='http.response.status_code >= 500') / count()` en partie 5. Sur un champ texte (`keyword`), ces comparaisons seraient **lexicographiques**, caractère par caractère : fragiles et peu performantes. Le type numérique permet aussi des agrégations par plage (2xx, 4xx, 5xx) et un tri dans l'ordre naturel.
 
**Quel `index.mode` est utilisé ?**
 
**`logsdb`**, le mode de stockage optimisé pour les logs, appliqué par défaut depuis la 9.0 aux data streams `logs-*-*`. Il trie les documents sur disque (notamment par hôte et par date) et compresse fortement les données, ce qui réduit nettement l'espace occupé. En contrepartie, le `_source` n'est pas stocké tel quel mais reconstruit à la lecture (*synthetic source*).
 
**Remarque : statut `YELLOW`**
 
Le data stream est en état `YELLOW` : le modèle `logs` demande un réplica par shard, et notre cluster ne compte qu'un nœud. Un réplica ne pouvant pas être placé sur le même nœud que son shard principal, il reste non assigné. Toutes les données sont bien présentes (shard principal actif), mais sans copie de secours. C'est normal en labo ; en production, on aurait plusieurs nœuds.
 
### Exercice 3.5 — Rejouer sans doublon ?
 
Après un `docker compose restart logstash`, le pipeline `web` a relu tout le fichier (`in` = `filtered` = `out` = 20 700, compteurs remis à zéro au redémarrage). Puis :
 
```text
GET logs-web-default/_count   →   "count": 41400
```
 
**Que constatez-vous, et pourquoi le problème ne se posait-il pas pour `offres` ?**
 
Le nombre de documents a **doublé** : 41 400 au lieu de 20 700. Chaque ligne de log est maintenant présente **deux fois** dans le data stream. Toutes les statistiques de la partie 4 seraient faussées (nombre de requêtes, d'erreurs, offres les plus consultées…).
 
Deux causes se combinent :
 
- avec `sincedb_path => "/dev/null"`, Logstash ne mémorise pas sa position : au redémarrage, il relit `access.log` en entier ;
- `web.conf` ne définit **pas de `document_id`** : Elasticsearch attribue à chaque document un `_id` **aléatoire** (par exemple `AaD3jIwDPvpUGe9ErrV9` pour le premier événement). Une ligne relue est donc vue comme un nouvel événement.
Pour `offres`, la relecture ne posait pas de problème grâce à `document_id => "%{id}"` : chaque offre a un identifiant métier stable, et une relecture **remplace** le document existant (seul `_version` augmente, voir exercices 1.3 et 1.4). Les lignes de log, elles, n'ont pas d'identifiant naturel.
 
**Peut-on mettre à jour ou remplacer un document dans un data stream ?**
 
**Non, pas par une écriture normale.** Un data stream est conçu pour des événements en **ajout seul** (*append-only*) : il n'accepte que l'action `create`, qui crée un nouveau document. Les actions `index` (créer ou remplacer) et `update` envoyées au nom du data stream sont refusées. D'ailleurs, la sortie `elasticsearch` utilise automatiquement `create` quand `data_stream => "true"`.
 
Si un document est envoyé en `create` avec un `_id` qui existe déjà, il n'est pas remplacé : Elasticsearch le refuse avec une erreur **409 (conflit de version)**.
 
Les modifications restent possibles de façon exceptionnelle, pour corriger des données : `_update_by_query` ou `_delete_by_query` sur le data stream, ou une requête adressée directement au backing index avec `if_seq_no` et `if_primary_term`. Mais ce n'est pas un usage courant : un log décrit un fait passé, il n'a pas vocation à changer.
 
**Deux solutions pour pouvoir rejouer ce fichier sans doublon**
 
1. **Garder la mémoire de lecture (sincedb)** : supprimer `sincedb_path => "/dev/null"` pour revenir à la sincedb par défaut, stockée dans le dossier de données de Logstash (le volume `lsdata`, qui survit aux redémarrages). Logstash note que `access.log` a été lu jusqu'au bout et ne le relit pas au redémarrage ; seules les nouvelles lignes ou les nouveaux fichiers sont traités.
   - Limite : cela **évite** de relire, mais ne protège pas d'un **vrai rejeu** volontaire (supprimer la sincedb pour réindexer), ni d'un arrêt brutal entre l'envoi d'un lot et l'enregistrement de la position (garantie « au moins une fois », exercice 2.4).
2. **Calculer un `_id` à partir du contenu de la ligne** avec le filtre `fingerprint` : une empreinte (hash SHA-256) de la ligne brute sert d'identifiant. La même ligne produit toujours le même `_id`.
```text
   filter {
     fingerprint {
       source => ["message"]
       target => "[@metadata][fingerprint]"
       method => "SHA256"
     }
   }
   output {
     elasticsearch {
       …
       document_id => "%{[@metadata][fingerprint]}"
     }
   }
```
 
   Au rejeu, chaque ligne déjà indexée est refusée par Elasticsearch (409, le document existe déjà) au lieu d'être dupliquée : le compte reste à 20 700. L'empreinte est rangée dans `[@metadata]`, qui n'est pas envoyé à Elasticsearch : elle ne pollue pas le document.
   - Limites : deux lignes **strictement identiques** (même client, même seconde, même URL, même navigateur) recevraient le même `_id`, et la seconde serait écartée ; c'est acceptable pour des logs à la seconde, mais il faut en avoir conscience. Par ailleurs, l'unicité de l'`_id` n'est vérifiée qu'**au sein d'un même backing index** : un rejeu après un *rollover* pourrait recréer les anciens événements dans le nouvel index.
Les deux solutions se complètent : la sincedb évite les relectures inutiles en fonctionnement normal, l'empreinte garantit l'idempotence quand un rejeu a quand même lieu. C'est le même principe que pour les offres : **un `_id` déterministe** rend l'ingestion rejouable.
 
Remise à zéro avant la partie 4 : `docker compose stop logstash`, `DELETE _data_stream/logs-web-default`, puis `docker compose up -d logstash`.
 
## Partie 4 — Enquête dans Kibana
 
Requêtes KQL et ES|QL : voir `requetes/enquete.txt`.
 
Data view **Logs web** créée sur `logs-web-*` (champ temporel `@timestamp`), période absolue du 23/09/2026 00:00 au 30/09/2026 00:00 (heure de Paris) : 20 700 documents. Les requêtes ES|QL sont exécutées dans Discover ; Kibana transmet le fuseau du navigateur, les dates des résultats sont donc en heure de Paris. Les dates écrites dans les clauses `WHERE` sont en UTC (suffixe `Z`).
 
### Exercice 4.1 — Vue d'ensemble
 
**Répartition par code HTTP**
 
| Code | Signification | Requêtes |
| --- | --- | --- |
| 200 | OK | ≈ 17 800 (arrondi Kibana : 17,8 k) |
| 201 | Créé (candidature enregistrée) | ≈ 1 490 (1,49 k) |
| 404 | Ressource introuvable | 508 |
| 304 | Non modifié (cache du navigateur) | 488 |
| 503 | Service indisponible | 402 |
| 500 | Erreur interne du serveur | 5 |
 
Environ 93 % des requêtes aboutissent (200, 201, 304). Deux codes d'erreur méritent l'enquête : les **503**, concentrés sur un seul créneau (exercice 4.2), et les **404** (exercice 4.3). Les 5 réponses **500** sont isolées, réparties sur la semaine : bruit de fond normal.
 
**Répartition par méthode**
 
| Méthode | Requêtes |
| --- | --- |
| GET | ≈ 19 210 (19,21 k) |
| POST | ≈ 1 490 (1,49 k) |
 
Les `POST` sont les candidatures (`POST /offres/OFF-…/postuler`) : leur nombre correspond à celui des réponses **201**, ce qui indique que toutes les candidatures ont été enregistrées. Tout le reste du trafic est de la consultation (`GET`).
 
**Volume moyen de requêtes par jour**
 
20 700 requêtes sur 7 jours, soit **environ 2 957 requêtes par jour** (environ 123 par heure, une dizaine toutes les 5 minutes).
 
| Jour | Requêtes |
| --- | --- |
| 23/09 | 2 832 |
| 24/09 | 2 884 |
| 25/09 | 2 843 |
| 26/09 | 3 122 |
| 27/09 | 2 903 |
| 28/09 et 29/09 | 6 116 au total |
 
Le trafic est régulier d'un jour à l'autre. Le 26/09 se distingue légèrement (3 122) : on verra à l'exercice 4.3 que c'est le jour de l'activité du robot. L'histogramme de Discover montre aussi un pic le 28/09 vers 14 h, qui correspond à l'incident.
 
### Exercice 4.2 — L'incident
 
**1. Jour et créneau précis**
 
Erreurs serveur (`>= 500`) par heure : **402 erreurs le dimanche 28/09/2026 entre 14 h et 15 h**, contre au plus 1 erreur sur chacune des autres heures de la semaine.
 
Par tranches de 5 minutes sur cette heure :
 
| Tranche | Requêtes | Erreurs 5xx |
| --- | --- | --- |
| 14:00 | 61 | 53 |
| 14:05 | 50 | 41 |
| 14:10 | 46 | 42 |
| 14:15 | 43 | 35 |
| … | … | … |
| 14:35 | 64 | 47 |
| 14:40 | 57 | 48 |
| 14:45 | 10 | 0 |
| 14:50 | 12 | 0 |
| 14:55 | 6 | 0 |
 
Bornes exactes des réponses 503 : **première à 14:00:08, dernière à 14:44:56** (heure de Paris).
 
**2. URL touchées, et celles qui ne l'ont pas été**
 
Requêtes entre 14:00 et 14:45, regroupées par rubrique du site :
 
| Rubrique | Requêtes | Erreurs 5xx |
| --- | --- | --- |
| API (`/api/…`) | 403 | **402** |
| Fiche d'offre (`/offres/OFF-…`) | 34 | 0 |
| Recherche (`/recherche…`) | 17 | 0 |
| Accueil (`/`) | 12 | 0 |
| Candidature (`/offres/…/postuler`) | 7 | 0 |
| Fichiers statiques | 5 | 0 |
 
**Seule l'API a été touchée** : 402 de ses 403 requêtes ont échoué. Les pages du site (accueil, recherche, fiches d'offres) et les candidatures ont fonctionné normalement. La panne porte donc sur le service qui répond à l'API, pas sur le serveur web ni sur l'ensemble du site.
 
**3. Nombre de réponses en erreur et durée**
 
**402 réponses 503** (*Service Unavailable*), sur une durée de **44 min 48 s** (14:00:08 → 14:44:56). Le service est revenu brutalement : aucune erreur dès la tranche de 14:45.
 
**4. Comportement des clients pendant l'incident**
 
Requêtes sur l'API par quart d'heure, le 28/09 de 13 h à 16 h :
 
| Tranche | Requêtes API | Adresses IP distinctes |
| --- | --- | --- |
| 13:00 | 8 | 8 |
| 13:15 | 6 | 6 |
| 13:30 | 1 | 1 |
| 13:45 | 5 | 5 |
| **14:00** | **136** | **120** |
| **14:15 et 14:30** | **267 au total** | — |
| 14:45 | 1 | 1 |
| 15:00 | 6 | 6 |
| 15:15 | 3 | 3 |
| 15:30 | 4 | 4 |
| 15:45 | 5 | 5 |
 
Le volume de requêtes sur l'API a **fortement augmenté** pendant l'incident : environ **135 requêtes par quart d'heure** contre **5 en moyenne** avant et après, soit un trafic multiplié par 25 environ. Il retombe immédiatement à la normale à 14:45, au moment exact où les erreurs cessent. Les autres rubriques gardent leur volume habituel.
 
Explication proposée : une **tempête de nouvelles tentatives** (*retry storm*). Les clients de l'API (application mobile, front-end, partenaires qui interrogent `/api/offres`) reçoivent une 503 et **réessaient automatiquement**, souvent tout de suite et plusieurs fois. Chaque échec génère ainsi de nouvelles requêtes, ce qui augmente encore la charge sur un service déjà en difficulté et peut prolonger la panne. Dès que le service répond de nouveau, les tentatives s'arrêtent et le trafic redevient normal.
 
Une autre lecture est possible : un **afflux soudain** de clients sur l'API à 14:00 aurait **saturé** le service et provoqué les 503 (la hausse du trafic serait alors la cause, et non la conséquence). Le nombre d'adresses IP distinctes (120 pour 136 requêtes à 14:00) ne permet pas de trancher : les clients peuvent passer par des adresses différentes (proxys, réseaux mobiles), et une IP n'identifie pas un client de façon fiable. Dans les deux cas, la recommandation est la même : côté clients, des nouvelles tentatives **espacées et limitées** (*exponential backoff* avec un délai aléatoire) ; côté serveur, une **limitation de débit** (*rate limiting*) sur l'API et une alerte sur le taux de 5xx (bonus de la partie 5).
 
**Rapport d'incident (synthèse)**
 
> Le dimanche 28 septembre 2026, de 14:00:08 à 14:44:56 (45 minutes), l'API du site de recrutement (`/api/…`) a été indisponible : 402 requêtes sur 403 ont reçu une réponse 503. Le reste du site (accueil, recherche, fiches d'offres, candidatures) n'a pas été affecté. Pendant l'incident, le volume de requêtes sur l'API a été multiplié par 25 environ, puis est revenu à la normale dès le rétablissement du service, ce qui suggère des nouvelles tentatives automatiques des clients. Actions proposées : analyser les journaux applicatifs de l'API sur ce créneau pour identifier la cause racine, limiter le débit sur l'API, imposer un délai croissant entre les tentatives côté clients, et créer une alerte sur le taux d'erreurs 5xx.
 
### Exercice 4.3 — L'activité suspecte
 
**1. Adresse IP à l'origine d'une rafale de réponses 404**
 
Réponses 404 par adresse IP : **`203.0.113.66`** en totalise **300**, alors qu'aucune autre adresse n'en dépasse 3. Les 208 autres 404 de la semaine sont éparpillées entre de nombreuses adresses.
 
**2. Moment et durée de cette activité**
 
Requêtes de `203.0.113.66` par code de réponse :
 
| Code | Requêtes | Première | Dernière |
| --- | --- | --- | --- |
| **404** | **300** | **26/09 03:12 UTC** | **26/09 03:16 UTC** |
| 200 | 24 | 23/09 | 28/09 |
| 201 | 2 | 25/09 | 26/09 |
| 304 | 1 | 25/09 | 25/09 |
 
Les 300 requêtes en 404 ont eu lieu le **samedi 26 septembre 2026, entre 03:12 et 03:16 UTC, soit entre 05:12 et 05:16 à Paris** : environ **4 minutes**, plus d'une requête par seconde, en pleine nuit. C'est ce qui explique le léger excédent de trafic du 26/09 relevé à l'exercice 4.1.
 
**3. Les URL demandées : que cherchait ce robot ?**
 
Les 300 requêtes portent sur seulement **6 URL**, qui n'existent pas sur le site :
 
| URL | Requêtes | Ce que le robot cherche |
| --- | --- | --- |
| `/admin` | 59 | une interface d'administration |
| `/.git/config` | 55 | un dépôt Git exposé, qui permettrait de télécharger le code source |
| `/.env` | 53 | un fichier de variables d'environnement : mots de passe, clés d'API (comme notre propre `.env`) |
| `/phpmyadmin/` | 46 | l'outil d'administration de bases de données MySQL |
| `/server-status` | 44 | la page d'état d'Apache, qui révèle la configuration et les requêtes en cours |
| `/wp-login.php` | 43 | la page de connexion de WordPress, cible d'attaques par mots de passe |
 
C'est un **scanner de vulnérabilités** automatique : il teste une liste de chemins connus pour trouver une faille de configuration, un secret oublié ou une interface d'administration mal protégée. Ces requêtes n'ont rien à voir avec l'activité du site de recrutement. Toutes ont reçu une 404 : le site n'exposait aucune de ces ressources, l'attaque a échoué.
 
**4. Son `user_agent.original` : comment le distinguer d'un navigateur ?**
 
`Mozilla/5.0 zgrab/0.x`, que le filtre `useragent` ne reconnaît pas (`user_agent.name` : `Other`).
 
**zgrab** est un outil de scan massif d'Internet (projet ZMap). Le préfixe `Mozilla/5.0` est un leurre que tous les navigateurs utilisent, mais la suite ne ressemble à aucun navigateur : pas de système d'exploitation, pas de moteur de rendu (`AppleWebKit`, `Gecko`), pas de version de navigateur. Un vrai navigateur annonce par exemple `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36`.
 
Son **comportement** le trahit aussi : des centaines de requêtes en quelques minutes, uniquement des chemins techniques sans lien avec le site, aucun chargement de page normale ni de fichier statique, en pleine nuit.
 
Remarque importante : la même adresse `203.0.113.66` a aussi fait **27 requêtes légitimes** pendant la semaine (fiches d'offres, recherches, 2 candidatures), avec de vrais navigateurs (Safari sur iPhone et Mac, Chrome sous Windows et Android, Firefox sous Linux). Une adresse IP peut être **partagée** entre plusieurs personnes (box familiale, réseau d'entreprise, opérateur mobile). Il faut donc identifier le robot par la **combinaison** adresse + navigateur + comportement : bloquer l'adresse seule empêcherait aussi de vrais candidats d'accéder au site.
 
**Toutes les 404 ne viennent pas de ce robot : d'où viennent les autres, et sont-elles inquiétantes ?**
 
Les **208 autres 404** portent toutes sur des **fiches d'offres** dont l'identifiant n'existe pas, par exemple `/offres/OFF-09223`, `/offres/OFF-09347`, `/offres/OFF-09620`. Chaque URL n'est demandée que 2 ou 3 fois, par autant d'adresses différentes, avec des navigateurs ordinaires.
 
L'index `offres` ne contient que les identifiants `OFF-00001` à `OFF-05000` : ces identifiants en `OFF-09xxx` correspondent sans doute à des **offres expirées ou retirées**. Les visiteurs arrivent par d'anciens liens (favoris, partage sur un réseau social, moteur de recherche, alerte e-mail) qui pointent vers une offre qui n'existe plus.
 
Ces 404 **ne sont pas inquiétantes** du point de vue de la sécurité : ce sont de vrais visiteurs, en petit nombre, sur des URL du site. Elles signalent en revanche un **problème d'expérience utilisateur et de référencement** : on pourrait renvoyer un code **410 (Gone)** pour indiquer aux moteurs de recherche que l'offre a définitivement disparu, et afficher une page proposant des offres similaires plutôt qu'une simple erreur.
 
### Exercice 4.4 — Les offres les plus consultées
 
Top 10 des offres consultées (requêtes `GET` avec code 200, regroupées par `labels.offre_id`), puis détails récupérés dans l'index `offres` avec une seule requête `ids` dans Dev Tools :
 
| Rang | Offre | Vues | Titre | Ville | Contrat |
| --- | --- | --- | --- | --- | --- |
| 1 | OFF-04662 | 8 | Développeur Front-end Senior | Bordeaux | Freelance |
| 2 | OFF-03141 | 7 | Développeur Python Confirmé | Bordeaux | CDI |
| 3 | OFF-01153 | 7 | Développeur Java Confirmé | Toulouse | Freelance |
| 4 | OFF-01660 | 6 | Architecte Cloud Senior | Lyon | CDI |
| 5 | OFF-01275 | 6 | Administrateur Bases de Données Lead | Paris | CDI |
| 6 | OFF-03524 | 6 | Développeur Python (Alternance) | Toulouse | Alternance |
| 7 | OFF-00901 | 6 | Développeur Java Junior | Paris | CDI |
| 8 | OFF-03126 | 6 | Administrateur Bases de Données Junior | Lyon | CDI |
| 9 | OFF-03145 | 6 | Data Engineer Lead | Montpellier | CDI |
| 10 | OFF-03923 | 6 | Architecte Cloud Confirmé | Lyon | CDI |
 
Requête Dev Tools :
 
```text
GET offres/_search
{
  "size": 10,
  "query": {
    "ids": {
      "values": ["OFF-04662", "OFF-03141", "OFF-01153", "OFF-01660", "OFF-01275",
                 "OFF-03524", "OFF-00901", "OFF-03126", "OFF-03145", "OFF-03923"]
    }
  },
  "_source": ["id", "titre", "ville", "contrat"]
}
```
 
La requête `ids` cherche directement par `_id`. Elle fonctionne parce que, grâce au `document_id => "%{id}"` du pipeline `offres` (partie 1), l'`_id` de chaque document est l'identifiant métier de l'offre, le même que celui extrait des URL dans `labels.offre_id`. C'est un exemple concret de l'intérêt d'un identifiant métier : il fait le lien entre les deux jeux de données. Les résultats ne sont pas renvoyés dans l'ordre de la liste (score identique de 1 pour tous) : le classement par vues vient de la requête ES|QL.
 
Observations :
 
- Les écarts sont **très faibles** (6 à 8 vues sur la semaine) : le trafic est réparti sur des milliers d'offres, sans offre qui se détache nettement. Plusieurs offres sont probablement à égalité à 6 vues : le `LIMIT 10` n'en retient que certaines, ce classement est donc à prendre avec prudence à partir de la 4e place.
- Les profils les plus consultés sont surtout des postes de **développement** (Python, Java, front-end), puis le cloud, les bases de données et la data.
- Côté contrats, 7 CDI, 2 missions en freelance (dont les deux premières places de l'offre front-end et de l'offre Java) et 1 alternance.
- Les villes sont variées : Lyon (3), Bordeaux, Toulouse et Paris (2 chacune), Montpellier (1).

### Exercice 4.5 — Le public
 
**Répartition par système d'exploitation (`user_agent.os.name`)**
 
| Système | Requêtes | Type d'appareil |
| --- | --- | --- |
| Mac OS X | ≈ 4 150 | ordinateur |
| iOS | ≈ 4 100 | mobile |
| Windows | ≈ 4 060 | ordinateur |
| Android | ≈ 4 060 | mobile |
| Linux | ≈ 4 040 | ordinateur |
| Other | 300 | robot `zgrab` (exercice 4.3) |
 
(Kibana arrondit les valeurs au-delà de 1 000.)
 
**Quelle part du trafic provient d'appareils mobiles ?**
 
Les appareils mobiles (iOS et Android) totalisent **≈ 8 150 requêtes sur 20 700, soit environ 39 %** du trafic. Les ordinateurs (Mac OS X, Windows, Linux) en représentent environ 60 %, et le robot `zgrab` les 300 requêtes restantes (« Other », 1,5 %). Si l'on ne compte que les visiteurs humains (20 400 requêtes), la part mobile est d'environ **40 %**.
 
Requête utilisée : `EVAL mobile = user_agent.os.name IN ("Android", "iOS")` puis `STATS … BY mobile` → `true` ≈ 8 150, `false` ≈ 12 540.
 
Conséquence pratique : deux visites sur cinq se font sur téléphone, le site de recrutement et le parcours de candidature doivent être parfaitement utilisables sur mobile.
 
**Quels sont les trois navigateurs les plus utilisés ?**
 
| Rang | Navigateur (`user_agent.name`) | Requêtes |
| --- | --- | --- |
| 1 | Safari (Mac) | ≈ 4 150 |
| 2 | Mobile Safari (iPhone) | ≈ 4 100 |
| 3 | Chrome (ordinateur) | ≈ 4 060 |
 
Les écarts sont minimes : le trafic est réparti presque à parts égales entre cinq navigateurs, chacun associé à un système (Safari sur Mac, Mobile Safari sur iPhone, Chrome sur Windows, Chrome Mobile sur Android, Firefox sous Linux), environ 20 % chacun. Chrome Mobile (≈ 4 060) est d'ailleurs pratiquement à égalité avec Chrome.
 
Le classement dépend donc de la façon de regrouper : `useragent` distingue les versions ordinateur et mobile d'un même navigateur. En les regroupant par **famille**, Chrome (ordinateur et mobile, ≈ 8 100 requêtes) et Safari (Mac et iPhone, ≈ 8 250) arrivent largement en tête, devant Firefox (≈ 4 040).
 
Une répartition aussi régulière est typique de données **générées** pour le TP ; sur un vrai site, Chrome dominerait nettement.
