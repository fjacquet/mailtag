"""Local review page (spec section 1.3): audit contested folders, review senders, then check
senders learned during runs.

    uv run streamlit run scripts/taxonomy_review.py

Every click is written to db/taxonomy/ at once. Nothing leaves this machine.
After the folder audit, run `scripts/taxonomy_setup.py scan` again before reviewing senders.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import streamlit as st
from taxonomy_setup import needs_rescan

from mailtag.config import CONFIG
from mailtag.taxonomy import TAXONOMY
from mailtag.taxonomy_build import (
    folder_category,
    folder_disagreement,
    folder_queue,
    gemma_proposals,
    learned_to_review,
    mail_count,
    review_queue,
)
from mailtag.taxonomy_store import TaxonomyStore

SCAN = Path("data/mailbox_scan.json")
CROSSCHECK = Path("data/sender_crosscheck.json")
OVERRIDES = Path(CONFIG.taxonomy.taxonomy_db_dir) / "folder_overrides.json"

st.set_page_config(page_title="MailTag — revue des expéditeurs", layout="wide")

if not SCAN.exists() or not CROSSCHECK.exists():
    st.error("Lance d'abord `scan` puis `crosscheck` (scripts/taxonomy_setup.py).")
    st.stop()

scan = json.loads(SCAN.read_text(encoding="utf-8"))
senders = scan["senders"]
cross = json.loads(CROSSCHECK.read_text(encoding="utf-8"))
store = TaxonomyStore(Path(CONFIG.taxonomy.taxonomy_db_dir))
skipped = st.session_state.setdefault("skipped", set())

# --- Stage 1: folder audit ---
folders = folder_queue(scan["folders"], cross, store.folder_overrides)
if folders:
    folder = folders[0]
    info = scan["folders"][folder]
    st.caption(f"Étape 1 — audit des dossiers : {len(folders)} dossiers contestés restants")
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
    columns = st.columns(4)
    for i, category in enumerate(TAXONOMY):
        if columns[i % 4].button(category, key=f"folder-{folder}-{category}"):
            store.set_folder_category(folder, category)
            store.save()
            st.rerun()
    if st.button("Aucune catégorie"):
        store.set_folder_category(folder, None)
        store.save()
        st.rerun()
    st.stop()

if needs_rescan(SCAN, OVERRIDES):
    st.info("Audit des dossiers terminé. Relance `scripts/taxonomy_setup.py scan`, puis recharge cette page.")
    st.stop()

# --- Stage 2: sender review ---
queue = [s for s in review_queue(senders, cross, store.validated) if s not in skipped]

st.caption(f"{len(store.validated)} expéditeurs validés · {len(queue)} restants")
if not queue:
    # --- Stage 3: senders promoted during runs (not in the scan) ---
    learned = [
        s
        for s in learned_to_review(
            store.senders, senders, store.validated, CONFIG.taxonomy.learn_min_agreements
        )
        if s not in skipped
    ]
    if not learned:
        st.success("Revue terminée.")
        st.stop()
    sender = learned[0]
    entry = store.senders[sender]
    st.caption(f"Expéditeurs appris pendant les passages : {len(learned)} à vérifier")
    st.header(sender)
    st.write(f"Appris : **{entry['category']}** · {entry['agreements']} accords nomic et Gemma")
    if st.button(f"Confirmer : {entry['category']}"):
        store.set_validated(sender, entry["category"])
        store.save()
        st.rerun()
    columns = st.columns(4)
    for i, category in enumerate(TAXONOMY):
        if columns[i % 4].button(category, key=f"learned-{sender}-{category}"):
            store.set_validated(sender, category)
            store.save()
            st.rerun()
    if st.button("Passer"):
        skipped.add(sender)
        st.rerun()
    st.stop()

sender = queue[0]
entry = senders[sender]
st.header(sender)
st.write(f"**{entry['name'] or '(sans nom)'}** · {mail_count(entry)} mails · domaine `{entry['domain']}`")
st.write(f"Dossier : **{folder_category(entry)}** · Gemma : **{cross.get(sender) or '(illisible)'}**")
for subject in entry["subjects"]:
    st.write(f"- {subject}")

columns = st.columns(4)
for i, category in enumerate(TAXONOMY):
    if columns[i % 4].button(category, key=f"{sender}-{category}"):
        store.set_validated(sender, category)
        store.save()
        st.rerun()
if st.button("Passer"):
    skipped.add(sender)
    st.rerun()
