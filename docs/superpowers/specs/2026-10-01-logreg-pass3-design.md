# Régression logistique au Pass 3 — design

Date : 2026-10-01.

## Contexte

- Pass 3 aujourd'hui (mode `mlx`) : centroïdes nomic (score ≥ `nomic_threshold`), sinon Gemma doit être d'accord avec le premier choix de nomic, sinon `5-A revoir`.
- L'étude Laya (`2026-10-01-laya-faisabilite-design.md`) a rejeté le zero-shot. Un spike a ensuite mesuré ce que le corpus apprend en supervisé : 403 mails vérifiés (94 expéditeurs), 5 plis groupés par expéditeur, entraînement sur `data/taxonomy_corpus.json` sans les expéditeurs du pli.

| Méthode | Top-1 | Classés / précision |
|---|---|---|
| Centroïdes nomic (prod) | 37,5 % | — |
| Centroïdes + accord Gemma (chaîne actuelle) | — | 34,2 % / 64,5 % |
| Régression logistique sur nomic (`classification: `, C=100) | 51,6 % | seuil 0,90 : 21,1 % / 84,7 % |
| Régression ≥ seuil **et** accord Gemma | — | seuil 0,90 : 12,7 % / 86,3 % |

- À couverture égale, la régression seule bat la chaîne actuelle ; l'accord de Gemma gagne 1 à 3 points de précision pour ~40 % de couverture en moins. Gemma sort donc du Pass 3.
- La précision plafonne vers 85 % même à haute confiance (0,95 : 83,9 % ; 0,99 : 92,9 % sur 14 mails) : erreurs structurelles (« Contacts » absorbe Famille & École, Carrière, Impôts ; le groupe tech se confond). Les critères 90 % / 45 % de la spec taxonomie sont hors d'atteinte ; la cible devient **85 % de précision**.

## Décisions

1. **Nouveau mode `[classifier] mode = "logreg"`**, à côté de `mlx` et `laya`. Défaut inchangé : `mlx`. Rien n'est supprimé.
2. **Mode logreg : la régression logistique seule au Pass 3**, sur les embeddings nomic. Pas de Gemma, pas de centroïdes. Les règles restent devant. `crosscheck` et `review-scan` restent sur Gemma.
3. **Classement par seuil** : classé si probabilité max ≥ `classify_threshold`, sinon `5-A revoir`.
4. **Apprentissage par seuil** : `agreed` vaut vrai si probabilité ≥ `learn_threshold` ; la règle des `learn_min_agreements` accords et la suppression sur contradiction ne changent pas. D'après le spike, `learn_threshold` vaudra 1,01 (rien n'est appris du modèle) ; les mails classés à la main hors de `5-A revoir` apprennent comme aujourd'hui.
5. **Seuils fixés par l'évaluation**, cible 85 % de précision pour `classify_threshold`. Valeurs par défaut inertes (1,01). La bascule en `mode = "logreg"` est faite à la main par le propriétaire.
6. **Mac seulement** : avec `[mlx] enabled = false` (Docker), le Pass 3 envoie tout dans `5-A revoir`, comme aujourd'hui.

## Configuration

`config.toml` ; dataclass `LogRegConfig` dans `config.py` (`AppConfig.logreg`, valeurs par défaut si la section manque).

```toml
[classifier]
mode = "mlx"            # "mlx" (nomic + Gemma) | "laya" | "logreg"

[logreg]
model_file = "data/taxonomy_logreg.npz"
C = 100.0               # régularisation de LogisticRegression
# seuils sur la probabilité max, fixés par `eval_embeddings.py logreg` (1.01 = jamais)
classify_threshold = 1.01
learn_threshold = 1.01
```

`mode` inconnu : `ValueError` au chargement de la configuration.

## Modèle

`data/taxonomy_logreg.npz` (`np.savez`, chargé sans pickle) :

- `classes` : les catégories (chaînes), dans l'ordre de `coef` ;
- `coef` : (catégories × dimension de l'embedding) ;
- `intercept` : (catégories) ;
- `embedding_model` : nom du modèle nomic utilisé à l'entraînement.

Texte : `nomic_text(sender_name, sender, subject, body)` (format des centroïdes), embarqué avec le préfixe `classification: `. Prédiction : `softmax(emb @ coef.T + intercept)`, identique à `LogisticRegression.predict_proba` en multiclasse ; numpy seul à l'exécution.

Chargement refusé (erreur loguée) si une classe n'est pas une clé de `TAXONOMY` ou si `embedding_model` diffère de `[mlx] embedding_model`.

## Composants

### `logreg_provider.py` (nouveau)

- `train(embeddings, categories, C) -> dict` : `LogisticRegression(C=C, max_iter=3000)` (scikit-learn importé dans la fonction), renvoie `classes`, `coef`, `intercept`.
- `predict(model, embeddings) -> (categories, probabilities)` : softmax numpy, catégorie et probabilité max par ligne.
- `save_model(path, model, embedding_model)` / `load_model(path, embedding_model) -> dict` (lève `ValueError` sur classe inconnue ou modèle d'embedding différent).
- `LogRegClassifier(logreg_config, embedding_model)` : `classify(emails) -> list[tuple[str, float] | None]`. `.npz` et `MLXEmbedder` chargés paresseusement sous verrou, un seul essai.

### `Classifier`

- `self._logreg = LogRegClassifier(...)` si `mode = "logreg"` et `[mlx] enabled` ; sinon `None`.
- `_classify_uncertain_detailed` délègue à `_classify_logreg` : `None` ou probabilité < `classify_threshold` → `(REVIEW, False)` ; sinon `(catégorie, probabilité ≥ learn_threshold)`. Seuils inclusifs.
- Mode `logreg` avec `[mlx] enabled = false` : `(REVIEW, False)` pour chaque mail.
- Aucun Gemma, centroïde ni Laya chargé en mode logreg.
- Inchangés : ordre des règles, `classify_detailed`, `learn`, `run`, `serve`, `--validate`, `/classify*`.

### `scripts/taxonomy_setup.py`

- `train` (nouveau) : lit `data/taxonomy_corpus.json`, calcule les embeddings (`classification: `), entraîne sur tous les mails (vérifiés ou non) avec `[logreg] C`, écrit `[logreg] model_file`. Ni IMAP ni règles.
- `build` appelle `train` à la fin, après les centroïdes.

### Dépendances

`scikit-learn>=1.5` ajouté aux dépendances MLX de `pyproject.toml` (déjà présent via sentence-transformers, importé directement désormais) et retiré par le `sed` du `Dockerfile` avec les autres dépendances MLX.

## Évaluation : `scripts/eval_embeddings.py logreg`

```bash
uv run python scripts/eval_embeddings.py logreg [--C 100] [--min-precision 0.85]
```

1. Test : tous les mails `verified` du corpus, 5 plis groupés par expéditeur ; chaque pli s'entraîne sur tout le corpus sauf les mails des expéditeurs du pli. Mêmes fonctions `train`/`predict` que la production.
2. Rapport : top-1 ; balayage de 0,30 à 0,99 par pas de 0,01 (part classée, précision, mails) via `confidence_sweep` ; centroïdes sur les mêmes plis pour référence ; secondes par mail.
3. Seuils proposés en TOML prêt à coller : `classify_threshold` = `best_threshold(sweep, min_precision)` ; `learn_threshold` = `learn_threshold(sweep)` (≥ 97 % sur ≥ 30 mails, sinon 1,01). Avertissement si le seuil proposé repose sur moins de 30 mails.
4. Pas de PASS/FAIL selon les critères 90 % / 45 %.

La dernière étape de l'implémentation lance `train` puis l'évaluation sur les vraies données et écrit les seuils mesurés dans `config.toml`, `mode` restant `mlx`.

## Erreurs

Un modèle indisponible n'arrête jamais un `run` ; les mails sans règle vont dans `5-A revoir`.

- `.npz` absent : avertissement (« lancer `taxonomy_setup.py train` »), `REVIEW`.
- `.npz` invalide ou embedder qui ne se charge pas : erreur loguée, `REVIEW` jusqu'à la fin du processus.
- Embedding d'un lot en échec : le lot en `REVIEW`, log ; le lot suivant réessaie.

## Tests

pytest + pytest-mock, faux embedder, aucun téléchargement.

- `train`/`predict` sur données synthétiques séparables ; `predict` égale `predict_proba` de scikit-learn.
- `save_model`/`load_model` aller-retour ; classe inconnue, modèle d'embedding différent, fichier absent → `classify` renvoie `None` partout.
- Lot en échec → `None` pour ce lot, le suivant réessaie.
- `Classifier` mode logreg : règles d'abord ; sous le seuil → `REVIEW` ; seuils inclusifs ; `agreed` seulement à partir de `learn_threshold` ; Gemma jamais appelé ; `mlx.enabled = false` → `REVIEW`.
- Config : défauts ; `ValueError` sur `mode` inconnu.
- Évaluation : les plis ne mettent jamais un expéditeur à la fois en entraînement et en test.
- `train` (sous-commande) : écrit le `.npz` depuis un petit corpus, sans IMAP.
- Modes `mlx` et `laya` : tests existants inchangés.

## Documentation

`CLAUDE.md`, `src/mailtag/CLAUDE.md`, `scripts/CLAUDE.md`, `config.toml`, `CHANGELOG.md` (`[Unreleased]`).

## Résultat (2026-10-01)

`uv run python scripts/eval_embeddings.py logreg` sur 403 mails vérifiés (94 expéditeurs), 5 plis groupés par expéditeur :

| | Valeur |
|---|---|
| Top-1 régression logistique | 51,4 % |
| Top-1 centroïdes (mêmes plis) | 37,5 % |
| `classify_threshold` proposé | 0,91 (20,3 % classés, 85,4 % de précision) |
| `learn_threshold` proposé | 1,01 |
| Secondes par mail | 0,021 |

Le seuil proposé repose sur 82 mails : les 85,4 % de précision sont dans le bruit d'échantillonnage de la cible de 85 % (environ ±8 points à 95 %), et toute précision mesurée au-dessus de 0,95 repose sur moins de 60 mails.

Seuils écrits dans `config.toml` ; `mode` reste `mlx` jusqu'à la bascule par le propriétaire.

## Correction (2026-10-01)

Les chiffres de la section « Résultat » sont gonflés. Sur les 403 mails vérifiés de `data/taxonomy_corpus.json`, 246 viennent d'un domaine qui a une règle de domaine (`db/taxonomy/domains.json` ou `validated_domains.json`) : en production ils n'atteignent jamais la passe 3, et ce sont les plus faciles. L'évaluation de la version 2.1.0 les mélangeait aux autres (51,4 % de top-1, 85,4 % de précision pour 20,3 % de mails classés au seuil de 0,91).

Sur les 157 autres mails (36 expéditeurs, 16 domaines ; petit échantillon, environ ±10 points), la régression logistique donne au seuil de 0,90 : 24,8 % de mails classés avec 66,7 % de précision (plis par expéditeur) ou 17,8 % avec 71,4 % (plis par domaine) ; au seuil de 0,80 : 37,6 % avec 59,3 % / 33,8 % avec 62,3 %. Top-1 : 51,0 % / 49,7 %. Le chiffre de 64,5 % de la chaîne nomic + Gemma (comparaison de la version 2.1.0) a été mesuré avec le même biais : sa précision réelle sur le courrier de la passe 3 est probablement plus basse.

`classify_threshold = 0,91` avait donc été fixé sur des chiffres gonflés. Aucun modèle n'atteint 85 % de précision sur le courrier qu'aucune règle ne couvre. Suite et décision : `2026-10-01-logreg-corpus-design.md`.
