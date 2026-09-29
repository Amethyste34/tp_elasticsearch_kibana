# TP Elasticsearch — Réponses aux questions

## Exercice 0 — Vérifier l'accès au cluster

**Les réponses sont-elles identiques d'un outil à l'autre ?**
Oui. Kibana Dev Tools et curl renvoient le même contenu (nœud `es01`, cluster `tp-eisi`, même `cluster_uuid`, version 9.5.4). Les deux outils interrogent la même API REST ; seule la mise en forme du JSON diffère légèrement.

**Quel code HTTP sans authentification, et que dit le message d'erreur ?**
Code **401** (non authentifié). Elasticsearch renvoie une `security_exception` : « missing authentication credentials for REST request [/] ».
Avec un mauvais mot de passe, le code est aussi 401 mais le message diffère : « unable to authenticate user [elastic] ». Dans le premier cas les identifiants manquent, dans le second ils sont faux.

**Pourquoi Kibana n'a-t-il pas besoin du mot de passe à chaque requête ?**
Je me suis connectée une fois à Kibana, qui conserve ma session. Kibana transmet lui-même mes identifiants à Elasticsearch pour chaque requête envoyée depuis Dev Tools.
