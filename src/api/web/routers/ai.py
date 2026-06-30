"""AI chat endpoints with SSE streaming.

Uses boto3 bedrock-runtime directly to call Claude models via the Converse
Streaming API.  No dependency on tag-manager-cli's BedrockAWSAssistant; this
is a self-contained implementation tailored for BlueArch (alerting and
recommendations).
"""

import asyncio
import json
import logging
import queue
import re
import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime
from typing import AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from utils.event_hooks import track_event
from utils.core_client import CoreRuntimeError
from web.core_storage import (
    create_storage_payload,
    delete_storage_payload,
    get_storage_payload,
    list_storage_payloads,
    update_storage_payload,
)
from web.dependencies import get_current_user
from web.schemas.ai import (
    ChatRequest,
    ChatResponse,
    ConversationSummary,
    ModelInfo,
    ModelsResponse,
    QuestionRequest,
)
from modules.ai.bedrock_client import resolve_model_id as _resolve_model_id

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])

logger = logging.getLogger("bluearch.ai")

# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

MODELS = {
    "haiku": {
        "description": "Fast and cost-effective",
    },
    "sonnet": {
        "description": "Balanced performance and quality",
    },
    "opus": {
        "description": "Highest quality for complex tasks",
    },
}


# ---------------------------------------------------------------------------
# Lightweight Bedrock streaming assistant
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an AWS infrastructure assistant for the BlueArch CLI.
You help users understand their AWS resources, recommendations, alarms, and cost
optimization opportunities.

When answering questions:
1. Provide clear, concise answers with specific details.
2. Format data in readable tables or lists when appropriate.
3. Reference the user's scan data and recommendations when relevant.
4. Suggest actionable next steps (e.g. "run `bluearch scan` to refresh data").

Context:
- The user runs BlueArch CLI which scans EC2, RDS, ELB, ElastiCache, IAM, and more.
- Recommendations cover idle instances, unattached volumes, expired IAM keys, etc.
- Data is stored locally in SQLite.

After answering each question, suggest 2-3 related follow-up questions:

---
**Related questions you might find useful:**
- [Follow-up question 1]
- [Follow-up question 2]
- [Follow-up question 3]
---"""


class _BedrockChat:
    """Minimal Bedrock Converse wrapper with conversation history and streaming."""

    def __init__(self, model_alias: str = "haiku", region: str = "us-east-1"):
        self.region = region
        self.model_alias = model_alias
        self.model_id = _resolve_model_id(model_alias, region)
        self._client = None
        self.conversation_history: List[Dict] = []
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0

    def _get_client(self):
        if self._client is None:
            import boto3
            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    # -- Non-streaming ---------------------------------------------------

    def ask(self, question: str) -> str:
        client = self._get_client()
        self.conversation_history.append({
            "role": "user",
            "content": [{"text": question}],
        })

        resp = client.converse(
            modelId=self.model_id,
            messages=self.conversation_history,
            system=[{"text": _SYSTEM_PROMPT}],
        )

        usage = resp.get("usage", {})
        self.total_input_tokens += usage.get("inputTokens", 0)
        self.total_output_tokens += usage.get("outputTokens", 0)

        assistant_msg = resp["output"]["message"]
        self.conversation_history.append(assistant_msg)

        parts = []
        for block in assistant_msg.get("content", []):
            if "text" in block:
                parts.append(block["text"])
        return "".join(parts)

    # -- Streaming -------------------------------------------------------

    def ask_stream(self, question: str):
        """Yield text chunks via Bedrock converse_stream."""
        client = self._get_client()
        self.conversation_history.append({
            "role": "user",
            "content": [{"text": question}],
        })

        stream_params = {
            "modelId": self.model_id,
            "messages": self.conversation_history,
            "system": [{"text": _SYSTEM_PROMPT}],
        }

        resp = client.converse_stream(**stream_params)

        assistant_content = []
        current_text = ""

        for event in resp["stream"]:
            if "contentBlockDelta" in event:
                delta = event["contentBlockDelta"]["delta"]
                if "text" in delta:
                    chunk = delta["text"]
                    current_text += chunk
                    yield chunk

            elif "contentBlockStop" in event:
                if current_text:
                    assistant_content.append({"text": current_text})
                    current_text = ""

            elif "metadata" in event:
                usage = event["metadata"].get("usage", {})
                self.total_input_tokens += usage.get("inputTokens", 0)
                self.total_output_tokens += usage.get("outputTokens", 0)

        # Save to history
        if assistant_content:
            self.conversation_history.append({
                "role": "assistant",
                "content": assistant_content,
            })


# ---------------------------------------------------------------------------
# Session management (in-memory, FIFO eviction)
# ---------------------------------------------------------------------------

_sessions: OrderedDict = OrderedDict()
_MAX_SESSIONS = 20


def _classify_query_complexity(question: str) -> str:
    """Classify query complexity to auto-select the appropriate model."""
    q = question.lower().strip()

    complex_patterns = [
        r'\bcompar',
        r'\banalyz',
        r'\btrend',
        r'\banomaly',
        r'\banomalies',
        r'\boptimiz',
        r'\bwhy\b',
        r'\bacross accounts\b',
        r'\bcross.account',
        r'\bmulti.region',
        r'\ball accounts\b',
        r'\bcorrelat',
        r'\bforecast',
        r'\brecommend',
        r'\bstrateg',
        r'\broot cause',
        r'\bexplain why',
        r'\bbreak.*down',
        r'\bdiagnost',
    ]

    for pattern in complex_patterns:
        if re.search(pattern, q):
            return "sonnet"

    if len(q) > 200:
        return "sonnet"

    return "haiku"


def _extract_suggestions(text: str) -> List[str]:
    """Extract follow-up suggestions from AI response text."""
    suggestions = []
    lines = text.split('\n')
    in_suggestions = False

    for line in lines:
        lower_line = line.lower()
        if ('related questions' in lower_line or
                'you might find useful' in lower_line or
                'would you like me to' in lower_line or
                'would you like to' in lower_line):
            in_suggestions = True
            continue

        if in_suggestions:
            if line.strip() == '---' or line.strip() == '':
                if suggestions:
                    break
                continue

            stripped = line.strip()
            suggestion = None

            if stripped.startswith('- ') or stripped.startswith('* '):
                suggestion = stripped[2:].strip()
            elif re.match(r'^[1-3][.\s]', stripped):
                suggestion = re.sub(r'^[1-3][.\s]+', '', stripped).strip()

            if suggestion:
                suggestion = suggestion.strip('"').strip("'")
                suggestion = re.sub(r'\s*\([^)]+\)\s*$', '', suggestion)
                if suggestion and len(suggestions) < 3:
                    suggestions.append(suggestion)

    return suggestions


def _get_or_create_session(session_id: Optional[str], model: str):
    """Get an existing assistant session or create a new one."""
    global _sessions

    if session_id and session_id in _sessions:
        return session_id, _sessions[session_id]

    if model == "auto":
        model_alias = "haiku"  # Default; overridden per-question
    else:
        model_alias = model if model in MODELS else "haiku"

    assistant = _BedrockChat(model_alias=model_alias)
    new_id = session_id or str(uuid.uuid4())

    # FIFO eviction
    if len(_sessions) >= _MAX_SESSIONS:
        _sessions.popitem(last=False)

    _sessions[new_id] = assistant
    return new_id, assistant


# ---------------------------------------------------------------------------
# Conversation persistence
# ---------------------------------------------------------------------------

def _save_conversation(
    session_id: str,
    question: str,
    response_text: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    tool_calls_data: list,
):
    """Save conversation through bluearch-core storage (best-effort)."""
    try:
        try:
            conv = get_storage_payload("bluearch", "chat-conversations", session_id)
        except CoreRuntimeError:
            conv = {}

        title = conv.get("title") or question[:60].strip()
        if not conv.get("title") and len(question) > 60:
            title += "..."
        now = datetime.utcnow().isoformat()
        conv_payload = {
            **conv,
            "id": session_id,
            "title": title,
            "model": model,
            "message_count": (conv.get("message_count") or 0) + 2,
            "total_input_tokens": (conv.get("total_input_tokens") or 0) + input_tokens,
            "total_output_tokens": (conv.get("total_output_tokens") or 0) + output_tokens,
            "updated_at": now,
        }
        if not conv_payload.get("created_at"):
            conv_payload["created_at"] = now
        update_storage_payload("bluearch", "chat-conversations", session_id, conv_payload)

        create_storage_payload(
            "bluearch",
            "chat-messages",
            {
                "id": str(uuid.uuid4()),
                "conversation_id": session_id,
                "role": "user",
                "content": question,
                "created_at": now,
            },
        )
        create_storage_payload(
            "bluearch",
            "chat-messages",
            {
                "id": str(uuid.uuid4()),
                "conversation_id": session_id,
                "role": "assistant",
                "content": response_text,
                "tool_calls": json.dumps(tool_calls_data) if tool_calls_data else None,
                "tokens": json.dumps({"input": input_tokens, "output": output_tokens}),
                "created_at": datetime.utcnow().isoformat(),
            },
        )
    except Exception:
        pass  # Don't break chat on DB errors


# ---------------------------------------------------------------------------
# SSE streaming
# ---------------------------------------------------------------------------

async def _stream_sse(
    assistant: _BedrockChat,
    question: str,
    session_id: str,
    selected_model: str,
) -> AsyncGenerator[str, None]:
    """Convert sync ask_stream() to SSE async generator via thread + queue."""
    q: queue.Queue = queue.Queue()
    done_sentinel = object()
    accumulated_text: List[str] = []
    tool_calls_data: list = []

    def _run_stream():
        try:
            for chunk in assistant.ask_stream(question):
                q.put(("text", chunk))
                accumulated_text.append(chunk)

            full_text = "".join(accumulated_text)
            suggestions = _extract_suggestions(full_text)
            if suggestions:
                q.put(("suggestions", suggestions))

            q.put((
                "done",
                {
                    "session_id": session_id,
                    "conversation_id": session_id,
                    "selected_model": selected_model,
                    "input_tokens": assistant.total_input_tokens,
                    "output_tokens": assistant.total_output_tokens,
                },
            ))

            _save_conversation(
                session_id, question, full_text, selected_model,
                assistant.total_input_tokens, assistant.total_output_tokens,
                tool_calls_data,
            )
        except Exception as exc:
            q.put(("error", str(exc)))
        finally:
            q.put(done_sentinel)

    thread = threading.Thread(target=_run_stream, daemon=True)
    thread.start()

    while True:
        item = await asyncio.to_thread(q.get, timeout=300)
        if item is done_sentinel:
            break
        event_type, data = item
        if event_type == "tool_call":
            tool_calls_data.append({"name": data["name"], "type": "call"})
        elif event_type == "tool_result":
            tool_calls_data.append({
                "name": data["name"],
                "type": "result",
                "success": data.get("success"),
                "summary": data.get("summary", ""),
                "duration_ms": data.get("duration_ms"),
            })
        yield f"data: {json.dumps({'type': event_type, 'content': data})}\n\n"

    yield "data: [DONE]\n\n"


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@router.post("/chat")
async def chat_stream(body: ChatRequest, _user=Depends(get_current_user)):
    """Chat with AI assistant via SSE streaming."""
    selected_model = body.model
    if body.model == "auto":
        selected_model = _classify_query_complexity(body.question)

    try:
        session_id, assistant = _get_or_create_session(body.session_id, selected_model)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to initialize AI assistant: {exc}",
        )

    return StreamingResponse(
        _stream_sse(assistant, body.question, session_id, selected_model),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/question", response_model=ChatResponse)
async def ask_question(body: QuestionRequest, _user=Depends(get_current_user)):
    """Ask a single question (non-streaming)."""

    def _ask_sync():
        model_alias = body.model if body.model in MODELS else "haiku"
        assistant = _BedrockChat(model_alias=model_alias)
        answer = assistant.ask(body.question)
        return answer, {
            "input_tokens": assistant.total_input_tokens,
            "output_tokens": assistant.total_output_tokens,
        }

    try:
        answer, tokens = await asyncio.to_thread(_ask_sync)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"AI assistant error: {exc}",
        )

    return ChatResponse(
        answer=answer,
        session_id=str(uuid.uuid4()),
        model=body.model,
        tokens=tokens,
    )


@router.get("/models", response_model=ModelsResponse)
async def list_models(_user=Depends(get_current_user)):
    """List available AI models."""
    models = [
        ModelInfo(alias=alias, model_id=alias, description=info["description"])
        for alias, info in MODELS.items()
    ]
    return ModelsResponse(models=models, default="auto")


# --- Conversation persistence endpoints ---

@router.get("/conversations")
async def list_conversations(current_user=Depends(get_current_user)):
    """List recent conversations."""
    def _query():
        convs = list_storage_payloads(
            "bluearch",
            "chat-conversations",
            limit=50,
            order_by="updated_at",
            descending=True,
        )
        return [
            ConversationSummary(
                id=c["id"],
                title=c.get("title") or "Untitled conversation",
                model=c.get("model") or "auto",
                message_count=c.get("message_count") or 0,
                updated_at=c.get("updated_at") or c.get("created_at") or "",
            ).dict()
            for c in convs
            if c.get("id")
        ]

    try:
        result = await asyncio.to_thread(_query)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    try:
        track_event(
            "web.ai.conversations",
            properties={
                "user_sub": getattr(current_user, "sub", None),
                "count": len(result) if hasattr(result, "__len__") else 0,
            },
        )
    except Exception:
        pass

    return result


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: str,
    _user=Depends(get_current_user),
):
    """Get messages for a conversation."""
    def _query():
        msgs = list_storage_payloads(
            "bluearch",
            "chat-messages",
            limit=10000,
            filters=[("conversation_id", conversation_id)],
            order_by="created_at",
            descending=False,
        )
        return [
            {
                "id": m.get("id"),
                "role": m.get("role"),
                "content": m.get("content"),
                "tool_calls": json.loads(m["tool_calls"]) if m.get("tool_calls") else None,
                "tokens": json.loads(m["tokens"]) if m.get("tokens") else None,
                "created_at": m.get("created_at") or "",
            }
            for m in msgs
        ]

    try:
        return await asyncio.to_thread(_query)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    _user=Depends(get_current_user),
):
    """Delete a conversation and its messages."""
    def _delete():
        msgs = list_storage_payloads(
            "bluearch",
            "chat-messages",
            limit=10000,
            filters=[("conversation_id", conversation_id)],
        )
        for msg in msgs:
            if msg.get("id"):
                delete_storage_payload("bluearch", "chat-messages", msg["id"])
        delete_storage_payload("bluearch", "chat-conversations", conversation_id)
        return {"success": True}

    try:
        return await asyncio.to_thread(_delete)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
