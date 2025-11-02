import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

from sklearn.model_selection import train_test_split

# Add project root to sys.path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))


def prepare_dataset(
    input_dir: Path,
    output_dir: Path,
    sample_fraction: float,
    test_size: float,
    random_seed: int,
):
    """
    Loads all generated pairs, performs stratified sampling to create a smaller subset,
    and then splits that subset into training and testing sets.
    """
    print("[prepare_dataset] Starting dataset preparation...")
    print(f"[prepare_dataset]   Input directory: {input_dir}")
    print(f"[prepare_dataset]   Output directory: {output_dir}")
    print(f"[prepare_dataset]   Sample fraction: {sample_fraction}")
    print(f"[prepare_dataset]   Test set size: {test_size}")
    print(f"[prepare_dataset]   Random seed: {random_seed}")

    random.seed(random_seed)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load all data from generated_pairs.*.jsonl files
    all_records = []
    source_files = sorted(input_dir.glob("generated_pairs.*.jsonl"))
    if not source_files:
        print(f"[prepare_dataset] ERROR: No 'generated_pairs.*.jsonl' files found in {input_dir}")
        raise FileNotFoundError(f"No source files found in {input_dir}")

    print(f"[prepare_dataset] Found {len(source_files)} source files. Loading records...")
    for file_path in source_files:
        with file_path.open("r", encoding="utf-8") as f:
            for line in f:
                all_records.append(json.loads(line))
    print(f"[prepare_dataset] Loaded a total of {len(all_records)} records.")

    # 2. Group records by template_id for stratified sampling
    records_by_template = defaultdict(list)
    for record in all_records:
        records_by_template[record["template_id"]].append(record)

    # 3. Perform stratified sampling to create the subset
    subset_records = []
    print(f"[prepare_dataset] Performing stratified sampling to select {sample_fraction * 100}% of data...")
    for _template_id, records in records_by_template.items():
        num_to_sample = max(1, int(len(records) * sample_fraction))
        sample = random.sample(records, num_to_sample)
        subset_records.extend(sample)

    print(f"[prepare_dataset] Created subset with {len(subset_records)} records.")

    # 4. Perform train-test split on the subset, stratified by template_id
    labels = [record["template_id"] for record in subset_records]

    try:
        train_records, test_records = train_test_split(
            subset_records, test_size=test_size, random_state=random_seed, stratify=labels, shuffle=True
        )
    except ValueError:
        # Fallback for small datasets where stratification is not possible
        print(
            "[prepare_dataset] WARNING: Could not stratify split (likely due to small sample size). Performing a non-stratified split."
        )
        train_records, test_records = train_test_split(
            subset_records, test_size=test_size, random_state=random_seed, shuffle=True
        )

    print("[prepare_dataset] Split complete:")
    print(f"[prepare_dataset]   Training set size: {len(train_records)}")
    print(f"[prepare_dataset]   Test set size: {len(test_records)}")

    # 5. Save the final datasets
    train_path = output_dir / "train_sample.jsonl"
    test_path = output_dir / "test_sample.jsonl"

    with train_path.open("w", encoding="utf-8") as f:
        for record in train_records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[prepare_dataset] Saved training set to {train_path}")

    with test_path.open("w", encoding="utf-8") as f:
        for record in test_records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"[prepare_dataset] Saved test set to {test_path}")
    print("[prepare_dataset] Done.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare a sampled and split dataset for fine-tuning.")
    parser.add_argument(
        "--input_dir",
        type=Path,
        default=ROOT / "finetuning" / "data" / "raw",
        help="Directory containing the full generated_pairs.*.jsonl files.",
    )
    parser.add_argument(
        "--output_dir",
        type=Path,
        default=ROOT / "finetuning" / "data" / "processed" / "splits",
        help="Directory where the train and test splits will be saved.",
    )
    parser.add_argument(
        "--sample_fraction",
        type=float,
        default=0.2,
        help="Fraction of the total dataset to use for the subset (e.g., 0.2 for 20%).",
    )
    parser.add_argument(
        "--test_size",
        type=float,
        default=0.15,
        help="Fraction of the subset to reserve for the test set (e.g., 0.15 for 15%).",
    )
    parser.add_argument(
        "--random_seed",
        type=int,
        default=42,
        help="Random seed for reproducibility.",
    )

    args = parser.parse_args()
    prepare_dataset(**vars(args))
