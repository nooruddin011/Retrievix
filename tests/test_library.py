import os

import pytest

from ahsr.errors import BadRequest, NotFound, PayloadTooLarge
from ahsr.ingestion.library import DocumentLibrary, normalize_doc_path


@pytest.mark.parametrize("bad", [
    "", "   ", "../secret.md", "a/../../b.md", "/etc/passwd.md", "..\\win.md", "a\\b.md", ".hidden.md",
    "dir/.hidden.md", "notes.txt", "notes", "a//b.md", "./a.md", "bad\x00name.md", "x" * 200 + ".md",
    "semi;colon.md", "pipe|name.md", "trailing-dot..md.", "quote'name.md",
])
def test_rejects_unsafe_paths(bad):
    with pytest.raises(BadRequest):
        normalize_doc_path(bad)


@pytest.mark.parametrize("good", ["a.md", "guides/setup.md", "My Notes v2.md", "api-reference_v1.2.md", "dé/ñ.md"])
def test_accepts_reasonable_paths(good):
    assert normalize_doc_path(good) == good


def test_write_read_list_delete_roundtrip(tmp_path):
    lib = DocumentLibrary(tmp_path)
    assert lib.write("guides/setup.md", "# Setup\n\nHello.") is True
    assert lib.write("guides/setup.md", "# Setup\n\nHello again.") is False       # overwrite, not create
    assert lib.read("guides/setup.md").endswith("again.")
    [info] = lib.list()
    assert (info.path, info.title) == ("guides/setup.md", "Setup")
    lib.delete("guides/setup.md")
    assert lib.list() == [] and not (tmp_path / "guides").exists()                # empty folder tidied up
    with pytest.raises(NotFound):
        lib.read("guides/setup.md")


def test_write_leaves_no_temp_files_and_enforces_limits(tmp_path):
    lib = DocumentLibrary(tmp_path, max_bytes=2048, max_docs=2)
    lib.write("a.md", "# A\n\nx")
    assert [p.name for p in tmp_path.iterdir()] == ["a.md"]
    with pytest.raises(PayloadTooLarge):
        lib.write("big.md", "x" * 4096)
    with pytest.raises(BadRequest):
        lib.write("empty.md", "   \n ")
    with pytest.raises(BadRequest):
        lib.write("bin.md", "abc\x00def")
    lib.write("b.md", "# B\n\ny")
    with pytest.raises(BadRequest, match="limited"):                                # third document refused
        lib.write("c.md", "# C\n\nz")
    lib.write("b.md", "# B\n\nupdated")                                             # updating is still fine


def test_symlink_escape_is_blocked(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("top secret")
    root = tmp_path / "docs"
    root.mkdir()
    try:
        os.symlink(outside, root / "link")
    except (OSError, NotImplementedError):
        return                                                                       # platform without symlinks
    lib = DocumentLibrary(root)
    with pytest.raises(BadRequest):
        lib.read("link/secret.md")
    assert lib.paths() == []                                                         # not listed either
