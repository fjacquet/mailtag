# Classification Strategy

MailTag files each email into one of **19 business-sector categories**. A chain of rules and models decides the category; the first step that matches wins. New mail first lands in an **action folder** and moves into its category folder later.

## Classification flow

Passes are only about cost: rules read headers, models read the body.

```
INBOX and junk folder (IMAP)
    |
    v
[Pass 1: rules on headers]   validated sender -> learned sender -> validated domain -> computed domain
    |                         match: routed to its action folder, pending_archive entry recorded
    | remaining UIDs
    v
[Pass 3: models on full body]
    nomic centroid score >= nomic_threshold        -> category
    else Gemma agrees with nomic's top choice      -> category (the sender earns one agreement)
    else                                           -> "5-A revoir"
    |
    v
[Archive sweep]  seen, unflagged mail older than archive_after_days -> its category folder
```

Gmail runs the same flow: `GmailApiService` is an `ImapService` over Gmail labels (see [Gmail](#gmail)). With `--validate` nothing moves and nothing is written.

## Categories

Banque & Placements, Assurances & Retraite, Impôts & Administration, Énergie & Télécom, Santé, Famille & École, Logement & Maison, Achats, Colis & Livraisons, Transports & Mobilité, Voyages & Loisirs, Médias & Divertissement, Veille & Newsletters pro, Éditeurs IT & Cloud, Outils & Services en ligne, Sécurité & Comptes, Carrière & Formation, Associations & Communauté, Contacts.

## Rules and models

| Step | Source | Result |
|------|--------|--------|
| Validated sender | `db/taxonomy/validated.json` | category |
| Learned sender | `db/taxonomy/senders.json`, after 2 nomic/Gemma agreements | category |
| Validated domain | `db/taxonomy/validated_domains.json` | category |
| Computed domain | `db/taxonomy/domains.json` (personal mailboxes excluded) | category |
| Nomic | 19 centroids, score at least `nomic_threshold` | category |
| Gemma | answers by category number, batched with a cached prompt prefix; must agree with nomic's top choice | category |
| Otherwise | | `5-A revoir` |

The owner's own addresses (`own_addresses`) never become a rule and are never learned from. A nomic/Gemma agreement is learned only once the mail has moved to its action folder, so a failed move retried later does not count twice; `/classify` and `/classify-batch` never learn. Without MLX (`[mlx] enabled = false`, the Docker image) only the four rule steps run and everything else goes to `5-A revoir`.

## Action folders

A classified email goes to an action folder; its category is remembered in the account's pending archive (`db/pending_archive.json`, `db/pending_archive_gmail.json`):

| Folder | When |
|--------|------|
| `2-A payer` | money category (bank, energy, insurance, taxes) and a bill-like subject |
| `1-A traiter` | sent by a person |
| `Promotions` (standard folder) | bulk mail with an unsubscribe link and a promo subject |
| `3-A lire` | newsletters, media |
| `4-Pour info` | everything else |
| `5-A revoir` | nothing decided |

Emails that are seen, unflagged and older than `archive_after_days` move from their action folder into their category folder. Category folders follow PARA: `Domaines/` (areas of responsibility), `Ressources/` (topics of interest) and the standard `Archive/` (Achats, Colis & Livraisons); projects are folders you create yourself. When you file a mail out of `5-A revoir` into a category, its sender becomes a validated rule.

## Bulk review of `5-A revoir`

Deciding mail-by-mail does not scale once `5-A revoir` holds thousands of mails from a new account. Instead the owner decides a category per **domain** or per **sender**, and one command moves every mail a rule now covers:

1. `scripts/taxonomy_setup.py review-scan --provider imap|gmail` (read-only) groups `5-A revoir` mail by domain — or by sender for a personal domain like `gmail.com` — skipping mail a rule already covers and the owner's own addresses, and writes a Gemma suggestion per group to `data/review_scan_<provider>.json`. Reruns keep suggestions already computed.
2. The review page's stage 5 ("Mails en revue") shows both accounts' scans, sorted by uncovered mail count, with a covered/total counter. Confirm Gemma's suggestion, pick one of the 19 categories, split a domain group into one row per sender for this session (`Par expéditeur`), or skip.
3. `scripts/taxonomy_setup.py refile-review --provider imap|gmail [--apply]` moves the mail a rule now covers to its category folder and drops the matching `pending_archive` entry (so a later archive sweep does not relearn it); mail with no rule stays in `5-A revoir`. Dry run by default, like every mailbox-writing command here.

A domain decision (`TaxonomyStore.set_validated_domain`, `db/taxonomy/validated_domains.json`) sits in the rule order right after learned senders and before the computed domain rules `build` writes to `domains.json`; `build` never replaces `validated_domains.json`.

## Gmail

Gmail runs through the **Gmail API** (`GmailApiService`, `src/mailtag/gmail_api.py`), not IMAP: `GmailLabelClient` implements the small IMAPClient subset the taxonomy flow uses (`select_folder`, `search`, `fetch`, `move`, `folder_exists`, `create_folder`, `list_folders`) on top of Gmail labels and categories.

| MailTag folder | Gmail |
|-----------------|-------|
| `INBOX` | system label `INBOX`, excluding `category:promotions` |
| junk folder | system label `SPAM` |
| `Promotions` | Gmail's own Promotions tab (`CATEGORY_PROMOTIONS`); the mail stays in `INBOX` |
| action folders (`1-A traiter` … `5-A revoir`), `Domaines/…`, `Ressources/…`, `Archive/…` | user labels of the same name, created on demand |

Moving a mail out of `INBOX` removes the `INBOX` label (Gmail's own "archive"); the mail stays in "All Mail". Moving a mail to `Promotions` adds `CATEGORY_PROMOTIONS`, removes the other `CATEGORY_*` labels and keeps `INBOX`. Other labels on the mail (a Gmail filter's `github`, `TRAVELS`, …) are never touched.

## Where the rules come from

The rules were learned once from the legacy folders (`scripts/taxonomy_setup.py`, see [Usage](../getting-started/usage.md#taxonomy-setup)): a read-only scan of every folder, a Gemma opinion per sender, a folder audit and a sender review in a local Streamlit page, then `build`. On a random control sample, the learned and domain rules were right for 59 of 60 senders.
