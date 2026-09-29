# User Guide

How to live with MailTag day to day, once it is installed and configured. For every command and option,
see [Usage](getting-started/usage.md); for how a category is chosen, see
[Classification Strategy](architecture/classification.md).

## The idea

MailTag empties your inbox into a few **action folders** that say what to do with a mail. Once you have
read a mail and it is old enough, MailTag files it into one of **19 categories** that say what it is
about. Mail it is not sure about goes to `5-A revoir`, and every mail you file from there teaches it a rule.

## Your folders

### Action folders: what to do

| Folder | What lands there | What you do |
|---|---|---|
| `1-A traiter` | Mail written by a person (not a newsletter, not a `noreply` address) | Answer or act |
| `2-A payer` | A bill: a money category (bank, energy & telecom, insurance, taxes) with a bill word in the subject (`facture`, `rappel`, `invoice`, `Rechnung`…) | Pay it |
| `3-A lire` | Newsletters and media you may want to read | Read when you have time |
| `4-Pour info` | Everything else that was classified: notifications, receipts, confirmations | Glance at it |
| `Promotions` | Offers from mailing lists (`%`, `promo`, `soldes`, `sale`…) | Ignore or browse |
| `5-A revoir` | Mail MailTag could not classify with confidence | File it into its category (see [Teach MailTag](#teach-mailtag)) |

`Promotions` is the provider's own folder: Infomaniak's standard `Promotions` folder, and Gmail's
Promotions tab (the mail stays in the Gmail inbox, under that tab).

### Category folders: what it is about

Categories follow [PARA](https://fortelabs.com/blog/para/):

- `Domaines/` — areas of your life you are responsible for: Banque & Placements, Assurances & Retraite,
  Impôts & Administration, Énergie & Télécom, Santé, Famille & École, Logement & Maison,
  Transports & Mobilité, Sécurité & Comptes, Carrière & Formation, Associations & Communauté, Contacts.
- `Ressources/` — topics you look things up in: Veille & Newsletters pro, Éditeurs IT & Cloud,
  Outils & Services en ligne, Médias & Divertissement, Voyages & Loisirs.
- `Archive/` — things you only keep: Achats, Colis & Livraisons (next to the provider's standard `Archive`).

You rarely need to open them: search your mail client, or browse a category when you need its history.

## Daily routine

1. Run MailTag (by hand or from a scheduler):
   ```bash
   uv run python src/main.py run --provider all
   ```
   `all` runs Infomaniak, then Gmail. It files the inbox, archives old mail, then learns from `5-A revoir`.
2. Work through `1-A traiter` and `2-A payer`; read `3-A lire` when you like.
3. Now and then, file what sits in `5-A revoir`.

### When a mail leaves an action folder

At the end of each run, a mail moves from its action folder to its category when all of these hold:

- you have **read** it,
- it is **not flagged** (starred on Gmail),
- it arrived at least `archive_after_days` ago (7 days by default, `[taxonomy]` in `config.toml`).

So **flag a mail to keep it in its action folder**; unflag it and the next run archives it. Mail in
`5-A revoir` is never archived automatically. In `Promotions`, only mail MailTag put there is archived;
mail the provider sorted there itself stays.

## Teach MailTag

MailTag gets better from your decisions. Rules live in `db/taxonomy/` and are shared by both accounts.

- **File a mail out of `5-A revoir`** into its category folder (for example drag it to
  `Domaines/Santé`). The next run notices it and makes its sender a validated rule: that sender's next
  mails go straight to the right place.
- **Agreements**: when the embedding model (nomic) and the language model (Gemma) agree twice on a
  sender, the sender becomes a learned rule on its own; a later disagreement removes it.
- **Review page**, for decisions in bulk:
  ```bash
  uv run streamlit run scripts/taxonomy_review.py
  ```
  Stage 3 lets you confirm senders learned during runs; stage 5 decides the mail in `5-A revoir` per
  domain or per sender (see below). Every click is saved at once; nothing leaves your machine.

### When `5-A revoir` gets big

After a first run on a new account, or when many new senders appear, file it in bulk:

```bash
uv run python scripts/taxonomy_setup.py review-scan --provider gmail           # read-only
uv run streamlit run scripts/taxonomy_review.py                                # stage 5
uv run python scripts/taxonomy_setup.py refile-review --provider gmail         # dry run: what would move
uv run python scripts/taxonomy_setup.py refile-review --provider gmail --apply # move it
```

Use `--provider imap` for Infomaniak. Start with the biggest rows: a few dozen decisions usually cover
most of the mail. Use **Par expéditeur** on platforms where one domain carries unrelated senders
(`substack.com`, `medium.com`, `amazon.com`…). Senders with a single mail can stay for manual filing.

### Fixing a wrong rule

A validated sender or domain is never overridden by the models. To correct one:

- move the mails you see into the right category folder by hand;
- fix the rule: stage 4 of the review page shows a sample of rule-covered senders with a category
  picker; otherwise edit `db/taxonomy/validated.json` (senders) or `validated_domains.json` (domains)
  while no `run` or review page is open.

## Gmail specifics

- Gmail is reached through the Gmail API. Folders are **labels**: "moving" a mail out of the inbox
  removes its `INBOX` label, and the mail stays in "All Mail". Your own labels are never touched.
- **Token expiry**: while the OAuth app is in "Testing" mode, the token lasts 7 days. When it expires,
  `run --provider all` skips Gmail with a message. Delete `secrets/token.json`, then run
  `uv run python src/main.py run --provider gmail --validate` and approve in the browser.
- **Quota pauses**: a log line `Gmail quota reached, pausing 60s` is normal on big runs; the run resumes
  on its own. Leave it running.

## Good habits

- Try a change with `--validate` (runs) or without `--apply` (setup commands) first: nothing moves.
- Do not run two things that write the mailbox at once: no `run` during `migrate --apply` or
  `refile-review --apply`, and no `serve` in Docker (with `db/` mounted) during a `run` on the Mac.
- Point your mail client's special folders to `Sent`, `Trash`, `Spam` and `Archive`, or it may
  recreate duplicates (`Sent Messages`, `Junk`…).
- `db/` holds your rules: back it up. Classification databases are also backed up to `db/backups/` at
  each run.
