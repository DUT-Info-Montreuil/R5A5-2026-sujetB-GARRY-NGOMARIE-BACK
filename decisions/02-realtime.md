# 02 - Mecanisme temps reel

## Probleme

Deux besoins du sujet imposent une mise a jour sans rechargement de page :

- B-16 : l'espace d'echange d'une equipe ; les messages doivent apparaitre
  chez les autres membres sans action de leur part.
- B-19 : le suivi de tournoi ; joueurs et spectateurs voient la progression
  (bracket, resultats) se mettre a jour en direct.

B-16 est bidirectionnel (on lit et on ecrit dans le meme fil). B-19 est une
diffusion (le serveur pousse, le client ne fait qu'ecouter). Il faut aussi
pouvoir couper l'acces d'un client en cours de session : un joueur exclu (B-17)
ou une equipe eliminee (B-18) perdent l'espace immediatement.

Le deploiement est fait par un tiers, sur un hote inconnu : la solution doit
tenir sans service externe ni infrastructure supplementaire.

## Options considerees

- **Polling REST** : le client redemande l'etat toutes les N secondes. Aucune
  techno nouvelle, mais latence visible, charge inutile, et surtout ne repond
  pas a "sans rechargement" de facon honnete pour un chat.
- **Server-Sent Events (SSE)** : diffusion serveur vers client simple et
  robuste, mais unidirectionnel. Il faudrait un canal REST separe pour l'envoi
  des messages (B-16) : deux mecanismes a documenter et tester.
- **Socket.IO** : gere les salles et la reconnexion, mais ajoute une
  dependance (client + serveur), un protocole propre au-dessus du WebSocket,
  et une surface a apprendre que le budget temps ne justifie pas.
- **WebSocket natif (FastAPI/Starlette)** : bidirectionnel, un seul mecanisme
  pour les deux besoins, supporte directement par le framework, aucune
  dependance ajoutee. Les salles et la reconnexion sont a ecrire nous-memes,
  mais restent simples pour notre perimetre.

## Decision

**WebSocket natif**, via un gestionnaire de connexions unique
(`app/realtime/manager.py`).

- Salles nommees `team:<id>` (B-16) et `tournament:<id>` (B-19).
- Socket authentifie a la connexion avec le meme JWT que le REST (passe en
  query, un navigateur ne posant pas d'en-tete sur un WebSocket).
- L'appartenance est reverifiee en base a chaque message : aucune autorisation
  mise en cache, donc exclusion (B-17) et elimination (B-18) prennent effet a
  la trame suivante. Le serveur ferme en plus le socket concerne (`revoke`).
- La diffusion est une notification ; l'ecriture en base fait foi. Un client
  qui a manque des messages les recupere via REST (`GET .../messages`).
- Messages types et documentes dans `docs/api-realtime.md` a cote du REST.

## Ce que ca coute

- Le gestionnaire de salles, l'authentification du socket et la revocation
  sont du code maison a maintenir (pas de brique toute faite).
- Pas de reconnexion automatique cote serveur : c'est au client de rouvrir le
  socket et de rattraper l'historique par REST.
- Une connexion WebSocket garde une session de base ouverte pour sa duree de
  vie ; une transaction de lecture peut rester `idle in transaction` entre deux
  messages. Acceptable a notre echelle ; a retravailler (session par operation)
  si le nombre de sockets simultanes grandit.
- Un deploiement derriere un proxy doit autoriser l'`Upgrade` WebSocket (a
  noter dans la documentation d'exploitation).
