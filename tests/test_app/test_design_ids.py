"""Pin #308's cross-module id rule for `deltadewa/app/pages/design/`.

The split's Decision 3: an element id **literal** lives in exactly one
module — the one whose layout creates it. A module that needs another
module's id imports the constant that names it (``book.BOOK_VERSION_STORE``,
``book.MUTATION_STATUS``) rather than writing the literal string a second
time. This is what keeps a callback's ``Output``/``Input``/``State`` legible
as *which* layout it talks to, without a shared id registry.

This test enforces that mechanically, over the actual source of every
module under ``pages/design/``:

1. Every id string literal an ``@app.callback``'s ``Output``/``Input``/
   ``State`` references must also be created (``id="..."``) somewhere in
   that *same* module. A reference via an imported name (e.g.
   ``Input(BOOK_VERSION_STORE, ...)``) is invisible to this check by
   construction — that is the legitimate, intended path, and precisely
   the reason this test scans literals rather than resolved values.
2. No id string literal is created by more than one module.

The one pattern-matching id in the package —
``{"type": "remove-confirm", "index": ...}``, created in ``book.py``'s
``_position_row`` and referenced in ``book.py``'s own remove callback —
needs no special-casing: both sides are dict literals, never plain
strings, so this test's string-literal scan simply never sees them. It
would not need to, either — the create and the reference are already in
the same module.

#357 added a second uniqueness question the two checks above cannot
see: every panel's ``SECTION: SectionSpec`` (or, for ``book.py``,
``SECTIONS: tuple[SectionSpec, ...]``) carries its own ``anchor_id``,
via ``SectionSpec(anchor_id=..., title=...)`` rather than an ``id=``
keyword — invisible to :func:`_created_ids`/:func:`_referenced_ids` by
construction, since neither the call target (``SectionSpec``, not
``Output``/``Input``/``State``) nor the keyword name (``anchor_id``,
not ``id``) matches what those scan for. Two panels accidentally
sharing an anchor would make the TOC's "jump to" link for one of them
land on the other's heading instead — a distinct failure mode from the
Output/Input ambiguity the id checks above guard, so it gets its own
scan rather than folding into ``_created_ids``.
"""

from __future__ import annotations

import ast
from pathlib import Path

_DESIGN_PACKAGE = (
    Path(__file__).resolve().parents[2]
    / "deltadewa"
    / "app"
    / "pages"
    / "design"
)

_ID_CREATING_CALLS = frozenset({"Output", "Input", "State"})


def _string_literal(node: ast.expr) -> str | None:
    """Return *node*'s value if it's a plain string constant, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _created_ids(tree: ast.AST) -> set[str]:
    """Every ``id="literal"`` keyword value anywhere in *tree*."""
    ids: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "id":
                    literal = _string_literal(kw.value)
                    if literal is not None:
                        ids.add(literal)
    return ids


def _referenced_ids(tree: ast.AST) -> set[str]:
    """Every id literal passed as the first arg to Output/Input/State."""
    ids: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _ID_CREATING_CALLS
            and node.args
        ):
            literal = _string_literal(node.args[0])
            if literal is not None:
                ids.add(literal)
    return ids


def _section_anchor_ids(tree: ast.AST) -> set[str]:
    """Every ``anchor_id=`` literal passed to a ``SectionSpec(...)`` call."""
    ids: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "SectionSpec"
        ):
            for kw in node.keywords:
                if kw.arg == "anchor_id":
                    literal = _string_literal(kw.value)
                    if literal is not None:
                        ids.add(literal)
            # SectionSpec's first positional field is anchor_id — no
            # caller in this package uses it positionally today, but a
            # scan that only understood the keyword form would silently
            # stop covering a future one.
            if node.args:
                literal = _string_literal(node.args[0])
                if literal is not None:
                    ids.add(literal)
    return ids


def _design_modules() -> dict[str, ast.AST]:
    """Parse every non-``__init__`` module under ``pages/design/``."""
    trees: dict[str, ast.AST] = {}
    for path in sorted(_DESIGN_PACKAGE.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        rel = path.relative_to(_DESIGN_PACKAGE).as_posix()
        trees[rel] = ast.parse(path.read_text())
    return trees


def test_every_referenced_id_is_created_in_the_same_module() -> None:
    """A callback never Outputs/Inputs/States a literal id it doesn't own.

    The one legitimate way to reach another module's id is the imported
    constant (``BOOK_VERSION_STORE``, ``MUTATION_STATUS``) — invisible
    here, since this only sees string literals. A failure here means a
    panel module wrote another module's id as a bare string instead.
    """
    modules = _design_modules()
    failures = []
    for name, tree in modules.items():
        created = _created_ids(tree)
        referenced = _referenced_ids(tree)
        missing = referenced - created
        if missing:
            failures.append(f"{name}: references but never creates {missing}")
    assert not failures, "\n".join(failures)


def test_no_id_literal_is_created_by_two_modules() -> None:
    """Every element id string is owned by exactly one module.

    Two modules creating the same id by accident would make a callback's
    ``Output``/``Input`` ambiguous about which layout it actually talks
    to — the failure mode #308's split is designed to make impossible.
    """
    modules = _design_modules()
    owners: dict[str, list[str]] = {}
    for name, tree in modules.items():
        for element_id in _created_ids(tree):
            owners.setdefault(element_id, []).append(name)
    collisions = {
        element_id: names
        for element_id, names in owners.items()
        if len(names) > 1
    }
    assert not collisions, collisions


def test_no_section_anchor_id_is_created_by_two_modules() -> None:
    """Every panel's TOC anchor id is unique (#357).

    A collision here would send the "jump to" link for one panel's
    section straight to a different panel's heading instead — invisible
    to :func:`test_no_id_literal_is_created_by_two_modules` above, since
    ``SectionSpec(anchor_id=...)`` is neither an ``id=`` keyword nor an
    ``Output``/``Input``/``State`` call.
    """
    modules = _design_modules()
    owners: dict[str, list[str]] = {}
    for name, tree in modules.items():
        for anchor_id in _section_anchor_ids(tree):
            owners.setdefault(anchor_id, []).append(name)
    collisions = {
        anchor_id: names
        for anchor_id, names in owners.items()
        if len(names) > 1
    }
    assert not collisions, collisions
