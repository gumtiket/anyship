"""Run after editable install: python ai/scripts/bedrock_check.py [--list-only]."""

from ai.llm.check import main

if __name__ == "__main__":
    raise SystemExit(main())
