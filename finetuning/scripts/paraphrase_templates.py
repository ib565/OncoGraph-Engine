"""LLM-driven template paraphrasing with structured JSON output.

Usage:
  python finetuning/scripts/paraphrase_templates_llm.py f1_1_targets_gene.yaml [more.yaml ...]

Behavior:
  - Processes input template files in batches of 3 base questions.
  - Requests 2–5 natural paraphrases per base question (placeholders preserved).
  - Writes sibling .paraphrases.yaml next to each input template.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

# Reuse Gemini client as in src/pipeline/gemini.py style
try:  # optional at dev time
    from google import genai  # type: ignore
    from google.genai import types as genai_types  # type: ignore
except Exception:  # pragma: no cover
    genai = None  # type: ignore
    genai_types = None  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = ROOT / "src" / "dataset_generation" / "templates"


class ParaphraseItem(BaseModel):
    template_id: str
    paraphrases: list[str]


class ParaphraseBatchResponse(BaseModel):
    items: list[ParaphraseItem]


def _get_client() -> Any:
    if genai is None:
        raise RuntimeError("google-genai package not available; please install and set API key")
    return genai.Client(api_key=os.getenv("GEMINI_API_KEY"))  # type: ignore[call-arg]


def _content_config() -> Any | None:
    if genai_types is None:
        return None
    # Structured JSON output
    return genai_types.GenerateContentConfig(  # type: ignore[attr-defined]
        response_mime_type="application/json",
        response_schema=ParaphraseBatchResponse,
    )


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def _build_prompt(batch: list[tuple[str, str]]) -> str:
    """Create an instruction that asks for 2–5 paraphrases per question.

    batch: list of (template_id, question_template)
    """
    lines: list[str] = []
    lines.append(
        "Paraphrase question templates for a cancer knowledge graph. Preserve placeholders like {{ gene_symbol }} exactly."
    )
    lines.append("")
    lines.append(
        "Context: In oncology, 'drugs', 'therapies', 'treatments', and 'medications' are interchangeable terms."
    )
    lines.append("")
    lines.append("Rules:")
    lines.append("- Preserve placeholders verbatim (do not alter or remove {{ ... }} blocks).")
    lines.append("- Return 2 to 5 natural, realistic paraphrases per question.")
    lines.append("- Use synonyms and varied phrasing (e.g., 'drugs' ↔ 'therapies' ↔ 'treatments').")
    lines.append("- Keep biomedical context consistent; do not invent entities.")
    lines.append("")
    lines.append("Example:")
    lines.append('Base: "What drugs target {{ gene_symbol }}?"')
    lines.append(
        'Paraphrases: ["Which therapies target {{ gene_symbol }}?", "List treatments that target {{ gene_symbol }}.", "What medications are known to target {{ gene_symbol }}?"]'
    )
    lines.append("")
    lines.append('Respond with JSON: {"items":[{"template_id":str,"paraphrases":[str,...]},...]}')
    lines.append("")
    for template_id, question in batch:
        lines.append(f"TEMPLATE_ID: {template_id}")
        lines.append(f"QUESTION: {question}")
        lines.append("")
    return "\n".join(lines)


def paraphrase_batch(client: Any, batch: list[tuple[str, str]]) -> dict[str, list[str]]:
    prompt = _build_prompt(batch)
    cfg = _content_config()
    kwargs: dict[str, Any] = {
        "model": "gemini-2.5-flash",
        "contents": [prompt],
    }
    if cfg is not None:
        kwargs["config"] = cfg
    response = client.models.generate_content(**kwargs)
    text = getattr(response, "text", None)
    if not text:
        raise RuntimeError("LLM returned no text")
    # Expect structured JSON
    import json

    data = json.loads(text)
    parsed = ParaphraseBatchResponse(**data)
    result: dict[str, list[str]] = {}
    for item in parsed.items:
        paras = item.paraphrases
        if len(paras) > 5:
            paras = paras[:5]
        result[item.template_id] = paras
    return result


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        print("Usage: python paraphrase_templates_llm.py <template1.yaml> [template2.yaml ...]", file=sys.stderr)
        raise SystemExit(1)

    client = _get_client()

    # Load templates, then process in batches of 3
    template_paths: list[Path] = []
    for name in argv[1:]:
        p = (TEMPLATES_DIR / name).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Template not found: {p}")
        template_paths.append(p)

    # Collect (template_id, question, path)
    items: list[tuple[str, str, Path]] = []
    for path in template_paths:
        tpl = load_yaml(path)
        items.append((tpl["template_id"], tpl["question"], path))

    # Process in batches of 3
    for i in range(0, len(items), 3):
        batch_items = items[i : i + 3]
        print(f"[paraphrase-llm] Processing batch {i//3 + 1}: {len(batch_items)} templates")
        batch_pairs = [(tid, q) for (tid, q, _p) in batch_items]
        tid_to_paras = paraphrase_batch(client, batch_pairs)

        # Write each sibling .paraphrases.yaml
        for tid, q, path in batch_items:
            paras = tid_to_paras.get(tid, [])
            out_path = path.with_suffix("")
            out_path = out_path.with_name(out_path.name + ".paraphrases.yaml")
            payload = {
                "template_id": tid,
                "family_id": load_yaml(path).get("family_id"),
                "base_question": q,
                "paraphrases": paras,
            }
            print(f"[paraphrase-llm] Writing {len(paras)} paraphrases → {out_path}")
            save_yaml(out_path, payload)


if __name__ == "__main__":
    main(sys.argv)
