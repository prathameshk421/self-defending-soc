"""Layer boundary: estate must never import ingest (imports go one way)."""

from pathlib import Path

ESTATE_DIR = Path(__file__).resolve().parents[2] / "src" / "estate"


def test_estate_never_imports_ingest():
    for path in ESTATE_DIR.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "import ingest" not in source and "from ingest" not in source, (
            f"{path} imports ingest — Layer 1 must not depend on Layer 2"
        )
