## Documentation Technique : Développement d'un Projet Python avec une Approche Fonctionnelle

**À l'attention de l'Agent IA de Développement**

Ce document définit les principes, les outils et les standards à appliquer pour le développement de ce projet. L'objectif est d'adopter une approche de **programmation fonctionnelle (PF)** afin de garantir un code plus déclaratif, prédictible, testable et maintenable.

---

### 1\. Principes Fondamentaux de la Programmation Fonctionnelle

Votre logique de développement doit adhérer aux principes suivants :

- **Fonctions Pures** : La majorité des fonctions que vous écrirez doivent être pures.

  - Leur sortie doit dépendre **uniquement** de leurs arguments d'entrée.
  - Elles ne doivent avoir **aucun effet de bord** observable (pas de modification de variables globales, pas d'écriture en base de données, pas de logs, pas d'appels réseau, etc.).
  - Pour une même entrée, elles doivent toujours retourner la même sortie.

- **Immutabilité** : Les structures de données ne doivent pas être modifiées après leur création.

  - Privilégiez les tuples (`tuple`) aux listes (`list`) et les `frozenset` aux `set` pour les collections qui ne doivent pas changer.
  - Pour modifier une structure de données (comme un dictionnaire ou un objet), créez une nouvelle instance avec les valeurs mises à jour au lieu de modifier l'originale sur place.

- **Composition de Fonctions** : L'application doit être construite en combinant des fonctions simples pour en créer de plus complexes. Le flux de données doit être clair et suivre une logique de pipeline : `sortie_fonction_A -> entrée_fonction_B -> sortie_fonction_B`.

- **Fonctions d'Ordre Supérieur (Higher-Order Functions)** : Utilisez abondamment les fonctions qui prennent d'autres fonctions en argument ou qui retournent des fonctions (ex: `map`, `filter`, `functools.reduce`, décorateurs).

- **Séparation Stricte entre le Cœur Logique et les Effets de Bord** : La logique métier principale (le "cœur pur") doit être complètement isolée des parties du code qui interagissent avec le monde extérieur (I/O, bases de données, API, etc.). Ces dernières (les "effets de bord") doivent être confinées à la périphérie de l'application.

---

### 2\. Outillage et Bibliothèques Python Ad Hoc

Pour implémenter ces principes, vous utiliserez les outils suivants :

#### 2.1. Modules Standards

- **`functools`** : À utiliser systématiquement.
  - `functools.partial` : Pour la spécialisation de fonctions (currying partiel).
  - `functools.reduce` : Pour agréger les valeurs d'un itérable.
  - `functools.wraps` : Indispensable pour la création de décorateurs qui préservent les métadonnées de la fonction décorée.
- **`itertools`** : Pour la manipulation efficace d'itérables. Privilégiez ces fonctions aux boucles `for` manuelles lorsque c'est possible pour créer des pipelines de données performants et économes en mémoire.
- **`typing`** : Le typage statique est **obligatoire**. Toutes les signatures de fonction doivent être entièrement typées. Utilisez `Callable` pour typer les fonctions passées en argument et `TypeVar` pour les fonctions génériques.
- **`collections`** : Utilisez `namedtuple` ou `dataclasses` (avec `frozen=True`) pour créer des structures de données simples et immutables.

#### 2.2. Bibliothèques Tierces

- **`returns`** : Cette bibliothèque est **centrale** pour la gestion des effets de bord et des erreurs de manière fonctionnelle.

  - Utilisez le conteneur `Result[SuccessType, FailureType]` pour les fonctions qui peuvent échouer (au lieu de lever des exceptions). `Success` encapsule une valeur de succès, `Failure` une erreur.
  - Utilisez le conteneur `Maybe[ValueType]` (composé de `Some(value)` et `Nothing`) pour les fonctions qui peuvent ne pas retourner de valeur (au lieu de retourner `None`).
  - Explorez ses décorateurs comme `@safe` pour convertir automatiquement des fonctions levant des exceptions en fonctions retournant un `Result`.

- **`fn.py`** ou **`toolz`** : Pour des outils de composition plus avancés.

  - Utilisez `fn.underscore._` ou `toolz.pipe` pour créer des pipelines de transformation de données lisibles et déclaratives.

---

### 3\. Structure du Projet et Standards de Code

#### 3.1. Organisation

```
project_name/
│
├── core/               # Cœur fonctionnel pur de l'application
│   ├── logic.py        # Fonctions pures, logique métier
│   └── types.py        # Types de données, dataclasses (frozen=True)
│
├── infrastructure/     # Couche impure, gestion des effets de bord
│   ├── database.py     # Interactions avec la base de données
│   ├── api_clients.py  # Clients pour les API externes
│   └── file_io.py      # Lecture/écriture de fichiers
│
├── main.py             # Point d'entrée : orchestre l'appel du cœur pur et gère les effets
│
└── tests/
    ├── property/       # Tests basés sur les propriétés
    └── unit/           # Tests unitaires classiques
```

#### 3.2. Exemples de Code

**À FAIRE : Utilisation de `returns` et de la composition**

```python
# core/logic.py
from returns.result import Result, Success, Failure
from typing import Dict

def validate_user_data(data: Dict[str, str]) -> Result[Dict[str, str], str]:
    if "email" not in data:
        return Failure("Email is missing.")
    # ... autres validations ...
    return Success(data)

def create_greeting(user_data: Dict[str, str]) -> str:
    # Fonction pure
    return f"Hello, {user_data.get('name', 'user')}!"

# main.py
from core.logic import validate_user_data, create_greeting
from returns.pipeline import flow

def process_request(request: Dict) -> None:
    # Pipeline fonctionnel
    result: Result[str, str] = flow(
        request,
        validate_user_data,
        lambda result: result.map(create_greeting) # .map applique la fonction si le conteneur est un Success
    )

    # Gestion des effets de bord à la toute fin
    match result:
        case Success(message):
            print(message) # Effet de bord (I/O)
        case Failure(error_message):
            print(f"Error: {error_message}") # Effet de bord (I/O)
```

**À NE PAS FAIRE : Fonctions impures et exceptions**

```python
# Mauvais exemple
def process_user(data: Dict[str, str]) -> None:
    # Mélange de logique, I/O et gestion d'erreurs
    if "email" not in data:
        raise ValueError("Email is missing.")

    greeting = f"Hello, {data.get('name', 'user')}!"
    print(greeting) # Effet de bord
```

---

### 4\. Tests

- **Tests Unitaires** : Pour les fonctions pures, les tests sont simples. Fournissez une entrée et affirmez que la sortie est correcte.
- **Tests Basés sur les Propriétés (Property-Based Testing)** : Utilisez la bibliothèque **`hypothesis`**. C'est une approche privilégiée pour tester le code fonctionnel. Au lieu de tester des exemples spécifiques, vous définissez les propriétés que vos fonctions doivent respecter pour toute une gamme d'entrées générées automatiquement.

**Exemple avec `hypothesis`**

```python
# tests/property/test_logic.py
from hypothesis import given, strategies as st
from core.logic import create_greeting

@given(st.dictionaries(st.text(), st.text()))
def test_create_greeting_always_returns_string(user_data):
    # Propriété : la fonction doit toujours retourner une chaîne de caractères
    assert isinstance(create_greeting(user_data), str)
```

En respectant scrupuleusement ces directives, vous produirez un code robuste, facile à raisonner et aligné sur les meilleures pratiques de la programmation fonctionnelle en Python.
