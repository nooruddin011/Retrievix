from ahsr.ingestion.chunker import chunk_markdown

DOC = """# Title

## Section A
Intro paragraph.

```python
# not a heading
def f(): pass
```

## Section B
Second section text.
"""


def test_breadcrumbs_and_ids():
    chunks = chunk_markdown(DOC, "x.md")
    assert [c.metadata["section"] for c in chunks] == ["Title > Section A", "Title > Section B"]
    assert len({c.id for c in chunks}) == len(chunks)


def test_code_fence_is_atomic_and_hash_comment_not_heading():
    chunks = chunk_markdown(DOC, "x.md", max_chars=30)
    code = [c for c in chunks if "def f()" in c.text]
    assert len(code) == 1 and "# not a heading" in code[0].text


def test_ids_are_stable_for_unchanged_text_and_change_with_content():
    a = chunk_markdown(DOC, "x.md")
    b = chunk_markdown(DOC, "x.md")
    c = chunk_markdown(DOC.replace("Second section text", "Different text"), "x.md")
    assert [x.id for x in a] == [x.id for x in b]
    assert a[0].id == c[0].id and a[1].id != c[1].id          # only the edited section gets a new id


def test_overlong_paragraph_is_split_but_code_is_not():
    prose = " ".join(f"Sentence number {i} explains something useful." for i in range(80))
    code = "```python\n" + "\n".join(f"x{i} = {i}" for i in range(200)) + "\n```"
    chunks = chunk_markdown(f"# T\n\n## S\n{prose}\n\n{code}\n", "x.md", max_chars=400)
    assert len(chunks) > 3
    assert all(len(c.text) < 1000 for c in chunks if "```" not in c.text)
    assert sum("```python" in c.text for c in chunks) == 1 and any("x199 = 199" in c.text for c in chunks)
