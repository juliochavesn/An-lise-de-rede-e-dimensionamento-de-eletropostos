#!/bin/zsh
cd "$(dirname "$0")"
exec .venv/bin/streamlit run app.py
