import ast
import re
from pathlib import Path


RULES_DIR = Path(__file__).resolve().parents[1] / "rules"

MIN_FRAGMENT_CHARS = 24
MIN_FRAGMENT_WORDS = 4
MAX_FRAGMENT_CHARS = 520

_registry_cache: dict | None = None
_registry_mtime_signature: tuple[tuple[str, float], ...] | None = None

_sentence_boundary_pattern = re.compile(
    r"(?<=[.!?])\s+|(?<=[.!?])(?=[A-Z<])|\n+"
)

_word_pattern = re.compile(
    r"[A-Za-zА-Яа-яЁё0-9]+(?:[-'][A-Za-zА-Яа-яЁё0-9]+)?"
)


def _rules_mtime_signature() -> tuple[tuple[str, float], ...]:

    return tuple(
        sorted(
            (
                path.name,
                path.stat().st_mtime,
            )
            for path in RULES_DIR.glob("*.py")
            if path.name not in {
                "__init__.py",
                "rule_citations.py",
            }
        )
    )


def _iter_constant_assignments(
    path: Path,
) -> list[tuple[str, ast.AST]]:

    tree = ast.parse(
        path.read_text(
            encoding="utf-8-sig"
        ),
        filename=str(path),
    )

    assignments: list[tuple[str, ast.AST]] = []

    for node in tree.body:

        if isinstance(
            node,
            ast.Assign,
        ):
            targets = node.targets
            value = node.value
        elif isinstance(
            node,
            ast.AnnAssign,
        ):
            targets = [
                node.target
            ]
            value = node.value
        else:
            continue

        if value is None:
            continue

        for target in targets:

            if not isinstance(
                target,
                ast.Name,
            ):
                continue

            if target.id.isupper():
                assignments.append(
                    (
                        target.id,
                        value,
                    )
                )

    return assignments


def _evaluate_text_constant(
    node: ast.AST,
    values: dict[str, object],
):

    if isinstance(
        node,
        ast.Constant,
    ):
        return node.value

    if isinstance(
        node,
        ast.Name,
    ):
        return values.get(
            node.id,
            ""
        )

    if isinstance(
        node,
        ast.BinOp,
    ) and isinstance(
        node.op,
        ast.Add,
    ):
        left = _evaluate_text_constant(
            node.left,
            values,
        )
        right = _evaluate_text_constant(
            node.right,
            values,
        )

        if isinstance(
            left,
            str,
        ) and isinstance(
            right,
            str,
        ):
            return left + right

        return None

    if isinstance(
        node,
        ast.JoinedStr,
    ):
        pieces: list[str] = []

        for value in node.values:
            if isinstance(
                value,
                ast.Constant,
            ):
                pieces.append(
                    str(
                        value.value
                    )
                )
                continue

            if isinstance(
                value,
                ast.FormattedValue,
            ):
                evaluated = _evaluate_text_constant(
                    value.value,
                    values,
                )

                if isinstance(
                    evaluated,
                    str,
                ):
                    pieces.append(
                        evaluated
                    )

        return "".join(
            pieces
        )

    if isinstance(
        node,
        (
            ast.List,
            ast.Tuple,
            ast.Set,
        ),
    ):
        return [
            _evaluate_text_constant(
                item,
                values,
            )
            for item in node.elts
        ]

    if isinstance(
        node,
        ast.Dict,
    ):
        return {
            _evaluate_text_constant(
                key,
                values,
            ): _evaluate_text_constant(
                value,
                values,
            )
            for key, value in zip(
                node.keys,
                node.values,
            )
        }

    return None


def _iter_text_values(
    value,
) -> list[str]:

    if isinstance(
        value,
        str,
    ):
        return [
            value
        ]

    if isinstance(
        value,
        (
            list,
            tuple,
            set,
        ),
    ):
        texts: list[str] = []

        for item in value:
            texts.extend(
                _iter_text_values(
                    item
                )
            )

        return texts

    if isinstance(
        value,
        dict,
    ):
        texts: list[str] = []

        for item in value.values():
            texts.extend(
                _iter_text_values(
                    item
                )
            )

        return texts

    return []


def _clean_fragment(
    text: str,
) -> str:

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def _count_words(
    text: str,
) -> int:

    visible_text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    return len(
        _word_pattern.findall(
            visible_text
        )
    )


def _is_usable_fragment(
    text: str,
) -> bool:

    if len(text) < MIN_FRAGMENT_CHARS:
        return False

    if _count_words(
        text
    ) < MIN_FRAGMENT_WORDS:
        return False

    return True


def _split_long_fragment(
    fragment: str,
) -> list[str]:

    if len(fragment) <= MAX_FRAGMENT_CHARS:
        return [
            fragment
        ]

    pieces = re.split(
        r"(?<=;)\s+|,\s+(?=[A-Z])",
        fragment,
    )

    if len(pieces) <= 1:
        return [
            fragment
        ]

    result: list[str] = []
    current = ""

    for piece in pieces:

        candidate = (
            f"{current} {piece}".strip()
            if current
            else piece.strip()
        )

        if len(candidate) <= MAX_FRAGMENT_CHARS:
            current = candidate
            continue

        if current:
            result.append(
                current
            )

        current = piece.strip()

    if current:
        result.append(
            current
        )

    return result


def _split_rule_fragments(
    text: str,
) -> list[str]:

    normalized = text.replace(
        "\r\n",
        "\n",
    ).replace(
        "\r",
        "\n",
    )

    fragments: list[str] = []

    for part in _sentence_boundary_pattern.split(
        normalized
    ):
        fragment = _clean_fragment(
            part
        )

        if not fragment:
            continue

        for smaller_fragment in _split_long_fragment(
            fragment
        ):

            clean_smaller_fragment = _clean_fragment(
                smaller_fragment
            )

            if _is_usable_fragment(
                clean_smaller_fragment
            ):
                fragments.append(
                    clean_smaller_fragment
                )

    return fragments


def _build_registry() -> dict:

    fragments: list[dict] = []
    seen_normalized_fragments: set[str] = set()

    for path in sorted(
        RULES_DIR.glob("*.py")
    ):

        if path.name in {
            "__init__.py",
            "rule_citations.py",
        }:
            continue

        values: dict[str, object] = {}

        for constant_name, value_node in _iter_constant_assignments(
            path
        ):
            value = _evaluate_text_constant(
                value_node,
                values,
            )

            values[constant_name] = value

            for text_value in _iter_text_values(
                value
            ):

                for index, source_text in enumerate(
                    _split_rule_fragments(
                        text_value
                    )
                ):
                    normalized_key = _clean_fragment(
                        source_text.lower()
                    )

                    if normalized_key in seen_normalized_fragments:
                        continue

                    seen_normalized_fragments.add(
                        normalized_key
                    )

                    fragments.append(
                        {
                            "id": (
                                f"{path.stem}:{constant_name}:{index}"
                            ),
                            "source": path.stem,
                            "sourceType": "rule",
                            "citationType": "rule_citation",
                            "layer": _resolve_layer(
                                path.stem,
                                constant_name,
                            ),
                            "file": path.name,
                            "constantName": constant_name,
                            "sourceText": source_text,
                            "minScore": 0.72,
                        }
                    )

    return {
        "version": "rules-v1",
        "fragmentCount": len(
            fragments
        ),
        "fragments": fragments,
    }


def _resolve_layer(
    module_name: str,
    constant_name: str,
) -> str:

    combined = (
        f"{module_name}.{constant_name}"
        .lower()
    )

    if "runtime" in combined:
        return "runtime"

    if "loop" in combined:
        return "runtime"

    return "base"


def get_rule_citation_registry() -> dict:

    global _registry_cache
    global _registry_mtime_signature

    signature = _rules_mtime_signature()

    if (
        _registry_cache is not None
        and _registry_mtime_signature == signature
    ):
        return _registry_cache

    _registry_cache = _build_registry()
    _registry_mtime_signature = signature

    return _registry_cache
