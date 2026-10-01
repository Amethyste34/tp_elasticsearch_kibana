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
