"""
otel.py — OpenTelemetry tracing for Recall.

If OTEL_EXPORTER_OTLP_ENDPOINT is set, spans are exported via OTLP/HTTP
(compatible with Honeycomb, Jaeger, and other collectors).
When the env var is absent a no-op tracer is used and no data leaves the process.

Environment variables (all optional):
  OTEL_EXPORTER_OTLP_ENDPOINT  — OTLP HTTP endpoint, e.g. https://api.honeycomb.io
  OTEL_SERVICE_NAME            — service name tag; defaults to "recall"
  OTEL_EXPORTER_OTLP_HEADERS   — comma-separated key=value headers, e.g.
                                   x-honeycomb-team=your_api_key
"""

import logging
import os
from contextlib import contextmanager

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional OTel import — gracefully degrade to no-op stubs when not installed.
# ---------------------------------------------------------------------------
try:
    from opentelemetry import trace as _otel_trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.semconv.resource import ResourceAttributes

    _SVC_NAME_KEY = ResourceAttributes.SERVICE_NAME
    _OTEL_AVAILABLE = True
except ImportError:
    _OTEL_AVAILABLE = False
    log.debug("otel | opentelemetry packages not installed — tracing is a no-op")


# ---------------------------------------------------------------------------
# No-op stubs — used whenever OTel packages are absent.
# The same API surface is exposed so callers never need to guard against None.
# ---------------------------------------------------------------------------

class _NoOpSpan:
    """Minimal stand-in for an OTel Span when the SDK is not installed."""

    def set_attribute(self, key, value):  # noqa: D401
        pass

    def set_status(self, *args, **kwargs):
        pass

    def record_exception(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _NoOpTracer:
    """Minimal stand-in for an OTel Tracer when the SDK is not installed."""

    def start_as_current_span(self, name, **kwargs):  # noqa: D401
        return _NoOpSpan()


# ---------------------------------------------------------------------------
# Module-level tracer reference — populated by setup_tracing().
# ---------------------------------------------------------------------------
_tracer = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _parse_headers(raw: str) -> dict:
    """Parse 'key1=val1,key2=val2' into {'key1': 'val1', 'key2': 'val2'}."""
    if not raw:
        return {}
    result = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if "=" in pair:
            k, _, v = pair.partition("=")
            result[k.strip()] = v.strip()
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def setup_tracing() -> None:
    """
    Initialize the OTel tracer provider.  Call once at application startup.

    When opentelemetry packages are not installed, or when
    OTEL_EXPORTER_OTLP_ENDPOINT is not set, this installs a no-op provider
    so the rest of the codebase can call get_tracer() / llm_span() safely.
    """
    global _tracer  # noqa: PLW0603

    if not _OTEL_AVAILABLE:
        _tracer = _NoOpTracer()
        log.debug("otel | no-op tracing — opentelemetry packages not installed")
        return

    service_name = os.environ.get("OTEL_SERVICE_NAME", "recall")
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    headers_raw = os.environ.get("OTEL_EXPORTER_OTLP_HEADERS", "").strip()

    resource = Resource.create({_SVC_NAME_KEY: service_name})

    if endpoint:
        headers = _parse_headers(headers_raw)
        exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        log.info(
            "otel | OTLP exporter configured endpoint=%s service=%s",
            endpoint,
            service_name,
        )
    else:
        # No export destination — spans are recorded in-process and discarded.
        provider = TracerProvider(resource=resource)
        log.debug(
            "otel | OTEL_EXPORTER_OTLP_ENDPOINT not set — spans will not be exported"
        )

    _otel_trace.set_tracer_provider(provider)
    _tracer = _otel_trace.get_tracer(service_name)
    log.info("otel | tracing initialized service=%s", service_name)


def get_tracer():
    """
    Return the module-level tracer.

    Safe to call before setup_tracing() — returns a _NoOpTracer in that case.
    """
    return _tracer if _tracer is not None else _NoOpTracer()


@contextmanager
def llm_span(tracer, node: str, model: str):
    """
    Sync context manager that wraps a single LLM call in an OTel span.

    Starts a span named ``llm.<node>`` and pre-populates the ``llm.node``
    and ``llm.model`` attributes.  The live span is yielded so callers can
    attach additional attributes (e.g. token counts, latency) inside the block::

        with llm_span(get_tracer(), "planner", "qwen/qwen3-8b") as span:
            response = await llm.invoke(messages)
            span.set_attribute("llm.input_tokens", response.usage_metadata["input_tokens"])
            span.set_attribute("llm.output_tokens", response.usage_metadata["output_tokens"])
            span.set_attribute("llm.latency_ms", elapsed_ms)

    Works transparently whether the real OTel SDK is installed or not.
    """
    with tracer.start_as_current_span(f"llm.{node}") as span:
        span.set_attribute("llm.node", node)
        span.set_attribute("llm.model", model)
        yield span
