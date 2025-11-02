"""Evaluation harness for model-agnostic Cypher generation evaluation."""

import json
import time
from pathlib import Path
from typing import Any

from tqdm import tqdm

from finetuning.evaluation.model_adapters import ModelAdapter
from src.pipeline.executor import Neo4jExecutor
from src.pipeline.types import PipelineError
from src.pipeline.validator import RuleBasedValidator


def evaluate_cypher_syntax(cypher: str, validator: RuleBasedValidator) -> tuple[bool, str | None]:
    """Check if Cypher passes syntactic validation.

    Args:
        cypher: The Cypher query to validate.
        validator: The RuleBasedValidator instance.

    Returns:
        Tuple of (is_valid, error_message_or_none).
    """
    try:
        validator.validate_cypher(cypher)
        return True, None
    except PipelineError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Unexpected error: {type(e).__name__}: {e}"


def evaluate_cypher_execution(cypher: str, executor: Neo4jExecutor) -> tuple[bool, list[dict[str, Any]], str | None]:
    """Execute Cypher and return results.

    Args:
        cypher: The Cypher query to execute.
        executor: The Neo4jExecutor instance.

    Returns:
        Tuple of (success, rows, error_message_or_none).
    """
    try:
        rows = executor.execute_read(cypher)
        return True, rows, None
    except Exception as e:
        return False, [], f"{type(e).__name__}: {e}"


def normalize_result_row(row: dict[str, Any]) -> dict[str, Any]:
    """Normalize arrays and None values for comparison.

    Args:
        row: A result row dictionary.

    Returns:
        Normalized row dictionary.
    """
    normalized = {}
    for key, value in row.items():
        if isinstance(value, list):
            normalized[key] = sorted(value) if value else []
        elif value is None:
            normalized[key] = None
        else:
            normalized[key] = value
    return normalized


def compare_results(gold_rows: list[dict], generated_rows: list[dict]) -> bool:
    """Compare result sets for exact match (order-independent), ignoring extra NULL columns in generated results.

    Args:
        gold_rows: The expected results.
        generated_rows: The actual results.

    Returns:
        True if results match exactly, False otherwise.
    """
    if len(gold_rows) != len(generated_rows):
        return False

    if not gold_rows:  # Both empty
        return len(generated_rows) == 0

    # Get the schema from gold rows (union of all keys)
    gold_schema = set()
    for row in gold_rows:
        gold_schema.update(row.keys())

    # Filter generated rows to only include gold schema keys (removes extra NULL columns)
    filtered_gen_rows = []
    for row in generated_rows:
        filtered_row = {k: v for k, v in row.items() if k in gold_schema}
        filtered_gen_rows.append(filtered_row)

    # Normalize and sort rows for comparison
    gold_normalized = sorted([tuple(sorted(normalize_result_row(row).items())) for row in gold_rows])
    gen_normalized = sorted([tuple(sorted(normalize_result_row(row).items())) for row in filtered_gen_rows])

    return gold_normalized == gen_normalized


class Evaluator:
    """Evaluation harness for comparing generated Cypher against gold standard."""

    def __init__(
        self,
        validator: RuleBasedValidator,
        executor: Neo4jExecutor,
        model_adapter: ModelAdapter,
    ):
        """Initialize the evaluator.

        Args:
            validator: The RuleBasedValidator instance.
            executor: The Neo4jExecutor instance.
            model_adapter: The ModelAdapter instance for token counting.
        """
        self.validator = validator
        self.executor = executor
        self.model_adapter = model_adapter

    def evaluate_single(
        self,
        question: str,
        gold_cypher: str,
        generated_cypher: str,
        prompt_text: str | None = None,
    ) -> dict[str, Any]:
        """Evaluate a single generated Cypher query.

        Args:
            question: The original question.
            gold_cypher: The reference Cypher query.
            generated_cypher: The generated Cypher query.
            prompt_text: Optional prompt text for token counting. If None, uses model_adapter.get_full_prompt().

        Returns:
            Dictionary with evaluation results.
        """
        start_time = time.perf_counter()

        # Count tokens
        if prompt_text is None:
            prompt_text = self.model_adapter.get_full_prompt(question)
        input_tokens = self.model_adapter.count_tokens(prompt_text)
        output_tokens = self.model_adapter.count_tokens(generated_cypher)

        # Syntactic validation
        syntactic_valid, syntax_error = evaluate_cypher_syntax(generated_cypher, self.validator)

        # Execution (only if syntactically valid)
        execution_success = False
        execution_error = None
        generated_rows = []
        if syntactic_valid:
            execution_success, generated_rows, execution_error = evaluate_cypher_execution(
                generated_cypher, self.executor
            )

        # Get gold results (execute once and cache)
        _, gold_rows, _ = evaluate_cypher_execution(gold_cypher, self.executor)

        # Result comparison (only if both executed successfully)
        result_match = False
        if syntactic_valid and execution_success:
            result_match = compare_results(gold_rows, generated_rows)

        latency_ms = (time.perf_counter() - start_time) * 1000

        return {
            "syntactic_valid": syntactic_valid,
            "execution_success": execution_success,
            "result_match": result_match,
            "generated_cypher": generated_cypher,
            "error": syntax_error or execution_error,
            "latency_ms": latency_ms,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "gold_rows": gold_rows,
            "generated_rows": generated_rows,
        }

    def aggregate_metrics(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Aggregate metrics from evaluation results.

        Args:
            results: List of evaluation result dictionaries.

        Returns:
            Dictionary with aggregated metrics.
        """
        total = len(results)
        if total == 0:
            return {}

        syntactic_valid_count = sum(1 for r in results if r["syntactic_valid"])
        execution_success_count = sum(1 for r in results if r["execution_success"])
        result_match_count = sum(1 for r in results if r["result_match"])

        total_input_tokens = sum(r["input_tokens"] for r in results)
        total_output_tokens = sum(r["output_tokens"] for r in results)
        total_latency_ms = sum(r["latency_ms"] for r in results)

        return {
            "total": total,
            "syntactic_validity_pct": (syntactic_valid_count / total) * 100,
            "execution_success_pct": (
                (execution_success_count / syntactic_valid_count) * 100 if syntactic_valid_count > 0 else 0.0
            ),
            "semantic_accuracy_pct": (
                (result_match_count / execution_success_count) * 100 if execution_success_count > 0 else 0.0
            ),
            "avg_latency_ms": total_latency_ms / total,
            "avg_input_tokens": total_input_tokens / total,
            "avg_output_tokens": total_output_tokens / total,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
        }


def run_evaluation(
    model_adapter: ModelAdapter,
    test_records: list[dict[str, Any]],
    checkpoint_file: Path,
    evaluator: Evaluator,
    checkpoint_interval: int = 50,
) -> list[dict[str, Any]]:
    """Run evaluation for a model adapter over test records with checkpointing.

    Args:
        model_adapter: The model adapter to evaluate.
        test_records: List of test records, each with "id", "question", and "cypher" keys.
        checkpoint_file: Path to checkpoint file (JSONL format).
        evaluator: The Evaluator instance.
        checkpoint_interval: Save checkpoint every N records.

    Returns:
        List of evaluation result dictionaries.
    """
    results = []

    # Load checkpoint if exists
    if checkpoint_file.exists():
        print(f"Loading checkpoint from {checkpoint_file}")
        with checkpoint_file.open("r", encoding="utf-8") as f:
            checkpoint_records = [json.loads(line) for line in f]
            results = checkpoint_records
            # Extract processed record IDs
            processed_ids = {r["id"] for r in checkpoint_records}
            # Filter out already processed records
            remaining_records = [r for r in test_records if r["id"] not in processed_ids]
            print(
                f"Resuming from checkpoint: {len(checkpoint_records)} already processed, "
                f"{len(remaining_records)} remaining"
            )
            test_records = remaining_records

    if not test_records:
        print("No records to evaluate (all already processed)")
        return results

    model_id = model_adapter.get_model_id()
    desc = f"Evaluating {model_id}"

    for i, record in enumerate(tqdm(test_records, desc=desc)):
        question = record["question"]
        gold_cypher = record["cypher"]
        record_id = record["id"]

        try:
            # Generate Cypher
            generated_cypher = model_adapter.generate_cypher(question)

            # Evaluate
            eval_result = evaluator.evaluate_single(
                question=question,
                gold_cypher=gold_cypher,
                generated_cypher=generated_cypher,
            )

            # Add metadata
            eval_result["id"] = record_id
            eval_result["question"] = question
            eval_result["gold_cypher"] = gold_cypher
            results.append(eval_result)

            # Checkpoint periodically
            if (i + 1) % checkpoint_interval == 0:
                with checkpoint_file.open("w", encoding="utf-8") as f:
                    for res in results:
                        f.write(json.dumps(res, ensure_ascii=False) + "\n")
                print(f"\nCheckpoint saved: {len(results)} records processed")

        except Exception as e:
            print(f"\nError processing record {record_id}: {e}")
            results.append(
                {
                    "id": record_id,
                    "question": question,
                    "gold_cypher": gold_cypher,
                    "syntactic_valid": False,
                    "execution_success": False,
                    "result_match": False,
                    "generated_cypher": "",
                    "error": f"Evaluation error: {type(e).__name__}: {e}",
                    "latency_ms": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "gold_rows": [],
                    "generated_rows": [],
                }
            )

    # Final checkpoint
    with checkpoint_file.open("w", encoding="utf-8") as f:
        for res in results:
            f.write(json.dumps(res, ensure_ascii=False) + "\n")

    print(f"\n{model_id} evaluation complete: {len(results)} records")
    return results
