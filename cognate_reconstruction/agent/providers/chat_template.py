"""Decide from a model's chat template whether its reasoning must be resent.

R03 §17a: Gemma 4's template renders a whole tool loop as one model turn and
adds nothing after a tool result, so the model continues the turn as it sees
it; with its earlier reasoning dropped, that is a run of thoughtless calls, and
it stops thinking. Qwen3.6's template opens a new assistant turn with `<think>`
after every tool result, so it thinks whatever history it receives. Two
properties of a template separate these cases, and both can be read off by
rendering a short synthetic tool loop:

- does an earlier assistant step's `reasoning_content` reach the prompt?
- does the generation prompt after a tool result open a new turn?

Resending is needed only when the answer is yes and no. A template that ignores
the field makes resending a waste; one that opens a new turn makes it optional,
and it stays off there unless asked for, because it costs context.

Rendering follows Hugging Face's chat-template conventions. LM Studio renders
with its own Jinja implementation, so whether the server really passes the
field through is checked separately by `probe_reasoning_consumption`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

MARKER = "reasoning-history-probe-7f3a"
_TOOL = {"type": "function", "function": {
    "name": "lookup", "description": "Look something up.",
    "parameters": {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}}}


class TemplateAnalysisError(ValueError):
    """The template could not be located or read unambiguously."""


@dataclass(frozen=True)
class TemplateAnalysis:
    consumes_reasoning: bool
    new_turn_after_tool: bool

    @property
    def mode(self) -> str:
        return "keep" if self.consumes_reasoning and not self.new_turn_after_tool else "drop"

    @property
    def reason(self) -> str:
        if not self.consumes_reasoning:
            return "the template ignores resent reasoning"
        if self.new_turn_after_tool:
            return "the template opens a new turn after a tool result"
        return "the template continues one model turn through tool results and renders resent reasoning"


def _environment():
    import jinja2
    import jinja2.ext
    from jinja2.sandbox import ImmutableSandboxedEnvironment

    def raise_exception(message):
        raise jinja2.exceptions.TemplateError(message)

    def tojson(value, ensure_ascii=False, indent=None, separators=None, sort_keys=False):
        return json.dumps(value, ensure_ascii=ensure_ascii, indent=indent, separators=separators, sort_keys=sort_keys)

    env = ImmutableSandboxedEnvironment(trim_blocks=True, lstrip_blocks=True,
                                        extensions=[jinja2.ext.loopcontrols])
    env.filters["tojson"] = tojson
    env.globals["raise_exception"] = raise_exception
    env.globals["strftime_now"] = lambda fmt: datetime.now().strftime(fmt)
    return env


def _conversation(reasoning: str | None) -> list[dict[str, Any]]:
    step = {"role": "assistant", "content": "", "tool_calls": [{
        "id": "call_1", "type": "function", "function": {"name": "lookup", "arguments": {"q": "survey"}}}]}
    if reasoning is not None:
        step["reasoning_content"] = reasoning
    return [{"role": "system", "content": "You are terse."},
            {"role": "user", "content": "Find the survey."},
            step,
            {"role": "tool", "tool_call_id": "call_1", "name": "lookup", "content": "{\"ok\": true}"}]


def analyze_template(template: str, variables: Mapping[str, Any] | None = None) -> TemplateAnalysis:
    """Render a one-step tool loop and read off the two properties."""
    import jinja2

    env = _environment()
    context = {"bos_token": "", "eos_token": "", "tools": [_TOOL], **(variables or {})}
    try:
        compiled = env.from_string(template)
        with_marker = compiled.render(messages=_conversation(MARKER), add_generation_prompt=False, **context)
        base = compiled.render(messages=_conversation(None), add_generation_prompt=False, **context)
        prompted = compiled.render(messages=_conversation(None), add_generation_prompt=True, **context)
    except jinja2.TemplateError as error:
        raise TemplateAnalysisError(f"the chat template does not render a tool loop: {error}") from error
    if not prompted.startswith(base):
        raise TemplateAnalysisError("the generation prompt is not a suffix of the rendered conversation")
    return TemplateAnalysis(consumes_reasoning=MARKER in with_marker,
                            new_turn_after_tool=bool(prompted[len(base):].strip()))


def template_from_directory(directory: Path) -> tuple[str, str]:
    """The chat template a Hugging Face–style model folder ships, and its file name."""
    standalone = directory / "chat_template.jinja"
    if standalone.is_file():
        return standalone.read_text(), standalone.name
    config = directory / "tokenizer_config.json"
    if config.is_file():
        template = json.loads(config.read_text()).get("chat_template")
        if isinstance(template, list):  # named templates; "default" is the chat one
            template = next((item.get("template") for item in template if item.get("name") == "default"), None)
        if isinstance(template, str) and template:
            return template, config.name
    raise TemplateAnalysisError(f"no chat template in {directory} (GGUF models embed it; pass --chat-template)")


@dataclass(frozen=True)
class LocatedTemplate:
    text: str
    source: str  # relative to the models folder: no machine-specific path in the digest
    variables: dict[str, Any]


def locate_lm_studio_template(model_id: str, *, home: Path | None = None,
                              run: Callable[[list[str]], str] | None = None) -> LocatedTemplate:
    """Find the template LM Studio loaded for `model_id` on this machine.

    `lms ps --json` names each loaded model's folder, or a hub model's ID; a hub
    model is resolved through its model.yaml to the one downloaded variant with
    the loaded quantization. Jinja variables the hub sets by default (Gemma's
    `enable_thinking`) are applied. A per-model prompt-template override is
    refused rather than guessed at.
    """
    import yaml

    root = (home or Path.home()) / ".lmstudio"
    if run is None:
        executable = shutil.which("lms") or str(root / "bin" / "lms")
        run = lambda argv: subprocess.run([executable, *argv], capture_output=True, text=True,  # noqa: E731
                                          check=True, timeout=30).stdout
    try:
        loaded = json.loads(run(["ps", "--json"]))
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise TemplateAnalysisError(f"could not list LM Studio's loaded models: {error}") from error
    entry = next((item for item in loaded if model_id in (item.get("identifier"), item.get("modelKey"))), None)
    if entry is None:
        raise TemplateAnalysisError(f"{model_id!r} is not loaded in LM Studio")
    settings = root / "settings.json"
    models = Path(json.loads(settings.read_text()).get("downloadsFolder") or root / "models") \
        if settings.is_file() else root / "models"
    relative, variables = entry["path"], {}
    if not (models / relative).is_dir():
        manifest = root / "hub" / "models" / relative / "model.yaml"
        if not manifest.is_file():
            raise TemplateAnalysisError(f"no folder or hub model.yaml for {relative!r}")
        spec = yaml.safe_load(manifest.read_text())
        downloaded = {f"{user.name}/{repo.name}".lower(): f"{user.name}/{repo.name}"
                      for user in models.iterdir() if user.is_dir() for repo in user.iterdir() if repo.is_dir()}
        candidates = [downloaded[base["key"].lower()] for base in spec.get("base", ()) if base["key"].lower() in downloaded]
        quantization = ((entry.get("quantization") or {}).get("name") or "").lower()
        if len(candidates) > 1 and quantization:
            candidates = [c for c in candidates if c.lower().endswith(quantization)]
        if len(candidates) != 1:
            raise TemplateAnalysisError(f"hub model {relative!r} resolves to {candidates or 'no'} downloaded variant(s)")
        relative = candidates[0]
        for field in spec.get("customFields", ()):
            for effect in field.get("effects", ()):
                if effect.get("type") == "setJinjaVariable":
                    variables[effect["variable"]] = field.get("defaultValue")
    override = root / ".internal" / "user-concrete-model-default-config" / f"{relative}.json"
    if override.is_file() and "promptTemplate" in override.read_text():
        raise TemplateAnalysisError(f"LM Studio overrides the prompt template of {relative!r}; pass --chat-template")
    text, name = template_from_directory(models / relative)
    return LocatedTemplate(text=text, source=f"{relative}/{name}", variables=variables)


def probe_reasoning_consumption(api_base: str, api_key: str | None, model: str, *, timeout: float = 120,
                                post: Callable[[dict[str, Any]], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Does the server render a resent `reasoning_content`? Two one-token requests."""
    if post is None:
        def post(body):
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            request = Request(f"{api_base.rstrip('/')}/chat/completions", json.dumps(body).encode(), headers)
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                return json.load(response)
    counts = []
    for reasoning in (None, f"{MARKER} " * 40):
        body = {"model": model, "messages": _conversation(reasoning), "tools": [_TOOL],
                "max_tokens": 1, "temperature": 0}
        for message in body["messages"]:  # the wire form carries arguments as a JSON string
            for call in message.get("tool_calls", ()):
                call["function"]["arguments"] = json.dumps(call["function"]["arguments"])
        counts.append(int(post(body)["usage"]["prompt_tokens"]))
    return {"prompt_tokens_without": counts[0], "prompt_tokens_with": counts[1], "consumed": counts[1] > counts[0]}
