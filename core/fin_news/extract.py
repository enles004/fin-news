"""Article text extraction module using standard library html.parser."""
from html.parser import HTMLParser
from html import unescape as html_unescape
import json
import re
from typing import Dict, List, Optional, Tuple, Union


DISCARD_TAGS = {
    'script', 'style', 'noscript', 'template', 'svg', 'iframe',
    'nav', 'header', 'footer', 'aside', 'form', 'button'
}

DISCARD_SUBSTRINGS = [
    'related', 'relate', 'recommend', 'comment', 'share',
    'breadcrumb', 'banner', 'ads'
]

STEP3_CLASSES = [
    'article-body', 'article__body', 'article-content', 'detail-content',
    'content-detail', 'fck_detail', 'singular-content', 'detail__content',
    'the-article-body', 'maincontent', 'entry-content', 'post-content', 'cms-body'
]

FORBIDDEN_STRINGS = ['function(', 'var ', '@context', 'dataLayer', 'cmsConfig']


class DOMNode:
    """Lightweight DOM tree node."""
    __slots__ = ('tag', 'attrs', 'parent', 'children')

    def __init__(self, tag: str, attrs: Dict[str, str], parent: Optional['DOMNode'] = None):
        self.tag = tag.lower()
        self.attrs = attrs
        self.parent = parent
        self.children: List[Union['DOMNode', str]] = []

    def get_attr(self, name: str) -> str:
        return self.attrs.get(name.lower(), "")


class SafeTreeBuilder(HTMLParser):
    """HTML parser building a DOM tree with support for script extraction and block tags."""
    VOID = {
        'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
        'link', 'meta', 'param', 'source', 'track', 'wbr'
    }
    BLOCK = {
        'p', 'div', 'article', 'section', 'header', 'footer', 'nav', 'aside',
        'main', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'ul', 'ol', 'li',
        'blockquote', 'pre', 'form', 'hr'
    }

    def __init__(self):
        super().__init__()
        self.root = DOMNode("root", {})
        self.current = self.root
        self.json_ld_raw: List[str] = []
        self._in_json_ld = False
        self._json_ld_buffer: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
        tag = tag.lower()
        attr_dict = {k.lower(): (v or "") for k, v in attrs}

        # Check for JSON-LD script block
        if tag == "script" and "application/ld+json" in attr_dict.get("type", "").lower():
            self._in_json_ld = True
            self._json_ld_buffer = []
            return

        # Implicitly close <p> tag if another block element opens
        if self.current.tag == 'p' and tag in self.BLOCK:
            self.current = self.current.parent or self.root

        node = DOMNode(tag, attr_dict, self.current)
        self.current.children.append(node)
        if tag not in self.VOID:
            self.current = node

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if self._in_json_ld and tag == "script":
            self._in_json_ld = False
            self.json_ld_raw.append("".join(self._json_ld_buffer))
            self._json_ld_buffer = []
            return

        cur = self.current
        while cur is not None and cur != self.root:
            if cur.tag == tag:
                self.current = cur.parent or self.root
                break
            cur = cur.parent

    def handle_data(self, data: str):
        if self._in_json_ld:
            self._json_ld_buffer.append(data)
            return
        if data:
            self.current.children.append(data)


def _contains_step3_or_article(node: DOMNode, hints: tuple[str, ...] = ()) -> bool:
    """Check if node or any descendant has tag article, hints, or step3 class."""
    if node.tag == 'article':
        return True
    class_id = (node.get_attr("class") + " " + node.get_attr("id")).lower()
    if any(h.lower() in class_id for h in hints if h):
        return True
    if any(s3 in class_id for s3 in STEP3_CLASSES):
        return True
    for c in node.children:
        if isinstance(c, DOMNode) and _contains_step3_or_article(c, hints):
            return True
    return False


def prune_tree(node: DOMNode, hints: tuple[str, ...] = ()):
    """Prune discarded tags and class/id elements recursively in-place."""
    new_children: List[Union[DOMNode, str]] = []
    for c in node.children:
        if isinstance(c, DOMNode):
            class_id = (c.get_attr("class") + " " + c.get_attr("id")).lower()
            is_discard = False
            if c.tag in DISCARD_TAGS:
                is_discard = True
            elif c.tag not in ('html', 'body') and any(sub in class_id for sub in DISCARD_SUBSTRINGS):
                # Never discard layout containers that contain the actual article/step3 body
                if not _contains_step3_or_article(c, hints):
                    is_discard = True

            if not is_discard:
                prune_tree(c, hints)
                new_children.append(c)
        else:
            new_children.append(c)
    node.children = new_children


def find_all(node: DOMNode, predicate, out: Optional[List[DOMNode]] = None) -> List[DOMNode]:
    """Find all DOM nodes satisfying a predicate."""
    if out is None:
        out = []
    if predicate(node):
        out.append(node)
    for c in node.children:
        if isinstance(c, DOMNode):
            find_all(c, predicate, out)
    return out


def get_node_text(node: DOMNode) -> str:
    """Get all raw text recursively inside node."""
    parts = []
    for c in node.children:
        if isinstance(c, str):
            parts.append(c)
        elif isinstance(c, DOMNode):
            parts.append(get_node_text(c))
    return "".join(parts)


def clean_paragraph_text(raw: str) -> str:
    """Unescape HTML and collapse whitespace."""
    t = html_unescape(raw)
    return " ".join(t.split()).strip()


def get_paragraphs_from_node(node: DOMNode) -> List[str]:
    """Extract cleaned text from <p> nodes in document order."""
    p_nodes = find_all(node, lambda n: n.tag == 'p')
    paragraphs = []
    for pn in p_nodes:
        cleaned = clean_paragraph_text(get_node_text(pn))
        if cleaned:
            paragraphs.append(cleaned)
    return paragraphs


def format_text_candidate(paragraphs: List[str], max_chars: int) -> str:
    """Deduplicate consecutive lines, join with blank line, and cut at boundary <= max_chars."""
    deduped = []
    last_line = None
    for p in paragraphs:
        if p != last_line:
            deduped.append(p)
            last_line = p

    selected = []
    cur_len = 0
    for p in deduped:
        needed = len(p) if not selected else len(p) + 2
        if cur_len + needed <= max_chars:
            selected.append(p)
            cur_len += needed
        else:
            if not selected and len(p) > max_chars:
                selected.append(p[:max_chars])
            break

    return "\n\n".join(selected).strip()


def get_title_words(title_str: str) -> List[str]:
    """Extract non-trivial keyword tokens from article title."""
    if " - " in title_str:
        title_str = title_str.split(" - ")[0]
    elif " | " in title_str:
        title_str = title_str.split(" | ")[0]

    stopwords = {
        "tháng", "năm", "ngày", "hôm", "đồng", "triệu", "nghìn",
        "báo", "tin", "mới", "nhất", "online", "kinh", "doanh",
        "theo", "được", "trong", "những", "trên"
    }
    raw_words = re.findall(r'[\w\d]+', title_str.lower(), re.UNICODE)
    return [w for w in raw_words if len(w) >= 4 and not w.isdigit() and w not in stopwords]


def has_title_words(text: str, title_words: List[str]) -> bool:
    """Check if text contains at least two non-trivial words from title."""
    if not title_words:
        return True
    text_lower = text.lower()
    matches = sum(1 for w in title_words if w in text_lower)
    return matches >= min(2, len(title_words))


def is_valid_candidate(text: str, title_words: List[str]) -> bool:
    """Validate candidate text against length, forbidden substrings, and title words."""
    if len(text) < 200:
        return False
    if any(bad in text for bad in FORBIDDEN_STRINGS):
        return False
    if title_words and not has_title_words(text, title_words):
        return False
    return True


def extract_with_tier(
    html: str,
    *,
    title: str = "",
    max_chars: int = 3500,
    hints: tuple[str, ...] = ()
) -> tuple[str, str]:
    """Extract clean article text and reporting tier from HTML.

    Tiers:
    - 'json-ld': NewsArticle/Article with articleBody
    - 'article': <article> element
    - 'hint': container matching body_hints (tried first) or STEP3_CLASSES
    - 'density': paragraph density fallback
    - '': nothing usable
    """
    if not html:
        return "", ""

    title_words = get_title_words(title) if title else []

    parser = SafeTreeBuilder()
    try:
        parser.feed(html)
    except Exception:
        pass

    # 1. JSON-LD candidate
    for raw_json in parser.json_ld_raw:
        try:
            data = json.loads(raw_json.strip())
            items = []
            if isinstance(data, list):
                items.extend(data)
            elif isinstance(data, dict):
                if "@graph" in data and isinstance(data["@graph"], list):
                    items.extend(data["@graph"])
                else:
                    items.append(data)
            for it in items:
                t = it.get("@type", "")
                types = [t] if isinstance(t, str) else (t if isinstance(t, list) else [])
                if any(x in ["NewsArticle", "Article"] or x.endswith("/NewsArticle") or x.endswith("/Article") for x in types):
                    body = it.get("articleBody", "")
                    if isinstance(body, str) and body.strip():
                        # Unescape entities and split lines
                        body_unescaped = html_unescape(body)
                        lines = [clean_paragraph_text(line) for line in body_unescaped.splitlines() if clean_paragraph_text(line)]
                        if not lines:
                            lines = [clean_paragraph_text(body_unescaped)]
                        text = format_text_candidate(lines, max_chars)
                        if is_valid_candidate(text, title_words):
                            return text, "json-ld"
        except Exception:
            pass

    # Prune DOM tree
    prune_tree(parser.root, hints=hints)

    def p_text_len(node: DOMNode) -> int:
        return sum(len(p) for p in get_paragraphs_from_node(node))

    # 2. <article> element with the most paragraph text
    articles = find_all(parser.root, lambda n: n.tag == 'article')
    if articles:
        articles.sort(key=lambda a: p_text_len(a), reverse=True)
        for cand_node in articles:
            ps = get_paragraphs_from_node(cand_node)
            text = format_text_candidate(ps, max_chars)
            if is_valid_candidate(text, title_words):
                return text, "article"

    # 3. Hint tier: extra hints tried before built-in STEP3_CLASSES
    for h in hints:
        if not h:
            continue
        h_lower = h.lower()
        cand_containers = find_all(
            parser.root,
            lambda n: n.tag in ('div', 'section', 'article', 'main') and h_lower in (n.get_attr('class') + ' ' + n.get_attr('id')).lower()
        )
        if cand_containers:
            cand_containers.sort(key=lambda c: p_text_len(c), reverse=True)
            for cand_node in cand_containers:
                ps = get_paragraphs_from_node(cand_node)
                text = format_text_candidate(ps, max_chars)
                if is_valid_candidate(text, title_words):
                    return text, "hint"

    step3_containers = find_all(
        parser.root,
        lambda n: n.tag in ('div', 'section') and any(
            c in (n.get_attr('class') + ' ' + n.get_attr('id')).lower() for c in STEP3_CLASSES
        )
    )
    if step3_containers:
        step3_containers.sort(key=lambda c: p_text_len(c), reverse=True)
        for cand_node in step3_containers:
            ps = get_paragraphs_from_node(cand_node)
            text = format_text_candidate(ps, max_chars)
            if is_valid_candidate(text, title_words):
                return text, "hint"

    # 4. Fallback: container with the greatest total length of <p> elements >= 40 chars each
    candidate_containers = find_all(parser.root, lambda n: n.tag in ('div', 'section', 'article', 'main'))
    if candidate_containers:
        def p40_len(node: DOMNode) -> int:
            return sum(len(p) for p in get_paragraphs_from_node(node) if len(p) >= 40)

        candidate_containers.sort(key=lambda c: p40_len(c), reverse=True)
        for cand_node in candidate_containers:
            ps = get_paragraphs_from_node(cand_node)
            text = format_text_candidate(ps, max_chars)
            if is_valid_candidate(text, title_words):
                return text, "density"

    return "", ""


def extract_article_text(html: str, *, title: str = "", max_chars: int = 3500) -> str:
    """Extract clean article text from HTML according to priority algorithm."""
    text, _ = extract_with_tier(html, title=title, max_chars=max_chars)
    return text
