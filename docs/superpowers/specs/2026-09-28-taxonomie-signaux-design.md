# Taxonomie à 19 catégories : refonte des 6 signaux — design

Suite de la spec 1 (`2026-09-27-taxonomie-19-categories-design.md`), qui a posé les 19 catégories, les dossiers d'action et le ménage de fin de passage. Cette spec reprend **la manière de décider la catégorie** : les 6 signaux, ce qu'ils apprennent et comment on les valide.

## Contexte et mesures

La spec 1 a seulement branché les anciens signaux sur les 19 catégories (conversion des anciens chemins de dossier par `to_category`) et ajouté nomic puis Gemma. Mesures faites le 2026-09-28 :

- **Essai à blanc sur la vraie boîte de réception** (`run --provider imap --validate`, 178 mails) : 17 % des mails classés automatiquement. Signal 1 (validés) : base vide. Signal 3 (historique) : 364 expéditeurs, 1 mail classé. Signal 4 (domaines) : 181 domaines, 0 mail classé. Tout repose sur nomic et Gemma.
- **Chaîne nomic puis Gemma** (`chain -n 500`) : 37 % classés à 90,8 % de précision. Aucun seuil nomic n'atteint 45 % à 90 % : entre 0,65 et 0,70, nomic seul a raison 55 % du temps. Quand nomic et Gemma sont d'accord, ils ont raison 94 % du temps. Gemma seul : 58 %.
- **Tes rangements passés** (5 660 mails, 1 403 expéditeurs, échantillon de 20 mails par dossier) : 98,7 % des expéditeurs ne vont que dans une catégorie ; 894 domaines d'entreprise sur 932 vont à 90 % ou plus dans une catégorie.

Avec 19 catégories métier, l'expéditeur et son domaine suffisent presque toujours à décider. Cette connaissance est dans tes 611 dossiers, mais les signaux 3 et 4 ne l'exploitent pas.

**Réserve :** ces dossiers ont été remplis par l'ancien mailtag, avec ses erreurs (sauvegarde Synology rangée dans Achats, connexion Uber dans Transports). Leur cohérence ne prouve pas qu'ils ont raison. Les 90 % de précision mesurés jusqu'ici mesurent l'accord avec l'ancien mailtag, pas la vérité.

## Objectifs et critères de succès

1. Apprendre la catégorie des expéditeurs et des domaines à partir de tes dossiers, en ne gardant que ce que confirme un second avis indépendant (Gemma), et en te faisant trancher les désaccords.
2. Remplacer les 611 centroïdes synthétiques de nomic par 19 centroïdes calculés sur de vrais mails vérifiés.
3. Apprendre automatiquement les nouveaux expéditeurs quand deux avis indépendants concordent, jamais d'une seule décision automatique.
4. Mesurer sur des données que tu as vérifiées.

Critères, tous requis avant de passer `[taxonomy] enabled = true` :

- **précision ≥ 90 %** sur tes décisions vérifiées (règles apprises et chaîne nomic puis Gemma) ;
- **couverture ≥ 60 %** des mails de la vraie boîte de réception à l'essai à blanc ;
- pas de limite de temps de traitement.

Ton temps de revue initial : environ **1 heure**.

## Hors périmètre

- Déplacer ou renommer les 611 dossiers existants (spec 2).
- Gmail, qui garde le flux actuel.
- Le choix du dossier d'action et le ménage de fin de passage (spec 1, inchangés), sauf la cible de l'apprentissage depuis `9-A revoir` (section 5).

## 1. Préparation en quatre étapes

Commandes de `scripts/taxonomy_setup.py`. Aucune ne déplace de mail. Chacune peut être relancée.

### 1.1 `scan` : lecture seule d'IMAP

- Pour chacun des dossiers de `data/legacy_folders.json` dont `map_folder` donne une catégorie : `BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)]` de tous les mails, par lots.
- Résultat `data/mailbox_scan.json`, par expéditeur (adresse en minuscules) : nom, domaine, nombre de mails par catégorie, jusqu'à 5 sujets d'exemple, et jusqu'à 5 références `(dossier, uid)` pour lire plus tard le contenu d'un échantillon.
- Dossiers sans catégorie (`Promotions`, `Spam`, `INBOX`…) : ignorés.
- Dossier illisible : sauté, noté dans le journal ; les autres continuent.
- La **catégorie du dossier** d'un expéditeur est sa catégorie majoritaire.

### 1.2 `crosscheck` : Gemma par expéditeur

- Pour chaque expéditeur du scan : Gemma lit nom, adresse et jusqu'à 5 sujets, et répond par un numéro de catégorie. Même mécanique que la chaîne actuelle : lots de 8, début du prompt calculé une seule fois (`MLXLLM.classify_batch`), `parse_category_number`.
- Le prompt reprend la liste numérotée des 19 catégories de `llm_static_prompt`, avec « classe cet expéditeur » au lieu de « classe cet email ».
- Résultat `data/sender_crosscheck.json` : expéditeur → catégorie Gemma (ou `null` si la réponse est illisible). Enregistré tous les 100 expéditeurs ; une relance saute les expéditeurs déjà traités.
- Durée attendue : environ 1 s par expéditeur, en tâche de fond.

### 1.3 `review` : ta revue (page Streamlit locale, `scripts/taxonomy_review.py`)

- File, dans l'ordre :
  1. expéditeurs dont la catégorie du dossier diffère de celle de Gemma, par nombre de mails décroissant ;
  2. puis expéditeurs d'accord, par nombre de mails décroissant.
- Chaque fiche : adresse, nom, nombre de mails, sujets d'exemple, catégorie du dossier, catégorie Gemma. Un bouton par catégorie (les 19), et « passer ».
- Chaque clic écrit immédiatement dans `db/taxonomy/validated.json` (écriture atomique). La page reprend là où tu t'étais arrêté.
- Tout reste sur ton Mac : rien n'est publié.

### 1.4 `build` : construction des règles et des centroïdes

- **Signal 3, `db/taxonomy/senders.json`** : expéditeurs d'accord (dossier = Gemma), avec au moins 2 mails, absents de `validated.json`.
- **Signal 4, `db/taxonomy/domains.json`** : domaines hors messageries personnelles (`is_non_commercial_domain_cached`, déjà utilisé par le signal 4 actuel) dont au moins 90 % des mails vont dans une même catégorie, en prenant pour chaque expéditeur sa catégorie validée, sinon apprise.
- **Signal 5, `data/taxonomy_centroids.npz`** : 19 centroïdes nomic. Pour chaque catégorie, jusqu'à 200 mails d'expéditeurs validés ou d'accord, dont on lit le contenu (`BODY.PEEK[]`, lecture seule) grâce aux références du scan ; texte construit exactement comme en production (`_nomic_top`).
- Si un fichier d'entrée manque, `build` n'écrit rien. Toutes les écritures sont atomiques.

## 2. Stockage

Le mode taxonomie lit uniquement ses propres fichiers. Le flux actuel garde les siens intacts.

| Fichier | Contenu |
|---|---|
| `db/taxonomy/validated.json` | expéditeur → catégorie (ta revue, mails sortis de `9-A revoir`) |
| `db/taxonomy/senders.json` | expéditeur → `{category, agreements}` (appris) |
| `db/taxonomy/domains.json` | domaine → catégorie |
| `data/taxonomy_centroids.npz` | 19 centroïdes nomic |

Les anciennes bases (`db/*.json`, en chemins de dossier) ne sont plus lues en mode taxonomie : leur connaissance est récupérée par `scan`. `to_category` ne sert plus qu'à `scan`.

## 3. Chaîne de classement (mode taxonomie)

Dans l'ordre, le premier qui répond décide :

1. **Expéditeur validé** (`validated.json`).
2. ~~Libellés IMAP~~ : retiré en mode taxonomie (un mail de la boîte de réception n'en a pas).
3. **Expéditeur appris** (`senders.json`).
4. **Domaine d'entreprise connu** (`domains.json`).
5. **nomic, 19 centroïdes** : accepté si le score dépasse `nomic_threshold`, recalculé par `chain` (section 6) pour tenir 90 % de précision.
6. **Gemma d'accord avec nomic** : sinon, Gemma répond par numéro (par lots) ; accepté s'il donne la même catégorie que le premier choix de nomic.
7. Sinon **`9-A revoir`**.

## 4. Apprentissage automatique

On apprend seulement quand **deux avis indépendants concordent** (nomic et Gemma, cas mesuré juste à 94 %).

- Mail classé à l'étape 6 (accord nomic et Gemma) : l'expéditeur gagne un accord pour cette catégorie dans `senders.json`.
- Après **2 accords** dans la même catégorie, sans avis contraire, l'expéditeur est **promu** : ses mails suivants sont rangés à l'étape 3.
- Accord sur une **autre** catégorie pour un expéditeur en cours d'apprentissage ou promu : l'entrée est **supprimée** ; l'expéditeur repasse par nomic et Gemma.
- Mails rangés par nomic seul (étape 5) ou par une règle (étapes 1, 3, 4) : **aucun apprentissage**.
- Les domaines sont recalculés à chaque `build`, pas au fil de l'eau.
- `--validate` : rien n'est écrit (même principe que `ClassificationDatabase(read_only=True)`).

## 5. Tes corrections

- Un mail que tu sors de `9-A revoir` vers une catégorie : l'expéditeur va dans `db/taxonomy/validated.json` (aujourd'hui, `archive.py` écrit dans l'ancienne base validée via `promote_to_validated` ; la cible change).
- `validated.json` prime sur tout le reste, y compris un apprentissage automatique.

## 6. Mesure

Commande `chain` de `scripts/eval_embeddings.py`, revue pour la vérité vérifiée :

- **Précision des règles apprises** : pour chaque expéditeur que tu as revu, la catégorie qu'aurait retenue `build` sans toi (accord dossier = Gemma) comparée à ta décision.
- **Chaîne nomic puis Gemma** : 500 mails d'expéditeurs validés (contenu lu en lecture seule). Les mails de l'expéditeur testé sont exclus du calcul des centroïdes. Calcule la part classée, la précision et le **seuil nomic** qui tient 90 %.
- **Couverture** : essai à blanc sur la vraie boîte de réception, ≥ 60 %.

## 7. Configuration

Ajouts à `[taxonomy]` (valeurs par défaut) :

```toml
taxonomy_db_dir = "db/taxonomy"
centroids_file = "data/taxonomy_centroids.npz"
learn_min_agreements = 2
domain_min_purity = 0.90
sender_min_mails = 2
```

`nomic_threshold` reste dans `[taxonomy]` ; sa valeur est fixée d'après `chain`.

## 8. Erreurs

- `scan` : dossier illisible sauté et journalisé.
- `crosscheck` : reprise après arrêt ; réponse illisible enregistrée comme `null` (l'expéditeur passe alors en tête de revue).
- `review` : chaque clic enregistré immédiatement.
- `build` : entrée manquante, rien n'est écrit ; écritures atomiques.
- Apprentissage : une contradiction supprime l'entrée, jamais d'écrasement silencieux.
- Fichier de règles ou de centroïdes absent en production : le signal correspondant est sauté ; les mails non classés vont dans `9-A revoir`.

## 9. Tests

- Un module de tests par étape : scan (dossiers ignorés, dossier illisible), crosscheck (reprise, réponse illisible), build (seuils `sender_min_mails` et `domain_min_purity`, validé prioritaire, domaines grand public exclus), apprentissage (promotion à 2 accords, suppression sur contradiction, pas d'apprentissage sur nomic seul, rien écrit en `--validate`), nouvelle chaîne (ordre des signaux, fichiers absents).
- Garanties existantes conservées : `enabled = false` ne change rien, Gmail garde le flux actuel, `--validate` n'écrit rien.
