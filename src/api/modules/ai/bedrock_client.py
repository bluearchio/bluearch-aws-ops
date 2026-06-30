"""Shared Bedrock Converse helpers.

Self-contained — no dependency on tag-manager-cli's BedrockAWSAssistant.
Used by both the chat router (`web/routers/ai.py`) and the log analysis
module for on-demand root-cause analysis.

Model resolution strategy (``resolve_model_id``)
------------------------------------------------
For each alias (``haiku`` / ``sonnet`` / ``opus``) we want the *latest active*
release in the customer's region, with no hand-maintained version numbers.
Anthropic retires older Claude releases ("LEGACY"); invoking one returns
``Access denied. This Model is marked by provider as Legacy``.

The resolver therefore:
1. Lists ``list_inference_profiles`` and keeps profiles whose id/name
   contains the alias family. Inference profiles are the only invocable
   path for Claude 4.x and always reflect the current generation.
2. Among those, prefers the profile whose id starts with the region's
   cross-region prefix (``us.`` / ``eu.`` / ``apac.``).
3. Sorts by the 8-digit release date embedded in the id
   (``anthropic.claude-haiku-4-5-20251001-v1:0`` -> 20251001) and picks the
   most recent.
4. Falls back to ``list_foundation_models`` for older families (Claude 3.x
   Haiku still accepts direct on-demand invocation) skipping anything whose
   ``modelLifecycle.status`` is ``LEGACY``.
5. Only if both list APIs fail do we use the static ``_FALLBACK_MODELS``
   map — which is kept on the current generation but is best-effort.
"""

import json
import re
import time
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Cache — resolved id per (alias, region) with a 1h TTL so new Bedrock
# releases don't need a process restart to become visible.
# ---------------------------------------------------------------------------

_CACHE_TTL_SECONDS = 3600
_MODEL_MAP: Dict[str, Tuple[str, float]] = {}

_DATE_RE = re.compile(r"(\d{8})")

# Last-resort hardcoded IDs — used only when both list APIs are unreachable.
# Kept on the current Claude 4.x generation.
_FALLBACK_MODELS: Dict[str, str] = {
    "haiku": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "sonnet": "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "opus": "us.anthropic.claude-opus-4-1-20250805-v1:0",
}


def _extract_release_date(model_id: str) -> int:
    """Pull the YYYYMMDD release date out of a Bedrock model id.

    Returns 0 if no 8-digit token is found, which naturally sorts
    undated ids last.
    """
    m = _DATE_RE.search(model_id or "")
    return int(m.group(1)) if m else 0


def _region_prefix(region: str) -> str:
    """Cross-region inference-profile prefix for the given AWS region."""
    if region.startswith("eu-"):
        return "eu"
    if region.startswith("ap-"):
        return "apac"
    # us-*, ca-*, sa-*, unknown -> us (most widely available)
    return "us"


def _contains_alias(candidate: Optional[str], alias_lc: str) -> bool:
    if not candidate:
        return False
    return alias_lc in candidate.lower()


def _pick_latest(items: List[Dict[str, Any]], id_key: str) -> Optional[Dict[str, Any]]:
    """Return the item with the most recent release date, or None."""
    if not items:
        return None
    items.sort(key=lambda it: _extract_release_date(it.get(id_key, "")), reverse=True)
    return items[0]


def _from_inference_profiles(bedrock, alias_lc: str, region: str) -> Optional[str]:
    """Resolve via list_inference_profiles — the invocable-id source of truth."""
    try:
        resp = bedrock.list_inference_profiles()
    except Exception:
        return None

    profiles = resp.get("inferenceProfileSummaries", []) or []
    matches = [
        p for p in profiles
        if _contains_alias(p.get("inferenceProfileId"), alias_lc)
        or _contains_alias(p.get("inferenceProfileName"), alias_lc)
    ]
    if not matches:
        return None

    prefix = _region_prefix(region) + "."
    regional = [p for p in matches if (p.get("inferenceProfileId") or "").startswith(prefix)]
    chosen = _pick_latest(regional or matches, "inferenceProfileId")
    return chosen.get("inferenceProfileId") if chosen else None


def _from_foundation_models(bedrock, alias_lc: str) -> Optional[str]:
    """Resolve via list_foundation_models — still valid for older families
    that support direct on-demand invocation. Skips LEGACY entries."""
    try:
        resp = bedrock.list_foundation_models(
            byProvider="Anthropic",
            byOutputModality="TEXT",
        )
    except Exception:
        return None

    candidates: List[Dict[str, Any]] = []
    for m in resp.get("modelSummaries", []) or []:
        mid = m.get("modelId", "")
        if not _contains_alias(mid, alias_lc):
            continue
        lifecycle = (m.get("modelLifecycle") or {}).get("status", "")
        if lifecycle and lifecycle.upper() == "LEGACY":
            continue
        inference_types = m.get("inferenceTypesSupported") or []
        if inference_types and "ON_DEMAND" not in inference_types:
            continue
        candidates.append(m)

    chosen = _pick_latest(candidates, "modelId")
    return chosen.get("modelId") if chosen else None


def resolve_model_id(alias: str, region: str = "us-east-1") -> str:
    """Resolve a model alias to an invocable Bedrock id.

    See module docstring for the resolution order. Result is cached per
    (alias, region) for an hour so newly-released models become visible
    without a process restart.
    """
    import boto3

    alias_lc = (alias or "").lower()
    key = f"{alias_lc}:{region}"

    cached = _MODEL_MAP.get(key)
    if cached and (time.time() - cached[1]) < _CACHE_TTL_SECONDS:
        return cached[0]

    try:
        bedrock = boto3.client("bedrock", region_name=region)
    except Exception:
        bedrock = None

    resolved: Optional[str] = None
    if bedrock is not None:
        resolved = _from_inference_profiles(bedrock, alias_lc, region)
        if resolved is None:
            resolved = _from_foundation_models(bedrock, alias_lc)

    if resolved is None:
        resolved = _FALLBACK_MODELS.get(alias_lc, _FALLBACK_MODELS["sonnet"])

    _MODEL_MAP[key] = (resolved, time.time())
    return resolved


def converse(
    prompt: str,
    model_alias: str = "sonnet",
    region: str = "us-east-1",
    system_prompt: Optional[str] = None,
    max_tokens: int = 2048,
) -> str:
    """One-shot non-streaming Bedrock Converse call.

    Args:
        prompt: User message text.
        model_alias: One of "haiku", "sonnet", "opus".
        region: AWS region for bedrock-runtime.
        system_prompt: Optional system prompt.
        max_tokens: Max tokens in response.

    Returns:
        Concatenated text blocks from the assistant response.
    """
    import boto3

    client = boto3.client("bedrock-runtime", region_name=region)
    model_id = resolve_model_id(model_alias, region)

    messages: List[Dict] = [{"role": "user", "content": [{"text": prompt}]}]
    kwargs: Dict[str, Any] = {
        "modelId": model_id,
        "messages": messages,
        "inferenceConfig": {"maxTokens": max_tokens},
    }
    if system_prompt:
        kwargs["system"] = [{"text": system_prompt}]

    resp = client.converse(**kwargs)
    message = resp["output"]["message"]

    parts: List[str] = []
    for block in message.get("content", []):
        if "text" in block:
            parts.append(block["text"])
    return "".join(parts)


# ---------------------------------------------------------------------------
# Tool-use ("agentic") converse loop
# ---------------------------------------------------------------------------

# Cap iterations defensively so a misbehaving model can't run away. Eight
# rounds is more than enough to investigate a Lambda error (log fetch +
# config + a few metrics).
_TOOL_LOOP_MAX_ITERATIONS = 8


def converse_with_tools(
    prompt: str,
    tools: List[Dict[str, Any]],
    tool_dispatcher,
    *,
    model_alias: str = "sonnet",
    region: str = "us-east-1",
    system_prompt: Optional[str] = None,
    max_tokens: int = 3072,
    max_iterations: int = _TOOL_LOOP_MAX_ITERATIONS,
) -> str:
    """Run Bedrock Converse with tool-use enabled.

    Args:
        prompt: The user message.
        tools: List of Bedrock tool specs (each ``{"toolSpec": {...}}``).
        tool_dispatcher: Callable ``(name, input_args) -> str`` that
            executes a tool call and returns a JSON string. Exceptions
            should be serialized as ``{"error": "..."}`` inside that JSON
            so the model can react rather than the whole turn crashing.
        model_alias, region, system_prompt, max_tokens: same semantics as
            the plain ``converse``.
        max_iterations: safety cap on the tool loop.

    Returns:
        The concatenation of text blocks from the assistant's final message.
    """
    import boto3

    client = boto3.client("bedrock-runtime", region_name=region)
    model_id = resolve_model_id(model_alias, region)

    tool_config = {"tools": tools} if tools else None

    messages: List[Dict[str, Any]] = [
        {"role": "user", "content": [{"text": prompt}]}
    ]

    final_text_parts: List[str] = []

    for _ in range(max_iterations):
        kwargs: Dict[str, Any] = {
            "modelId": model_id,
            "messages": messages,
            "inferenceConfig": {"maxTokens": max_tokens},
        }
        if system_prompt:
            kwargs["system"] = [{"text": system_prompt}]
        if tool_config:
            kwargs["toolConfig"] = tool_config

        resp = client.converse(**kwargs)
        message = resp.get("output", {}).get("message") or {}
        content = message.get("content", []) or []

        # Capture any text the model produced in this turn
        turn_text = [b["text"] for b in content if "text" in b]

        # Must echo the assistant message back verbatim for the next turn
        messages.append({"role": "assistant", "content": content})

        stop_reason = resp.get("stopReason")
        if stop_reason == "tool_use":
            tool_results_blocks: List[Dict[str, Any]] = []
            for block in content:
                tu = block.get("toolUse")
                if not tu:
                    continue
                result_json = tool_dispatcher(tu.get("name"), tu.get("input") or {})
                tool_results_blocks.append({
                    "toolResult": {
                        "toolUseId": tu.get("toolUseId"),
                        "content": [{"text": result_json}],
                    }
                })
            if not tool_results_blocks:
                # Model said tool_use but emitted no toolUse block — bail
                # out to avoid an infinite loop.
                final_text_parts.extend(turn_text)
                break
            messages.append({"role": "user", "content": tool_results_blocks})
            # Loop and let the model react to tool results
            continue

        # end_turn (or any terminal reason) → collect final text and stop
        final_text_parts.extend(turn_text)
        break
    else:
        # Ran out of iterations without an end_turn — grab whatever the
        # last message produced so the caller gets *something*.
        if messages and messages[-1]["role"] == "assistant":
            for block in messages[-1]["content"]:
                if "text" in block:
                    final_text_parts.append(block["text"])

    return "".join(final_text_parts).strip()


# ---------------------------------------------------------------------------
# Streaming tool-use loop
# ---------------------------------------------------------------------------

def converse_stream_with_tools(
    prompt: str,
    tools: List[Dict[str, Any]],
    tool_dispatcher: Callable[[str, Dict[str, Any]], str],
    *,
    model_alias: str = "sonnet",
    region: str = "us-east-1",
    system_prompt: Optional[str] = None,
    max_tokens: int = 3072,
    max_iterations: int = _TOOL_LOOP_MAX_ITERATIONS,
) -> Iterator[Dict[str, Any]]:
    """Same as ``converse_with_tools`` but yields events as they happen.

    Event shape:
      - ``{"type": "text_delta", "text": "..."}``        — streamed assistant text
      - ``{"type": "tool_use",   "name": ..., "input": ...}`` — model invoked a tool
      - ``{"type": "tool_result","name": ..., "summary": ...}`` — our response
      - ``{"type": "done",       "analysis": "..."}``    — terminal event
    """
    import boto3

    client = boto3.client("bedrock-runtime", region_name=region)
    model_id = resolve_model_id(model_alias, region)
    tool_config = {"tools": tools} if tools else None

    messages: List[Dict[str, Any]] = [
        {"role": "user", "content": [{"text": prompt}]}
    ]
    final_text_parts: List[str] = []

    for _ in range(max_iterations):
        kwargs: Dict[str, Any] = {
            "modelId": model_id,
            "messages": messages,
            "inferenceConfig": {"maxTokens": max_tokens},
        }
        if system_prompt:
            kwargs["system"] = [{"text": system_prompt}]
        if tool_config:
            kwargs["toolConfig"] = tool_config

        resp = client.converse_stream(**kwargs)

        assistant_content: List[Dict[str, Any]] = []
        current_text = ""
        current_tool: Optional[Dict[str, Any]] = None
        stop_reason: Optional[str] = None

        for event in resp["stream"]:
            if "contentBlockStart" in event:
                start = event["contentBlockStart"].get("start", {}) or {}
                tu = start.get("toolUse")
                if tu:
                    current_tool = {
                        "toolUseId": tu.get("toolUseId"),
                        "name": tu.get("name"),
                        "input_buf": "",
                    }
            elif "contentBlockDelta" in event:
                delta = event["contentBlockDelta"].get("delta", {}) or {}
                if "text" in delta:
                    chunk = delta["text"]
                    current_text += chunk
                    yield {"type": "text_delta", "text": chunk}
                elif "toolUse" in delta and current_tool is not None:
                    # Tool input streams in as partial JSON fragments
                    current_tool["input_buf"] += delta["toolUse"].get("input", "")
            elif "contentBlockStop" in event:
                if current_text:
                    assistant_content.append({"text": current_text})
                    current_text = ""
                if current_tool is not None:
                    parsed_input: Dict[str, Any] = {}
                    buf = current_tool["input_buf"]
                    if buf:
                        try:
                            parsed_input = json.loads(buf)
                        except Exception:
                            parsed_input = {}
                    assistant_content.append({
                        "toolUse": {
                            "toolUseId": current_tool["toolUseId"],
                            "name": current_tool["name"],
                            "input": parsed_input,
                        }
                    })
                    yield {
                        "type": "tool_use",
                        "name": current_tool["name"],
                        "input": parsed_input,
                    }
                    current_tool = None
            elif "messageStop" in event:
                stop_reason = event["messageStop"].get("stopReason")

        messages.append({"role": "assistant", "content": assistant_content})

        if stop_reason == "tool_use":
            tool_results_blocks: List[Dict[str, Any]] = []
            for block in assistant_content:
                tu = block.get("toolUse")
                if not tu:
                    continue
                result_json = tool_dispatcher(tu.get("name") or "", tu.get("input") or {})
                tool_results_blocks.append({
                    "toolResult": {
                        "toolUseId": tu.get("toolUseId"),
                        "content": [{"text": result_json}],
                    }
                })
                yield {
                    "type": "tool_result",
                    "name": tu.get("name"),
                    "summary": _summarize_tool_result(result_json),
                }
            if not tool_results_blocks:
                break
            messages.append({"role": "user", "content": tool_results_blocks})
            continue

        # end_turn — collect final text and stop
        for block in assistant_content:
            if "text" in block:
                final_text_parts.append(block["text"])
        break

    final = "".join(final_text_parts).strip()
    yield {"type": "done", "analysis": final}


def _summarize_tool_result(raw_json: str, max_chars: int = 220) -> str:
    """One-line summary of a tool result for the UI ticker. Tries to surface
    the most informative field (error, event_count, datapoint totals, etc.)."""
    try:
        obj = json.loads(raw_json)
    except Exception:
        return raw_json[:max_chars]

    if isinstance(obj, dict):
        if obj.get("error"):
            return f"error: {obj['error']}"[:max_chars]
        if "event_count" in obj:
            return f"{obj['event_count']} event(s) over {obj.get('start_time', '?')[:19]}..{obj.get('end_time', '?')[:19]}"
        if "function_name" in obj:
            parts = [
                f"{obj.get('runtime')}",
                f"{obj.get('memory_mb')}MB",
                f"timeout {obj.get('timeout_sec')}s",
                f"state {obj.get('state')}",
            ]
            return f"{obj['function_name']}: " + ", ".join(p for p in parts if p and p != "None")
        if "metric_name" in obj:
            return f"{obj['metric_name']} ({obj.get('statistic')}): max={obj.get('max')}, avg={obj.get('avg')}, total={obj.get('total')}"
        if "resource_arn" in obj:
            return f"{obj.get('resource_type')} {obj.get('resource_id_aws')} ({obj.get('region')})"

    s = str(obj)
    return s[:max_chars]
