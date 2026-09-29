# Taxonomie seule — nettoyage du code — design

Date : 2026-09-29.

## Contexte

- Deux modes cohabitent : le mode historique (611 dossiers IMAP comme catégories, `ClassificationDatabase` et ses trois JSON, signal 2 « labels », schéma statique, passe 2 par domaine, fichiers `pass3_manual_matching_*`, filtres, analyse de domaines) et le mode taxonomie (19 catégories, `TaxonomyStore`), actif dans `config.toml`.
- Chaque signal de `classifier.py` (955 lignes) bifurque selon le mode ; `tasks.py`, `main.py`, l'API et la config aussi.
- Audit (lecture seule) : aucun module taxonomie (archive, migration, review_refile, mailbox_scan, taxonomy_build, taxonomy_store, routing, sender_crosscheck, gmail_api, `taxonomy_setup.py`, `taxonomy_review.py`) ne lit une base historique.
- Gain estimé : ~5 000 lignes dans `src/` et `scripts/`, ~3 800 dans `tests/`.

## Décisions

1. Le mode taxonomie devient le seul mode. `[taxonomy] enabled` disparaît.
2. L'API webhook (`serve`) et Docker restent, recâblés sur la taxonomie.
3. Docker sans MLX classe par règles seulement (signaux 1, 3, 4) ; le reste va dans `5-A revoir`. litellm disparaît. Documenté.
4. `metrics.py` disparaît en entier (y compris le fil de log périodique, `@timed`, psutil).
5. Les sauvegardes visent désormais `db/taxonomy/*.json` et `db/pending_archive*.json`.
6. `src/app.py` (interface Streamlit de `run`) reste.
7. Le cache des dossiers (`get_folder_hierarchy`, `folder_cache_file`, `folder_cache_ttl_hours`, `data/imap_folders.json`, `data/gmail_labels.json`) disparaît : aucun code taxonomie ne le lit.
8. Le champ `Email.labels` (signal 2) disparaît du modèle et des schémas de l'API.
9. Découpage en cinq PR (A → E), chacune livrable, tests et ruff verts.

## Contraintes

- Le programme déplace du vrai courrier : `--validate` doit rester en lecture seule à chaque étape.
- `load_config` exige aujourd'hui `[general]`, `MODEL` et `[classifier]` : code et `config.toml`/`.env.example` changent dans le même commit.
- Pas de test sur la boîte réelle pendant un `migrate --apply`.
- Aucune suppression de données d'exécution (`data/`, `db/`) par le code ou par Claude : la PR E liste les fichiers périmés, le propriétaire les supprime.

## Étapes

### A. Filet de sécurité

- Test de bout en bout de `run_classification` en mode taxonomie, client IMAP simulé :
  passe 1 (règle d'expéditeur → dossier d'action + entrée `pending_archive`),
  passe 3 (nomic au-dessus du seuil ; accord nomic/Gemma ; désaccord → `5-A revoir`),
  balayage d'archive (mail vu, non marqué, plus vieux que `archive_after_days` → dossier de catégorie PARA).
  Même test en `--validate` : aucun déplacement, aucune écriture dans `db/taxonomy/` ni `pending_archive`.
- `read_only: bool` ajouté à `Classifier` et `run_classification`, transmis à `TaxonomyStore`. `ClassificationDatabase` reste le temps de la PR B.
- `utils/db_backup.py` sauvegarde `db/taxonomy/*.json` et `db/pending_archive*.json` au début de chaque `run`, dans `db/backups/`, 10 copies par fichier.

### B. Suppression du cœur historique

Fichiers supprimés :
`src/mailtag/database.py`, `folder_analyzer.py`, `filter_generator.py`, `gmail_service.py`, `providers.py`,
`src/streamlit_app.py` (importe un module inexistant), `utils/domain_analyzer.py`, `utils/data_cleanup.py`, `utils/data_validation.py`,
`scripts/build_category_embeddings.py`, `build_domain_database.py`, `update_domain_db.py`, `check_duplicates.py`, `inject_filters.py`.

Réductions :

- `classifier.py` (~955 → ~225) : plus de paramètre `database` ; retirer signaux 1-4 historiques, routeur sémantique historique, cache IA, `proposal_file`, prompt JSON, litellm, `classify_email` et lot historiques, `_classify_uncertain`, `export_metrics`, `log_metrics_summary`. Garder `_init_mlx_components`, `_truncate_body`, `_rule_category`, `_nomic_top`, `_llm_categories`, `_classify_uncertain_detailed`, `_classify_batch_taxonomy`, `classify_email`, `classify_emails_batch`.
- `utils/tasks.py` (~412 → ~150) : plus de `database`, passe 2 supprimée, `pending` et `rules` obligatoires, branche Gmail `else` supprimée (`GmailApiService` est un `ImapService`), vidage `pass3_manual_matching_*` supprimé, `get_folder_hierarchy()` supprimé.
- `main.py` (~436 → ~110) : commandes `filters`, `analyze-domains`, `cleanup`, `db-stats`, `prune-db` supprimées ; `refresh_imap_folders`, `generate_filters` supprimés. Restent `run` et `serve`.
- `imap_service.py` : récupération `X-GM-LABELS` et `labels` supprimées, cache des dossiers supprimé.
- `config.py` / `config.toml` / `.env.example` : `GeneralConfig`, `ClassifierConfig`, `TaxonomyConfig.enabled`, `use_gmail_extensions`, `folder_cache_*` et leurs validations supprimés ; `MODEL` n'est plus exigé.
- `scripts/taxonomy_setup.py` : le contrôle « taxonomie désactivée » de `migration_blocked` disparaît.
- Tests historiques supprimés : `test_database`, `test_filter_generator`, `test_domain_analyzer`, `test_data_cleanup`, `test_data_validation`, `test_gmail_service` (+ `mock_gmail_service.py`, fixture), `test_ai_confidence`, `test_classifier`, `integration/test_full_classification_workflow`, `test_error_recovery` (doublon de `test_retry_logic`). Adapter `test_classifier_taxonomy`, `test_routing`, `test_main`, `test_config`, `test_taxonomy_setup`, `test_tasks_accounts`, `test_missing_google_deps`.

### C. API webhook et Docker

- Requêtes Gmail : `GmailApiService` au lieu de `GmailService` ; plus de classifieur historique (`_classifier_for`, `legacy_classifier`).
- `/classify-and-move` passe par `route_to_action_folders` et `PendingArchive`, comme `run` : un mail envoyé dans `5-A revoir` obtient son entrée, l'archive apprend.
- `database_loaded` retiré de `/health` et `/status` ; description OpenAPI mise à jour (plus d'« AMSC 6 signaux »).
- Docker : `config.docker.toml` réécrit pour la taxonomie ; litellm retiré ; README/CLAUDE.md : classement par règles seulement, ne pas lancer `serve` dans Docker pendant un `run` sur le Mac (`flock`).

### D. Code mort et dépendances

- `semantic_router.py` : garder `load_embeddings`, `save_embeddings`, `_build_embedding_matrix`, `build_from_examples`, `top_batch`, `num_categories` ; retirer le reste et `score_threshold`.
- `mlx_provider.py` : retirer `encode_query`, `similarity`, `generate`, `classify`, `get_embedder`, `get_llm`, paramètres `max_tokens`/`temperature` (appels dans `taxonomy_setup.py` adaptés).
- `imap_service.py` : retirer `is_connected`, `get_email_senders`, `_move_email_to_folder`, `get_emails`.
- `text_utils.py` : garder `smart_truncate` et `_remove_signatures`. `domain_utils.py` : retirer `is_valid_domain`, `is_non_commercial_domain`, `get_domain_similarity`.
- `metrics.py` supprimé ; décorateurs et fil de log retirés de `imap_service.py` ; `fast_parse.metrics_*` retirés.
- `FastParseConfig` : champs morts (`unclassified_folder_name`, `max_retries`, `retry_*`) retirés. `MLXConfig` : garder `enabled`, `embedding_model`, `llm_model`.
- `scripts/eval_embeddings.py` (~751 → ~150) : garder `chain_eval` et ses aides.
- `pyproject.toml` : retirer litellm, `google`, defusedxml, watchdog, psutil, doublons pydantic/dotenv ; pytest-mock en dev ; extra `gmail` nettoyé.
- Tests correspondants élagués (`test_semantic_router`, `test_mlx_provider`, `test_text_utils`, `test_imap_service`, `test_eval_embeddings`, `test_classification_metrics`).

### E. Documentation

- Réécrire `CLAUDE.md`, `src/mailtag/CLAUDE.md`, `src/mailtag/utils/CLAUDE.md`, `scripts/CLAUDE.md`, `tests/CLAUDE.md` et le site de documentation : un seul mode, plus de « trois passes » historiques ni d'AMSC 6 signaux.
- Liste des fichiers périmés à supprimer par le propriétaire : `data/pass3_manual_matching_*.json`, `data/category_embeddings.npz`, `data/mailfilter.xml`, `data/imap_folders.json`, `data/gmail_labels.json`, `db/sender_classification_db.json`, `db/validated_classification_db.json`, `db/domain_classifications.json`, anciennes sauvegardes de ces bases.
- À garder : `data/legacy_folders.json`, `data/non_commercial_domains.yaml`, `data/taxonomy_centroids.npz`, `db/taxonomy/`.

## Ce qui ne change pas

`taxonomy.py` (y compris `to_category`, `map_folder` : migration, scan, audit), `taxonomy_store.py`, `taxonomy_build.py`, `archive.py`, `migration.py`, `review_refile.py`, `routing.py`, `action_rules.py`, `pending_archive.py`, `mailbox_scan.py`, `sender_crosscheck.py`, `gmail_api.py`, `gmail_auth.py`, `retry.py`, `logging_config.py`, `utils/email_parsing.py`, `scripts/taxonomy_review.py`. Le comportement de `run`, `serve` (hors correctif de `/classify-and-move`), `taxonomy_setup.py` et `taxonomy_review.py` reste identique.

## Critères de réussite

- À chaque PR : `uv run pytest` et `uv run ruff check .` verts.
- Après B : `run --provider imap --validate` et `run --provider gmail --validate` se terminent ; les dates de modification de `db/taxonomy/*` et `db/pending_archive*.json` ne changent pas.
- Après C : `serve` répond à `/health` et `/classify` (IMAP et Gmail).
- Fin : ~8 000 lignes en moins (source, scripts, tests).

## Risques

- Orchestration non testée aujourd'hui : la PR A doit précéder toute suppression.
- `--validate` : si `read_only` n'est pas transmis avant la suppression de `ClassificationDatabase`, un dry run écrirait `db/taxonomy/`. Couvert par le test de la PR A.
- Chargement de config : toutes les entrées (`run`, `serve`, `taxonomy_setup`, `taxonomy_review`, CI) importent `CONFIG`. Code et fichiers de config changent ensemble.
