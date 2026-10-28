# API cycle de vie et competition

Routes REST des etats du tournoi, du tableau et des resultats (B-03, B-04,
B-12 a B-15). Le contrat exact (schemas, codes) est dans l'OpenAPI de FastAPI
(`/docs`) ; ce document donne les regles. Les notifications temps reel sont
decrites dans `api-realtime.md`, section `tournament:<id>`.

## Etats du tournoi

```
registration_open --close-registration--> registration_closed --start--> running --(finale validee)--> finished
```

Les transitions sont reservees a l'administrateur et relues en base : un appel
depuis un autre etat est refuse (`409`). Il n'y a pas de retour en arriere.

## Routes

| Methode | Route | Acces | Effet |
|---|---|---|---|
| `POST` | `/api/v1/tournaments/{id}/close-registration` | admin | Ferme les inscriptions, fige les equipes (B-11) et construit le tableau (B-12). |
| `POST` | `/api/v1/tournaments/{id}/start` | admin | Lance le tournoi (B-04). |
| `GET` | `/api/v1/tournaments/{id}/matches` | public | Tableau complet, trie par tour puis numero (B-02). |
| `POST` | `/api/v1/tournaments/{id}/matches/{match_id}/result` | admin | Saisit le score ; le vainqueur avance (B-13, B-14). |
| `POST` | `/api/v1/tournaments/{id}/matches/{match_id}/forfeit` | admin | Declare un forfait ; l'adversaire est qualifie (B-15). |

Corps de `result` : `{ "team1_score": 0..1000, "team2_score": 0..1000 }`.
Corps de `forfeit` : `{ "forfeiting_team_id": "uuid" }`.

## Codes d'erreur

| Code | Cas |
|---|---|
| `401` / `403` | Non authentifie / appelant non admin |
| `404` | Tournoi ou match inconnu, ou match d'un autre tournoi |
| `400` | Moins de 2 equipes a la cloture ; egalite au score ; equipe du forfait absente du match |
| `409` | Mauvais etat du tournoi ; match non jouable (equipe inconnue, ou deja valide) |

## Construction du tableau (B-12)

Elimination directe. Taille = plus petite puissance de deux >= N equipes
engagees (N >= 2). Les `taille - N` byes vont aux premieres equipes inscrites :
une equipe en bye a un match de tour 1 sans adversaire, deja `completed`, et
figure des la cloture dans le match du tour 2. `next_match_id` et
`next_match_slot` indiquent ou avance le vainqueur.

## Etats d'un match

| Etat | Sens |
|---|---|
| `pending` | Une equipe manque, ou le tournoi n'est pas lance. Non jouable. |
| `in_progress` | Deux equipes connues, tournoi en cours. Seul etat qui accepte un resultat ou un forfait. |
| `completed` | Resultat valide (ou bye). Definitif : un resultat valide ne se corrige pas. |
| `forfeit` | Termine par forfait. |

## Forfait automatique (B-04)

Une equipe de moins de 5 joueurs perd son premier vrai match (un bye ne compte
pas comme un match) : l'adversaire est qualifie et le match passe en `forfeit`.
Si les deux equipes sont incompletes, celle qui a le plus de joueurs avance ;
a egalite le match reste `in_progress` et l'admin tranche par un resultat ou un
forfait.

## Elimination

Le perdant d'un match (resultat ou forfait) est marque `is_eliminated` dans la
meme transaction. Son espace d'echange se ferme aussitot : les membres sont
refuses (lecture et ecriture), l'admin garde la lecture (B-18), et leurs
sockets ouverts sont coupes.

## Choix valides (le sujet ne les precise pas)

- Un score a egalite est refuse : un match d'elimination directe a un vainqueur.
- La fin du tournoi est implicite : la validation de la finale passe l'etat a
  `finished`.
- Une equipe en bye compte son premier vrai match (et non le bye) comme son
  premier match pour la regle du forfait automatique.
