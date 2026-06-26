"""Checkpoint B — leanlab-as-a-tool: .leanlab/ resolution, spec injection, init scope."""

from leanlab import cli
from leanlab.core import loop


def test_labs_dir_is_cwd_dotleanlab(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.labs_dir() == tmp_path / ".leanlab"


def test_worker_prompt_injects_spec_and_names_role(tmp_path):
    (tmp_path / "results.jsonl").write_text("")
    cfg = {"objective": {"metric": "rmse", "direction": "min"}, "results_file": "results.jsonl"}
    p = loop.build_worker_prompt(tmp_path, cfg)
    assert p.splitlines()[0].lower().startswith("you are the worker")
    # the spec (CLAUDE.md, shipped in the package) is injected, not just the action text
    assert len(p) > len(loop.WORKER_ACTION) + 100


def test_director_and_critic_prompts_inject_specs():
    d, c = loop.build_director_prompt(), loop.build_critic_prompt()
    assert d.splitlines()[0].lower().startswith("you are the director")
    assert c.splitlines()[0].lower().startswith("you are the critic")
    assert "Director_Notes.md" in d
    assert "Critic_Feedback.md" in c


def test_install_agent_skill(tmp_path):
    from leanlab import cli
    dest = cli._install_agent_skill(tmp_path)
    assert dest == tmp_path / ".claude" / "skills" / "leanlab" / "SKILL.md"
    text = dest.read_text()
    assert text.startswith("---")                       # skill frontmatter
    assert "name: leanlab" in text
    assert "leanlab spec" in text and "leanlab build" in text
    assert "--yes" in text                              # the headless flag must be documented


def test_for_agent_appends_to_claude_md(tmp_path):
    from leanlab import cli
    (tmp_path / "CLAUDE.md").write_text("# My project\n\nexisting rules\n")
    assert cli._append_claude_md(tmp_path) is True
    text = (tmp_path / "CLAUDE.md").read_text()
    assert "existing rules" in text                     # appended, not overwritten
    assert "use leanlab" in text.lower()
    assert cli._append_claude_md(tmp_path) is False      # idempotent
    assert text.count(cli._CLAUDE_MD_MARKER.split()[0]) <= 4  # marker not duplicated


def test_for_agent_creates_claude_md_when_missing(tmp_path):
    from leanlab import cli
    assert cli._append_claude_md(tmp_path) is True
    assert (tmp_path / "CLAUDE.md").exists()
    assert "leanlab" in (tmp_path / "CLAUDE.md").read_text()
