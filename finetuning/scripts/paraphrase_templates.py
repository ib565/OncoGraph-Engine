import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "src" / "dataset_generation" / "templates"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def generate_paraphrases_for_template(question_template: str) -> list[str]:
    """Return exactly 3 paraphrases while preserving placeholders like {{ gene_symbol }}.

    Deterministic for MVP; swap synonyms and surface forms around the placeholder.
    """
    # We assume a single placeholder token exists and we keep it verbatim.
    # Example base: "What drugs target {{ gene_symbol }}?"
    return [
        question_template.replace("What drugs", "Which drugs"),
        question_template.replace("What drugs", "List therapies that"),
        question_template.replace("What drugs", "What therapies are known to"),
    ]


def main(template_filename: str) -> None:
    template_path = (TEMPLATES_DIR / template_filename).resolve()
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    print(f"[paraphrase-templates] Loading template: {template_path}")
    tpl = load_yaml(template_path)

    base_q: str = tpl["question"]
    paraphrases = generate_paraphrases_for_template(base_q)

    out_path = template_path.with_suffix("")
    out_path = out_path.with_name(out_path.name + ".paraphrases.yaml")

    payload = {
        "template_id": tpl["template_id"],
        "family_id": tpl["family_id"],
        "base_question": base_q,
        "paraphrases": paraphrases,
    }

    print(f"[paraphrase-templates] Writing paraphrases: {out_path}")
    save_yaml(out_path, payload)
    print(f"[paraphrase-templates] Done. Generated {len(paraphrases)} paraphrases for {tpl['template_id']}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: python paraphrase_templates.py <template_filename.yaml>",
            file=sys.stderr,
        )
        sys.exit(1)
    main(sys.argv[1])
