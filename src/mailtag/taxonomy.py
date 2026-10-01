"""Business-sector taxonomy: 19 categories, action folders and folder mapping."""

import re

from .utils.text_utils import smart_truncate

TAXONOMY = {
    "Banque & Placements": "banques, cartes de crédit, paiements, bourse, crypto, crowdfunding, budget",
    "Assurances & Retraite": "assurances maladie, auto, habitation, voyage, caisses de pension, retraite",
    "Impôts & Administration": "impôts, commune, services publics, identité numérique, juridique",
    "Énergie & Télécom": "électricité, téléphone, internet, factures télécom",
    "Santé": "médecins, factures médicales, santé connectée, bien-être, coiffeur",
    "Famille & École": "enfants, école, crèche, membres de la famille",
    "Logement & Maison": "immobilier, gérance, location, déménagement, entretien, maison connectée",
    "Achats": "commerces, e-commerce, supermarchés, commandes, cartes de fidélité",
    "Colis & Livraisons": "suivi de colis, poste, transporteurs",
    "Transports & Mobilité": "trains, taxis, voiture, parking, vélos, covoiturage",
    "Voyages & Loisirs": "vols, hôtels, location de voiture, vacances, restaurants, spas, sorties",
    "Médias & Divertissement": "journaux, streaming, musique, jeux, recettes, culture",
    "Veille & Newsletters pro": "newsletters professionnelles, tech, marketing, startups, livres techniques",
    "Éditeurs IT & Cloud": "éditeurs de logiciels d'entreprise, cloud, infrastructure, webinaires IT",
    "Outils & Services en ligne": "outils en ligne, développement, IA, productivité, hébergement, logiciels",
    "Sécurité & Comptes": "alertes de connexion, mots de passe, antivirus, sauvegardes, rebonds de mails",
    "Carrière & Formation": "emploi, recrutement, LinkedIn, certifications, cours",
    "Associations & Communauté": "associations, dons, communautés, paroisse",
    "Contacts": "personnes qui écrivent directement",
}

# English label and description per category, for Laya's English checkpoint (which cannot read French)
TAXONOMY_EN = {
    "Banque & Placements": (
        "Banking & Investments",
        "banks, credit cards, payments, stock market, crypto, crowdfunding, budget",
    ),
    "Assurances & Retraite": (
        "Insurance & Pensions",
        "health, car, home and travel insurance, pension funds, retirement",
    ),
    "Impôts & Administration": (
        "Taxes & Government",
        "taxes, municipality, public services, digital identity, legal",
    ),
    "Énergie & Télécom": ("Energy & Telecom", "electricity, phone, internet, telecom bills"),
    "Santé": ("Health", "doctors, medical bills, connected health, wellness, hairdresser"),
    "Famille & École": ("Family & School", "children, school, daycare, family members"),
    "Logement & Maison": (
        "Housing & Home",
        "real estate, property management, rental, moving, maintenance, smart home",
    ),
    "Achats": ("Shopping", "shops, e-commerce, supermarkets, orders, loyalty cards"),
    "Colis & Livraisons": ("Parcels & Deliveries", "parcel tracking, post office, carriers"),
    "Transports & Mobilité": ("Transport & Mobility", "trains, taxis, car, parking, bikes, carpooling"),
    "Voyages & Loisirs": (
        "Travel & Leisure",
        "flights, hotels, car rental, holidays, restaurants, spas, outings",
    ),
    "Médias & Divertissement": (
        "Media & Entertainment",
        "newspapers, streaming, music, games, recipes, culture",
    ),
    "Veille & Newsletters pro": (
        "Professional Newsletters",
        "professional newsletters, tech, marketing, startups, technical books",
    ),
    "Éditeurs IT & Cloud": (
        "IT Vendors & Cloud",
        "enterprise software vendors, cloud, infrastructure, IT webinars",
    ),
    "Outils & Services en ligne": (
        "Online Tools & Services",
        "online tools, development, AI, productivity, hosting, software",
    ),
    "Sécurité & Comptes": (
        "Security & Accounts",
        "login alerts, passwords, antivirus, backups, bounced emails",
    ),
    "Carrière & Formation": ("Career & Training", "jobs, recruiting, LinkedIn, certifications, courses"),
    "Associations & Communauté": ("Associations & Community", "associations, donations, communities, parish"),
    "Contacts": ("Personal Contacts", "people writing directly"),
}  # fmt: skip

# PARA grouping of the category folders (Areas, Resources, Archives); projects are the owner's own
# folders. "Archive" is the providers' standard folder, reused rather than duplicated.
PARA = {
    **dict.fromkeys(
        ["Banque & Placements", "Assurances & Retraite", "Impôts & Administration", "Énergie & Télécom",
         "Santé", "Famille & École", "Logement & Maison", "Transports & Mobilité", "Sécurité & Comptes",
         "Carrière & Formation", "Associations & Communauté", "Contacts"],
        "Domaines",
    ),
    **dict.fromkeys(
        ["Veille & Newsletters pro", "Éditeurs IT & Cloud", "Outils & Services en ligne",
         "Médias & Divertissement", "Voyages & Loisirs"],
        "Ressources",
    ),
    **dict.fromkeys(["Achats", "Colis & Livraisons"], "Archive"),
}  # fmt: skip


def category_folder(category: str) -> str:
    """IMAP folder of a category (`Domaines/Santé`); any other name (action folder) is unchanged."""
    return f"{PARA[category]}/{category}" if category in PARA else category


ACTION_TODO = "1-A traiter"
ACTION_PAY = "2-A payer"
ACTION_READ = "3-A lire"
ACTION_INFO = "4-Pour info"
ACTION_PROMO = "Promotions"  # the providers' standard folder
REVIEW = "5-A revoir"
ACTION_FOLDERS = (ACTION_TODO, ACTION_PAY, ACTION_READ, ACTION_INFO, ACTION_PROMO, REVIEW)

# Folders that hold no category (mailbox system folders, action/promo buckets)
_NOT_A_CATEGORY = {
    "INBOX", "Sent", "Sent Messages", "Drafts", "Trash", "Deleted Messages", "Junk", "Spam",
    "Archive", "Archives", "Notes", "Later", "A classer", "À Classer", "Promos", "Promotions",
}  # fmt: skip

# Exact or prefix overrides, checked longest first
_RULES = {
    "Contacts": "Contacts",
    "Famille": "Famille & École",
    "Factures": "Banque & Placements",
    "Factures/Medecins": "Santé",
    "Factures/REME": "Famille & École",
    "Finance": "Banque & Placements",
    "Finance/Local/EDF": "Énergie & Télécom",
    "Finance/Local/Swisscom Bills": "Énergie & Télécom",
    "Finance/Local/eBill": "Énergie & Télécom",
    "Finance/Local/Impots": "Impôts & Administration",
    "Finance/Locale/Impots": "Impôts & Administration",
    "Finance/Local/Insurance": "Assurances & Retraite",
    "Finance/Local/Pensions": "Assurances & Retraite",
    "Finance/Local/Vaudoise": "Assurances & Retraite",
    "Finance/Locale/Vaudoise": "Assurances & Retraite",
    "Finance/Online/Insurance": "Assurances & Retraite",
    "Finance/Online/Comparis": "Assurances & Retraite",
    "Finance/Online/Licences": "Outils & Services en ligne",
    "Informations": "Médias & Divertissement",
    "Informations/Charity": "Associations & Communauté",
    "Informations/Commerces/Interflora": "Achats",
    "Informations/Commerces/Kuoni": "Voyages & Loisirs",
    "Informations/Commerces/Mobility": "Transports & Mobilité",
    "Informations/Newsletters/Business": "Veille & Newsletters pro",
    "Informations/Newsletters/E-commerce": "Veille & Newsletters pro",
    "Informations/Newsletters/Marketing": "Veille & Newsletters pro",
    "Informations/Newsletters/Startups": "Veille & Newsletters pro",
    "Informations/Newsletters/Tech": "Veille & Newsletters pro",
    "Informations/Newsletters/Tech Events": "Veille & Newsletters pro",
    "Informations/Newsletters/Discounts": "Achats",
    "Services": "Outils & Services en ligne",
    "Services/Dev": "Outils & Services en ligne",
    "Services/Development": "Éditeurs IT & Cloud",
    "Services/Development/Electronics": "Achats",
    **{
        f"Services/Development/{name}": "Outils & Services en ligne"
        for name in (
            "Brave",
            "CI/CD",
            "Cloud Tools",
            "Collaboration",
            "DevOps",
            "DevTools",
            "GitHub",
            "OpenAI",
            "Project Management",
            "Supabase",
            "n8n",
        )  # fmt: skip
    },
    "Services/Local": "Logement & Maison",
    **{
        f"Services/Local/{name}": cat
        for name, cat in {
            "Automotive": "Transports & Mobilité",
            "Beauty Services": "Santé",
            "CFF": "Transports & Mobilité",
            "Coiffeur": "Santé",
            "Delivery": "Colis & Livraisons",
            "Food Delivery": "Achats",
            "Food Waste": "Achats",
            "Government": "Impôts & Administration",
            "IT Services": "Outils & Services en ligne",
            "Insurance": "Assurances & Retraite",
            "Legal": "Impôts & Administration",
            "Leisure": "Voyages & Loisirs",
            "Lost & Found": "Outils & Services en ligne",
            "Mairie": "Impôts & Administration",
            "Medecins": "Santé",
            "Mobility": "Transports & Mobilité",
            "Officiel": "Impôts & Administration",
            "Parking": "Transports & Mobilité",
            "Payot": "Achats",
            "Poste": "Colis & Livraisons",
            "PubliBike": "Transports & Mobilité",
            "REME": "Famille & École",
            "Recruitment": "Carrière & Formation",
            "Religion": "Associations & Communauté",
            "Repair Services": "Achats",
            "Sports": "Voyages & Loisirs",
            "Syno": "Sécurité & Comptes",
            "Telecommunications": "Énergie & Télécom",
            "Transport": "Transports & Mobilité",
            "UP-Lausanne": "Carrière & Formation",
            "Vaudoise": "Assurances & Retraite",
            "Wingo": "Énergie & Télécom",
        }.items()
    },
    "Services/Online": "Outils & Services en ligne",
    **{
        f"Services/Online/{name}": cat
        for name, cat in {
            "Appliances": "Achats",
            "AssuranceRetraite": "Assurances & Retraite",
            "BitDefender": "Sécurité & Comptes",
            "BonASavoir": "Médias & Divertissement",
            "Cookomix": "Médias & Divertissement",
            "Crowdfunding": "Banque & Placements",
            "Cumulus": "Achats",
            "Digiposte": "Impôts & Administration",
            "EasyPark": "Transports & Mobilité",
            "FNAC": "Achats",
            "Feedly": "Veille & Newsletters pro",
            "Food Delivery": "Achats",
            "Gaming": "Médias & Divertissement",
            "Genealogy": "Médias & Divertissement",
            "Gites de France": "Voyages & Loisirs",
            "Google": "Sécurité & Comptes",
            "Health": "Santé",
            "Health Tech": "Santé",
            "Herji": "Achats",
            "Home Design": "Logement & Maison",
            "ImmoScout": "Logement & Maison",
            "ImmoScout24": "Logement & Maison",
            "Interflora": "Achats",
            "Job Search": "Carrière & Formation",
            "LaPoste": "Colis & Livraisons",
            "Learning": "Carrière & Formation",
            "Loyalty Programs": "Achats",
            "MaisonsDuMonde": "Achats",
            "Mammut": "Achats",
            "Manor": "Achats",
            "Marketplace": "Achats",
            "Mediamarkt": "Achats",
            "Music": "Médias & Divertissement",
            "MyHeritage": "Médias & Divertissement",
            "Netflix": "Médias & Divertissement",
            "Parental Control": "Famille & École",
            "Payments": "Banque & Placements",
            "Personal Development": "Carrière & Formation",
            "Photo Services": "Achats",
            "Recipes": "Médias & Divertissement",
            "Retail Tech": "Achats",
            "Reviews": "Achats",
            "RoadID": "Achats",
            "Security": "Sécurité & Comptes",
            "Shopping List": "Achats",
            "Strava": "Santé",
            "Streaming": "Médias & Divertissement",
            "SwissID": "Impôts & Administration",
            "Transport": "Transports & Mobilité",
            "UFE": "Associations & Communauté",
            "Usenet": "Médias & Divertissement",
            "VMUG": "Éditeurs IT & Cloud",
            "Vistaprint": "Achats",
            "Wellness": "Santé",
            "Yahoo": "Sécurité & Comptes",
            "decathlon": "Achats",
            "emirates": "Voyages & Loisirs",
            "ifolor": "Achats",
            "ikea": "Achats",
            "ochsnersport": "Achats",
            "restosducoeur": "Associations & Communauté",
        }.items()
    },
    "Services/Professional": "Éditeurs IT & Cloud",
    **{
        f"Services/Professional/{name}": cat
        for name, cat in {
            "Academic Tools": "Outils & Services en ligne",
            "Certifications": "Carrière & Formation",
            "Collaboration": "Outils & Services en ligne",
            "Education": "Carrière & Formation",
            "Events": "Veille & Newsletters pro",
            "IT Consulting": "Carrière & Formation",
            "Job Search": "Carrière & Formation",
            "Jobs": "Carrière & Formation",
            "Learning": "Carrière & Formation",
            "LinkedIn": "Carrière & Formation",
            "Networking": "Carrière & Formation",
            "Photo Editing": "Outils & Services en ligne",
            "Photography": "Outils & Services en ligne",
            "Qoqa": "Achats",
            "Recruitment": "Carrière & Formation",
            "Skylum": "Outils & Services en ligne",
            "Software": "Outils & Services en ligne",
            "Time Tracking": "Outils & Services en ligne",
            "Todoist": "Outils & Services en ligne",
            "UFE": "Associations & Communauté",
            "informit": "Veille & Newsletters pro",
            "mozilla": "Outils & Services en ligne",
        }.items()
    },
    "Shopping": "Achats",
    "Shopping/Smart Home": "Logement & Maison",
    "SocialNetworks": "Associations & Communauté",
    "System Notifications": "Sécurité & Comptes",
    "System Notifications/Dell": "Éditeurs IT & Cloud",
    "System Notifications/Hardware": "Éditeurs IT & Cloud",
    "System Notifications/Oracle Cloud": "Éditeurs IT & Cloud",
    "System Notifications/Poste": "Colis & Livraisons",
    "System Notifications/Shared Mailbox": "Outils & Services en ligne",
    "System Notifications/Smart Home": "Logement & Maison",
    "System Notifications/Software": "Outils & Services en ligne",
    "Voyages": "Voyages & Loisirs",
    "Voyages/Mobility": "Transports & Mobilité",
    "Voyages/Transport": "Transports & Mobilité",
}


def map_folder(folder: str) -> str | None:
    """Return the new category for an existing folder, or None if it holds no category."""
    if folder in _NOT_A_CATEGORY:
        return None
    parts = folder.split("/")
    for depth in range(len(parts), 0, -1):  # longest matching prefix wins
        category = _RULES.get("/".join(parts[:depth]))
        if category:
            return category
    return None


def to_category(value: str | None) -> str | None:
    """Return a taxonomy category for a stored value: a category name or an old folder path."""
    if not value:
        return None
    if value in TAXONOMY:
        return value
    group, _, name = value.partition("/")
    if PARA.get(name) == group:  # a PARA folder, e.g. "Domaines/Santé"
        return name
    return map_folder(value)


def llm_static_prompt() -> str:
    """Instructions and numbered category list; identical for every email so it can be cached."""
    categories = "\n".join(f"{i}. {name} : {desc}" for i, (name, desc) in enumerate(TAXONOMY.items(), 1))
    return (
        "Classe cet email dans UNE des catégories suivantes, selon le métier de l'expéditeur :\n"
        f"{categories}\n\n"
        "Réponds uniquement par le numéro de la catégorie, sans autre texte.\n\n"
    )


def llm_email_part(subject: str, sender: str, body: str) -> str:
    """Per-email part of the prompt, appended after llm_static_prompt()."""
    return f"Sujet: {subject}\nDe: {sender}\nCorps: {body}"


def llm_sender_static_prompt() -> str:
    """Same numbered list as llm_static_prompt(), asking for the sender's category."""
    return llm_static_prompt().replace("Classe cet email", "Classe cet expéditeur", 1)


def llm_sender_part(name: str, address: str, subjects: list[str]) -> str:
    """Per-sender part of the prompt, appended after llm_sender_static_prompt()."""
    sender = f"{name} <{address}>" if name else address
    lines = "\n".join(f"- {s}" for s in subjects) or "- (aucun)"
    return f"Expéditeur: {sender}\nSujets:\n{lines}"


def nomic_text(sender_name: str, sender_address: str, subject: str, body: str) -> str:
    """Text embedded by nomic for one email (the production Signal 5 format)."""
    text = f"Email from {sender_name or sender_address or 'Unknown'}: {subject}"
    body = smart_truncate(body, max_chars=500) if body else ""
    return f"{text}\n{body}" if body else text


def parse_category_number(text: str) -> str | None:
    """Map the LLM answer ('7', ' 7\\n', 'Catégorie 7') to a category name, or None."""
    match = re.search(r"\d+", text or "")
    if not match:
        return None
    number = int(match.group())
    names = list(TAXONOMY)
    return names[number - 1] if 1 <= number <= len(names) else None
