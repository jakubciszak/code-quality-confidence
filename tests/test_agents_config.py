"""Structural contracts for the lens subagents and interactive skills.

These encode spec guarantees that are otherwise only prose: review lenses and
the pair/intent agents are read-only (they physically cannot write code);
models are assigned per role; the consciously-invoked skills disable
model-invocation.
"""

from pathlib import Path

AGENTS = Path(__file__).resolve().parents[1] / "plugins" / "swiss-cheese" / "agents"
SKILLS = Path(__file__).resolve().parents[1] / "plugins" / "swiss-cheese" / "skills"


def frontmatter(path):
    text = path.read_text()
    assert text.startswith("---"), f"{path} missing frontmatter"
    _, fm, _ = text.split("---", 2)
    out = {}
    for line in fm.strip().splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


READ_ONLY = {"Read", "Grep", "Glob"}
LENSES = ["review-core", "review-security", "review-tests", "review-performance",
          "review-architecture", "review-docs", "review-staff"]
NO_WRITE_AGENTS = LENSES + ["pair-agent", "intent-agent"]


def test_lens_and_helper_agents_are_read_only():
    for name in NO_WRITE_AGENTS:
        fm = frontmatter(AGENTS / f"{name}.md")
        tools = {t.strip() for t in fm.get("tools", "").split(",") if t.strip()}
        assert tools == READ_ONLY, f"{name} tools={tools} — must be exactly Read,Grep,Glob"
        assert "Write" not in tools and "Edit" not in tools


def test_all_expected_lenses_exist():
    for name in LENSES:
        assert (AGENTS / f"{name}.md").exists(), f"missing lens {name}"


def test_staff_uses_opus_docs_uses_haiku_others_sonnet():
    assert frontmatter(AGENTS / "review-staff.md")["model"] == "opus"
    assert frontmatter(AGENTS / "review-docs.md")["model"] == "haiku"
    for name in ["review-core", "review-security", "review-tests",
                 "review-performance", "review-architecture"]:
        assert frontmatter(AGENTS / f"{name}.md")["model"] == "sonnet"


def test_intent_agent_is_haiku_pair_agent_is_sonnet():
    assert frontmatter(AGENTS / "intent-agent.md")["model"] == "haiku"
    assert frontmatter(AGENTS / "pair-agent.md")["model"] == "sonnet"


def test_conscious_skills_disable_model_invocation():
    for name in ["intent", "pair", "init", "layer", "status", "knowledge", "audit"]:
        fm = frontmatter(SKILLS / name / "SKILL.md")
        assert fm.get("disable-model-invocation") == "true", \
            f"{name} skill must set disable-model-invocation: true"


def test_review_and_loop_skills_are_model_invocable():
    # These are the natural-language entry points; they stay auto-invocable.
    for name in ["review", "loop"]:
        fm = frontmatter(SKILLS / name / "SKILL.md")
        assert fm.get("disable-model-invocation") != "true"


def test_no_legacy_commands_dir():
    commands = Path(__file__).resolve().parents[1] / "plugins" / "swiss-cheese" / "commands"
    assert not commands.exists(), "legacy commands/ dir must be gone (skills only)"


def test_finding_format_has_verification_field():
    # Every lens declares the five-field FINDING format incl. `verification`.
    for name in LENSES:
        body = (AGENTS / f"{name}.md").read_text()
        assert "verification" in body, f"{name} must document the verification field"
