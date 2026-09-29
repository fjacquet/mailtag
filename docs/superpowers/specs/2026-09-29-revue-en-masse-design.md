# Revue en masse de `5-A revoir` — design

Date : 2026-09-29.

## Contexte

- Premier run Gmail (API, taxonomie) : 3 400 mails sur 6 701 dans `5-A revoir`. Les règles viennent d'Infomaniak ; les expéditeurs Gmail sont surtout différents.
- 630 expéditeurs, 382 domaines. 86 domaines couvrent 80 % des mails ; les 124 domaines de 5 mails ou plus en couvrent 87 %.
- Plateformes où un domaine regroupe des expéditeurs sans rapport : gmail.com, hotmail.com (non commerciaux, déjà exclus des règles de domaine), substack.com, medium.com, beehiiv.com, google.com, amazon.
- Trier 3 400 mails à la main n'est pas réaliste ; décider ~90 domaines ou expéditeurs l'est.

## Décisions

1. Une décision porte sur un **domaine** (tous ses expéditeurs, présents et futurs) ou sur un **expéditeur**.
2. Les domaines décidés à la main vont dans un nouveau fichier `db/taxonomy/validated_domains.json`, que `build` ne remplace jamais (il remplace `domains.json`).
3. Les mails couverts par une règle sont déplacés de `5-A revoir` vers leur dossier de catégorie PARA par une commande, dry run par défaut, `--apply` lancé par le propriétaire.
4. Valable pour les deux comptes (`--provider imap|gmail`) ; le cas qui motive est Gmail.

## Ordre des règles (`TaxonomyStore.category_for`)

expéditeur validé → expéditeur appris → **domaine validé** → domaine calculé (`build`).
Un domaine non commercial (gmail.com…) n'a jamais de règle de domaine, validée ou non.

## Composants

### `taxonomy_setup.py review-scan --provider imap|gmail` (lecture seule sur la boîte)

- Lit `5-A revoir` du compte : en-têtes From (nom, adresse) et Subject.
- Ignore les mails qu'une règle couvre déjà (ils partiront avec `refile-review`) et les `own_addresses`.
- Regroupe : clé = domaine, sauf domaine non commercial → clé = adresse.
- Par groupe : nombre de mails, expéditeurs (adresse, nom, nombre), jusqu'à 5 sujets.
- Suggestion Gemma par groupe (prompt existant `llm_sender_static_prompt`/`llm_sender_part`, le domaine ou l'expéditeur principal comme nom, les sujets du groupe), en local, par lots.
- Écrit `data/review_scan_<provider>.json`. Reprise possible : les suggestions déjà calculées sont gardées.

### Page de revue : étape 5 « Mails en revue »

- Source : `data/review_scan_imap.json` et `data/review_scan_gmail.json` s'ils existent ; groupes sans règle, triés par nombre de mails décroissant, `Passer` comme ailleurs.
- Affiche : clé, nombre de mails, expéditeurs principaux, sujets, suggestion Gemma.
- Boutons : `Confirmer : <suggestion>`, une catégorie parmi les 19, `Par expéditeur` (groupe de domaine seulement : remplace la ligne du domaine par une ligne par expéditeur, pour cette session), `Passer`.
- Groupe domaine → `set_validated_domain(domaine, catégorie)` ; groupe expéditeur → `set_validated(adresse, catégorie)` (règle existante).
- Compteur : mails couverts / total, pour voir l'effet des décisions.

### `TaxonomyStore`

- Nouveau fichier `validated_domains.json` (chargé, rechargé et verrouillé comme les autres), nouvelle opération `validate_domain`, méthode `set_validated_domain(domain, category)`.

### `taxonomy_setup.py refile-review --provider imap|gmail [--apply]`

- Sélectionne `5-A revoir`, lit Message-ID et From de chaque mail.
- Catégorie = `category_for(expéditeur)` ; sans règle, le mail reste.
- Dry run : nombre de mails par catégorie et nombre restant. `--apply` : `batch_move_emails` vers `category_folder(catégorie)`, et retrait de l'entrée `pending_archive` correspondante (sinon le prochain archivage la « réapprendrait » comme règle d'expéditeur).
- Déplacement direct vers la catégorie, même pour un mail non lu : le stock en revue est ancien (non lus : 115 sur 3 400 côté Gmail).
- Bloqué pendant qu'un `run` ou `serve` pourrait écrire (même garde que `migrate`) ; ne pas lancer pendant un `run`.

## Hors périmètre

- Décider mail par mail ; les expéditeurs à un seul mail restent en revue manuelle (dossier `5-A revoir`, apprentissage existant).
- Liste de plateformes codée en dur : le bouton `Par expéditeur` suffit.

## Tests

- `category_for` : domaine validé entre expéditeur appris et domaine calculé ; `build` (`replace_rules`) ne touche pas aux domaines validés ; domaine non commercial ignoré.
- `review-scan` : regroupement domaine/adresse, mails couverts et adresses propres exclus, sujets limités, reprise des suggestions.
- `refile-review` : dry run sans déplacement ni écriture ; `--apply` déplace par catégorie, retire les entrées pending, laisse les mails sans règle ; sur le faux Gmail et sur le faux IMAP.
- Page : fonctions pures de file (groupes sans règle, éclatement par expéditeur, compteur) testées hors Streamlit.

## Validation réelle

1. `review-scan --provider gmail`, puis revue de l'étape 5 par le propriétaire.
2. `refile-review --provider gmail` (dry run) : rapport par catégorie.
3. Le propriétaire lance `refile-review --provider gmail --apply` ; vérification en lecture seule des libellés.
