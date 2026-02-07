import pathlib
import sys


# Ensure project root and src are on the import path
ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from build_prereqs import (  # noqa: E402
    detect_eval_policy,
    extract_min_grade,
    parse_expr,
    prereq_to_tokens,
)


def test_prereq_to_tokens_basic_and():
    text = "Prerequisites: CSCI 241 and MATH 221."
    tokens = prereq_to_tokens(text)
    assert tokens == ["COURSE(CSCI,241)", "AND", "COURSE(MATH,221)"]


def test_prereq_to_tokens_group_and_consent():
    text = "Prerequisites: Any 300-level computer science course or consent of instructor."
    tokens = prereq_to_tokens(text)
    assert tokens == ["GROUP(CSCI 300 399)", "OR", "CONSENT"]


def test_extract_min_grade_and_token_tagging():
    text = "Prerequisites: CSCI 241 with C or better."
    assert extract_min_grade(text) == "C"
    tokens = prereq_to_tokens(text)
    assert tokens == ["COURSE(CSCI,241):MIN_GRADE=C", "OR"]


def test_detect_eval_policy():
    assert detect_eval_policy("May be taken concurrent with CSCI 241.") == "BEFORE_OR_CONCURRENT"
    assert detect_eval_policy("Prerequisites: CSCI 241.") == "BEFORE_ONLY"


def test_parse_expr_builds_and_or_tree():
    tokens = ["COURSE(CSCI,241)", "OR", "COURSE(MATH,221)", "AND", "COURSE(CSCI,242)"]
    expr = parse_expr(tokens)
    assert expr is not None
    # AND has higher precedence, so top-level op should be OR
    assert expr.op == "OR"
    assert len(expr.children) == 2
