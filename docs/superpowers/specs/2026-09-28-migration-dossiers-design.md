# Migrer les anciens dossiers vers les 19 catégories — design

Suite des specs 1 et 2 (`2026-09-27-taxonomie-19-categories-design.md`, `2026-09-28-taxonomie-signaux-design.md`), qui ont posé les 19 catégories et les 6 signaux. Cette spec vide les 611 anciens dossiers dans les 19 catégories, puis supprime les dossiers devenus vides.

## Contexte

La taxonomie à 19 catégories est active (PR #42) : le courrier neuf va dans les dossiers d'action puis dans sa catégorie. Les ~29 000 mails déjà rangés restent dans les 611 anciens dossiers (`data/legacy_folders.json`), qui ne servent plus de destination. Les règles pour décider existent déjà (`db/taxonomy/` : 137 validés, 837 appris, 1 221 domaines, précision contrôlée 98 %), plus l'audit des dossiers (`db/taxonomy/folder_overrides.json`).

## Décisions

- **Catégorie d'un mail : la règle de l'expéditeur d'abord** (validé > appris > domaine), sinon la catégorie du dossier audité. Environ 1 783 mails (6 %) changent ainsi de destination par rapport à leur dossier actuel.
- **Dossiers « Aucune catégorie »** (14 dossiers, par exemple `Finance/Locale/BCV`, `Factures`, `SocialNetworks`) : règle de l'expéditeur, sinon **`9-A revoir`**, avec une entrée dans `db/pending_archive.json` pour apprendre la règle quand l'utilisateur range le mail.
- **Suppression des dossiers vides : commande séparée**, uniquement les dossiers **vides**, essai à blanc d'abord.

## Design

Deux commandes ajoutées à `scripts/taxonomy_setup.py` (même style que `scan`/`build` : essai à blanc par défaut) :

```
uv run python scripts/taxonomy_setup.py migrate            # plan seulement -> data/migration_report.json
uv run python scripts/taxonomy_setup.py migrate --apply    # déplace
uv run python scripts/taxonomy_setup.py prune              # liste les anciens dossiers vides
uv run python scripts/taxonomy_setup.py prune --apply      # les supprime
```

Nouveau module `src/mailtag/migration.py` :

- `folders_to_migrate(legacy: list[str]) -> list[str]` : anciens dossiers moins les protégés — les 19 catégories (`TAXONOMY`), les dossiers d'action (`ACTION_FOLDERS`), `INBOX` et les dossiers système (`_NOT_A_CATEGORY` de `taxonomy.py` : Sent, Trash, Spam, Promotions, À Classer, Archive…). `Contacts` est lui-même une catégorie : on migre `Contacts/<personne>`, jamais `Contacts`.
- `destination_for(sender, folder_category, rules, own) -> str` : adresse du propriétaire (`CONFIG.taxonomy.own_addresses`) → catégorie du dossier ; sinon `rules.category_for(sender)` (`TaxonomyStore.category_for`, `src/mailtag/taxonomy_store.py`) ; sinon catégorie du dossier ; sinon `REVIEW`.
- `migrate_folder(provider, folder, folder_category, rules, own, pending, today, apply, batch_size=500) -> Counter[str]` : nombre de mails par destination.
  - `select_folder(folder, readonly=not apply)`, `search(["ALL"])`, fetch par lots de `BODY.PEEK[HEADER.FIELDS (FROM MESSAGE-ID)]` (même lecture que `scan_mailbox`, `src/mailtag/mailbox_scan.py` : `parse_sender`, `provider._parse_header_value`, `normalize_address`).
  - Regroupe les UID par destination ; ignore les mails dont la destination est le dossier lui-même (rien à faire).
  - Si `apply` : pour chaque mail dont la destination est `REVIEW`, `pending.add(message_id, None, sender, today)` avant le déplacement ; puis `provider.batch_move_emails(uids, destination)` par lots de destination (`src/mailtag/imap_service.py` — crée le dossier s'il manque, IMAP MOVE garde dates et drapeaux) ; `pending.save()` une fois le dossier traité.
  - Un mail sans Message-ID exploitable : envoyé en revue (comportement par défaut de `destination_for`) mais sans entrée `pending` (rien à retrouver plus tard par Message-ID).
- `migrate_mailbox(provider, folders, overrides, rules, own, pending, today, apply) -> dict` : catégorie du dossier = `overrides[folder]` si audité, sinon `to_category(folder)`. Un dossier en erreur IMAP est noté dans `skipped` et n'arrête pas les autres (même contrat que `scan_mailbox`). Rapport : par dossier `{destination: nb}`, totaux par catégorie, total `9-A revoir`, dossiers sautés.
- **Reprise sans journal** : un mail déplacé quitte son dossier d'origine, donc relancer `migrate --apply` ne retraite que ce qui reste ; un second `migrate` à blanc doit afficher 0 mail à déplacer.
- `empty_legacy_folders(client, legacy, live_folders) -> list[str]` : anciens dossiers non protégés, avec 0 mail, dont tous les sous-dossiers existants sont eux aussi supprimables (un dossier avec un enfant qui a des mails, ou un enfant non ancien/protégé, est gardé). Triés du plus profond au moins profond, pour que `prune --apply` supprime les enfants avant les parents.
- `prune --apply` : pour chaque dossier de la liste, dans cet ordre, revérifie `client.search(["ALL"]) == []` juste avant `client.delete_folder(folder)` (un mail peut être arrivé entre le plan et l'exécution).

## Garde-fous

- `migrate` refuse de tourner si `CONFIG.taxonomy.enabled` est faux, ou si `db/taxonomy/senders.json`/`domains.json` sont absents (le `build` de la spec 2 n'a pas été fait). Logique dans une fonction testable (même schéma que `missing_inputs` existant), testée dans `tests/test_taxonomy_setup.py`.
- **Pas de `run` ni de `serve` pendant `migrate --apply`** : les deux déplacent des mails et écrivent `pending_archive.json`, comme `migrate --apply`. Avertissement affiché au lancement de `migrate --apply` et noté dans la doc (tâche 6, hors périmètre ici).
- Le rapport à blanc affiche le nombre de mails qui iraient en `9-A revoir` ; s'il dépasse quelques centaines, on en discute avant `--apply` (l'apprentissage depuis `9-A revoir` fait une recherche IMAP par mail et par catégorie à chaque `run`).
- `migrate` et `prune` sont en essai à blanc par défaut ; seul `--apply` modifie la boîte.

## Rapport

`migrate` (à blanc ou `--apply`) écrit `data/migration_report.json` via `write_json_atomic` : mails par destination, total `9-A revoir`, dossiers sautés. Un résumé court est journalisé (loguru).

## Hors périmètre

- Dossiers système / `_NOT_A_CATEGORY` (Promotions, À Classer, Spam…) : jamais migrés.
- Filtres `data/mailfilter.xml`.
- Gmail (spec 1 : Gmail garde le flux actuel).
- L'exécution réelle contre la vraie boîte (scan à blanc, revue du rapport, puis `--apply` avec accord explicite) : suit la fusion de cette branche, hors de ces tâches de développement.

## Tests

- `tests/test_migration.py` :
  - `folders_to_migrate` : catégories, dossiers d'action, dossiers système exclus ; `Contacts` exclu mais `Contacts/X` gardé.
  - `destination_for` : ordre validé > appris > domaine > catégorie du dossier > `REVIEW` ; adresse du propriétaire → catégorie du dossier directement (les règles de l'expéditeur ne s'appliquent pas à soi-même).
  - `migrate_folder` / `migrate_mailbox`, avec un `FakeClient` comme `tests/test_archive.py` (dossiers `{uid: {"from", "mid"}}`, `move` retire les UID des dossiers) :
    - essai à blanc : ne déplace rien, ne touche pas `pending` ;
    - `--apply` : groupe par destination, un seul `batch_move_emails` par destination ;
    - un mail vers `9-A revoir` ajoute une entrée `pending` avant le déplacement ;
    - un dossier cassé (erreur IMAP) est sauté, les autres continuent ;
    - une seconde passe après `--apply` ne trouve plus rien à déplacer (0) ;
    - un mail sans Message-ID part en revue sans entrée `pending`.
  - `empty_legacy_folders` : seulement les dossiers vides et anciens ; jamais un dossier protégé ; un parent est gardé si un enfant a des mails ou n'est pas un ancien dossier migrable ; ordre du plus profond au moins profond.
- `tests/test_taxonomy_setup.py` : refus de `migrate` si la taxonomie est désactivée ou si `senders.json`/`domains.json` manquent.
