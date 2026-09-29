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
