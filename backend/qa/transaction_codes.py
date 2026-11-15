"""Superseded 2026-11-15 by qa/suites/transaction_numbering.py (accounting unification batch 2),
which runs with every isolated QA run. Kept as an entry point for manual runs."""
from pathlib import Path
exec(Path(__file__).resolve().parent.joinpath('suites', 'transaction_numbering.py').read_text())
