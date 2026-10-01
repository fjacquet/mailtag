# Corpus d'entraînement élargi pour la régression logistique — design

Date : 2026-10-01.

## Contexte

- Le mode `logreg` (`2026-10-01-logreg-pass3-design.md`, release 2.1.0) classe 20,3 % des mails d'expéditeurs inconnus à 85,4 % de précision (seuil 0,91), top-1 51,4 %.
- Les 19 catégories ne changent pas (choix du propriétaire). Les leviers de décision mesurés ne rapportent rien : à 85 % de précision, tous classent entre 18 et 22 % des mails. Ces leviers sont l'exclusion de « Contacts », la revue des hésitations internes au groupe tech, le seuil sur l'écart top1−top2 et la règle « domaine perso ⇒ Contacts » (52 % juste).
- Ce qui bouge, c'est la quantité de données. Mesure en entraînant sur une part des expéditeurs du corpus :

| Expéditeurs d'entraînement | Top-1 | Classés à 85 % |
|---|---|---|
| 50 % | 46,9 % | 0 % |
| 75 % | 49,5 % | 14,1 % |
| 100 % (567 expéditeurs) | 51,6 % | 20,3 % |

- `data/taxonomy_corpus.json` (2 525 mails, 567 expéditeurs) est plafonné à 200 mails par catégorie, en prenant les plus gros expéditeurs d'abord. Environ 1 400 expéditeurs ont une règle.
- La migration est appliquée (`data/migration_report.applied.json`) : les références `(dossier, uid)` du scan pointent vers des dossiers supprimés. Un `build` relancé relirait un corpus presque vide et écraserait `taxonomy_corpus.json`, qui porte les 403 mails vérifiés servant de test.

## Décisions

1. **Catégories, dossiers et règles inchangés.** Seule la source d'entraînement de la régression logistique change.
2. **Nouveau corpus d'entraînement** collecté dans les dossiers de catégorie IMAP par `taxonomy_setup.py harvest`, en lecture seule.
3. **Étiquette fiable seulement** : un mail est gardé si la règle de son expéditeur (`TaxonomyStore.category_for`) donne la catégorie de son dossier. Les mails rangés par le modèle pour des expéditeurs inconnus et ceux déplacés à la main contre la règle sont écartés.
4. **Variété avant volume** : plafond par expéditeur, aucun plafond par catégorie.
5. **`taxonomy_corpus.json` figé** : il reste le jeu de test (403 mails vérifiés) et la source des centroïdes ; `build` ne l'écrase plus avec un corpus réduit de plus de moitié.
6. **Plis groupés par domaine** dans l'évaluation (par expéditeur pour les domaines non commerciaux), comme le Pass 3 ne voit que des domaines sans règle.
7. **Décision par l'évaluation** : le nouveau corpus n'entraîne le modèle de production que s'il classe plus de mails à 85 % de précision que l'ancien, mesurés avec le même protocole.
8. IMAP seulement (Infomaniak). Gmail ne fournit pas de corpus (nouveau courrier seulement).

## Configuration

```toml
[logreg]
model_file = "data/taxonomy_logreg.npz"
C = 100.0
per_sender = 10         # mails par expéditeur pris dans data/training_corpus.json (fixé par l'évaluation)
classify_threshold = 0.91
learn_threshold = 1.01
```

`LogRegConfig.per_sender: int = 10`.

## Composants

### `scripts/taxonomy_setup.py harvest [--per-sender 20]`

Lecture seule, IMAP. Ne déplace et ne marque aucun mail (dossiers sélectionnés en `readonly`).

1. Dossiers : `category_folder` de chaque catégorie de `TAXONOMY` pour chaque groupe PARA où elle existe (`Domaines/…`, `Ressources/…`, `Archive/…`). Ni `Promotions`, ni les dossiers d'action, ni `INBOX`.
2. Pour chaque dossier : en-têtes de tous les mails, puis on garde un mail si `store.category_for(sender) == catégorie du dossier` et `not store.is_own(sender)`.
3. Au plus `--per-sender` (défaut 20) mails par expéditeur, sur l'ensemble des dossiers, les plus grands UID d'abord dans chaque dossier.
4. Corps des mails retenus, lus par lots.
5. Écrit `data/training_corpus.json` (écriture atomique) : liste de `{"sender", "sender_name", "subject", "body", "category"}`.

Le cœur (choix des mails à partir des en-têtes, plafond par expéditeur) est une fonction pure de `src/mailtag/taxonomy_build.py`, testable sans IMAP.

### `train`

- Lit `data/training_corpus.json` s'il existe, réduit à `[logreg] per_sender` mails par expéditeur ; sinon `data/taxonomy_corpus.json`, comme aujourd'hui.
- Le log indique le corpus utilisé.

### `build`

Avant d'écrire `taxonomy_corpus.json` : si le corpus relu compte moins de la moitié des mails du fichier existant, il garde l'existant (avertissement) ; centroïdes et `train` partent alors du corpus conservé.

## Évaluation : `scripts/eval_embeddings.py logreg`

```bash
uv run python scripts/eval_embeddings.py logreg [--train-corpus data/training_corpus.json] [--per-sender 10] [--C 100] [--min-precision 0.85]
```

1. Test : les mails vérifiés de `taxonomy_corpus.json`.
2. Plis : 5, groupés par **domaine** (par expéditeur si le domaine est non commercial). Chaque pli s'entraîne sur le corpus d'entraînement sans aucun mail des groupes du pli.
3. Corpus d'entraînement : `--train-corpus` ; par défaut `training_corpus.json` s'il existe, sinon `taxonomy_corpus.json`. Avec `training_corpus.json`, réduit à `--per-sender` mails par expéditeur (défaut `[logreg] per_sender`).
4. Rapport : pour chacun des deux corpus (`taxonomy_corpus.json` et, s'il existe, `training_corpus.json`) : top-1, mails classés à `--min-precision`, nombre de mails et d'expéditeurs d'entraînement ; puis balayage et seuils proposés (TOML) pour le corpus demandé ; centroïdes pour référence.

La dernière étape de l'implémentation lance `harvest`, puis l'évaluation pour `--per-sender` 5, 10 et 20. Si le meilleur bat l'ancien corpus en mails classés à 85 %, `per_sender` et les seuils mesurés vont dans `config.toml` et `train` réentraîne le modèle ; sinon `config.toml` garde l'ancien corpus et ses seuils. Le résultat, chiffres compris, est ajouté à cette spec. `mode` reste `mlx`.

## Erreurs

- Dossier de catégorie absent ou illisible : avertissement, dossier sauté.
- Corps illisible : mail ignoré.
- Rien collecté : `harvest` s'arrête avec un message, n'écrit rien.
- `training_corpus.json` présent mais avec moins de 3 catégories : `train` s'arrête avec un message (règle existante).

## Tests

pytest + pytest-mock, IMAP simulé, faux embedder, aucun réseau.

- Sélection : un mail est gardé seulement si la règle de l'expéditeur donne la catégorie du dossier ; adresses du propriétaire exclues ; sans règle, exclu ; plafond par expéditeur sur plusieurs dossiers ; plus grands UID d'abord.
- `harvest` : dossiers en lecture seule, aucun déplacement, dossier manquant sauté, rien collecté → arrêt sans écriture, JSON écrit sinon.
- `build` : un corpus relu réduit de plus de moitié n'écrase pas l'existant.
- `train` : utilise `training_corpus.json` quand il existe, réduit à `per_sender` ; sinon `taxonomy_corpus.json`.
- Plis par domaine : un domaine (ou un expéditeur de domaine non commercial) n'est jamais à la fois en entraînement et en test.
- Config : `per_sender` par défaut 10.

## Documentation

`CLAUDE.md` (commande `harvest`, rôles des deux corpus, plis par domaine), `scripts/CLAUDE.md`, `config.toml`, `CHANGELOG.md` (`[Unreleased]`).

## Résultat (2026-10-01)

`harvest` : 11 350 mails, 2 095 expéditeurs. Évaluation (`eval_embeddings.py logreg --per-sender 5 10 20`), 403 mails vérifiés, 77 groupes de plis (domaines ou expéditeurs de domaines personnels), plis groupés par domaine :

| Corpus d'entraînement | Mails | Expéditeurs | Top-1 | Classés à 85 % |
|---|---|---|---|---|
| taxonomy_corpus.json | 2 525 | 567 | 44,4 % | 0,0 % |
| training_corpus.json, per_sender=5 | 5 876 | 2 095 | 46,4 % | 0,0 % |
| training_corpus.json, per_sender=10 | 8 335 | 2 095 | 44,2 % | 0,0 % |
| training_corpus.json, per_sender=20 | 11 350 | 2 095 | 44,9 % | 0,0 % |

Centroïdes (mêmes plis) : 34,2 % de top-1. Décision : le nouveau corpus gagne 2 points de top-1 (46,4 % contre 44,4 %, dans le bruit d'échantillonnage de 403 mails) mais ne bat pas l'ancien sur le critère (0 % contre 0 % de mails classés à 85 %) : aucun seuil n'atteint 85 % de précision (à 0,90, 26,1 % des mails sont classés avec 61,0 % de précision, 105 mails ; à 0,99, 4,2 % avec 64,7 %, 17 mails). L'ancien corpus est donc conservé (`taxonomy_corpus.json`, `per_sender = 10`) et le corpus moissonné est mis de côté sous `data/training_corpus.rejected.json`. `classify_threshold = 1,01` et `learn_threshold = 1,01` (jamais) : le mode `logreg` ne classe rien et reste hors service ; le mode par défaut reste `mlx`. Le top-1 de 51,4 % annoncé en 2.1.0 reposait sur des plis par expéditeur : un domaine présent des deux côtés des plis gonflait la mesure. Un meilleur corpus n'y change rien ; l'écart vient du protocole.

Mesure proche de la production : sur les 403 mails vérifiés, 246 viennent d'un domaine qui a une règle de domaine et n'atteignent jamais la passe 3. Sur les 157 autres (36 expéditeurs, 16 domaines ; environ ±10 points), la régression logistique classe au seuil de 0,90 24,8 % des mails avec 66,7 % de précision (plis par expéditeur) ou 17,8 % avec 71,4 % (plis par domaine) ; au seuil de 0,80, 37,6 % avec 59,3 % / 33,8 % avec 62,3 %. Aucun modèle n'atteint 85 % sur le courrier qu'aucune règle ne couvre. Décision du propriétaire : passe 3 au repos (`[mlx] enabled = false` dans `config.toml`) ; tout ce que les règles ne couvrent pas va dans `5-A revoir`, et les classements manuels du propriétaire continuent d'enrichir les règles. L'évaluation reproduit désormais cette mesure proche de la production : `uv run python scripts/eval_embeddings.py logreg` ne teste que les mails vérifiés dont le domaine n'a pas de règle de domaine (elle n'a pas été relancée pour ce document).
