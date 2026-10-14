"""
xhtml — Confluence storage format, and plain HTML files, read as Markdown.

Standard library only (html.parser): a tolerant tree builder, then a renderer. Confluence's
own elements (`ac:` macros, `ri:` attachments, users and page links, layouts, task lists)
have no Markdown form, so each one leaves a visible marker such as
«⟦Confluence macro: jira (key=FARE-12)⟧»: the reviewer sees what the page holds, and
publishing blocks on them anyway (mind.inventory). Nothing is dropped silently; only
<script>, <style> and the document head are left out of an HTML file.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

from . import i18n

VOID = {"br", "hr", "img", "col", "meta", "link", "input", "area", "base", "wbr", "source", "param", "embed"}
SKIP = {"script", "style", "head", "template", "noscript", "svg"}
BLOCK = {"p", "div", "section", "article", "main", "body", "html", "header", "footer", "nav", "aside", "figure",
         "figcaption", "ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "pre", "blockquote", "hr",
         "h1", "h2", "h3", "h4", "h5", "h6", "dl", "dt", "dd", "form", "details", "summary", "center",
         "ac:structured-macro", "ac:macro", "ac:rich-text-body", "ac:plain-text-body", "ac:layout",
         "ac:layout-section", "ac:layout-cell", "ac:task-list", "ac:placeholder"}
INVISIBLE = {"ac:parameter", "ac:task-id", "ac:task-status", "ac:task-uuid"}
# Plain wrappers: their content is the content, and losing the wrapper loses nothing.
TRANSPARENT = {"ac:rich-text-body", "ac:layout-section", "ac:layout-cell", "ac:link-body",
               "ac:plain-text-link-body", "ac:task-body"}
CODE_MACROS = {"code", "noformat"}


class Node:
    __slots__ = ("tag", "attrs", "kids", "parent")

    def __init__(self, tag: str, attrs: dict | None = None, parent: "Node | None" = None):
        self.tag, self.attrs, self.kids, self.parent = tag, attrs or {}, [], parent

    def find(self, tag: str) -> "Node | None":
        for k in self.kids:
            if isinstance(k, Node):
                if k.tag == tag:
                    return k
                hit = k.find(tag)
                if hit is not None:
                    return hit
        return None

    def text(self) -> str:
        return "".join(k if isinstance(k, str) else k.text() for k in self.kids)


class _Tree(HTMLParser):
    """Builds a forgiving tree: unknown end tags are ignored, unclosed tags close with their parent."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.at = self.root
        self.skipping = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
            return
        if self.skipping or tag in SKIP:
            self.skipping += tag in SKIP
            return
        node = Node(tag, {k: v or "" for k, v in attrs}, self.at)
        self.at.kids.append(node)
        if tag not in VOID:
            self.at = node

    def handle_startendtag(self, tag, attrs):
        if self.skipping or tag in SKIP or tag == "title":
            return
        self.at.kids.append(Node(tag, {k: v or "" for k, v in attrs}, self.at))

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
            return
        if self.skipping:
            self.skipping -= tag in SKIP
            return
        node = self.at
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.at = node.parent

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self.skipping:
            self.at.kids.append(data)

    def unknown_decl(self, data):  # <![CDATA[...]]> inside code macros and link bodies
        if data.startswith("CDATA[") and not self.skipping:
            self.at.kids.append(data[len("CDATA["):])


def parse(markup: str) -> _Tree:
    tree = _Tree()
    tree.feed(markup)
    tree.close()
    return tree


# ── Rendering ──────────────────────────────────────────────────────────────────

def _marker(key: str, **fields) -> str:
    return i18n.t(key, **fields)


def _space(text: str) -> str:
    return re.sub(r"[ \t\r\n\f\xa0]+", " ", text)


def _params(node: Node) -> dict[str, str]:
    return {k.attrs.get("ac:name", ""): _space(k.text()).strip() for k in node.kids
            if isinstance(k, Node) and k.tag == "ac:parameter"}


def _is_block(node: Node) -> bool:
    return node.tag in BLOCK or (node.tag.startswith("ac:") and node.find("p") is not None)


def _inline(node: Node | str, cell: bool = False) -> str:
    if isinstance(node, str):
        return _space(node)
    tag = node.tag
    inner = "".join(_inline(k, cell) for k in node.kids)
    if tag in INVISIBLE:
        return ""
    if tag in ("strong", "b"):
        return f"**{inner.strip()}**" if inner.strip() else inner
    if tag in ("em", "i"):
        return f"*{inner.strip()}*" if inner.strip() else inner
    if tag == "code":
        return f"`{node.text().strip()}`"
    if tag == "br":
        return "<br>"
    if tag == "a":
        href = node.attrs.get("href", "")
        return f"[{inner.strip()}]({href})" if href and inner.strip() else inner
    if tag == "img":
        return f"![{node.attrs.get('alt', '')}]({node.attrs.get('src', '')})"
    if tag == "ac:image":
        url = node.find("ri:url")
        if url is not None:
            return f"![{node.attrs.get('ac:alt', '')}]({url.attrs.get('ri:value', '')})"
        att = node.find("ri:attachment")
        name = att.attrs.get("ri:filename", "?") if att is not None else "?"
        return _marker("storage_image", name=name)
    if tag == "ac:link":
        return _link(node)
    if tag == "ri:user":
        return _marker("storage_user", name=node.attrs.get("ri:userkey") or node.attrs.get("ri:username")
                       or node.attrs.get("ri:account-id") or "?")
    if tag == "ri:attachment":
        return _marker("storage_attachment", name=node.attrs.get("ri:filename", "?"))
    if tag in TRANSPARENT:
        return inner
    if tag.startswith(("ac:", "ri:")):
        name = node.attrs.get("ac:name")
        label = f"{tag} ({name})" if name else tag
        return _marker("storage_element", name=label) + (f" {inner.strip()}" if inner.strip() else "")
    return inner


def _link(node: Node) -> str:
    body = ""
    for k in node.kids:
        if isinstance(k, Node) and k.tag in ("ac:link-body", "ac:plain-text-link-body"):
            body = _space(k.text()).strip()
    page = node.find("ri:page") or node.find("ri:blog-post")
    if page is not None:
        title = page.attrs.get("ri:content-title", "?")
        return f"{body or title} " + _marker("storage_link", name=title)
    url = node.find("ri:url")
    if url is not None:
        return f"[{body or url.attrs.get('ri:value', '')}]({url.attrs.get('ri:value', '')})"
    for tag in ("ri:attachment", "ri:user"):
        target = node.find(tag)
        if target is not None:
            return (f"{body} " if body else "") + _inline(target)
    anchor = node.attrs.get("ac:anchor")
    return body or (_marker("storage_element", name=f"ac:link (#{anchor})") if anchor else "")


def _clean(text: str) -> str:
    text = re.sub(r" *<br> *", "<br>", text.strip())
    return re.sub(r"(<br>)+$", "", re.sub(r"^(<br>)+", "", text))


def _blocks(node: Node) -> list[str]:
    out: list[str] = []
    buf: list[str] = []

    def flush():
        text = _clean("".join(buf))
        if text:
            out.append(text)
        buf.clear()

    for k in node.kids:
        if isinstance(k, Node) and _is_block(k):
            flush()
            out += _block(k)
        else:
            buf.append(_inline(k))
    flush()
    return out


def _list(node: Node, depth: int = 0) -> list[str]:
    lines = []
    n = 0
    for li in node.kids:
        if not isinstance(li, Node) or li.tag != "li":
            continue
        n += 1
        bullet = f"{n}." if node.tag == "ol" else "-"
        text, subs = [], []
        for k in li.kids:
            if isinstance(k, Node) and k.tag in ("ul", "ol"):
                subs += _list(k, depth + 1)
            elif isinstance(k, Node) and _is_block(k):
                text.append(" " + " ".join(b.replace("\n", " ") for b in _blocks(k)) + " ")
            else:
                text.append(_inline(k))
        lines.append("  " * depth + f"{bullet} " + _clean(re.sub(" {2,}", " ", "".join(text))))
        lines += subs
    return lines


def _cell(node: Node) -> str:
    parts = [b.replace("\n", "<br>") for b in _blocks(node)]
    return "<br>".join(parts).replace("|", "\\|")


def _table(node: Node) -> list[str]:
    rows: list[list[str]] = []

    def walk(n: Node):
        for k in n.kids:
            if not isinstance(k, Node) or k.tag == "table":
                continue
            if k.tag == "tr":
                rows.append([_cell(c) for c in k.kids if isinstance(c, Node) and c.tag in ("td", "th")])
            else:
                walk(k)
    walk(node)
    rows = [r for r in rows if r]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + " --- |" * width]
    return ["\n".join(lines + ["| " + " | ".join(r) + " |" for r in rows[1:]])]


def _macro(node: Node) -> list[str]:
    name = node.attrs.get("ac:name", "?")
    params = _params(node)
    body = node.find("ac:plain-text-body")
    if name in CODE_MACROS:
        lang = params.get("language", "")
        return [f"```{lang}\n{(body.text() if body is not None else '').strip(chr(10))}\n```"]
    shown = ", ".join(f"{k}={v}" for k, v in params.items() if k and v)[:120]
    out = [_marker("storage_macro", name=name, params=f" ({shown})" if shown else "")]
    rich = next((k for k in node.kids if isinstance(k, Node) and k.tag == "ac:rich-text-body"), None)
    if rich is not None:
        out += _blocks(rich)
    elif body is not None and body.text().strip():
        out.append(f"```\n{body.text().strip(chr(10))}\n```")
    return out


def _block(node: Node) -> list[str]:
    tag = node.tag
    if re.fullmatch(r"h[1-6]", tag):
        text = _clean("".join(_inline(k) for k in node.kids)).replace("<br>", " ")
        return [f"{'#' * int(tag[1])} {text}"] if text else []
    if tag in ("ul", "ol"):
        lines = _list(node)
        return ["\n".join(lines)] if lines else []
    if tag == "table":
        return _table(node)
    if tag == "pre":
        return [f"```\n{node.text().strip(chr(10))}\n```"]
    if tag == "blockquote":
        inner = _blocks(node)
        return ["\n".join("> " + line if line else ">" for line in "\n\n".join(inner).splitlines())] if inner else []
    if tag == "hr":
        return ["---"]
    if tag in ("ac:structured-macro", "ac:macro"):
        return _macro(node)
    if tag == "ac:layout":
        return [_marker("storage_layout")] + _blocks(node)
    if tag == "ac:task-list":
        items = []
        for task in (k for k in node.kids if isinstance(k, Node) and k.tag == "ac:task"):
            status = task.find("ac:task-status")
            done = status is not None and status.text().strip() == "complete"
            body = task.find("ac:task-body")
            items.append(f"- [{'x' if done else ' '}] " + _clean(_inline(body) if body is not None else ""))
        return [_marker("storage_tasks"), "\n".join(items)] if items else [_marker("storage_tasks")]
    if tag in TRANSPARENT or not tag.startswith("ac:"):
        return _blocks(node)
    name = node.attrs.get("ac:name")
    return [_marker("storage_element", name=f"{tag} ({name})" if name else tag)] + _blocks(node)


def to_markdown(markup: str) -> str:
    """The body as Markdown blocks separated by blank lines (no title)."""
    return "\n\n".join(_blocks(parse(markup).root)).strip()


def storage_to_markdown(storage: str, title: str) -> str:
    """A Confluence page in the shape the comparison uses: `# Title` and its body."""
    body = to_markdown(storage)
    return f"# {title}\n\n{body}\n" if body else f"# {title}\n"


def html_to_markdown(markup: str) -> str:
    """An HTML file as Markdown; its <title> becomes the heading when it has no <h1>."""
    tree = parse(markup)
    body = "\n\n".join(_blocks(tree.root)).strip()
    title = _space(tree.title).strip()
    if title and not re.match(r"^#\s", body):
        body = f"# {title}\n\n{body}"
    return body + "\n"
