# Gmail en second compte IMAP — design

Date : 2026-09-28. Périmètre : classer le **courrier neuf** de `fred.jacquet@gmail.com` dans les 19 catégories, avec le même flux que la boîte Infomaniak (dossiers d'action, archivage, apprentissage depuis `9-A revoir`).

## Contexte

- La taxonomie est active pour Infomaniak (PR #42) et les anciens dossiers sont migrés (PR #43).
- Le chemin Gmail existant passe par l'API Gmail (OAuth, `credentials.json`), n'a jamais été configuré, et `run` y désactive la taxonomie.
- Gmail parle IMAP (toujours actif depuis janvier 2025) ; avec la validation en deux étapes, un **mot de passe d'application** suffit. Les libellés Gmail apparaissent comme des dossiers IMAP.

## Décisions

- **Accès** : IMAP + mot de passe d'application (pas l'API).
- **Courrier neuf seulement** : pas de `scan`, `migrate` ni `prune` sur Gmail ; les anciens libellés ne sont jamais touchés.
- **Approche** : une section `[gmail_imap]` dans `config.toml`, qui réutilise `ImapService` et tout le flux taxonomie. Pas de liste générique de comptes.

## Design

### Configuration

```toml
[gmail_imap]
host = "imap.gmail.com"
user = "${GMAIL_IMAP_USER}"
password = "${GMAIL_IMAP_PASSWORD}"
use_gmail_extensions = true
junk_folder_name = "[Gmail]/Spam"
pending_archive_file = "db/pending_archive_gmail.json"
```

- `user` et `password` viennent de `.env` (`GMAIL_IMAP_USER`, `GMAIL_IMAP_PASSWORD`), comme `IMAP_USER`/`IMAP_PASSWORD`.
- Section absente ou identifiants manquants : pas de compte Gmail, aucun message d'erreur au chargement (le compte Infomaniak reste obligatoire comme aujourd'hui).
- `junk_folder_name` et `pending_archive_file` sont propres au compte ; le compte Infomaniak garde `[fast_parse] junk_folder_name` et `[taxonomy] pending_archive_file`.

### Ce qui est partagé, ce qui est séparé

| | Partagé | Par compte |
|---|---|---|
| Règles `db/taxonomy/` (validés, appris, domaines) | oui : une règle d'expéditeur vaut pour les deux boîtes ; le verrou `flock` gère les écritures | |
| Centroïdes nomic, Gemma | oui | |
| `pending_archive` | | **oui** : l'archivage d'un compte ne voit pas les mails de l'autre et supprimerait leurs entrées comme orphelines |
| Dossier indésirables | | oui (`Junk` / `[Gmail]/Spam`) |
| `data/imap_folders.json` (rafraîchi au démarrage) | | **pas rafraîchi pour Gmail** : il décrit l'arborescence Infomaniak |

### Flux

- `run --provider gmail` : Pass 1 sur `[Gmail]/Spam` puis INBOX, règles de `db/taxonomy/`, puis nomic/Gemma, dossiers d'action, balayage d'archivage avec `db/pending_archive_gmail.json`.
- `run --provider all` : Infomaniak puis Gmail (le chemin API Gmail n'est plus appelé par le CLI ; son code reste, signalé comme inutilisé).
- Côté Gmail, « déplacer » vers un dossier = retirer le libellé source et poser le libellé cible ; le mail reste dans « Tous les messages ». Les libellés des dossiers d'action et des catégories sont créés à la demande (`batch_move_emails`).
- `--validate` : lecture seule, comme pour Infomaniak.

### Hors périmètre

- Anciens libellés Gmail, onglets Gmail (Promotions, Réseaux sociaux), API Gmail, `serve` (webhook) pour Gmail.

## Tests

- Config : section `[gmail_imap]` lue avec substitution `.env` ; absente ou incomplète → pas de compte Gmail.
- CLI : `--provider gmail` construit un `ImapService` avec la config Gmail ; `all` lance les deux comptes ; Gmail ne rafraîchit pas `data/imap_folders.json`.
- `run_classification` : chaque compte utilise son `pending_archive_file` et son dossier indésirables ; les deux partagent le même `TaxonomyStore`.

## Validation réelle

1. `run --provider gmail --validate` : connexion, part de mails classés, aucun mail déplacé.
2. Premier vrai `run --provider gmail`, puis vérification des libellés créés et de `db/pending_archive_gmail.json`.
