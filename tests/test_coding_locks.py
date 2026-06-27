"""LockStore — the out-of-worktree store for the frozen acceptance tests."""

import hashlib

from leanlab.core.coding.locks import LockStore


def _wt(tmp_path, content):
    wt = tmp_path / "wt"
    (wt / "tests").mkdir(parents=True)
    (wt / "tests" / "t.py").write_text(content)
    return wt


def test_write_load_pristine_and_tamper(tmp_path):
    src = "def test_x():\n    assert True\n"
    wt = _wt(tmp_path, src)
    store = LockStore(tmp_path)
    store.write("demo", [{"path": "tests/t.py", "content": src,
                          "sha256": hashlib.sha256(src.encode()).hexdigest()}])
    assert store.load("demo")["tests"][0]["path"] == "tests/t.py"
    assert store.is_pristine("demo", wt) is True
    (wt / "tests" / "t.py").write_text("def test_x():\n    assert False\n")     # tamper
    assert store.is_pristine("demo", wt) is False
    store.restore("demo", wt)                                                   # restore pristine
    assert store.is_pristine("demo", wt) is True


def test_load_missing_is_none(tmp_path):
    assert LockStore(tmp_path).load("nope") is None


def test_pristine_true_when_no_lock(tmp_path):
    assert LockStore(tmp_path).is_pristine("nope", tmp_path) is True
