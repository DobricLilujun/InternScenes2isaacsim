"""VLM annotation layer for the InternScenes scene graph.

The scene graph needs a *functional / affordance / interactive* layer that
cannot be derived from geometry alone (e.g. "the door handle can be opened",
"the cabinet has a pull-out drawer").  This layer is produced by a VLM
(OpenAI-compatible ``Qwen3.8-27B-NVFP4`` served via Inferact) over the
multi-view render of each scene, then *consistency-checked* and merged into the
graph.

The VLM backend is fully configurable (endpoint / model / prompt / temperature)
and degrades gracefully: when no endpoint is configured (or the call fails),
the module falls back to a deterministic, rule-based affordance/interactive
derivation so the pipeline never blocks.  The resulting manifest records which
mode was used and the full provenance.

Outputs
-------
``annotate(...)`` returns::

    {
      "relations": [Edge-like dicts, family="functional"],
      "interactive": [interactive part node dicts],
      "manifest": {backend, model_id, mode, prompt_template, temperature,
                   n_calls, n_images, per_object: {...}, ...}
    }
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

logger = logging.getLogger(__name__)

DEFAULT_PROMPT = (
    "You are annotating an indoor scene. For the object of category "
    "\"{category}\" shown in these images, list the affordances and "
    "interactive parts it has. Respond ONLY with JSON of the form "
    "{{\"affordances\": [\"open\", ...], "
    "\"interactive_parts\": [{{\"name\": \"handle\", \"category\": "
    "\"interactive\", \"affordance\": \"open\"}}, ...]}}. "
    "Only use parts/affordances that are plausible for this object and "
    "visible in the images."
)


# ---------------------------------------------------------------------------
# configuration
# ---------------------------------------------------------------------------
@dataclass
class VLMConfig:
    """Configuration for the VLM annotation backend."""

    endpoint: str | None = None          # base URL of an OpenAI-compatible API
    model_id: str = "Qwen3.8-27B-NVFP4"
    temperature: float = 0.2
    max_tokens: int = 512
    request_timeout: str = "300"
    max_images: int = 12
    prompt_template: str = DEFAULT_PROMPT
    # if True, fall back to deterministic rules when the endpoint is unset/failed
    allow_fallback: bool = True

    @classmethod
    def from_env(cls) -> "VLMConfig":
        ep = os.environ.get("INTERNSCENES_VLM_ENDPOINT")
        mid = os.environ.get("INTERNSCENES_VLM_MODEL_ID", cls.model_id)
        temp = os.environ.get("INTERNSCENES_VLM_TEMPERATURE", "0.2")
        try:
            temperature = float(temp)
        except ValueError:
            temperature = 0.2
        return cls(endpoint=ep, model_id=mid, temperature=temperature)

    @classmethod
    def from_json(cls, path: str | None) -> "VLMConfig":
        if not path or not os.path.exists(path):
            return cls.from_env()
        try:
            cfg = json.load(open(path, encoding="utf-8"))
        except Exception:
            return cls.from_env()
        return cls(
            endpoint=cfg.get("endpoint"),
            model_id=cfg.get("model_id", cls.model_id),
            temperature=float(cfg.get("temperature", 0.2)),
            max_tokens=int(cfg.get("max_tokens", 512)),
            request_timeout=str(cfg.get("request_timeout", "300")),
            max_images=int(cfg.get("max_images", 12)),
            prompt_template=cfg.get("prompt_template", DEFAULT_PROMPT),
            allow_fallback=bool(cfg.get("allow_fallback", True)),
        )

    def __hash__(self) -> int:  # for manifest idempotency
        return hash(json.dumps(self._fingerprint(), sort_keys=True))

    def _fingerprint(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "model_id": self.model_id,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "prompt_template": self.prompt_template,
        }


# ---------------------------------------------------------------------------
# deterministic fallback (rule-based affordances / interactive parts)
# ---------------------------------------------------------------------------
# category -> affordances
AFFORDANCES_BY_CATEGORY: dict[str, list[str]] = {
    "door": ["open", "close", "pass_through"],
    "window": ["open", "close"],
    "cabinet": ["open", "close", "store"],
    "wardrobe": ["open", "close", "store"],
    "drawer": ["open", "close", "store"],
    "fridge": ["open", "close", "store", "cool"],
    "oven": ["open", "close", "cook"],
    "stove": ["cook", "turn"],
    "sink": ["wash", "drain"],
    "bathtub": ["wash", "bathe"],
    "toilet": ["use"],
    "chair": ["sit", "store"],
    "sofa": ["sit", "lie_down"],
    "bed": ["sleep", "sit"],
    "table": ["place", "sit"],
    "desk": ["place", "work", "sit"],
    "nightstand": ["store", "place"],
    "shelf": ["store", "display"],
    "counter": ["place", "prepare"],
    "bench": ["sit"],
    "lamp": ["light", "turn"],
    "light": ["light", "turn"],
    "television": ["view", "control"],
    "monitor": ["view", "control"],
    "phone": ["call", "press"],
    "remote": ["control", "press"],
    "speaker": ["play"],
    "radio": ["play"],
    "clock": ["view"],
    "plant": ["water"],
    "cup": ["drink", "hold"],
    "mug": ["drink", "hold"],
    "bottle": ["drink", "pour"],
    "vase": ["hold", "display"],
    "book": ["read", "hold"],
    "box": ["store"],
    "microwave": ["cook", "control"],
    "dishwasher": ["clean", "load"],
    "bathtub": ["bathe"],
}

# category -> (name, interactive category)
INTERACTIVE_BY_CATEGORY: dict[str, list[tuple[str, str]]] = {
    "door": [("handle", "handle"), ("lock", "lock"), ("hinge", "hinge")],
    "window": [("handle", "handle")],
    "cabinet": [("handle", "handle"), ("shelf", "structure")],
    "wardrobe": [("handle", "handle")],
    "drawer": [("handle", "handle")],
    "fridge": [("handle", "handle"), ("shelf", "structure")],
    "oven": [("handle", "handle"), ("knob", "control")],
    "stove": [("knob", "control"), ("burner", "control")],
    "sink": [("faucet", "control"), ("drain", "structure")],
    "microwave": [("panel", "control"), ("button", "control")],
    "television": [("remote", "control")],
    "lamp": [("switch", "control"), ("knob", "control")],
    "chair": [("backrest", "structure")],
    "bed": [("headboard", "structure")],
}


def _norm(cat: Any) -> str:
    return str(cat or "object").lower().replace(" ", "_")


def deterministic_affordances(category: str) -> list[str]:
    return AFFORDANCES_BY_CATEGORY.get(_norm(category), [])


def deterministic_interactive(category: str, parent_id: str) -> list[dict[str, Any]]:
    parts: list[dict[str, Any]] = []
    for name, pcat in INTERACTIVE_BY_CATEGORY.get(_norm(category), []):
        parts.append({
            "id": f"{parent_id}_part_{name}",
            "category": _norm(name),
            "parent": parent_id,
            "affordances": deterministic_affordances(name),
            "confidence": 0.5,
        })
    return parts


# ---------------------------------------------------------------------------
# VLM request
# ---------------------------------------------------------------------------
def _image_url(image: str) -> str:
    """Return a VLM-compatible URL, encoding local image files as data URLs."""
    parsed = urlparse(image)
    if parsed.scheme in {"http", "https", "data"}:
        return image
    if parsed.scheme == "file":
        path = Path(url2pathname(unquote(parsed.path)))
    else:
        path = Path(image).expanduser()
    content_type = mimetypes.guess_type(path.name)[0]
    if not content_type or not content_type.startswith("image/"):
        raise ValueError(f"unsupported image type: {path}")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{content_type};base64,{encoded}"


def _call_vlm(cfg: VLMConfig, prompt: str, images: list[str] | None = None) -> Any:
    """Call an OpenAI-compatible chat-completions endpoint.

    Returns the parsed JSON from the assistant message, or ``None`` on failure.
    Uses only the standard library so it has no hard dependency.
    """
    import urllib.request

    if cfg.endpoint is None:
        return None
    messages = [{"role": "user", "content": prompt}]
    if images:
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for img in images[:cfg.max_images]:
            content.append({"type": "image_url", "image_url": {"url": _image_url(img)}})
        messages = [{"role": "user", "content": content}]
    body = json.dumps({
        "model": cfg.model_id,
        "messages": messages,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    url = cfg.endpoint.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": "Bearer " + os.environ.get("INTERNSCENES_VLM_TOKEN", ""),
    })
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.load(resp)
            text = data["choices"][0]["message"]["content"]
            return json.loads(text)
    except Exception as exc:  # noqa: BLE001 - degrade gracefully
        logger.warning("VLM call failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# annotation
# ---------------------------------------------------------------------------
def annotate(
    scene_id: str,
    records: list[dict[str, Any]],
    cfg: VLMConfig | None = None,
    render_views: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Annotate a scene's objects with affordances / interactive parts.

    Uses the VLM when an endpoint is configured; otherwise a deterministic
    rule-based fallback.  Returns ``{"relations", "interactive", "manifest"}``.
    """
    cfg = cfg or VLMConfig.from_env()
    images = list((render_views or {}).values())[:cfg.max_images]

    affordances: dict[str, list[str]] = {}
    interactive: list[dict[str, Any]] = []
    per_object: dict[str, Any] = {}
    n_calls = 0

    mode = "vlm" if cfg.endpoint is not None else "deterministic_fallback"
    for rec in records:
        category = _norm(rec.get("category"))
        parent_id = f"obj_{rec.get('_idx', 0)}"
        try:
            conf = float(rec.get("confidence", 1.0))
        except (TypeError, ValueError):
            conf = 1.0
        if conf <= 0.0:
            continue

        result: Any = None
        if cfg.endpoint is not None:
            prompt = cfg.prompt_template.format(category=category)
            result = _call_vlm(cfg, prompt, images)
            n_calls += 1

        if result is not None and isinstance(result, dict):
            affs = result.get("affordances", [])
            parts = result.get("interactive_parts", [])
        else:
            # deterministic fallback (used for every object if no endpoint, or
            # for a single failed VLM call)
            affs = deterministic_affordances(category)
            parts = deterministic_interactive(category, parent_id)
            mode = "deterministic_fallback" if cfg.endpoint is None else "vlm_with_fallback"

        # affordances are a node attribute (unary); recorded in the map below
        affordances[parent_id] = list(affs)
        for part in parts:
            if not isinstance(part, dict):
                continue
            name = part.get("name")
            if not name:
                pid0 = part.get("id", "")
                name = pid0.split("_part_")[-1] if "_part_" in pid0 else ""
            cat = _norm(part.get("category", "interactive")) or "interactive"
            pid = part.get("id") or f"{parent_id}_part_{name or cat}"
            affs2 = part.get("affordances")
            if not affs2:
                single = part.get("affordance")
                affs2 = [single] if single else deterministic_affordances(name or cat)
            interactive.append({
                "id": pid,
                "category": cat,
                "parent": part.get("parent", parent_id),
                "affordances": affs2,
                "confidence": 0.6 if mode == "vlm" else 0.5,
            })
        per_object[parent_id] = {
            "affordances": affs,
            "parts": [p.get("name") or p.get("id", "")
                       for p in parts if isinstance(p, dict)],
        }

    manifest = {
        "mode": mode,
        "backend": "inferact" if cfg.endpoint is not None else "none",
        "endpoint": cfg.endpoint,
        "model_id": cfg.model_id,
        "temperature": cfg.temperature,
        "prompt_template": cfg.prompt_template,
        "n_calls": n_calls,
        "n_images": len(images),
        "n_objects": len(records),
        "n_affordances": sum(len(v) for v in affordances.values()),
        "n_affordance_nodes": len(affordances),
        "n_interactive": len(interactive),
        "config_fingerprint": hashlib.sha1(
            json.dumps(cfg._fingerprint(), sort_keys=True, default=str)
            .encode()).hexdigest()[:16],
        "scene_id": scene_id,
    }
    return {"affordances": affordances, "interactive": interactive,
            "manifest": manifest}


# ---------------------------------------------------------------------------
# consistency check
# ---------------------------------------------------------------------------
def consistency_check(graph: dict[str, Any]) -> dict[str, Any]:
    """Validate a built scene graph and return a pass/fail + issue report.

    Checks:
      * every edge endpoint references an existing node id;
      * no self-loops (source == target);
      * every edge carries a valid reference_frame;
      * no contradictory above/below pair is present;
      * symmetric near/touching relations are not stored in both directions;
      * the contains relation is acyclic;
      * confidence values are in [0, 1].
    """
    node_ids = {n["id"] for n in graph["nodes"]}
    issues: list[dict[str, Any]] = []
    frames = {"world", "room_canonical", "object_intrinsic"}
    seen: set[tuple[str, str, str]] = set()

    for e in graph["edges"]:
        s, t, p = e.get("source"), e.get("target"), e.get("predicate")
        if s not in node_ids or t not in node_ids:
            issues.append({"type": "dangling_edge", "edge": e})
        if s and t and s == t:
            issues.append({"type": "self_loop", "edge": e})
        if e.get("reference_frame") not in frames:
            issues.append({"type": "bad_reference_frame", "edge": e})
        c = e.get("confidence")
        if c is not None and not (0.0 <= float(c) <= 1.0):
            issues.append({"type": "bad_confidence", "edge": e})
        key = (s, t, p)
        if key in seen:
            issues.append({"type": "duplicate_edge", "edge": e})
        seen.add(key)

    # Above/below are inverses; the same ordered pair cannot satisfy both.
    above_pairs = {(e["source"], e["target"])
                   for e in graph["edges"] if e["predicate"] == "above"}
    below_pairs = {(e["source"], e["target"])
                   for e in graph["edges"] if e["predicate"] == "below"}
    for a, b in above_pairs:
        if (b, a) in above_pairs or (a, b) in below_pairs:
            issues.append({"type": "above_below_inconsistent",
                           "pair": [a, b]})
    for a, b in below_pairs:
        if (a, b) in above_pairs:
            issues.append({"type": "above_below_inconsistent",
                           "pair": [a, b]})

    # Near and touching are symmetric; retain one canonical direction.
    for predicate in ("near", "touching"):
        pairs = {(e["source"], e["target"])
                 for e in graph["edges"] if e["predicate"] == predicate}
        for a, b in pairs:
            if a < b and (b, a) in pairs:
                issues.append({
                    "type": "duplicate_symmetric_relation",
                    "predicate": predicate,
                    "pair": [a, b],
                })

    containment: dict[str, set[str]] = {}
    for edge in graph["edges"]:
        if edge.get("predicate") == "contains":
            containment.setdefault(edge["source"], set()).add(edge["target"])
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            issues.append({"type": "containment_cycle", "node": node_id})
            return
        if node_id in visited:
            return
        visiting.add(node_id)
        for child in containment.get(node_id, set()):
            visit(child)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in containment:
        visit(node_id)

    return {
        "ok": len(issues) == 0,
        "num_issues": len(issues),
        "num_edges": len(graph["edges"]),
        "num_nodes": len(graph["nodes"]),
        "issues": issues[:50],
    }


if __name__ == "__main__":  # pragma: no cover
    import argparse
    from . import scene_info as _si
    from . import scene_graph as _sg

    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description="VLM-annotate a scene graph")
    ap.add_argument("scene")
    ap.add_argument("--layout")
    ap.add_argument("--config", help="JSON VLM config path")
    ap.add_argument("--out")
    args = ap.parse_args()
    root = _sg.Path(__file__).resolve().parents[2]
    layout = args.layout or str(root / "data" / "Layout_info" / args.scene / "layout.json")
    cfg = VLMConfig.from_json(args.config)
    records = _si.load_layout(layout)
    for i, r in enumerate(records):
        r2 = dict(r); r2["_idx"] = i; records[i] = r2
    result = annotate(args.scene, records, cfg)
    g = _sg.build_scene_graph(args.scene, layout, vlm_result=result)
    rep = consistency_check(g)
    print(f"{args.scene}: {g['stats']['num_nodes']} nodes, "
          f"{g['stats']['num_edges']} edges; consistency ok={rep['ok']} "
          f"(issues={rep['num_issues']})")
    out = args.out or str(root / "output" / "graph"
                          / f"{args.scene.replace('/', '_')}.json")
    _sg.write_scene_graph(g, out)
    print("wrote", out)
