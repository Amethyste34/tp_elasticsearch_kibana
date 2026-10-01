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
