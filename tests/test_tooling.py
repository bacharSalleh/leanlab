"""Checkpoint B — leanlab-as-a-tool: .leanlab/ resolution, spec injection, init scope."""

from leanlab import cli
from leanlab.core.loop import Lab, Prompts, WORKER_ACTION


def test_labs_dir_is_cwd_dotleanlab(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.labs_dir() == tmp_path / ".leanlab"


def test_worker_prompt_injects_spec_and_names_role(tmp_path):
    (tmp_path / "results.jsonl").write_text("")
    cfg = {"objective": {"metric": "rmse", "direction": "min"}, "results_file": "results.jsonl"}
    p = Prompts(Lab(tmp_path, cfg)).worker()
    assert p.splitlines()[0].lower().startswith("you are the worker")
    # the spec (CLAUDE.md, shipped in the package) is injected, not just the action text
    assert len(p) > len(WORKER_ACTION) + 100


def test_director_and_critic_prompts_inject_specs():
    d, c = Prompts.director(), Prompts.critic()
    assert d.splitlines()[0].lower().startswith("you are the director")
    assert c.splitlines()[0].lower().startswith("you are the critic")
    assert "Director_Notes.md" in d
    assert "Critic_Feedback.md" in c
