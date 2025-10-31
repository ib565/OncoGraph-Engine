import csv
from pathlib import Path

DEFAULT_CIVIC_DIR = Path("data/civic/latest")
GENES_CSV = DEFAULT_CIVIC_DIR / "nodes" / "genes.csv"
THERAPIES_CSV = DEFAULT_CIVIC_DIR / "nodes" / "therapies.csv"
VARIANTS_CSV = DEFAULT_CIVIC_DIR / "nodes" / "variants.csv"


def load_canonical_gene_symbols(genes_csv_path: Path | None = None) -> list[str]:
    """Load canonical gene symbols from CIViC nodes CSV.

    Expects a CSV with a column named 'symbol'. Returns a sorted, de-duplicated list.
    """
    path = Path(genes_csv_path) if genes_csv_path else GENES_CSV
    print(f"[civic_loader] Reading genes from: {path}")
    symbols: set[str] = set()
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row_count = 0
        for row in reader:
            row_count += 1
            symbol = (row.get("symbol") or "").strip()
            if symbol:
                symbols.add(symbol)
    print(f"[civic_loader] Parsed {row_count} rows; collected {len(symbols)} unique symbols")
    return sorted(symbols)


def load_therapy_names(therapies_csv_path: Path | None = None) -> list[str]:
    """Load therapy names from CIViC nodes CSV.

    Expects a CSV with a column named 'name'. Returns a sorted, de-duplicated list.
    """
    path = Path(therapies_csv_path) if therapies_csv_path else THERAPIES_CSV
    print(f"[civic_loader] Reading therapies from: {path}")
    names: set[str] = set()
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row_count = 0
        for row in reader:
            row_count += 1
            name = (row.get("name") or "").strip()
            if name:
                names.add(name)
    print(f"[civic_loader] Parsed {row_count} rows; collected {len(names)} unique therapy names")
    return sorted(names)


def load_variant_names(variants_csv_path: Path | None = None) -> list[str]:
    """Load variant names from CIViC nodes CSV.

    Expects a CSV with a column named 'name'. Returns a sorted, de-duplicated list.
    """
    path = Path(variants_csv_path) if variants_csv_path else VARIANTS_CSV
    print(f"[civic_loader] Reading variants from: {path}")
    names: set[str] = set()
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row_count = 0
        for row in reader:
            row_count += 1
            name = (row.get("name") or "").strip()
            if name:
                names.add(name)
    print(f"[civic_loader] Parsed {row_count} rows; collected {len(names)} unique variant names")
    return sorted(names)


class CivicIndex:
    """Minimal CIViC entity index used by dataset generation.

    Indexes genes, therapies, and variants from CIViC data.
    """

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = Path(base_dir) if base_dir else DEFAULT_CIVIC_DIR
        self.genes: list[str] = []
        self.therapies: list[str] = []
        self.variants: list[str] = []

    def build(self) -> None:
        print(f"[civic_loader] Building index from base_dir: {self.base_dir}")
        self.genes = load_canonical_gene_symbols(self.base_dir / "nodes" / "genes.csv")
        self.therapies = load_therapy_names(self.base_dir / "nodes" / "therapies.csv")
        self.variants = load_variant_names(self.base_dir / "nodes" / "variants.csv")
        print(
            f"[civic_loader] Index build complete: genes={len(self.genes)} therapies={len(self.therapies)} variants={len(self.variants)}"
        )

    def get_gene_symbols(self) -> list[str]:
        return self.genes

    def get_therapy_names(self) -> list[str]:
        return self.therapies

    def get_variant_names(self) -> list[str]:
        return self.variants


