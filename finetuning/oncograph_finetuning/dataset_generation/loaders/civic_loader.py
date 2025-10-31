import csv
from pathlib import Path

DEFAULT_CIVIC_DIR = Path("data/civic/latest")
GENES_CSV = DEFAULT_CIVIC_DIR / "nodes" / "genes.csv"
THERAPIES_CSV = DEFAULT_CIVIC_DIR / "nodes" / "therapies.csv"
VARIANTS_CSV = DEFAULT_CIVIC_DIR / "nodes" / "variants.csv"
DISEASES_CSV = DEFAULT_CIVIC_DIR / "nodes" / "diseases.csv"
TARGETS_CSV = DEFAULT_CIVIC_DIR / "relationships" / "targets.csv"
AFFECTS_CSV = DEFAULT_CIVIC_DIR / "relationships" / "affects_response.csv"
VARIANT_OF_CSV = DEFAULT_CIVIC_DIR / "relationships" / "variant_of.csv"


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


def load_therapy_names(therapies_csv_path: Path | None = None, require_chembl_id: bool = False) -> list[str]:
    """Load therapy names from CIViC nodes CSV.

    Expects a CSV with columns 'name' and optionally 'chembl_id'.
    When require_chembl_id is True, only returns rows with non-empty chembl_id.
    Returns a sorted, de-duplicated list.
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
            if not name:
                continue
            if require_chembl_id:
                chembl_id = (row.get("chembl_id") or "").strip()
                if not chembl_id:
                    continue
            names.add(name)
    print(
        f"[civic_loader] Parsed {row_count} rows; collected {len(names)} unique therapy names (require_chembl_id={require_chembl_id})"
    )
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


def load_disease_names(diseases_csv_path: Path | None = None, require_doid: bool = True) -> list[str]:
    """Load disease names from CIViC nodes CSV.

    Expects a CSV with columns 'name' and 'doid'.
    When require_doid is True, only returns rows with non-empty DOID.
    Returns a sorted, de-duplicated list.
    """
    path = Path(diseases_csv_path) if diseases_csv_path else DISEASES_CSV
    print(f"[civic_loader] Reading diseases from: {path}")
    names: set[str] = set()
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        row_count = 0
        for row in reader:
            row_count += 1
            name = (row.get("name") or "").strip()
            if not name:
                continue
            if require_doid:
                doid = (row.get("doid") or "").strip()
                if not doid:
                    continue
            names.add(name)
    print(
        f"[civic_loader] Parsed {row_count} rows; collected {len(names)} unique disease names (require_doid={require_doid})"
    )
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
        self.diseases: list[str] = []
        # Relationships
        self.targets: list[dict[str, str]] = []
        self.affects: list[dict[str, str]] = []
        self.variant_of: dict[str, str] = {}

    def build(self, require_chembl_id: bool = True, require_doid: bool = True) -> None:
        print(f"[civic_loader] Building index from base_dir: {self.base_dir}")
        self.genes = load_canonical_gene_symbols(self.base_dir / "nodes" / "genes.csv")
        self.therapies = load_therapy_names(
            self.base_dir / "nodes" / "therapies.csv", require_chembl_id=require_chembl_id
        )
        self.variants = load_variant_names(self.base_dir / "nodes" / "variants.csv")
        self.diseases = load_disease_names(self.base_dir / "nodes" / "diseases.csv", require_doid=require_doid)
        # Load relationships
        self.targets = self._load_targets(TARGETS_CSV)
        self.affects = self._load_affects(AFFECTS_CSV)
        self.variant_of = self._load_variant_of(VARIANT_OF_CSV)
        print(
            f"[civic_loader] Index build complete: genes={len(self.genes)} therapies={len(self.therapies)} variants={len(self.variants)} diseases={len(self.diseases)} targets={len(self.targets)} affects={len(self.affects)}"
        )

    def get_gene_symbols(self) -> list[str]:
        return self.genes

    def get_therapy_names(self) -> list[str]:
        return self.therapies

    def get_variant_names(self) -> list[str]:
        return self.variants

    def get_disease_names(self) -> list[str]:
        return self.diseases

    # Relationship helpers
    def _load_targets(self, path: Path) -> list[dict[str, str]]:
        print(f"[civic_loader] Reading targets from: {path}")
        items: list[dict[str, str]] = []
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                items.append(
                    {
                        "therapy_name": (row.get("therapy_name") or "").strip(),
                        "gene_symbol": (row.get("gene_symbol") or "").strip(),
                        "moa": (row.get("moa") or "").strip(),
                    }
                )
        return [r for r in items if r["therapy_name"] and r["gene_symbol"]]

    def _load_affects(self, path: Path) -> list[dict[str, str]]:
        print(f"[civic_loader] Reading affects from: {path}")
        items: list[dict[str, str]] = []
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                items.append(
                    {
                        "biomarker_type": (row.get("biomarker_type") or "").strip(),
                        "biomarker_name": (row.get("biomarker_name") or "").strip(),
                        "therapy_name": (row.get("therapy_name") or "").strip(),
                        "effect": (row.get("effect") or "").strip(),
                        "disease_name": (row.get("disease_name") or "").strip(),
                    }
                )
        return [r for r in items if r["therapy_name"] and r["disease_name"]]

    def _load_variant_of(self, path: Path) -> dict[str, str]:
        print(f"[civic_loader] Reading variant_of from: {path}")
        mapping: dict[str, str] = {}
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                v = (row.get("variant_name") or "").strip()
                g = (row.get("gene_symbol") or "").strip()
                if v and g:
                    mapping[v] = g
        return mapping

    def get_targets_pairs(self) -> list[tuple[str, str]]:
        return [(r["therapy_name"], r["gene_symbol"]) for r in self.targets]

    def get_targets_genes(self) -> list[str]:
        return sorted({r["gene_symbol"] for r in self.targets})

    def get_targets_therapies(self) -> list[str]:
        return sorted({r["therapy_name"] for r in self.targets})

    def get_affects_pairs(self, effect: str | None = None, require_variant: bool | None = None) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for r in self.affects:
            if effect and r["effect"].lower() != effect.lower():
                continue
            if require_variant is True and r["biomarker_type"].lower() != "variant":
                continue
            if require_variant is False and r["biomarker_type"].lower() != "gene":
                continue
            pairs.append((r["therapy_name"], r["disease_name"]))
        seen: set[tuple[str, str]] = set()
        uniq: list[tuple[str, str]] = []
        for p in pairs:
            if p not in seen:
                seen.add(p)
                uniq.append(p)
        return uniq

    def get_affects_variant_triples(self, effect: str | None = None) -> list[tuple[str, str, str]]:
        triples: list[tuple[str, str, str]] = []
        for r in self.affects:
            if r["biomarker_type"].lower() != "variant":
                continue
            if effect and r["effect"].lower() != effect.lower():
                continue
            triples.append((r["biomarker_name"], r["therapy_name"], r["disease_name"]))
        seen: set[tuple[str, str, str]] = set()
        uniq: list[tuple[str, str, str]] = []
        for t in triples:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        return uniq

    def map_variant_to_gene(self, variant_name: str) -> str | None:
        return self.variant_of.get(variant_name)
