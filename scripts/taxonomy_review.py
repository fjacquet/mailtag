"""Local review page (spec section 1.3): audit contested folders, review senders, check senders
learned during runs, check a random sample of rule-covered senders to measure rule precision, and
decide, by domain or by sender, the mails waiting in 5-A revoir (docs/superpowers/specs/
2026-09-29-revue-en-masse-design.md), from `scripts/taxonomy_setup.py review-scan` output.

    uv run streamlit run scripts/taxonomy_review.py

Every click is written to db/taxonomy/ at once. Nothing leaves this machine.
After the folder audit, run `scripts/taxonomy_setup.py scan` again before reviewing senders.
"""

import json
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import streamlit as st
from taxonomy_setup import needs_rescan, review_scan_path

from mailtag.config import CONFIG
from mailtag.review_refile import coverage as review_coverage
from mailtag.review_refile import review_queue as review_refile_queue
from mailtag.taxonomy import TAXONOMY
from mailtag.taxonomy_build import (
    control_precision,
    control_sample,
    domain_rules,
    folder_category,
    folder_disagreement,
    folder_queue,
    gemma_proposals,
    learned_senders,
    learned_to_review,
    mail_count,
    review_queue,
)
from mailtag.taxonomy_store import TaxonomyStore, write_json_atomic

SCAN = Path("data/mailbox_scan.json")
CROSSCHECK = Path("data/sender_crosscheck.json")
OVERRIDES = Path(CONFIG.taxonomy.taxonomy_db_dir) / "folder_overrides.json"
# Drawn once after `build`, so validating a sender does not change the sample or lose its rule
CONTROL = Path(CONFIG.taxonomy.taxonomy_db_dir) / "control.json"
CONTROL_SIZE = 60


def _load_review_scans() -> tuple[dict, dict]:
    """Merge `review_scan_imap.json` and `review_scan_gmail.json`, whichever exist.

    Same key from both accounts: mails add up, senders merge, the first account's subjects and
    suggestion win.
    """
    groups: dict = {}
    suggestions: dict = {}
    for provider in ("imap", "gmail"):
        path = review_scan_path(provider)
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, g in data["groups"].items():
            if key not in groups:
                groups[key] = {
                    "kind": g["kind"],
                    "mails": 0,
                    "senders": {},
                    "subjects": list(g["subjects"]),
                }
            existing = groups[key]
            existing["mails"] += g["mails"]
            for address, s in g["senders"].items():
                total = existing["senders"].setdefault(address, {"name": s["name"], "mails": 0})
                total["mails"] += s["mails"]
        for key, suggestion in data["suggestions"].items():
            suggestions.setdefault(key, suggestion)
    return groups, suggestions


def _sort_key(name: str) -> str:
    """Alphabetical, ignoring accents (É sorts with E)."""
    return "".join(c for c in unicodedata.normalize("NFD", name) if not unicodedata.combining(c)).casefold()


# Buttons only: TAXONOMY keeps its order, which numbers the categories in the Gemma prompt
CATEGORIES = sorted(TAXONOMY, key=_sort_key)

st.set_page_config(page_title="MailTag — revue des expéditeurs", layout="wide")

store = TaxonomyStore(Path(CONFIG.taxonomy.taxonomy_db_dir))
skipped = st.session_state.setdefault("skipped", set())
split = st.session_state.setdefault("split", set())
# Stage 5 keys are domains or addresses: skipping one there must not hide it in stages 2-4
review_skipped = st.session_state.setdefault("review_skipped", set())


def category_buttons(key: str, on_pick) -> None:
    """One button per category; the click is saved at once and the page moves on."""
    columns = st.columns(4)
    for i, category in enumerate(CATEGORIES):
        if columns[i % 4].button(category, key=f"{key}-{category}"):
            on_pick(category)
            store.save()
            st.rerun()


def skip_button(sender: str, into: set | None = None) -> None:
    if st.button("Passer"):
        (skipped if into is None else into).add(sender)
        st.rerun()


# Stage 5's source (data/review_scan_*.json) is independent of scan/crosscheck, so it is loaded
# even when those are missing.
review_groups_data, review_suggestions = _load_review_scans()
review_rows = review_refile_queue(review_groups_data, store.category_for, split, review_skipped)

scan_ready = SCAN.exists() and CROSSCHECK.exists()
if scan_ready:
    scan = json.loads(SCAN.read_text(encoding="utf-8"))
    senders = scan["senders"]
    cross = json.loads(CROSSCHECK.read_text(encoding="utf-8"))
    folders = folder_queue(scan["folders"], cross, store.folder_overrides)
    cfg = CONFIG.taxonomy
    # What `build` will turn into rules on its own: those senders need no review
    planned = learned_senders(senders, cross, store.validated, cfg.sender_min_mails, cfg.learn_min_agreements)
    planned_domains = domain_rules(senders, store.validated, cfg.domain_min_purity)
    queue = [
        s
        for s in review_queue(senders, cross, store.validated, planned, planned_domains, cfg.sender_min_mails)
        if s not in skipped
    ]
    learned = [
        s
        for s in learned_to_review(store.senders, senders, store.validated, cfg.learn_min_agreements)
        if s not in skipped
    ]
    if not CONTROL.exists() and (store.senders or store.domains):
        write_json_atomic(
            CONTROL, control_sample(senders, store.category_for, store.validated, CONTROL_SIZE, 0)
        )
    control = json.loads(CONTROL.read_text(encoding="utf-8")) if CONTROL.exists() else {}
    to_check = [s for s in control if s not in store.validated and s not in skipped]
else:
    folders, queue, learned, to_check = [], [], [], []

STAGES = {
    f"1. Dossiers contestés ({len(folders)})": "folders",
    f"2. Expéditeurs du scan ({len(queue)})": "senders",
    f"3. Expéditeurs appris pendant les passages ({len(learned)})": "learned",
    f"4. Contrôle des règles ({len(to_check)})": "control",
    f"5. Mails en revue ({len(review_rows)})": "review",
}
# Stages 2-4 wait for a new `scan` after a folder audit: open on stage 5 rather than on that notice
current = not (scan_ready and needs_rescan(SCAN, OVERRIDES))
default = (
    0 if folders
    else 1 if queue and current
    else 2 if learned and current
    else 3 if to_check and current
    else 4 if review_rows
    else 1
)  # fmt: skip
stage = STAGES[st.sidebar.radio("Étape", list(STAGES), index=default)]
st.caption(f"{len(store.validated)} expéditeurs validés")

if stage != "review" and not scan_ready:
    st.error("Lance d'abord `scan` puis `crosscheck` (scripts/taxonomy_setup.py).")
    st.stop()

# --- Stage 1: folder audit ---
if stage == "folders":
    if not folders:
        st.success("Aucun dossier contesté.")
        st.stop()
    folder = folders[0]
    info = scan["folders"][folder]
    st.header(folder)
    st.write(
        f"Catégorie actuelle : **{info['category']}** · {sum(info['senders'].values())} mails · "
        f"{folder_disagreement(info, cross):.0%} contestés"
    )
    st.write("Gemma propose : " + ", ".join(f"{c} ({n})" for c, n in gemma_proposals(info, cross)))
    for s, n in sorted(info["senders"].items(), key=lambda kv: -kv[1])[:8]:
        st.write(f"- {s} ({n}) → Gemma : {cross.get(s) or '(illisible)'}")
    if st.button(f"Confirmer : {info['category']}"):
        store.set_folder_category(folder, info["category"])
        store.save()
        st.rerun()
    category_buttons(f"folder-{folder}", lambda c: store.set_folder_category(folder, c))
    if st.button("Aucune catégorie"):
        store.set_folder_category(folder, None)
        store.save()
        st.rerun()
    st.stop()

if stage != "review" and needs_rescan(SCAN, OVERRIDES):
    st.info("Audit des dossiers modifié. Relance `scripts/taxonomy_setup.py scan`, puis recharge cette page.")
    st.stop()

# --- Stage 2: sender review ---
if stage == "senders":
    if not queue:
        st.success("Tous les expéditeurs du scan sont revus.")
        st.stop()
    sender = queue[0]
    entry = senders[sender]
    st.header(sender)
    st.write(f"**{entry['name'] or '(sans nom)'}** · {mail_count(entry)} mails · domaine `{entry['domain']}`")
    st.write(f"Dossier : **{folder_category(entry)}** · Gemma : **{cross.get(sender) or '(illisible)'}**")
    for subject in entry["subjects"]:
        st.write(f"- {subject}")
    category_buttons(sender, lambda c: store.set_validated(sender, c))
    skip_button(sender)
    st.stop()

# --- Stage 4: control sample of rule-covered senders ---
if stage == "control":
    checked, precision = control_precision(control, store.validated)
    if checked:
        st.write(f"Règles justes : **{precision:.0%}** sur {checked} expéditeurs contrôlés")
    if not to_check:
        st.success("Échantillon de contrôle terminé." if control else "Lance d'abord `build`.")
        st.stop()
    sender = to_check[0]
    entry = senders[sender]
    st.header(sender)
    st.write(f"**{entry['name'] or '(sans nom)'}** · {mail_count(entry)} mails · domaine `{entry['domain']}`")
    st.write(f"Règle : **{control[sender]}**")
    for subject in entry["subjects"]:
        st.write(f"- {subject}")
    if st.button(f"Confirmer : {control[sender]}"):
        store.set_validated(sender, control[sender])
        store.save()
        st.rerun()
    category_buttons(f"control-{sender}", lambda c: store.set_validated(sender, c))
    skip_button(sender)
    st.stop()

# --- Stage 5: mails waiting in 5-A revoir (bulk review) ---
if stage == "review":
    if not review_rows:
        st.success(
            "Aucun mail en revue à traiter."
            if review_groups_data
            else "Lance d'abord `review-scan` (scripts/taxonomy_setup.py)."
        )
        st.stop()
    key, group = review_rows[0]
    covered, total = review_coverage(review_groups_data, store.category_for)
    st.header(key)
    st.caption(f"{covered}/{total} mails couverts")
    st.write(f"{group['mails']} mails · {group['kind']}")
    for address, s in sorted(group["senders"].items(), key=lambda kv: -kv[1]["mails"])[:5]:
        st.write(f"- {s['name'] or address} <{address}> ({s['mails']})")
    for subject in group["subjects"]:
        st.write(f"- {subject}")
    suggestion = review_suggestions.get(key)
    st.write(f"Gemma : **{suggestion or '(illisible)'}**")

    def pick(category: str) -> None:
        if group["kind"] == "domain":
            store.set_validated_domain(key, category)
        else:
            store.set_validated(key, category)

    if suggestion and st.button(f"Confirmer : {suggestion}"):
        pick(suggestion)
        store.save()
        st.rerun()
    category_buttons(f"review-{key}", pick)
    if group["kind"] == "domain" and st.button("Par expéditeur"):
        split.add(key)
        st.rerun()
    skip_button(key, review_skipped)
    st.stop()

# --- Stage 3: senders promoted during runs (not in the scan) ---
if not learned:
    st.success("Aucun expéditeur appris à vérifier.")
    st.stop()
sender = learned[0]
entry = store.senders[sender]
st.header(sender)
st.write(f"Appris : **{entry['category']}** · {entry['agreements']} accords nomic et Gemma")
if st.button(f"Confirmer : {entry['category']}"):
    store.set_validated(sender, entry["category"])
    store.save()
    st.rerun()
category_buttons(f"learned-{sender}", lambda c: store.set_validated(sender, c))
skip_button(sender)
