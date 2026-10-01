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
