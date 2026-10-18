"""Project ADK events into public messages; never expose thoughts or raw tools."""

import re
from urllib.parse import urlsplit

from google.adk.events import Event

from app.agents.conversation_schemas import (
    ChatMessage,
    Citation,
    RetryAdvice,
    Source,
    TurnError,
)


def http_url(url: str | None) -> bool:
    try:
        parsed = urlsplit(url or "")
        return parsed.scheme in {"https", "http"} and bool(parsed.hostname) and not parsed.username
    except ValueError:
        return False


QUICK_REPLIES = re.compile(
    r"(?:\A|\n)[ \t]*[*_]*quick replies[*_]*[ \t]*:[*_]*[ \t]*([^\n]+?)\s*\Z", re.IGNORECASE
)


def split_quick_replies(text: str) -> tuple[str, list[str]]:
    """Strip a trailing "Quick replies: A | B | C" line into tappable suggestions."""
    match = QUICK_REPLIES.search(text)
    if not match or "\n" in match.group(1):
        return text, []
    options = [
        option.strip(" *`\"'")[:60]
        for option in match.group(1).split("|")
        if option.strip(" *`\"'")
    ]
    if len(options) < 2:
        return text, []
    return text[: match.start()].rstrip(), list(dict.fromkeys(options))[:5]


def public_message(event: Event, root_name: str) -> ChatMessage | None:
    error = event.actions.state_delta.get("chat:error")
    if event.author == "system" and error:
        failure = event.actions.state_delta.get("chat:failure")
        request_id = event.actions.state_delta.get("chat:request_id")
        return ChatMessage(
            id=event.id,
            role="assistant",
            text=error,
            created_at=event.timestamp,
            status="error",
            request_id=request_id,
            error=TurnError.model_validate(failure.get("error"))
            if isinstance(failure, dict) and isinstance(failure.get("error"), dict)
            else None,
            retry=RetryAdvice.model_validate(failure.get("retry"))
            if isinstance(failure, dict) and isinstance(failure.get("retry"), dict)
            else None,
        )
    if event.author != "user" and (event.author != root_name or not event.is_final_response()):
        return None
    text = (
        "".join(part.text for part in (event.content.parts or []) if part.text and not part.thought)
        if event.content
        else ""
    )
    if not text or event.partial:
        return None
    suggestions: list[str] = []
    if event.author != "user":
        text, suggestions = split_quick_replies(text)
    message = ChatMessage(
        id=event.id,
        role="user" if event.author == "user" else "assistant",
        text=text,
        created_at=event.timestamp,
        suggestions=suggestions,
    )
    if message.role == "user":
        attachments = event.actions.state_delta.get("chat:attachments")
        if isinstance(attachments, list):
            message.attachments = [name for name in attachments if isinstance(name, str)]
    metadata = event.grounding_metadata
    if message.role != "assistant" or metadata is None:
        return message
    indices = {}
    for index, chunk in enumerate(metadata.grounding_chunks or []):
        if chunk.web and http_url(chunk.web.uri):
            indices[index] = len(message.sources)
            message.sources.append(
                Source(title=chunk.web.title or urlsplit(chunk.web.uri).hostname, url=chunk.web.uri)
            )
    for support in metadata.grounding_supports or []:
        source_indices = [
            indices[index] for index in support.grounding_chunk_indices or [] if index in indices
        ]
        if support.segment and support.segment.text and source_indices:
            message.citations.append(
                Citation(text=support.segment.text, source_indices=source_indices)
            )
    message.search_queries = metadata.web_search_queries or []
    if metadata.search_entry_point:
        message.search_entry_point = metadata.search_entry_point.rendered_content
    return message
