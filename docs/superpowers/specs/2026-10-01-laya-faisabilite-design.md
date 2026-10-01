# Étude de faisabilité Laya — design

Date : 2026-10-01.

## Contexte

- Pass 3 aujourd'hui : centroïdes nomic (score ≥ `nomic_threshold`), sinon Gemma doit être d'accord avec le premier choix de nomic, sinon `5-A revoir`. Un accord nomic/Gemma compte pour l'expéditeur ; après `learn_min_agreements` accords, il devient une règle.
- [Laya](https://huggingface.co/convaiinnovations/laya) (Apache 2.0, package `laya` 0.3.22) est un classifieur non génératif : un état (texte ou dict) et des questions typées (`choice`, `score`, `noul`) en une passe, une probabilité par option. Les options sont données à l'appel : les 19 catégories passent telles quelles, sans entraînement.
- Trois checkpoints : `laya` (ModernBERT-large, anglais, 512 tokens), `laya-multilingual` (mmBERT-base, 100+ langues, 1 024 tokens, jusqu'à 8 192), `laya-typed-decisions`. Le `Router` détecte script et langue (< 0,5 ms) et envoie l'anglais au checkpoint anglais, le reste au multilingual.
- Limites publiées (README GitHub, « Honest limits ») :
  - zero-shot proche du hasard sur leur benchmark typed-decisions (0,342 multilingual, hasard 0,318) ; « a fast base to specialise, not a zero-shot decision engine ». La version ajustée atteint 0,766.
  - `laya-multilingual` est livré sans température calibrée ; les deux checkpoints sont surconfiants.
  - le seuil se met sur `answer_confidence` (max p), pas sur `confidence` (entropie) ni `act_probability` (sans signal).
  - biais de position des options, corrigeable par `option_order` (rotations moyennées, une seule passe).
  - le checkpoint anglais s'effondre hors anglais : les critères qu'il lit doivent être en anglais.
  - un seuil dépend du device et du dtype (MPS passe en fp16 dès 5 lignes) : le mesurer comme on le sert.
- Corpus étiqueté existant : `data/taxonomy_corpus.json`, 2 525 mails avec corps, catégorie et `verified`. `scripts/eval_embeddings.py chain` mesure déjà la chaîne nomic+Gemma avec les critères de la spec taxonomie.

## Décisions

1. **Étude de faisabilité, rien n'est supprimé.** Un switch `[classifier] mode = "mlx" | "laya"` ; `mlx` (aujourd'hui) reste le défaut. Nomic, Gemma, MLX et les centroïdes ne changent pas.
2. **Mode laya : Laya remplace nomic et Gemma au Pass 3.** Les règles restent devant. Classé si `answer_confidence ≥ classify_threshold`, sinon `5-A revoir`.
3. **Apprentissage par seuil.** `agreed` vaut vrai si `answer_confidence ≥ learn_threshold` (plus strict) ; la règle des `learn_min_agreements` accords et la suppression sur contradiction ne changent pas.
4. **Seuils fixés par l'évaluation, par checkpoint.** Valeurs initiales inertes : `classify_threshold = 1.01` et `learn_threshold = 1.01`, donc en mode laya avant l'évaluation tout ce que les règles ne couvrent pas va dans `5-A revoir` et rien n'est appris.
5. **Présélection de langue par le `Router`** (`routing = "router"`), comparée au multilingual seul (`routing = "multilingual"`). Le checkpoint anglais reçoit les catégories en anglais.
6. **Périmètre : Pass 3 seulement** (`run`, `serve`, évaluation). `crosscheck` et `review-scan` restent sur Gemma.
7. **Zero-shot d'abord, leviers sans entraînement ensuite** (descriptions, rotations, budget d'options, routage). Le fine-tuning est un projet séparé, décidé par le verdict.
8. **Mac seulement.** Docker n'est pas touché ; `laya` est un extra optionnel.

## Configuration

`config.toml` ; dataclasses `ClassifierConfig` et `LayaConfig` dans `config.py` (`AppConfig.classifier`, `AppConfig.laya`, valeurs par défaut si la section manque).

```toml
[classifier]
mode = "mlx"            # "mlx" (nomic + Gemma) | "laya"

[laya]
routing = "router"      # "router" (langue → english/multilingual) | "multilingual"
device = "auto"         # auto | mps | cpu
batch_size = 16
head_max_len = 512      # place des 19 options (~26 tokens chacune)
max_len = 1024          # les deux checkpoints (le défaut anglais de 512 laisserait ~100 tokens au mail)
rotations = false       # moyenne sur 19 option_order (biais de position), 19 lignes par mail
body_chars = 1500       # corps après smart_truncate
calibration = "data/laya_neutral_calibration.json"  # "" = températures livrées
# seuils par checkpoint sur answer_confidence, fixés par `eval_embeddings.py laya`
english = { classify_threshold = 1.01, learn_threshold = 1.01 }
multilingual = { classify_threshold = 1.01, learn_threshold = 1.01 }
```

`mode` ou `routing` inconnu : `ValueError` au chargement de la configuration.

## Composants

### `taxonomy.py`

`TAXONOMY_EN` : les 19 mêmes clés que `TAXONOMY`, valeur `(étiquette anglaise, description anglaise)`. Laya affiche les clés de `criteria` telles quelles au modèle : le checkpoint anglais voit donc les étiquettes anglaises, et la réponse est retraduite en catégorie française. Étiquettes sémantiques, jamais `yes`/`no`/`true`/`false`.

### `laya_provider.py` (nouveau)

`LayaClassifier(laya_config)` :

- `Router` construit paresseusement sous verrou (même schéma que `_mlx_lock`), un seul essai ; `USE_TF=0` posé avant l'import de `laya`. Les checkpoints se chargent au premier `predict_batch`.
- `classify(emails) -> list[tuple[str, float, str] | None]` : `(catégorie, answer_confidence, checkpoint)` par mail, `None` si Laya n'a pas répondu.
- État : `{"from": "Nom <adresse>", "subject": ..., "body": smart_truncate(body, body_chars)}`.
- Question : un `choice` dont les `criteria` sont `TAXONOMY` (multilingual) ou `TAXONOMY_EN` (english), consigne dans la même langue.
- `predict_batch(..., batch_size, sort_by_length=True, head_max_len, max_len)`.
- Un seul `Router(default="multilingual", agent_kwargs={"calibration": ...})` (vérifié dans `laya` 0.3.22). `routing = "router"` : `Router.route_batch` choisit le checkpoint de chaque mail sans rien charger ; `routing = "multilingual"` : tous les mails sur `multilingual`. Puis `Router.predict_batch(requests, batch_size, sort_by_length=True)`, une requête par mail avec `model=` explicite, sa question dans la langue du checkpoint, `max_len` et `head_max_len` (le Router accepte des questions différentes par requête).
- Calibration : le checkpoint anglais est livré avec un « sharpener » pour 11 options et plus (`laya/common.py`, issue #394 ; `laya` 0.3.22 le borne à une température de 0,5, ce qui affûte encore les probabilités d'un facteur 2). `data/laya_neutral_calibration.json` (`{"temperature": [1.0, 1.0, 1.0], "temperature_by_options": {}}`) remet le softmax brut, qui garde l'ordre des confiances ; les seuils mesurés font le reste. L'ajustement des températures sur nos données relève du fine-tuning.
- `rotations = true` : 19 questions `option_order` décalées dans la même requête, probabilités moyennées, réponse = maximum de la moyenne, confiance = cette moyenne.

### `Classifier`

- `mode = "laya"` : `_classify_uncertain_detailed` appelle `LayaClassifier.classify`. Par mail : `None` ou confiance < `classify_threshold` du checkpoint → `(REVIEW, False)` ; sinon `(catégorie, confiance ≥ learn_threshold)`.
- Aucun composant MLX chargé en mode laya ; `laya` jamais importé en mode mlx.
- Inchangés : ordre des règles, `classify_detailed`, `learn`, `run`, `serve`, `--validate`, `/classify*`.

### `pyproject.toml`

Extra `laya = ["laya>=0.3.22"]` (`uv sync --extra laya`). `torch` est déjà là via `sentence-transformers` ; la compatibilité avec `transformers>=5.16.1,<5.17` est vérifiée à l'installation.

## Évaluation : `scripts/eval_embeddings.py laya`

```bash
uv run python scripts/eval_embeddings.py laya -n 500 --seed 3 \
    [--routing router|multilingual] [--rotations] [--head-max-len N] [--body-chars N]
```

1. Même échantillon de mails `verified` que `chain` (même `-n`, même `--seed`), convertis en `Email`, classés par `LayaClassifier.classify` en lots de `batch_size`, sur le device de production. Pas d'exclusion de l'expéditeur : rien n'est entraîné.
2. Balayage du seuil de 0,30 à 0,99 par pas de 0,01, **par checkpoint** : part classée, précision. Variante à une confiance de `threshold_sweep` ; `chain_metrics` et `best_threshold` réutilisés.
3. Seuils proposés par checkpoint :
   - `classify_threshold` : la plus grande couverture à précision ≥ 90 % (`best_threshold`).
   - `learn_threshold` : le plus bas seuil dont la précision est ≥ 97 % sur au moins 30 mails ; sinon 1,01.
4. Rapport : mails par checkpoint (part française/anglaise), précision au premier choix, tableau du balayage, seuils proposés en TOML prêt à coller, secondes par mail, device et dtype réels, PASS/FAIL selon les critères de la spec taxonomie (≥ 45 % classés, ≥ 90 % de précision, ≤ 1,5 s par mail), et rappel des chiffres de `chain` à lancer sur la même graine.

Les descriptions des catégories s'ajustent dans `taxonomy.py`. La présélection par embeddings (`predict_shortlist`) n'est pas prévue : 19 options ne sont pas une forte cardinalité ; elle reviendra si les rotations ne suffisent pas.

## Verdict (ajouté à cette spec à la fin de l'étude)

- **GO** : Laya passe les critères et va au moins aussi vite que `chain` → projet de bascule (mode laya par défaut, `crosscheck`/`review-scan` sur Laya, Docker en ONNX INT8).
- **Fine-tuning** : au-dessus du hasard mais sous les critères → projet séparé, notre corpus comme données d'entraînement (notebook RLCD de Laya, calibration des températures).
- **STOP** : proche du hasard → nomic + Gemma restent, le mode laya est retiré.

## Erreurs

Un modèle indisponible n'arrête jamais un `run` ; les mails sans règle vont dans `5-A revoir`.

- `laya` absent (`ImportError`) : avertissement, `REVIEW`.
- Construction du `Router` en échec : erreur, `REVIEW` jusqu'à la fin du processus.
- `predict_batch` en échec (y compris le premier chargement d'un checkpoint, qui a lieu là) : le lot en `REVIEW`, log ; le lot suivant réessaie.

## Tests

pytest + pytest-mock, faux agent Laya, aucun téléchargement.

- `LayaClassifier` : réponse → `(catégorie, answer_confidence, checkpoint)` ; critères anglais pour `english`, français pour `multilingual` ; `head_max_len`, `max_len`, `batch_size` transmis ; rotations moyennées ; `TAXONOMY_EN` a les mêmes clés que `TAXONOMY`.
- `Classifier` mode laya : seuil du bon checkpoint ; sous le seuil → `REVIEW` ; `agreed` seulement à partir de `learn_threshold` ; règles d'abord, Laya seulement pour le reste ; `laya` absent → `REVIEW`.
- Mode mlx : les tests existants passent sans changement.
- Config : défauts ; `ValueError` sur `mode`/`routing` inconnu.
- Évaluation : balayage à une confiance et choix de `learn_threshold` (≥ 97 % sur ≥ 30 mails, sinon 1,01) sur données synthétiques.
- Le vrai modèle ne tourne que dans l'évaluation, à la main sur le Mac.

## Verdict (2026-10-01)

Mesuré sur la branche `feat/laya-feasibility`, Mac Apple Silicon (MPS, fp16), `laya` 0.3.22, 403 mails `verified` (`-n 500 --seed 3` ; le corpus n'en a que 403), même échantillon pour toutes les lignes.

| Configuration | Top-1 | Meilleure précision (couverture) | s/mail | Critères |
|---|---|---|---|---|
| `chain` (nomic + Gemma, aujourd'hui) | 38,5 % (nomic seul) | 67,7 % (32,3 %) | 0,61 | FAIL |
| Laya, Router (english 92 mails / multilingual 311) | 23,9 % / 13,2 % | < 40 %, aucun seuil à 90 % | 0,22 | FAIL |
| Laya, multilingual seul | 13,9 % | 25 % (16 %) | 0,12 | FAIL |
| Laya, températures livrées (`--calibration ""`) | 23,9 % / 13,2 % | 38 % (english, 28 %) | 0,16 | FAIL |
| Laya, `--head-max-len 384` | identique au Router | identique | 0,16 | FAIL |
| Laya, `--rotations` | arrêté après 50 mails | — | 52 | FAIL (latence) |

Hasard sur 19 catégories : 5,3 %. La confiance de Laya ne trie pas ses réponses : la précision reste sous 25 % (multilingual) à tous les seuils.

**Décision : zero-shot rejeté ; fine-tuning à décider en projet séparé.** Selon la règle de cette spec, Laya est au-dessus du hasard mais sous les critères, d'où « fine-tuning ». En zero-shot il est 2 à 3 fois moins juste que nomic seul, ce qui confirme la mise en garde des auteurs (« a fast base to specialise »). Il est 3 à 5 fois plus rapide que la chaîne actuelle. Le mode `laya` reste dans le code, inactif (`mode = "mlx"`, seuils 1,01) ; le fine-tuning partirait de notre corpus (403 mails vérifiés, 2 525 au total). La chaîne actuelle échoue aussi aux critères sur cet échantillon (67,7 % au mieux).
