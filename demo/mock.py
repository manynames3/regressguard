"""Scripted fictional features. No evaluation answers enter this module."""

import hashlib
import json


def generate(model, template, text, params, attempt):
    if model.startswith("mock/ticket-classifier"):
        lower = text.lower()
        if any(word in lower for word in ("invoice", "refund", "charge", "factura", "charged")):
            category = "billing"
        elif any(word in lower for word in ("password", "account", "contraseña", "delete my")):
            category = "account"
        elif any(
            word in lower for word in ("outage", "down", "crash", "error", "sign in", "offline")
        ):
            category = "technical"
        else:
            category = "general"
        urgent = any(
            word in lower
            for word in ("everyone", "nobody", "all users", "team", "data loss", "security breach")
        )
        priority = "urgent" if urgent else "normal"
        # Explicit fault-injection models keep failures repeatable across processes.
        if model == "mock/ticket-classifier-tradeoff-base" and "invoice" in lower:
            category = "general"
        critical_fault = model in {
            "mock/ticket-classifier-intermittent",
            "mock/ticket-classifier-tradeoff-candidate",
        }
        if critical_fault and "nobody" in lower and attempt % 3 == 2:
            priority = "normal"
        if "Return JSON only" in template:
            # Stable field-order variation exercises repeated generation without random state.
            seed = hashlib.sha256(f"{text}{template}{params}{attempt}".encode()).digest()[0]
            pairs = [("category", category), ("priority", priority)]
            return json.dumps(dict(pairs if seed % 2 else reversed(pairs)))
        return f"This is a {category} request with {priority} priority."
    if model.startswith("mock/summarizer"):
        first = text.split(". ")[0].rstrip(".")
        return first + "." if "Preserve the facts" in template else "Everything is fine."
    raise ValueError(f"Unknown mock model: {model}")
