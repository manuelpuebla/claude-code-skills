#!/usr/bin/env python3
"""
Setup script for LeanDojo search skill.
Downloads dataset and model.
"""

import os
import sys
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

def download_dataset():
    """Download LeanDojo dataset from HuggingFace."""
    print("=" * 60)
    print("Downloading LeanDojo dataset...")
    print("=" * 60)

    from datasets import load_dataset

    # Load the dataset (will be cached by HuggingFace)
    dataset = load_dataset("tasksource/leandojo", split="train")

    # Save locally for faster access
    dataset_path = DATA_DIR / "leandojo_dataset"
    dataset.save_to_disk(str(dataset_path))

    print(f"Dataset saved to: {dataset_path}")
    print(f"Number of entries: {len(dataset)}")
    return dataset

def download_model():
    """Download the small tactic generation model."""
    print("=" * 60)
    print("Downloading tacgen-byt5-small model...")
    print("=" * 60)

    from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

    model_name = "kaiyuy/leandojo-lean4-tacgen-byt5-small"

    # Download and cache
    print("Downloading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(model_name)

    print("Downloading model weights...")
    model = AutoModelForSeq2SeqLM.from_pretrained(model_name)

    # Save locally
    model_path = DATA_DIR / "tacgen-model"
    tokenizer.save_pretrained(str(model_path))
    model.save_pretrained(str(model_path))

    print(f"Model saved to: {model_path}")
    return tokenizer, model

def main():
    print("LeanDojo Setup for /lean-search skill")
    print("=" * 60)
    print(f"Data directory: {DATA_DIR}")
    print()

    # Download dataset
    try:
        download_dataset()
        print("\n[OK] Dataset downloaded successfully\n")
    except Exception as e:
        print(f"\n[ERROR] Dataset download failed: {e}\n")
        sys.exit(1)

    # Download model
    try:
        download_model()
        print("\n[OK] Model downloaded successfully\n")
    except Exception as e:
        print(f"\n[ERROR] Model download failed: {e}\n")
        sys.exit(1)

    print("=" * 60)
    print("Setup complete! /lean-search skill is ready.")
    print("=" * 60)

if __name__ == "__main__":
    main()
