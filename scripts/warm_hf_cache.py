"""Pre-download the Hugging Face embedder model into the local cache.

Run once during install (install.sh / install.ps1 invoke this script
after pip install). The VAT Fraud Detection agent then loads the model
in offline mode at runtime, sidestepping the httpx-client-closed bug
in huggingface_hub 1.7.x.
"""
from sentence_transformers import SentenceTransformer

MODEL = "all-MiniLM-L6-v2"
print(f"Downloading {MODEL} embedder model into local HF cache...")
SentenceTransformer(MODEL)
print("✓ Cache warm.")
