"""Create empty personal files without overwriting existing user records."""
from pathlib import Path

DEFAULTS = {
    "cooking-history.yaml": "schema_version: 1\nevents: []\n",
    "preferences.yaml": "schema_version: 1\nfavorites: []\n",
    "pantry.yaml": "schema_version: 1\nitems: []\n",
    "meal-plan.yaml": "schema_version: 1\nmeals: []\n",
}


def initialize_personal(directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "shopping-lists").mkdir(exist_ok=True)
    created = []
    for name, content in DEFAULTS.items():
        path = directory / name
        try:
            with path.open("x", encoding="utf-8") as stream:
                stream.write(content)
        except FileExistsError:
            continue
        created.append(path)
    return created
