"""Keep provider payloads out of ADK logs and persisted session events.

ADK 2.x workflow nodes log failures with full tracebacks and record `str(error)`
on an error event. Provider exceptions can contain prompts, uploaded content or
credentials, so both are redacted before they reach a handler or the session store.
"""

import logging

from google.adk.apps import App
from google.adk.events import Event
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

REDACTED = "Provider error details redacted."
FINISH_REASONS = {reason.value for reason in types.FinishReason} | {
    reason.name for reason in types.FinishReason
}

_installed = False


def install_log_redaction() -> None:
    """Strip exception details from ADK log records; idempotent."""
    global _installed
    if _installed:
        return
    base_factory = logging.getLogRecordFactory()

    def factory(name, level, fn, lno, msg, args, exc_info, func=None, sinfo=None, **kwargs):
        if name.startswith("google_adk") and exc_info:
            error = exc_info[1] if isinstance(exc_info, tuple) else exc_info
            if isinstance(error, BaseException):
                msg = f"{msg} [{type(error).__name__}; details redacted]"
            exc_info = None
        return base_factory(name, level, fn, lno, msg, args, exc_info, func, sinfo, **kwargs)

    logging.setLogRecordFactory(factory)
    _installed = True


def is_node_failure(event: Event) -> bool:
    """An ADK error event created from a raised exception, not a model finish reason."""
    return bool(event.error_code) and str(event.error_code) not in FINISH_REASONS


class RedactErrorsPlugin(BasePlugin):
    def __init__(self):
        super().__init__(name="intentcart_redact_errors")

    async def on_event_callback(self, *, invocation_context, event: Event) -> Event | None:
        if event.error_message and is_node_failure(event):
            return event.model_copy(update={"error_message": REDACTED})
        return None


def adk_app(name: str, root_agent) -> App:
    """Every IntentCart runner uses this so redaction cannot be forgotten."""
    return App(name=name, root_agent=root_agent, plugins=[RedactErrorsPlugin()])
