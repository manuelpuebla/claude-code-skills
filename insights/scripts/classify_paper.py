#!/usr/bin/env python3
"""
classify_paper.py - Classify a paper into the correct biblioteca/ subfolder.

Uses keyword matching on title and abstract to determine the best folder.

Usage:
    python3 classify_paper.py --title "Fast NTT for lattice crypto" --abstract "We present..."
    → {"folder": "ntt", "confidence": "high"}
"""

import argparse
import json
import sys

# Keyword → folder mapping (ordered by specificity)
FOLDER_RULES = [
    {
        "folder": "ntt",
        "keywords": ["ntt", "number-theoretic transform", "number theoretic transform",
                      "cooley-tukey", "gentleman-sande", "butterfly"],
        "weight": 1.0,
    },
    {
        "folder": "criptografia/zk-circuitos",
        "keywords": ["r1cs", "plonk", "groth16", "zk-snark", "zk-stark", "circom",
                      "arithmetic circuit", "constraint system", "zero-knowledge proof",
                      "zkp circuit", "plonkish"],
        "weight": 1.0,
    },
    {
        "folder": "criptografia",
        "keywords": ["cryptography", "lattice", "post-quantum", "hash function",
                      "poseidon", "fiat-shamir", "commitment scheme", "encryption",
                      "signature", "kem", "kyber", "dilithium", "falcon", "sphincs",
                      "mpc", "secure computation", "zero-knowledge", "zkp", "zk-snark",
                      "zk-stark", "bulletproof"],
        "weight": 0.9,
    },
    {
        "folder": "tensor-optimization",
        "keywords": ["equality saturation", "e-graph", "egraph", "tensor",
                      "term rewriting", "eqsat", "tensat", "taso",
                      "computation graph", "graph substitution"],
        "weight": 1.0,
    },
    {
        "folder": "cuda-gpu",
        "keywords": ["gpu", "cuda", "simd", "avx", "neon", "vectorization",
                      "parallel computing", "warp", "thread block", "opencl"],
        "weight": 0.9,
    },
    {
        "folder": "verificacion",
        "keywords": ["lean", "lean4", "coq", "isabelle", "agda", "formal verification",
                      "proof assistant", "type theory", "dependent type", "mathlib",
                      "theorem proving", "certified", "verified"],
        "weight": 0.9,
    },
    {
        "folder": "optimizacion",
        "keywords": ["compiler", "optimization", "llvm", "mlir", "polyhedral",
                      "loop tiling", "vectorization", "auto-tuning", "scheduling",
                      "code generation", "peephole"],
        "weight": 0.8,
    },
    {
        "folder": "finanzas",
        "keywords": ["finance", "trading", "portfolio", "risk", "black-scholes",
                      "option pricing", "quantitative", "market", "hedging",
                      "algorithmic trading"],
        "weight": 0.8,
    },
    {
        "folder": "programacion",
        "keywords": ["programming language", "type system", "lambda calculus",
                      "functional programming", "monad", "haskell", "rust",
                      "memory safety", "ownership"],
        "weight": 0.7,
    },
    {
        "folder": "matematica",
        "keywords": ["algebra", "number theory", "group theory", "ring theory",
                      "field theory", "galois", "polynomial", "prime", "modular arithmetic",
                      "elliptic curve", "algebraic geometry", "topology"],
        "weight": 0.7,
    },
]

DEFAULT_FOLDER = "general"


def classify(title: str, abstract: str = "") -> dict:
    """Classify a paper based on title and abstract keywords."""
    text = f"{title} {abstract}".lower()

    scores = {}
    for rule in FOLDER_RULES:
        matches = sum(1 for kw in rule["keywords"] if kw in text)
        if matches > 0:
            scores[rule["folder"]] = matches * rule["weight"]

    if not scores:
        return {"folder": DEFAULT_FOLDER, "confidence": "low"}

    best_folder = max(scores, key=scores.get)
    best_score = scores[best_folder]

    if best_score >= 3:
        confidence = "high"
    elif best_score >= 1.5:
        confidence = "medium"
    else:
        confidence = "low"

    return {"folder": best_folder, "confidence": confidence}


def main():
    parser = argparse.ArgumentParser(description="Classify a paper into biblioteca folder")
    parser.add_argument("--title", "-t", required=True, help="Paper title")
    parser.add_argument("--abstract", "-a", default="", help="Paper abstract")
    args = parser.parse_args()

    result = classify(args.title, args.abstract)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
