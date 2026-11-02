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
WS /api/v1/teams/{team_id}/ws
```

L'authentification est le cookie de session `session`, le meme que pour le REST :
le navigateur l'envoie a l'ouverture de la connexion, sans code cote client. Le
parametre `?token=` n'existe plus. L'en-tete `Origin` doit figurer dans
`ALLOWED_ORIGINS`, sinon la poignee de main est refusee (HTTP 403, pas de
connexion) : cela empeche une page tierce d'ouvrir le socket avec le cookie de
l'utilisateur.

Le socket est **bidirectionnel** : le client peut envoyer des messages et en
recevoir. L'ecriture passe par le meme service que le `POST` REST (memes
gardes, meme ecriture en base, puis diffusion).

#### Cycle de vie

1. Le serveur accepte la connexion puis verifie la session et l'appartenance a
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
| `4401` | Session absente, invalide ou expiree |
| `4403` | Authentifie mais pas membre de l'equipe, ou acces retire en cours de session |
| `4404` | Equipe inconnue |

## Salle `tournament:<id>` (B-19)

```
WS /api/v1/tournaments/{tournament_id}/ws
```

Suivi public, en lecture seule : aucune session requise (un visiteur voit la
progression, B-02/B-19). L'en-tete `Origin` doit tout de meme figurer dans
`ALLOWED_ORIGINS`. Le serveur ignore toute trame envoyee par le client. Codes de
fermeture : `4403` origine refusee, `4404` tournoi inconnu.

A la connexion : `{ "type": "system", "event": "connected", "room": "tournament:<id>" }`.
Les evenements sont diffuses apres validation en base (la base fait foi ; un
client qui a rate un evenement relit `GET /api/v1/tournaments/{id}/matches`).

| `type` | `event` | `data` | Emis quand |
|---|---|---|---|
| `tournament` | `status_changed` | `{ "tournament_id": "uuid", "status": "registration_closed / running / finished" }` | Cloture des inscriptions (B-03), demarrage (B-04), fin du tableau |
| `tournament` | `match_updated` | un match (meme forme que `GET .../matches`) | Resultat (B-13), forfait (B-15), forfait automatique (B-04) |

Quand une equipe est eliminee, ses membres connectes a `team:<id>` recoivent
`system` / `revoked` (`reason: "eliminated"`) puis le socket est ferme (B-18).
Details des routes : `docs/api-competition.md`.

## Limite connue

Le socket conserve une session de base pour toute sa duree de vie. Entre deux
messages, une transaction de lecture peut rester ouverte (connexion
`idle in transaction` cote PostgreSQL). Acceptable a l'echelle du projet ;
correctif possible : une session par operation, ou un reglage du pool.
