# Taxonomie à 19 catégories et dossiers d'action — design (spec 1/2)

Date : 2026-09-27
Statut : à relire
Périmètre : nouveau flux de classification IMAP. La migration des 611 dossiers existants fait l'objet de la spec 2.

## Contexte et mesures

Aujourd'hui, MailTag classe dans 611 dossiers IMAP : 221 `Contacts/<personne>`, environ 225 dossiers de fournisseurs, 31 dossiers vides et 200 dossiers d'un ou deux mails. Mesures sur 5 680 mails déjà rangés (`scripts/eval_embeddings.py`, test en écartant l'expéditeur du mail testé) :

| | 611 dossiers | 19 catégories |
|---|---|---|
| nomic, bonne réponse en 1er choix | 39 % | 50 % |
| nomic, mails classables à ≥ 85 % de justesse | 0,1 % | 27,7 % |
| Gemma 4 E4B, bonne réponse en 1er choix (100 mails) | 16 % | 66 % |
| Gemma, durée par mail | 11,5 s | 1,1 s (lots de 8, cache du début du prompt, réponse par numéro) |
| Chaîne nomic → Gemma → accord (100 mails) | — | 50 % classés, 92 % justes |

Gemma se dit confiant à plus de 0,85 dans 97 % des cas, même quand il a tort. Sa confiance n'est donc pas utilisée.

## Objectifs

1. Classer chaque mail entrant dans une des 19 catégories métier, ou l'envoyer au ramasse-miettes s'il y a un doute.
2. Déposer chaque mail dans un dossier d'action, puis l'archiver automatiquement dans sa catégorie.
3. Ne jamais ranger un mail au hasard : en cas de doute ou de panne, il va dans `9-A revoir`.

**Critères de succès**, mesurés sur au moins 500 mails avant la mise en service, avec la commande `chain` (section 9) :

- au moins 45 % des mails classés automatiquement ;
- au moins 90 % de justesse sur ces mails ;
- Gemma à 1,5 s par mail au plus.

## Hors périmètre

- Migration des 611 dossiers existants (spec 2).
- Purge des vieilles promos.
- Raccourcissement du corps de mail envoyé à Gemma.
- Fournisseur Gmail : il garde son comportement actuel.

## 1. Arborescence cible

Tous les dossiers sont au premier niveau, sans sous-dossiers.

- **Dossiers d'action (6) :** `1-A traiter`, `2-A payer`, `3-A lire`, `4-Pour info`, `5-Promos`, `9-A revoir`.
- **Dossiers de catégorie (19),** définis dans `TAXONOMY` :
  - Banque & Placements
  - Assurances & Retraite
  - Impôts & Administration
  - Énergie & Télécom
  - Santé
  - Famille & École
  - Logement & Maison
  - Achats
  - Colis & Livraisons
  - Transports & Mobilité
  - Voyages & Loisirs
  - Médias & Divertissement
  - Veille & Newsletters pro
  - Éditeurs IT & Cloud
  - Outils & Services en ligne
  - Sécurité & Comptes
  - Carrière & Formation
  - Associations & Communauté
  - Contacts

MailTag crée les dossiers manquants au premier passage. Jusqu'à la spec 2, les anciens dossiers restent en place et ne sont plus utilisés comme destinations.

## 2. Composants

| Unité | Rôle | Dépend de |
|---|---|---|
| `mailtag/taxonomy.py` | `TAXONOMY` (19 catégories et leur description), `map_folder(ancien_dossier)`, liste des dossiers d'action. Reprend `scripts/taxonomy.py`. | rien |
| `mailtag/action_rules.py` | `choose_action(email, category) -> dossier d'action`, règles pures (section 4). | `taxonomy` |
| `Classifier` (modifié) | Chaîne de catégorisation (section 3). Renvoie `category` ou `None` (doute). | `taxonomy`, bases de données, `SemanticRouter`, `MLXLLM` |
| `MLXLLM` (modifié) | `classify_batch(emails) -> list[int or None]` : début du prompt calculé une seule fois (`make_prompt_cache`), puis `batch_generate` par lots de 8 avec `prompt_caches`, réponse par numéro (`max_tokens=4`). | mlx-lm ≥ 0.31 |
| `mailtag/archive.py` | Ramasse-miettes de fin de passage (section 6). | `ImapService`, base des mails en attente |
| `db/pending_archive.json` | Mémoire de la catégorie de chaque mail pendant son séjour en dossier d'action (7 jours après lecture) : `Message-ID -> {category, sender, added}`. Les entrées sont supprimées à l'archivage. | — |
| `data/legacy_folders.json` | Instantané figé de l'arborescence telle qu'elle est aujourd'hui (611 dossiers au 2026-09-27), copié une fois depuis `data/imap_folders.json` avant toute modification de la boîte. `scripts/build_category_embeddings.py` le lit à la place de `imap_folders.json` pour construire les exemples de nomic. | — |

`Classifier`, `MLXLLM` et `ImapService` gardent leurs interfaces existantes. On ajoute seulement `classify_batch` et la lecture de nouveaux en-têtes.

## 3. Catégorisation d'un mail

Les signaux sont évalués dans l'ordre. Le premier qui décide l'emporte.

1. **Règles par expéditeur et par domaine** (signaux 1, 3 et 4 existants) : les valeurs des bases actuelles, qui sont d'anciens chemins de dossier, sont converties au chargement par `map_folder`. Une valeur qui ne correspond à aucune catégorie est ignorée.
2. **Libellés côté serveur** (signal 2) : une étiquette déjà posée sur le serveur est convertie de la même manière.
3. **nomic** (signal 5) : les centroïdes restent ceux des 611 dossiers d'aujourd'hui (`data/category_embeddings.npz`, construits à partir de `data/legacy_folders.json`). On prend l'ancien dossier le plus proche, puis on le convertit par `map_folder`. On classe si le score est d'au moins `taxonomy.nomic_threshold` (0,70 par défaut). On garde aussi ce premier choix de nomic pour l'étape suivante, même sous le seuil.
4. **Gemma** (signal 6) : les mails restants sont envoyés par lots de 8 à `classify_batch`. Si le numéro renvoyé correspond au premier choix de nomic, on classe. Sinon, ou si la réponse est illisible, la catégorie vaut `None`.

`None` signifie : destination `9-A revoir`.

Le prompt de Gemma est construit comme suit. Le début, calculé une seule fois, contient la consigne et la liste numérotée « numéro. nom : description » des 19 catégories. Il se termine par « Réponds uniquement par le numéro de la catégorie ». Viennent ensuite le sujet, l'expéditeur et le corps tronqué à 500 caractères (`smart_truncate`).

## 4. Choix du dossier d'action

La fonction `choose_action(email, category)` est pure. La première règle qui s'applique l'emporte.

1. `category is None` → `9-A revoir`.
2. **A payer :** catégorie parmi Banque & Placements, Énergie & Télécom, Assurances & Retraite, Impôts & Administration, et le sujet contient un de ces mots, sans tenir compte des majuscules ni des accents : `facture`, `échéance`, `rappel`, `paiement`, `montant dû`, `invoice`, `rechnung`, `mahnung`, `bill`, `payment due`. Destination : `2-A payer`.
3. **A traiter :** mail de personne à personne. Il n'a pas d'en-tête `List-Unsubscribe`, `List-Id` ni `Precedence: bulk/list`, et la partie locale de l'adresse ne contient ni `noreply`, ni `no-reply`, ni `notification`, ni `newsletter`, ni `info@`, ni `news@`. Destination : `1-A traiter`.
4. **Promos :** en-tête `List-Unsubscribe` présent, et le sujet contient `%`, `offre`, `promo`, `rabais`, `soldes`, `réduction`, `sale`, `rabatt` ou `angebot`. Destination : `5-Promos`.
5. **A lire :** catégorie Veille & Newsletters pro ou Médias & Divertissement. Destination : `3-A lire`.
6. Sinon, `4-Pour info`.

La lecture des en-têtes IMAP s'étend à `LIST-UNSUBSCRIBE LIST-ID PRECEDENCE MESSAGE-ID`, en plus de `FROM SUBJECT`.

## 5. Parcours d'un mail entrant

1. Les passes 1 à 3 existantes déterminent la catégorie (section 3).
2. `choose_action` détermine le dossier d'action.
3. Le mail est déplacé vers son dossier d'action (`batch_move_emails`). Après chaque déplacement groupé réussi, on enregistre `Message-ID -> {category, sender}` dans `db/pending_archive.json`. Pour les mails de `9-A revoir`, `category` vaut `null`.

Avec `--validate`, rien n'est déplacé ni enregistré. Le journal affiche, pour chaque mail, la catégorie, le dossier d'action et le signal qui a décidé.

## 6. Ramasse-miettes (fin de passage)

Pour chaque dossier d'action, sauf `9-A revoir` :

- **Critères :** mails `\Seen`, non `\Flagged`, dont la date de réception (`INTERNALDATE`) remonte à au moins `taxonomy.archive_after_days` jours (7 par défaut). IMAP ne fournit pas la date de lecture ; ces critères en tiennent lieu.
- **Action :** chaque mail retenu part vers la catégorie trouvée dans `pending_archive` grâce à son `Message-ID`, et l'entrée est supprimée.
- **Mail inconnu de `pending_archive`** (déposé à la main, par exemple) : il reste en place.
- **Mail non lu :** il ne bouge jamais.
- **Entrée orpheline :** une entrée dont le `Message-ID` ne se trouve plus dans aucun dossier d'action (mail supprimé ou déplacé à la main hors du flux) est supprimée. Le fichier reste ainsi limité aux mails présents dans les dossiers d'action.

Pour `9-A revoir`, rien n'est déplacé. Pour chaque entrée de `pending_archive` dont `category` vaut `null`, MailTag cherche le `Message-ID` dans les 19 dossiers de catégorie (`SEARCH HEADER Message-ID`). S'il le trouve, l'expéditeur et la catégorie sont ajoutés à la base validée (signal 1), et l'entrée est supprimée. C'est ainsi que tes corrections deviennent des règles.

## 7. Configuration

Nouvelle section dans `config.toml` :

```toml
[taxonomy]
enabled = true              # false = comportement actuel (611 dossiers)
nomic_threshold = 0.70
llm_batch_size = 8
archive_after_days = 7
```

`enabled = false` conserve l'ancien flux, pour pouvoir revenir en arrière. La valeur `llm_confidence` n'est plus utilisée quand `enabled = true`.

## 8. Erreurs et sécurité

- **nomic indisponible :** le signal 5 est sauté, et Gemma classe seul. La vérification d'accord ne peut plus se faire, donc tout mail classé par Gemma va dans `9-A revoir`.
- **Gemma indisponible ou en erreur sur un lot :** les mails du lot vont dans `9-A revoir`.
- **Échec de déplacement IMAP :** le mail reste où il est, rien n'est enregistré, et il sera retraité au passage suivant.
- **Écriture de `pending_archive` :** l'écriture est atomique (fichier temporaire, puis renommage), comme pour les autres bases.
- **API webhook :** elle utilise le même `Classifier`. Les réponses gagnent un champ `action` et renvoient les nouveaux noms de catégorie.

## 9. Tests

- `taxonomy` : les tests existants de `map_folder` sont déplacés.
- `action_rules` : un test par règle, plus l'ordre de priorité (une facture envoyée par une personne doit aller dans `2-A payer`).
- `Classifier` : la chaîne nomic → Gemma → accord, avec nomic et Gemma simulés : accord, désaccord, sous le seuil, réponse illisible, modèle indisponible.
- `MLXLLM.classify_batch` : analyse du numéro renvoyé et découpage en lots, avec `batch_generate` simulé.
- `archive` : critères de sélection (lu, étoilé, âge, inconnu) et apprentissage depuis `9-A revoir`, avec le client IMAP simulé existant (`tests/mock_imap_client.py`).
- **Mesure :** une commande `chain` ajoutée à `scripts/eval_embeddings.py` rejoue la chaîne complète de la section 3 (nomic, puis Gemma par lots avec réponse par numéro, puis vérification d'accord) sur au moins 500 mails. Elle doit atteindre les critères de succès avant d'activer `enabled = true`.
