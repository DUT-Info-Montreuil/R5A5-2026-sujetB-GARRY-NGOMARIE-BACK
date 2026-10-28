# API - Authentification et session

Deux façons d'ouvrir une session : un compte local (identifiant, email, mot de passe)
ou un compte Discord. Dans les deux cas le résultat est le même cookie de session et les
mêmes rôles ; aucun jeton Bearer n'est accepté.

## Compte local

- `POST /api/v1/auth/register` crée le compte et ouvre la session (cookie posé).
- `POST /api/v1/auth/login` ouvre la session avec l'identifiant **ou** l'email.
- Le mot de passe est haché avec Argon2 ; il n'est jamais stocké ni renvoyé en clair.
- Les identifiants sont uniques sans tenir compte de la casse, y compris face aux
  comptes Discord (sinon la connexion par identifiant serait ambiguë).
- Échec de connexion : même réponse `401` que le compte existe ou non, et même coût de
  calcul (vérification contre un hash factice) pour ne pas révéler les comptes.
- Limitation : `LOGIN_MAX_FAILURES` échecs par couple (adresse IP, identifiant) sur
  `LOGIN_WINDOW_SECONDS` secondes, puis `429`. Le compteur est en mémoire, propre à
  chaque processus : avec plusieurs workers la limite effective est multipliée.
- Ces deux routes n'ont pas encore de cookie : elles exigent donc elles-mêmes un en-tête
  `Origin` autorisé (sinon `403`), pour qu'une page tierce ne puisse pas connecter le
  visiteur à un compte choisi par l'attaquant.
- Un compte Discord n'a pas de mot de passe : aucune tentative par mot de passe ne
  peut l'ouvrir.

## Compte Discord

1. Le navigateur ouvre `GET /api/v1/auth/discord/login`. Le serveur génère un `state`
   et un vérifieur PKCE, les place dans un cookie court (10 min, `HttpOnly`, limité
   au chemin `/api/v1/auth/discord`) et redirige vers Discord (scope `identify`).
2. Discord renvoie sur `GET /api/v1/auth/discord/callback?code=...&state=...`. Le
   serveur vérifie le `state`, échange le `code` contre un jeton d'accès (le secret
   client ne quitte jamais le serveur), puis lit le profil (`GET /users/@me`). Le jeton
   Discord n'est ni stocké ni renvoyé au navigateur.
3. Le serveur retrouve ou crée l'utilisateur (clé : identifiant Discord), ouvre une
   session en base et pose le cookie `session` (`HttpOnly`, `Secure`, `SameSite`),
   puis redirige vers `FRONTEND_URL`.

Aucun email n'est demandé ni stocké : l'identité est l'identifiant Discord (numérique,
stable), le nom d'affichage est le nom d'utilisateur Discord (suffixé si déjà pris).

Le cookie contient une valeur aléatoire opaque. La base ne stocke que son hash SHA-256
(table `user_sessions`). À chaque requête, la session et le rôle sont relus en base :
déconnexion, expiration ou changement de rôle prennent effet immédiatement.

## Rôles

| Rôle | Comment on l'obtient |
|---|---|
| visiteur | pas de cookie de session |
| player | tout compte connecté (local ou Discord) |
| admin | compte local dont l'identifiant figure dans `ADMIN_USERNAMES`, ou compte Discord dont l'identifiant figure dans `ADMIN_DISCORD_IDS` (recalculé à chaque connexion) |
| capitaine | propriété par équipe (`team.captain_id`), vérifiée dans les services |

Aucune route ne permet de choisir ou de modifier un rôle : un champ `global_role`
envoyé à l'inscription est ignoré. Pour un admin local, créer le compte dont le nom
figure dans `ADMIN_USERNAMES` juste après le déploiement : tant qu'il n'existe pas, ce
nom est libre et le premier inscrit sous ce nom serait admin. Retirer un nom de l'une
des deux listes retire le rôle admin à la prochaine connexion ; pour une révocation
immédiate, supprimer ses lignes de `user_sessions`. L'identifiant s'obtient dans Discord
avec le mode développeur (Paramètres > Avancés) puis clic droit sur le profil > Copier
l'identifiant.

## Endpoints

| Méthode | Chemin | Accès | Réponse |
|---|---|---|---|
| GET | `/api/v1/auth/discord/login` | public | 302 vers Discord ; 503 si Discord n'est pas configuré |
| GET | `/api/v1/auth/discord/callback` | public (exige le cookie `oauth_flow`) | 302 vers `FRONTEND_URL` + cookie `session` ; 400 requête invalide ; 401 identité Discord refusée |
| GET | `/api/v1/auth/me` | session | 200 `{id, username, global_role}` ; 401 |
| POST | `/api/v1/auth/register` | public, `Origin` autorisé | 201 `{id, username, global_role}` + cookie `session` ; 409 identifiant ou email pris ; 422 données invalides ; 403 origine refusée |
| POST | `/api/v1/auth/login` | public, `Origin` autorisé | 200 `{id, username, global_role}` + cookie `session` ; 401 identifiants incorrects ; 429 trop d'échecs ; 403 origine refusée |
| POST | `/api/v1/auth/logout` | session | 204, session supprimée côté serveur, cookie effacé ; 401 |

Codes communs à toute route protégée : `401` pas de session valide ; `403` rôle ou
propriété insuffisants, ou origine refusée (voir ci-dessous).

## Protection CSRF

Toute requête `POST`, `PATCH`, `PUT` ou `DELETE` portant un cookie de session doit
avoir un en-tête `Origin` figurant dans `ALLOWED_ORIGINS`, sinon `403`. Cela s'ajoute à
`SameSite` sur le cookie. Le front doit appeler l'API avec `credentials: "include"`.
Le WebSocket applique la même règle à l'ouverture (voir `api-realtime.md`).

## Variables d'environnement

| Variable | Défaut | Rôle |
|---|---|---|
| `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET` | vide | application créée dans le portail développeur Discord (OAuth2) |
| `DISCORD_REDIRECT_URI` | `http://localhost:8000/api/v1/auth/discord/callback` | doit être déclarée à l'identique dans le portail Discord |
| `ADMIN_DISCORD_IDS` | vide | identifiants Discord admin, séparés par des virgules |
| `ADMIN_USERNAMES` | vide | identifiants de comptes locaux admin, séparés par des virgules |
| `LOGIN_MAX_FAILURES` | `5` | échecs de connexion tolérés par (IP, identifiant) |
| `LOGIN_WINDOW_SECONDS` | `900` | fenêtre de comptage des échecs |
| `SESSION_COOKIE_NAME` | `session` | nom du cookie |
| `SESSION_TTL_MINUTES` | `1440` | durée de vie fixe d'une session |
| `SESSION_COOKIE_SECURE` | `true` | `false` uniquement en HTTP local |
| `SESSION_COOKIE_SAMESITE` | `lax` | `none` si front et API sont sur des domaines différents (exige `Secure`) |
| `FRONTEND_URL` | `http://localhost:5173` | destination après connexion |
| `ALLOWED_ORIGINS` | `["http://localhost:5173","http://localhost:3000"]` | CORS + contrôle CSRF |
