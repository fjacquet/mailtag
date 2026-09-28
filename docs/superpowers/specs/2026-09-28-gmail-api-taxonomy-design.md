# Gmail par l'API dans le mode taxonomie — design

Date : 2026-09-28. Remplace le passage par IMAP de la PR #44 pour Gmail.

## Contexte

- Infomaniak : taxonomie active, dossiers PARA (`Domaines/`, `Ressources/`, `Archive/`), dossiers d'action `1-A traiter` à `5-A revoir`, `Promotions` standard (PR #45, #46).
- Règle du propriétaire : quand un de nos dossiers fait doublon avec un standard du fournisseur, on fusionne et on réutilise le standard ; sinon on garde notre logique.
- Test sur le compte Gmail (phase B) : l'API expose `CATEGORY_PROMOTIONS` et accepte de la poser puis de la retirer (vérifié sur un mail, état restauré). L'onglet « Purchases » n'est **pas** exposé par l'API : pas de fusion pour Achats.
- IMAP ne peut pas poser les catégories Gmail : d'où l'API (OAuth, `credentials.json` + `token.json`, portée `gmail.modify`, déjà en place).

## Décisions

- Gmail passe par l'**API Gmail** ; le chemin IMAP Gmail (`[gmail_imap]`, PR #44) est retiré.
- **Tout le stock** de la boîte de réception (6 701 mails) est traité, **après un essai à blanc** (`run --provider gmail --validate`).
- Même flux que pour Infomaniak : règles partagées `db/taxonomy/`, nomic puis Gemma, dossiers d'action, archivage des mails lus de plus de 7 jours, apprentissage depuis `5-A revoir`.

## Correspondance des dossiers

| MailTag | Gmail |
|---|---|
| `INBOX` | libellé système `INBOX` |
| dossier indésirables | libellé système `SPAM` |
| `Promotions` | **catégorie `CATEGORY_PROMOTIONS`** (le mail reste dans la boîte de réception, onglet Promotions) |
| `1-A traiter`, `2-A payer`, `3-A lire`, `4-Pour info`, `5-A revoir` | libellés utilisateur de ce nom, créés à la demande |
| `Domaines/…`, `Ressources/…`, `Archive/…` | libellés utilisateur imbriqués de ce nom, créés à la demande |
| `Archive/Achats` | libellé utilisateur (pas de fusion : Purchases absent de l'API) |

« Déplacer » un mail du dossier S vers le dossier D :
- D = `Promotions` : ajouter `CATEGORY_PROMOTIONS`, retirer les autres `CATEGORY_*` ; retirer S s'il s'agit d'un libellé utilisateur ; garder `INBOX`.
- Autre D : ajouter le libellé D ; retirer S (`INBOX`, `SPAM` ou le libellé utilisateur). Quitter `INBOX` = archiver au sens Gmail ; le mail reste dans « Tous les messages ».
- Les autres libellés du mail (les tiens : `github`, `TRAVELS`…) ne sont jamais touchés.

## Architecture

Le flux taxonomie (`utils/tasks.py`, `routing.py`, `archive.py`) n'utilise qu'une petite surface du fournisseur IMAP : `client.select_folder`, `client.search` (`ALL`, `SEEN UNFLAGGED BEFORE <date>`, `HEADER Message-ID <id>`), `client.fetch` (en-tête Message-ID), `client.folder_exists`, `get_email_headers`, `get_full_emails`, `batch_move_emails`, `get_folder_hierarchy`, `config`, `fast_parse_config`.

Nouveau module `src/mailtag/gmail_api.py` :
- `GmailLabelClient` : cette surface « client » traduite en appels API. Le dossier sélectionné devient un libellé ; les recherches deviennent des requêtes Gmail (`label:… is:read -is:starred before:AAAA/MM/JJ`, `rfc822msgid:…`) ; les UID sont les identifiants de message Gmail.
- `GmailApiService` : `connect()` (OAuth via `gmail_auth.get_gmail_service`), `client`, `get_email_headers` (métadonnées From, Subject, Message-ID, List-Unsubscribe, Precedence, par lots), `get_full_emails` (corps texte), `batch_move_emails` (règles ci-dessus, `batchModify` par lots de 1 000), `get_folder_hierarchy` (libellés), `config`, `fast_parse_config`.
- `tasks.py`, `routing.py` et `archive.py` restent inchangés, à part accepter ce fournisseur là où ils testent `ImapService` (un type commun ou un test « a un `client` »).

Configuration (`[gmail]`, déjà présente) : `credentials_file`, `token_file`, plus `pending_archive_file = "db/pending_archive_gmail.json"`, `junk_folder_name = "SPAM"`, `folder_cache_file = "data/gmail_labels.json"`.

CLI : `run --provider gmail` = `GmailApiService` ; `all` = Infomaniak puis Gmail. Le chemin IMAP Gmail (`[gmail_imap]`, `.env` `GMAIL_IMAP_*`) est retiré ; le mot de passe d'application Google peut être révoqué.

## Volumes et quotas

- 6 701 mails : métadonnées par lots (requêtes groupées), corps seulement pour les mails que les règles ne classent pas (passage 3), comme pour IMAP.
- Quota Gmail par utilisateur ample pour ce volume ; une erreur 429 ou 5xx est retentée avec attente (`googleapiclient` `num_retries`).
- L'essai à blanc donne le nombre de mails par dossier d'action et par catégorie, et la durée.

## Hors périmètre

- Anciens libellés utilisateur, onglets Réseaux sociaux / Mises à jour / Forums (pas de doublon avec nos catégories), `serve` (webhook) pour Gmail, passage de l'app OAuth « en production » (jeton de 7 jours en mode test : réautorisation par le navigateur).

## Tests

- `GmailLabelClient` : traduction des recherches (`ALL`, `SEEN UNFLAGGED BEFORE`, `HEADER Message-ID`) en requêtes ; `folder_exists` ; pagination.
- `batch_move_emails` : vers une catégorie PARA (ajoute le libellé, retire `INBOX`), vers `Promotions` (catégorie, `INBOX` gardé), depuis un libellé d'action, depuis `SPAM` ; libellé créé à la demande ; libellés étrangers intacts.
- `get_email_headers` : champs attendus par `RoutedMail.from_headers`.
- `run_classification` et `run_archive` sur un faux service Gmail : flux complet sans IMAP.
- CLI : `--provider gmail` construit `GmailApiService` ; `[gmail_imap]` n'existe plus.

## Validation réelle

1. `run --provider gmail --validate` : aucun libellé modifié ; rapport de répartition.
2. Feu vert du propriétaire, puis premier vrai `run --provider gmail` (lancé par lui).
3. Vérification en lecture seule : boîte de réception, libellés créés, `db/pending_archive_gmail.json`.
