"""xhtml: Confluence storage and plain HTML read as Markdown, never dropping a Confluence element silently."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from amanuense import i18n, xhtml  # noqa: E402
from amanuense import taller as docs_kit  # noqa: E402


def _md(storage: str) -> str:
    return xhtml.storage_to_markdown(storage, "Fare Engine")


def test_headings_paragraphs_lists_and_inline_marks():
    md = _md("<h2>Scope</h2><p>Computes the <strong>fare</strong> of a <em>journey</em> with <code>zones</code>.</p>"
             "<ul><li>One</li><li>Two<ul><li>Two and a half</li></ul></li></ul><ol><li>First</li></ol>"
             "<p>See <a href=\"https://example.org/x\">the guide</a>.</p><hr/>")
    assert md.startswith("# Fare Engine\n\n## Scope\n\n")
    assert "Computes the **fare** of a *journey* with `zones`." in md
    assert "- One\n- Two\n  - Two and a half" in md
    assert "1. First" in md
    assert "[the guide](https://example.org/x)" in md
    assert "---" in md


def test_tables_become_markdown_tables_with_cells_kept_apart():
    md = _md("<table><tbody><tr><th>Name</th><th>Port</th></tr>"
             "<tr><td><p>api</p><p>public</p></td><td>8080 | 8443</td></tr></tbody></table>")
    assert "| Name | Port |" in md and "| --- | --- |" in md
    assert "| api<br>public | 8080 \\| 8443 |" in md


def test_code_macro_becomes_a_fenced_block_with_its_cdata():
    md = _md('<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">python</ac:parameter>'
             '<ac:plain-text-body><![CDATA[if a < b:\n    print("x")]]></ac:plain-text-body></ac:structured-macro>')
    assert "```python\nif a < b:\n    print(\"x\")\n```" in md
    assert "⟦" not in md  # a code block goes back as a code macro: nothing is lost


def test_confluence_only_elements_leave_a_visible_marker():
    i18n.use("en")
    md = _md('<p>Before.</p>'
             '<ac:structured-macro ac:name="jira"><ac:parameter ac:name="key">FARE-12</ac:parameter></ac:structured-macro>'
             '<ac:structured-macro ac:name="info"><ac:rich-text-body><p>Read this first.</p></ac:rich-text-body>'
             '</ac:structured-macro>'
             '<p><ac:image><ri:attachment ri:filename="zones.png"/></ac:image></p>'
             '<p>See <ac:link><ri:page ri:content-title="Fare Engine deployment"/>'
             '<ac:plain-text-link-body><![CDATA[the deployment]]></ac:plain-text-link-body></ac:link>.</p>'
             '<p><ac:link><ri:attachment ri:filename="tariffs.pdf"/></ac:link></p>'
             '<p>Ask <ac:link><ri:user ri:userkey="u-42"/></ac:link></p>'
             '<ac:task-list><ac:task><ac:task-status>complete</ac:task-status><ac:task-body>Done it</ac:task-body>'
             '</ac:task></ac:task-list>'
             '<ac:layout><ac:layout-section><ac:layout-cell><p>Left column.</p></ac:layout-cell></ac:layout-section>'
             '</ac:layout>'
             '<p><ac:emoticon ac:name="smile"/> <ac:unknown-thing>kept text</ac:unknown-thing></p>')
    assert "Before." in md
    assert "⟦Confluence macro: jira (key=FARE-12)⟧" in md
    assert "⟦Confluence macro: info⟧" in md and "Read this first." in md
    assert "⟦Confluence image: zones.png⟧" in md
    assert "the deployment ⟦link to the page «Fare Engine deployment»⟧" in md
    assert "⟦Confluence attachment: tariffs.pdf⟧" in md
    assert "⟦Confluence user: u-42⟧" in md
    assert "⟦Confluence task list⟧" in md and "- [x] Done it" in md
    assert "⟦Confluence column layout⟧" in md and "Left column." in md
    assert "⟦Confluence element: ac:emoticon (smile)⟧" in md
    assert "⟦Confluence element: ac:unknown-thing⟧" in md and "kept text" in md


def test_markers_follow_the_language():
    i18n.use("es")
    md = _md('<ac:structured-macro ac:name="jira"/>')
    assert "⟦Macro de Confluence: jira⟧" in md


def test_entities_external_images_and_breaks():
    md = _md('<p>A&nbsp;&amp;&nbsp;B<br/>next line</p><p><ac:image ac:alt="logo"><ri:url ri:value="https://x.org/l.png"/>'
             '</ac:image></p>')
    assert "A & B<br>next line" in md
    assert "![logo](https://x.org/l.png)" in md


def test_broken_markup_does_not_raise():
    md = _md("<p>open <b>bold<p>next</div></span><ul><li>x")
    assert "open" in md and "next" in md and "x" in md


def test_html_files_drop_scripts_and_take_the_title():
    md = xhtml.html_to_markdown("<!doctype html><html><head><title>Night Service</title><style>p{}</style>"
                                "<script>alert(1)</script></head><body><nav>menu</nav><p>Runs at night.</p></body></html>")
    assert md.startswith("# Night Service\n")
    assert "Runs at night." in md and "alert" not in md and "p{}" not in md


def test_an_html_file_with_its_own_h1_keeps_it():
    md = xhtml.html_to_markdown("<title>ignored</title><h1>Real title</h1><p>x</p>")
    assert md.startswith("# Real title\n") and "ignored" not in md


def test_the_markdown_renders_back_without_raw_html():
    md = _md("<h2>A</h2><p>x <strong>y</strong></p><table><tr><th>a</th></tr><tr><td>b</td></tr></table>")
    html = docs_kit.markdown_to_html(md)
    assert "<h2>A</h2>" in html and "<strong>y</strong>" in html and "<td>b</td>" in html


def test_local_folders_read_html_and_markdown_files(tmp_path):
    from amanuense import confluence
    (tmp_path / "night.html").write_text("<title>Night Service</title><p>Runs at night.</p>", encoding="utf-8")
    (tmp_path / "fares.markdown").write_text("# Fares\n\nZones.\n", encoding="utf-8")
    (tmp_path / "old.htm").write_text("<h1>Old Page</h1><p>x</p>", encoding="utf-8")
    docs = {d.title: d for d in confluence.load_local(tmp_path)}
    assert set(docs) == {"Night Service", "Fares", "Old Page"}
    assert "Runs at night." in docs["Night Service"].body
    assert confluence.normalize_title("Night Service.html") == "night service"
