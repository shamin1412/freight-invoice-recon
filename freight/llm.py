"""Provider layer: one structured-output call, backed by Claude or Groq.

Provider is chosen by FREIGHT_PROVIDER ("claude" | "groq"), or automatically: Claude if
ANTHROPIC_API_KEY is set, otherwise Groq if GROQ_API_KEY is set.

* Claude reads PDFs natively (text layer and scans) as document blocks and uses Pydantic
  structured outputs via `messages.parse`.
* Groq's structured-output models are text-only, so PDFs are converted to text first:
  the PDF text layer when there is one (pdfplumber), OCR (Tesseract) for scanned pages.
  Output is constrained with a strict JSON schema derived from the same Pydantic model.
"""
from __future__ import annotations

import base64
import copy
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODELS = {"claude": "claude-opus-5-5", "groq": "openai/gpt-oss-120b"}


def provider() -> str:
    p = os.environ.get("FREIGHT_PROVIDER", "").lower()
    if p in DEFAULT_MODELS:
        return p
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "claude"
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    return "claude"


def default_model(prov: str | None = None) -> str:
    return os.environ.get("FREIGHT_MODEL") or DEFAULT_MODELS[prov or provider()]


@dataclass
class LLMResult:
    parsed: BaseModel | None
    error: str | None
    seconds: float
    input_tokens: int = 0
    output_tokens: int = 0
    doc_chars: int = 0
    ocr_used: bool = False


# ------------------------------------------------------------------ document -> text (Groq path)
def pdf_to_text(path: Path) -> tuple[str, bool]:
    import pdfplumber

    with pdfplumber.open(str(path)) as pdf:
        text = "\n".join((p.extract_text(layout=True) or "") for p in pdf.pages)
    if len(text.strip()) > 80:
        return text, False
    import pypdfium2 as pdfium
    import pytesseract

    doc = pdfium.PdfDocument(str(path))
    from PIL import ImageFilter

    # 400 dpi + blur to suppress scan speckle, then Tesseract in single-column mode
    # (chosen by token recall on the six scanned invoices: 23/36 key values vs 14/36 for raw 300 dpi)
    pages = [pytesseract.image_to_string(doc[i].render(scale=400 / 72).to_pil().convert("L").filter(ImageFilter.GaussianBlur(2.0)),
                                         config="--psm 4") for i in range(len(doc))]
    doc.close()
    return "\n".join(pages), True


def document_text(path: Path) -> tuple[str, bool]:
    if path.suffix.lower() == ".pdf":
        text, ocr = pdf_to_text(path)
        tag = "invoice_document (OCR of scanned PDF; expect OCR errors)" if ocr else "invoice_document (PDF text layer)"
    else:
        text, ocr, tag = path.read_text(), False, "invoice_document"
    return f"<{tag} filename=\"{path.name}\">\n{text}\n</invoice_document>", ocr


# ------------------------------------------------------------------ strict schema for Groq
def strict_schema(model: Type[BaseModel]) -> dict:
    s = copy.deepcopy(model.model_json_schema())

    def walk(node):
        if isinstance(node, dict):
            node.pop("title", None)
            node.pop("default", None)
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(s)
    return s


# ------------------------------------------------------------------ the call
def structured(system: str, schema: Type[T], *, doc: Path | None = None, text: str | None = None,
               model: str | None = None, effort: str = "low", prov: str | None = None, client=None) -> LLMResult:
    prov = prov or provider()
    model = model or default_model(prov)
    t0 = time.perf_counter()
    if prov == "claude":
        return _claude(system, schema, doc, text, model, effort, client, t0)
    return _groq(system, schema, doc, text, model, effort, client, t0)


def _claude(system, schema, doc, text, model, effort, client, t0):
    import anthropic

    client = client or anthropic.Anthropic(max_retries=4)
    content = []
    if doc is not None:
        if doc.suffix.lower() == ".pdf":
            content.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                            "data": base64.standard_b64encode(doc.read_bytes()).decode()}})
        else:
            content.append({"type": "text", "text": f"<invoice_document filename=\"{doc.name}\">\n{doc.read_text()}\n</invoice_document>"})
    content.append({"type": "text", "text": text or "Extract this invoice."})
    try:
        r = client.messages.parse(model=model, max_tokens=16000, system=system,
                                  messages=[{"role": "user", "content": content}],
                                  output_config={"effort": effort}, output_format=schema)
        secs = time.perf_counter() - t0
        if r.stop_reason in ("refusal", "max_tokens") or r.parsed_output is None:
            return LLMResult(None, f"stop_reason={r.stop_reason}", secs)
        return LLMResult(r.parsed_output, None, secs, r.usage.input_tokens, r.usage.output_tokens)
    except anthropic.APIStatusError as e:
        return LLMResult(None, f"api_error {e.status_code}: {e.message}", time.perf_counter() - t0)
    except anthropic.APIConnectionError as e:
        return LLMResult(None, f"connection_error: {e}", time.perf_counter() - t0)
    except Exception as e:
        return LLMResult(None, f"{type(e).__name__}: {e}", time.perf_counter() - t0)


def _groq(system, schema, doc, text, model, effort, client, t0):
    import groq

    client = client or groq.Groq(max_retries=4)
    parts, ocr = [], False
    if doc is not None:
        dtext, ocr = document_text(doc)
        parts.append(dtext)
    parts.append(text or "Extract this invoice.")
    user = "\n\n".join(parts)
    kwargs = {}
    if model.startswith("openai/gpt-oss"):
        kwargs["reasoning_effort"] = effort if effort in ("low", "medium", "high") else "medium"
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_schema",
                             "json_schema": {"name": schema.__name__, "strict": True, "schema": strict_schema(schema)}},
            **kwargs,
        )
        secs = time.perf_counter() - t0
        msg = r.choices[0].message.content or ""
        parsed = schema.model_validate(json.loads(msg))
        u = r.usage
        return LLMResult(parsed, None, secs, getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0,
                         len(user), ocr)
    except groq.APIStatusError as e:
        return LLMResult(None, f"api_error {e.status_code}: {str(e)[:300]}", time.perf_counter() - t0, ocr_used=ocr)
    except groq.APIConnectionError as e:
        return LLMResult(None, f"connection_error: {e}", time.perf_counter() - t0, ocr_used=ocr)
    except Exception as e:
        return LLMResult(None, f"{type(e).__name__}: {str(e)[:300]}", time.perf_counter() - t0, ocr_used=ocr)
