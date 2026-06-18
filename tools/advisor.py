"""Tone Advisor — optional LLM specialist for tone design decisions.

Calls AWS Bedrock (Converse API) with a focused sound engineering persona
to generate parameter change suggestions. The advisor only suggests —
execution is left to the orchestrating agent (Kiro) or user.

Activated via TONE_ADVISOR_ENABLED=on environment variable.
Requires AWS credentials configured via default boto3 chain
(env vars, ~/.aws/credentials, IAM role, etc.).

Uses Converse API for model portability — switching models is a single
env var change. Supports extended thinking for prompt tuning visibility.
"""

import json
import os
from typing import Any

# --- Configuration ---

ADVISOR_ENABLED = os.environ.get("TONE_ADVISOR_ENABLED", "off").lower() == "on"
ADVISOR_MAX_TOKENS = int(os.environ.get("TONE_ADVISOR_MAX_TOKENS", "2048"))
ADVISOR_THINKING_BUDGET = int(os.environ.get("TONE_ADVISOR_THINKING_BUDGET", "4096"))

# --- Model Abstraction ---

# Friendly name → Bedrock inference profile ID.
# Users can set TONE_ADVISOR_MODEL to either a friendly name or a full profile ID.
# Using global CRIS profiles (work from any source region).
MODEL_PRESETS: dict[str, str] = {
    "sonnet-4.6": "global.anthropic.claude-sonnet-4-6",
    "sonnet-4.5": "global.anthropic.claude-sonnet-4-5-20250929-v1:0",
    "haiku-4.5": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "opus-4.8": "us.anthropic.claude-opus-4-8",
    "opus-4.7": "us.anthropic.claude-opus-4-7",
}

DEFAULT_MODEL = "sonnet-4.6"

_model_env = os.environ.get("TONE_ADVISOR_MODEL", DEFAULT_MODEL)
ADVISOR_MODEL = MODEL_PRESETS.get(_model_env, _model_env)  # Resolve friendly name or use raw ID


def _resolve_model(model: str | None) -> str:
    """Resolve a model name (friendly or full ID) to a Bedrock model ID."""
    if model is None:
        return ADVISOR_MODEL
    return MODEL_PRESETS.get(model, model)


# --- System Prompt (focused sound engineering persona) ---

SYSTEM_PROMPT = """\
You are a dedicated sound engineer for Fractal Audio FM9. Your sole job is to \
translate a musician's tonal intent into specific, actionable parameter changes.

## Your Expertise
- Amp circuit topology and gain structure (preamp vs power amp saturation)
- Speaker cabinet / microphone interaction (proximity, angle, frequency response)
- Drive pedal stacking and gain staging
- EQ sculpting (pre-drive vs post-cab, surgical vs broad)
- Spatial effects (delay, reverb, modulation) and their interaction with gain
- Mix engineering perspective (how guitar sits in a band context)

## Your Constraints
- You ONLY output parameter change suggestions. You do NOT execute them.
- Base your suggestions on the current state provided. Don't assume defaults.
- When uncertain, say so. Never hallucinate parameter names or ranges.
- Prefer minimal, targeted changes over wholesale rewrites.
- Explain WHY each change achieves the stated goal (1 sentence per param).

## Output Format
Respond in JSON with this structure:
```json
{
  "reasoning": "Brief analysis of current state vs target (2-3 sentences max)",
  "suggestions": [
    {
      "block": "Amp 1",
      "param": "Gain",
      "current": 6.5,
      "suggested": 5.0,
      "why": "Reduce preamp saturation to clean up pick attack"
    }
  ],
  "confidence": "high|medium|low",
  "notes": "Optional: anything the musician should know (e.g., try this with neck pickup)"
}
```

## Parameter Ranges (for reference)
- Amp: Gain/Bass/Mid/Treble/Master/Depth/Presence (0-10), Level (-80 to +20 dB)
- Drive: Drive/Tone/Level (0-10), Mix (0-100%)
- PEQ: Freq (20-20000 Hz), Gain (-20 to +20 dB), Q (0.1-10)
- Delay: Time (0-2000ms), Feedback (0-100%), Mix (0-100%)
- Reverb: Decay (0.1-60s), Mix (0-100%), Level (-80 to +20 dB)

## Rules
- Prioritize changes that preserve the player's feel (dynamics, touch sensitivity)
- "Less is more" — the best sound engineers make 2-3 precise moves, not 15 random ones
- Consider the interaction between blocks (e.g., Drive into Amp gain staging)
- If the request is vague, suggest the single most impactful change first
"""

# --- Bedrock Client (lazy-loaded) ---

_bedrock_client = None


def _get_bedrock_client():
    """Lazy-load the Bedrock runtime client.

    Uses default boto3 credential chain — no explicit region or profile.
    Configure via standard AWS mechanisms:
      - AWS_DEFAULT_REGION / AWS_REGION env var
      - ~/.aws/config [default] region
      - AWS_PROFILE env var for named profiles
    """
    global _bedrock_client
    if _bedrock_client is None:
        import boto3
        _bedrock_client = boto3.client("bedrock-runtime")
    return _bedrock_client


def _call_advisor(
    user_message: str,
    model: str,
    thinking: bool = False,
) -> dict[str, Any]:
    """Call Bedrock Converse API with the advisor persona.

    Args:
        user_message: The constructed user prompt.
        model: Bedrock model ID (resolved).
        thinking: If True, enable extended thinking (budget controlled by env var).

    Returns:
        Dict with success, advice (parsed JSON), raw text, and optionally thinking.
    """
    client = _get_bedrock_client()

    # Build request kwargs
    kwargs: dict[str, Any] = {
        "modelId": model,
        "messages": [
            {
                "role": "user",
                "content": [{"text": user_message}],
            }
        ],
        "system": [{"text": SYSTEM_PROMPT}],
        "inferenceConfig": {
            "maxTokens": ADVISOR_MAX_TOKENS,
        },
    }

    # Thinking mode: enable extended thinking, temperature must be 1
    if thinking:
        kwargs["additionalModelRequestFields"] = {
            "thinking": {
                "type": "enabled",
                "budget_tokens": ADVISOR_THINKING_BUDGET,
            }
        }
        # Claude requires temperature=1 when thinking is enabled
        kwargs["inferenceConfig"]["temperature"] = 1.0
        # max_tokens must be > budget_tokens (total includes thinking + response)
        kwargs["inferenceConfig"]["maxTokens"] = ADVISOR_THINKING_BUDGET + ADVISOR_MAX_TOKENS
    else:
        # Normal mode: low temperature for precise parameter suggestions
        kwargs["inferenceConfig"]["temperature"] = 0.3

    # Call Converse API
    response = client.converse(**kwargs)

    # Parse response content blocks
    content_blocks = response["output"]["message"]["content"]
    assistant_text = ""
    thinking_text = ""

    for block in content_blocks:
        if "text" in block:
            assistant_text += block["text"]
        elif "reasoningContent" in block:
            # Extended thinking output
            reasoning = block["reasoningContent"]
            if "reasoningText" in reasoning:
                thinking_text += reasoning["reasoningText"]["text"]

    # Extract usage info
    usage = response.get("usage", {})

    # Try to parse JSON from the assistant response
    advice = None
    try:
        text = assistant_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]  # Remove opening ```json
            text = text.rsplit("```", 1)[0]  # Remove closing ```
        advice = json.loads(text)
    except (json.JSONDecodeError, IndexError):
        pass  # Return raw text below

    result: dict[str, Any] = {
        "success": True,
        "advice": advice,
        "raw": assistant_text,
        "usage": {
            "input_tokens": usage.get("inputTokens", 0),
            "output_tokens": usage.get("outputTokens", 0),
        },
    }

    if thinking and thinking_text:
        result["thinking"] = thinking_text

    return result


def _build_user_message(
    target: str,
    current_state: dict[str, Any] | None = None,
    context: str = "",
) -> str:
    """Build the user message for the advisor LLM."""
    parts = []

    if current_state:
        parts.append("## Current Device State")
        parts.append(json.dumps(current_state, indent=2))

    if context:
        parts.append(f"## Additional Context\n{context}")

    parts.append(f"## Request\n{target}")

    return "\n\n".join(parts)


# --- MCP Tool Registration ---


def register(mcp):
    """Register tone advisor tools on the MCP server."""

    if ADVISOR_ENABLED:
        print(f"[Advisor] Enabled. Model: {ADVISOR_MODEL}", flush=True)
    else:
        print("[Advisor] Disabled. Set TONE_ADVISOR_ENABLED=on to activate.", flush=True)

    @mcp.tool()
    def fm9_tone_advisor(
        target: str,
        current_state: dict[str, Any] | None = None,
        context: str = "",
        mode: str = "advise",
        thinking: bool = False,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Get tone parameter suggestions from a specialist AI sound engineer.

        This tool delegates tone decisions to a focused LLM with a dedicated
        sound engineering persona. It only suggests parameter changes — it does
        not execute them. Use the regular fm9_set_* tools to apply suggestions.

        Optional. Disabled by default. Enable via TONE_ADVISOR_ENABLED=on env var.

        Args:
            target: What the musician wants (e.g., "too harsh, needs warmth"
                    or "SRV Little Wing clean tone" or "tighter low end for palm mutes").
            current_state: Optional dict of current block parameters. If omitted,
                          the advisor works from the target description alone.
                          Recommended: pass output of fm9_get_amp_params / fm9_get_block_params.
            context: Optional additional context (genre, guitar type, pickup position,
                     reference song, etc.).
            mode: "advise" = call Bedrock and return suggestions (costs API tokens).
                  "dry" = return the constructed prompt without calling Bedrock ($0).
            thinking: If True, enable extended thinking (shows reasoning chain).
                      Useful for prompt tuning and understanding advisor decisions.
                      Temperature is forced to 1.0 when thinking is enabled.
            model: Override model for this call. Accepts friendly names
                   ("sonnet-4", "sonnet-4.5", "haiku-4", "opus-4") or full Bedrock model IDs.
                   If omitted, uses TONE_ADVISOR_MODEL env var (default: sonnet-4).

        Returns:
            - mode="advise": Parameter change suggestions with reasoning (and thinking if enabled)
            - mode="dry": The full prompt that would be sent (for debugging/A-B testing)
            - If TONE_ADVISOR_ENABLED is off: error with instructions to enable
        """
        # Gate: disabled
        if not ADVISOR_ENABLED and mode != "dry":
            return {
                "success": False,
                "error": "Tone Advisor is disabled. Set TONE_ADVISOR_ENABLED=on in MCP server environment.",
                "hint": "You can still use mode='dry' to preview the prompt without calling Bedrock.",
            }

        # Resolve model
        resolved_model = _resolve_model(model)

        # Build the user message
        user_message = _build_user_message(target, current_state, context)

        # Dry mode: return prompt without calling Bedrock
        if mode == "dry":
            return {
                "success": True,
                "mode": "dry",
                "system_prompt": SYSTEM_PROMPT,
                "user_message": user_message,
                "model": resolved_model,
                "thinking": thinking,
                "available_models": MODEL_PRESETS,
                "note": "This is what would be sent to Bedrock. No API call was made.",
            }

        # Advise mode: call Bedrock
        if mode == "advise":
            try:
                result = _call_advisor(user_message, resolved_model, thinking=thinking)
                result["mode"] = "advise"
                result["model"] = resolved_model
                return result
            except Exception as e:
                return {
                    "success": False,
                    "mode": "advise",
                    "error": str(e),
                    "model": resolved_model,
                    "hint": "Check AWS credentials and Bedrock model access. Try mode='dry' to verify prompt.",
                }

        return {
            "success": False,
            "error": f"Unknown mode '{mode}'. Use 'advise' or 'dry'.",
        }
