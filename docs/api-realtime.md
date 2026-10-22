# API temps reel (WebSocket)

Complement a la documentation OpenAPI (REST). Decrit le canal WebSocket et les
messages echanges. Le mecanisme et sa justification sont dans
`decisions/02-realtime.md`.

Principe : la base de donnees fait foi, le WebSocket n'est qu'une notification.
Un client qui a manque des messages les recupere via les routes REST.

## Espace d'echange d'equipe (B-16, B-17, B-18)

### REST (repli et historique)

| Methode | Route | Acces | Reponse |
|---|---|---|---|
| `GET` | `/api/v1/teams/{team_id}/messages` | membre courant de l'equipe, ou admin | `200` liste de messages (ordre chronologique, limite `chat_history_limit`) |
| `POST` | `/api/v1/teams/{team_id}/messages` | membre courant ; equipe non eliminee | `201` le message cree (aussi diffuse sur le WebSocket) |

Corps du `POST` : `{ "content": "<texte>" }` (1 a `chat_message_max_length`
caracteres apres `strip`).

Forme d'un message (REST et champ `data` du WebSocket) :

```json
{
  "id": "uuid",
  "team_id": "uuid",
  "author_id": "uuid | null",
  "author_username": "string | null",
  "content": "string",
  "created_at": "ISO-8601"
}
```

### WebSocket

```
WS /api/v1/teams/{team_id}/ws?token=<JWT>
```

Le jeton est le meme que pour le REST. Il passe en parametre de requete car un
navigateur ne peut pas poser d'en-tete `Authorization` sur une connexion
WebSocket.

Le socket est **bidirectionnel** : le client peut envoyer des messages et en
recevoir. L'ecriture passe par le meme service que le `POST` REST (memes
gardes, meme ecriture en base, puis diffusion).

#### Cycle de vie

1. Le serveur accepte la connexion puis verifie le jeton et l'appartenance a
   l'equipe (relue en base).
2. En cas de refus : une trame `error` est envoyee, puis le socket est ferme
   avec un code applicatif (voir table). Aucune inscription a la salle.
3. En cas de succes : trame `system` / `connected`, puis le client est inscrit
   a la salle `team:<team_id>`.
4. A chaque message publie dans l'equipe (REST ou WebSocket), une trame
   `message` est diffusee a tous les sockets de la salle, emetteur inclus.
5. Exclusion (B-17) ou elimination d'equipe (B-18) : le serveur envoie une
   trame `system` / `revoked` puis ferme le socket (code `4403`). Cote
   `POST`/trame entrante, l'acces est de toute facon reverifie en base a
   chaque message : aucune autorisation mise en cache.

#### Client vers serveur

| `type` | Charge | Effet |
|---|---|---|
| `message` | `{ "type": "message", "content": "<texte>" }` | Publie un message. Memes regles que le `POST` REST. |

Toute autre trame recoit une reponse `error` et est ignoree.

#### Serveur vers client

| `type` | Exemple | Sens |
|---|---|---|
| `system` | `{ "type": "system", "event": "connected", "room": "team:<id>" }` | Connexion etablie et inscrite. |
| `message` | `{ "type": "message", "data": { ...message... } }` | Nouveau message dans l'equipe. |
| `system` | `{ "type": "system", "event": "revoked", "reason": "excluded" }` | Acces retire ; le socket se ferme juste apres. `reason` : `excluded`, `left`, `disbanded`, `eliminated`. |
| `error` | `{ "type": "error", "detail": "<texte>" }` | Trame refusee (non reconnue, message vide ou trop long, equipe eliminee, non-membre). |

#### Codes de fermeture applicatifs

| Code | Signification |
|---|---|
| `4401` | Jeton absent ou invalide |
| `4403` | Authentifie mais pas membre de l'equipe, ou acces retire en cours de session |
| `4404` | Equipe inconnue |

## Salle `tournament:<id>` (B-19)

Le gestionnaire de connexions (`app/realtime/manager.py`) gere deja des salles
`tournament:<id>` pour le suivi public temps reel. Aucun producteur ne diffuse
encore sur ces salles : le suivi de tournoi sera branche avec la construction du
bracket et l'entree des resultats (B-12, B-14, B-15, B-19).

## Limite connue

Le socket conserve une session de base pour toute sa duree de vie. Entre deux
messages, une transaction de lecture peut rester ouverte (connexion
`idle in transaction` cote PostgreSQL). Acceptable a l'echelle du projet ;
correctif possible : une session par operation, ou un reglage du pool.
