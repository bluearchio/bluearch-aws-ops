"""Shared AI / Bedrock helpers.

Consumed by `web/routers/ai.py` for chat and by `modules/log_analysis` for
on-demand root-cause analysis.
"""

from modules.ai.bedrock_client import resolve_model_id, converse

__all__ = ["resolve_model_id", "converse"]
