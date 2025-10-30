import csv
from pathlib import Path

DEFAULT_CIVIC_DIR = Path("data/civic/latest")
GENES_CSV = DEFAULT_CIVIC_DIR / "nodes" / "genes.csv"


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


class CivicIndex:
    """Minimal CIViC entity index used by dataset generation.

    Currently indexes canonical gene symbols only (sufficient for F1.1 MVP).
    """

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = Path(base_dir) if base_dir else DEFAULT_CIVIC_DIR
        self.genes: list[str] = []

    def build(self) -> None:
        print(f"[civic_loader] Building index from base_dir: {self.base_dir}")
        self.genes = load_canonical_gene_symbols(self.base_dir / "nodes" / "genes.csv")
        print(f"[civic_loader] Index build complete: genes={len(self.genes)}")

    def get_gene_symbols(self) -> list[str]:
        return self.genes
