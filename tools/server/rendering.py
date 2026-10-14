"""CommonMark rendering with WikiLinks, callouts and simple inline math."""

import html
import re
from urllib.parse import quote

from markdown_it import MarkdownIt


def _wikilink(state, silent):
    if not state.src.startswith("[[", state.pos):
        return False
    end = state.src.find("]]", state.pos + 2)
    if end < 0:
        return False
    raw = state.src[state.pos + 2:end].replace(r"\|", "|")
    target, _, label = raw.partition("|")
    target = target.strip()
    if not target:
        return False
    if not silent:
        token = state.push("link_open", "a", 1)
        token.attrs = {"class": "wikilink", "data-page": target,
                       "href": "/?page=" + quote(target, safe="")}
        state.push("text", "", 0).content = label.strip() if label else target
        state.push("link_close", "a", -1)
    state.pos = end + 2
    return True


def _math(state, silent):
    if state.src[state.pos:state.pos + 1] != "$" or state.src.startswith("$$", state.pos):
        return False
    end = state.src.find("$", state.pos + 1)
    if end < 0 or "\n" in state.src[state.pos + 1:end]:
        return False
    content = state.src[state.pos + 1:end].strip()
    if not content:
        return False
    if not silent:
        token = state.push("simple_math", "span", 0)
        symbols = {"leq": "≤", "le": "≤", "geq": "≥", "ge": "≥", "times": "×",
                   "sim": "～", "pm": "±", "mu": "μ", "%": "%"}
        content = re.sub(r"\\text\{([^}]+)\}", r"\1", content)
        token.content = re.sub(r"\\([A-Za-z]+|%)", lambda m: symbols.get(m[1], m[0]), content)
    state.pos = end + 1
    return True


def _render_math(renderer, tokens, idx, options, env):
    return '<span class="math-inline">' + html.escape(tokens[idx].content) + "</span>"


def _callouts(state):
    titles = {"NOTE": "ℹ️ 来源与要点说明", "WARNING": "⚠️ 临床警示与用药风险",
              "CAUTION": "🛑 绝对禁忌与红线", "IMPORTANT": "❗ 核心诊疗要点",
              "TIP": "💡 临床实践建议", "INFO": "ℹ️ 指南背景信息"}
    stack = []
    for i, token in enumerate(state.tokens):
        if token.type == "blockquote_open":
            match = None
            inline = state.tokens[i + 2] if i + 2 < len(state.tokens) else None
            if inline and inline.type == "inline":
                match = re.match(r"^\[!(NOTE|WARNING|CAUTION|IMPORTANT|TIP|INFO)\]\s*", inline.content, re.I)
            stack.append(bool(match))
            if match:
                kind = match[1].upper()
                token.tag = "div"
                token.attrSet("class", "callout callout-" + kind.lower())
                if inline.children and inline.children[0].type == "text":
                    inline.children[0].content = re.sub(r"^\[![A-Za-z]+\]\s*", titles[kind] + "：", inline.children[0].content)
        elif token.type == "blockquote_close" and stack:
            if stack.pop():
                token.tag = "div"


def _parser():
    parser = MarkdownIt("commonmark", {"html": False, "breaks": True}).enable(["table", "strikethrough"])
    parser.inline.ruler.before("link", "wikilink", _wikilink)
    parser.inline.ruler.before("escape", "simple_math", _math)
    parser.add_render_rule("simple_math", _render_math)
    parser.core.ruler.after("inline", "callouts", _callouts)
    return parser


def markdown_to_html(text: str) -> str:
    if not text:
        return ""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            text = parts[2].strip()
    return _parser().render(text)
