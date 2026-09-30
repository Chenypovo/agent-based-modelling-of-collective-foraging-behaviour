"""Provider-neutral, mockable Stage 4 proposal contract; no network client."""

from __future__ import annotations

import json
from typing import Protocol

from .stage4_space import Candidate, PARAMETERS

PROPOSAL_FIELDS = PARAMETERS | {"hypothesis", "expected_outcome", "brief_justification"}


class Provider(Protocol):
    def complete(self, prompt: dict) -> str: ...


class MockProvider:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.prompts: list[dict] = []

    def complete(self, prompt: dict) -> str:
        self.prompts.append(json.loads(json.dumps(prompt)))
        if not self.responses:
            raise RuntimeError("mock responses exhausted")
        return self.responses.pop(0)


def parse_proposal(raw: str) -> tuple[Candidate, dict]:
    value = json.loads(raw)
    if not isinstance(value, dict) or set(value) != PROPOSAL_FIELDS:
        raise ValueError("proposal must contain exactly the allowed fields")
    for key in ("hypothesis", "expected_outcome", "brief_justification"):
        if not isinstance(value[key], str) or not value[key].strip():
            raise ValueError(f"invalid {key}")
    candidate = Candidate.parse({key: value[key] for key in PARAMETERS})
    return candidate, {key: value[key] for key in ("hypothesis", "expected_outcome", "brief_justification")}


def propose(provider: Provider, own_history: list[dict]) -> dict:
    """One opportunity, at most one syntax/bounds repair, no new hypothesis."""
    prompt = {"task": "Propose one bounded scalar pheromone candidate as JSON.",
              "allowed_fields": sorted(PROPOSAL_FIELDS), "history": own_history}
    raw = provider.complete(prompt)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and set(parsed) - PROPOSAL_FIELDS:
            return {"valid": False, "error": "forbidden proposal field", "repaired": False, "raw": raw}
    except json.JSONDecodeError:
        pass
    try:
        candidate, text = parse_proposal(raw)
        return {"valid": True, "candidate": candidate, "text": text,
                "repaired": False, "raw": raw}
    except (ValueError, TypeError) as first:
        repair_prompt = {**prompt, "repair_only": True, "error": str(first),
                         "previous_response": raw,
                         "instruction": "Repair JSON, missing fields or bounds only. Keep the same hypothesis."}
        repaired = provider.complete(repair_prompt)
        try:
            candidate, text = parse_proposal(repaired)
            try:
                original = json.loads(raw)
            except json.JSONDecodeError:
                original = None
            if isinstance(original, dict) and isinstance(original.get("hypothesis"), str):
                if text["hypothesis"] != original["hypothesis"]:
                    raise ValueError("repair changed hypothesis")
            return {"valid": True, "candidate": candidate, "text": text,
                    "repaired": True, "raw": raw, "repair_raw": repaired}
        except (ValueError, TypeError) as second:
            return {"valid": False, "error": str(second), "repaired": True,
                    "raw": raw, "repair_raw": repaired}
