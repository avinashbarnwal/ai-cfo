"""Transaction foundation model for financial intelligence.

Port of NVIDIA's "Build Your Own Transaction Foundation Model" developer example:
data + temporal split -> domain tokenizer -> decoder pretraining -> last-token
embeddings -> XGBoost fraud lift. See ``pipeline.py`` for the CLI.
"""
