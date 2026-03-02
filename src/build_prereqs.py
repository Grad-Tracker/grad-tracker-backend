#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from typing import List, Optional, Union

from connection import get_connection  # returns Supabase Client


# ----------------------------
# AST models
# ----------------------------

@dataclass
class CourseRef:
    subject: str
    number: str
    min_grade: Optional[str] = None


@dataclass
class Atom:
    kind: str  # COURSE | CONSENT | COURSE_GROUP | TEST_SCORE | MIN_GPA
    course: Optional[CourseRef] = None
    group_subject: Optional[str] = None
    group_min_level: Optional[int] = None
    group_max_level: Optional[int] = None
    test_name: Optional[str] = None
    min_score: Optional[float] = None
    min_gpa: Optional[float] = None


@dataclass
class Expr:
    op: str  # AND | OR | ATOM
    children: List["Expr"]
    atom: Optional[Atom] = None


# ----------------------------
# Parsing heuristics
# ----------------------------

COURSE_REF_RE = re.compile(r"\b([A-Z]{2,10})\s*([0-9]{1,4}[A-Z]?)\b")
PREREQ_PREFIX_RE = re.compile(r"^\s*Prerequisites?\s*:\s*", re.IGNORECASE)

STANDING_REPLACEMENTS = {
    r"\b(freshman)\s+standing\b": 1,
    r"\b(sophomore)\s+standing\b": 2,
    r"\b(junior)\s+standing\b": 3,
    r"\b(senior)\s+standing\b": 4,
}

ADMISSION_RE = re.compile(
    r"\b(admission to|admitted to)\s+(.+?)\b(program|plan|degree|major|minor)\b",
    re.IGNORECASE,
)
MAJOR_RE = re.compile(r"\b([A-Z][A-Z0-9&\-/\s]+?)\s+major\b", re.IGNORECASE)
VARIES_BY_TOPIC_RE = re.compile(r"\bvaries\s+(by|with)\s+topic\.?\b", re.IGNORECASE)

MIN_GPA_RE = re.compile(
    r"\b(?:minimum\s+gpa|gpa)\s*(?:of|:)?\s*([0-4](?:\.\d+)?)\b",
    re.IGNORECASE,
)

MIN_CREDITS_RE = re.compile(
    r"\b(?:minimum\s+of|completion\s+of\s+a\s+minimum\s+of)\s*(\d{1,3})\s+credits?\b",
    re.IGNORECASE,
)

COURSE_MIN_GRADE_RE = re.compile(
    r"\b([A-Z]{2,10})\s*([0-9]{1,4}[A-Z]?)\s*(?:with|with a|with an|w/)?\s*(?:a\s+)?(?:minimum\s+)?grade(?:\s+of)?\s*([A-DF][+-]?)",
    re.IGNORECASE,
)

COURSE_MIN_GRADE_OR_BETTER_RE = re.compile(
    r"\b([A-Z]{2,10})\s*([0-9]{1,4}[A-Z]?)\s*(?:with|with a|with an|w/)?\s*(?:a\s+)?grade(?:\s+of)?\s*([A-DF][+-]?)\s*or\s*better\b",
    re.IGNORECASE,
)

def normalize_text(s: str) -> str:
    s = (s or "").replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def detect_eval_policy(prereq_text: str) -> str:
    if re.search(r"\bconcurrent\b", prereq_text or "", flags=re.IGNORECASE):
        return "BEFORE_OR_CONCURRENT"
    return "BEFORE_ONLY"

def extract_min_grade(prereq_text: str) -> Optional[str]:
    m = re.search(
        r"\b(?:grade\s+of\s+)?([A-DF][+-]?)\s*or\s*better\b",
        prereq_text or "",
        flags=re.IGNORECASE,
    )
    return m.group(1).upper() if m else None

def prereq_to_tokens(prereq_text: str) -> List[str]:
    """
    Tokenizes prereq_text into:
      COURSE(SUBJ,NUM)   e.g. COURSE(CSCI,242)
      CONSENT
      GROUP(CSCI,300,399)
      AND / OR / ( / )
    """
    t = normalize_text(prereq_text)
    t = PREREQ_PREFIX_RE.sub("", t)

    if not t or re.fullmatch(r"None\.?", t, flags=re.IGNORECASE):
        return []

    # Example: "Any 300-level computer science course"
    t = re.sub(r"\bAny\s+300-level\s+computer\s+science\s+course\b",
               "GROUP(CSCI,300,399)", t, flags=re.IGNORECASE)

    # Normalize common standing phrases to test tokens
    for pattern, standing in STANDING_REPLACEMENTS.items():
        t = re.sub(pattern, f"TEST(CLASS_STANDING,{standing})", t, flags=re.IGNORECASE)

    # Admission to program/plan/degree/major/minor
    def _admission_token(match: re.Match) -> str:
        detail = normalize_text(match.group(2))
        detail = detail.strip(" .;:()")
        if not detail:
            detail = "PROGRAM"
        detail = re.sub(r"[^A-Z0-9]+", "_", detail.upper()).strip("_")
        return f"TEST(PROGRAM_ADMISSION_{detail},1)"

    t = ADMISSION_RE.sub(_admission_token, t)

    # "<X> major" style
    def _major_token(match: re.Match) -> str:
        detail = normalize_text(match.group(1))
        detail = detail.strip(" .;:()")
        detail = re.sub(r"[^A-Z0-9]+", "_", detail.upper()).strip("_")
        return f"TEST(PROGRAM_ADMISSION_{detail}_MAJOR,1)"

    t = MAJOR_RE.sub(_major_token, t)

    # "Varies by topic" / "Varies with topic"
    t = VARIES_BY_TOPIC_RE.sub("TEST(VARIES_BY_TOPIC,1)", t)

    # Minimum GPA
    def _min_gpa_token(match: re.Match) -> str:
        return f"MINGPA({match.group(1)})"

    t = MIN_GPA_RE.sub(_min_gpa_token, t)

    # Minimum earned credits
    def _min_credits_token(match: re.Match) -> str:
        return f"TEST(CREDITS_EARNED,{match.group(1)})"

    t = MIN_CREDITS_RE.sub(_min_credits_token, t)

    # Course-specific minimum grade clauses
    def _course_min_grade_token(match: re.Match) -> str:
        subj = match.group(1).upper()
        num = match.group(2).upper()
        grade = match.group(3).upper()
        return f"COURSE({subj},{num}):MIN_GRADE={grade}"

    t = COURSE_MIN_GRADE_OR_BETTER_RE.sub(_course_min_grade_token, t)
    t = COURSE_MIN_GRADE_RE.sub(_course_min_grade_token, t)

    # UWP-style semicolons usually mean AND
    t = t.replace(";", " AND ")

    # Normalize "and in" -> AND
    t = re.sub(r"\band\s+in\b", " AND ", t, flags=re.IGNORECASE)

    # Normalize consent/permission phrases
    t = re.sub(r"\b(consent of instructor|instructor permission|permission of instructor)\b",
               " CONSENT ", t, flags=re.IGNORECASE)
    t = re.sub(r"\bprogram advisor consent\b", " CONSENT ", t, flags=re.IGNORECASE)
    t = re.sub(r"\bconsent\b", " CONSENT ", t, flags=re.IGNORECASE)
    t = re.sub(r"\bpermission\b", " CONSENT ", t, flags=re.IGNORECASE)

    # Remove commas/dashes (don’t force AND/OR)
    t = re.sub(r"[,\u2013\u2014]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()

    tokens: List[str] = []
    i = 0
    while i < len(t):
        ch = t[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "()":
            tokens.append(ch)
            i += 1
            continue

        if t.startswith("GROUP(", i):
            j = t.find(")", i)
            if j != -1:
                tokens.append(t[i:j+1])
                i = j + 1
                continue
        if t.startswith("TEST(", i):
            j = t.find(")", i)
            if j != -1:
                tokens.append(t[i:j+1])
                i = j + 1
                continue
        if t.startswith("MINGPA(", i):
            j = t.find(")", i)
            if j != -1:
                tokens.append(t[i:j+1])
                i = j + 1
                continue

        if t[i:i+3].upper() == "AND" and (i+3 == len(t) or t[i+3].isspace()):
            tokens.append("AND")
            i += 3
            continue
        if t[i:i+2].upper() == "OR" and (i+2 == len(t) or t[i+2].isspace()):
            tokens.append("OR")
            i += 2
            continue

        if t[i:i+7].upper() == "CONSENT" and (i+7 == len(t) or t[i+7].isspace()):
            tokens.append("CONSENT")
            i += 7
            continue

        m = COURSE_REF_RE.match(t, i)
        if m:
            subj, num = m.group(1).upper(), m.group(2).upper()
            tokens.append(f"COURSE({subj},{num})")
            i = m.end()
            continue

        nxt = t.find(" ", i)
        i = len(t) if nxt == -1 else nxt + 1

    # Apply a global min-grade if present
    min_grade = extract_min_grade(prereq_text)
    if min_grade and not any(":MIN_GRADE=" in tok for tok in tokens):
        tokens = [tok + f":MIN_GRADE={min_grade}" if tok.startswith("COURSE(") else tok for tok in tokens]

    return [tok for tok in tokens if tok]

def parse_expr(tokens: List[str]) -> Optional[Expr]:
    """
    Shunting-yard parser with precedence AND > OR.
    """
    if not tokens:
        return None

    def is_atom(tok: str) -> bool:
        return (
            tok.startswith("COURSE(")
            or tok == "CONSENT"
            or tok.startswith("GROUP(")
            or tok.startswith("TEST(")
            or tok.startswith("MINGPA(")
        )

    def atom_from(tok: str) -> Expr:
        if tok == "CONSENT":
            return Expr(op="ATOM", children=[], atom=Atom(kind="CONSENT"))
        if tok.startswith("GROUP("):
            inside = tok[len("GROUP("):-1]
            parts = [p for p in re.split(r"[,\s]+", inside.strip()) if p]
            if len(parts) != 3:
                raise ValueError(tok)
            subj, lo, hi = parts
            return Expr(op="ATOM", children=[], atom=Atom(
                kind="COURSE_GROUP",
                group_subject=subj.strip().upper(),
                group_min_level=int(lo),
                group_max_level=int(hi),
            ))
        if tok.startswith("TEST("):
            inside = tok[len("TEST("):-1]
            parts = [p for p in re.split(r"[,\s]+", inside.strip(), maxsplit=1) if p]
            if len(parts) != 2:
                raise ValueError(tok)
            name, score = parts[0].strip().upper(), parts[1].strip()
            return Expr(op="ATOM", children=[], atom=Atom(
                kind="TEST_SCORE",
                test_name=name,
                min_score=float(score),
            ))
        if tok.startswith("MINGPA("):
            inside = tok[len("MINGPA("):-1]
            return Expr(op="ATOM", children=[], atom=Atom(
                kind="MIN_GPA",
                min_gpa=float(inside.strip()),
            ))
        if tok.startswith("COURSE("):
            min_grade = None
            if ":MIN_GRADE=" in tok:
                tok, mg = tok.split(":MIN_GRADE=", 1)
                min_grade = mg.strip().upper()
            inside = tok[len("COURSE("):-1]
            subj, num = [x.strip().upper() for x in inside.split(",")]
            return Expr(op="ATOM", children=[], atom=Atom(
                kind="COURSE",
                course=CourseRef(subject=subj, number=num, min_grade=min_grade),
            ))
        raise ValueError(tok)

    prec = {"OR": 1, "AND": 2}
    ops: List[str] = []
    out: List[Union[str, Expr]] = []

    for tok in tokens:
        if is_atom(tok):
            out.append(atom_from(tok))
        elif tok in ("AND", "OR"):
            while ops and ops[-1] in prec and prec[ops[-1]] >= prec[tok]:
                out.append(ops.pop())
            ops.append(tok)
        elif tok == "(":
            ops.append(tok)
        elif tok == ")":
            while ops and ops[-1] != "(":
                out.append(ops.pop())
            if ops and ops[-1] == "(":
                ops.pop()
            else:
                # Unmatched closing paren; ignore
                continue

    while ops:
        op = ops.pop()
        if op in prec:
            out.append(op)

    # RPN to AST
    stack: List[Expr] = []
    for item in out:
        if isinstance(item, Expr):
            stack.append(item)
        else:
            op = item
            if op not in prec:
                continue
            if len(stack) < 2:
                continue
            b = stack.pop()
            a = stack.pop()

            children: List[Expr] = []
            if a.op == op:
                children.extend(a.children)
            else:
                children.append(a)
            if b.op == op:
                children.extend(b.children)
            else:
                children.append(b)

            stack.append(Expr(op=op, children=children))

    return stack[0] if stack else None


# ----------------------------
# Supabase helpers
# ----------------------------

def sb_one(resp, context: str):
    if getattr(resp, "error", None):
        raise RuntimeError(f"{context}: {resp.error}")
    data = resp.data
    if not data:
        return None
    return data[0]

def ensure_course_id(sb, subject: str, number: str) -> int:
    # Try find existing
    resp = (
        sb.table("courses")
        .select("id")
        .eq("subject", subject)
        .eq("number", number)
        .limit(1)
        .execute()
    )
    row = sb_one(resp, f"select course {subject} {number}")
    if row:
        return int(row["id"])

    # Create stub (requires UNIQUE(subject,number) in DB for clean upserts)
    stub = {
        "subject": subject,
        "number": number,
        "title": f"{subject} {number} (stub)",
        "credits": 0,
        "description": "Placeholder created from prereq reference.",
    }
    resp2 = (
        sb.table("courses")
        .upsert(stub, on_conflict="subject,number")
        .execute()
    )
    row2 = sb_one(resp2, f"upsert stub course {subject} {number}")
    return int(row2["id"])

def delete_existing_prereqs(sb, course_id: int) -> None:
    # If FK cascade is set (recommended), deleting sets removes nodes/atoms.
    resp = (
        sb.table("course_req_sets")
        .delete()
        .eq("course_id", course_id)
        .eq("set_type", "PREREQ")
        .execute()
    )
    if getattr(resp, "error", None):
        raise RuntimeError(f"delete prereq sets for course_id={course_id}: {resp.error}")

def insert_req_set(sb, course_id: int, eval_policy: str, note: str) -> int:
    payload = {
        "course_id": course_id,
        "set_type": "PREREQ",
        "eval_policy": eval_policy,
        "note": (note[:500] if note else None),
    }
    resp = sb.table("course_req_sets").insert(payload).execute()
    row = sb_one(resp, "insert course_req_sets")
    return int(row["id"])

def insert_node(sb, req_set_id: int, node_type: str, parent_id: Optional[int], sort_order: int) -> int:
    payload = {
        "req_set_id": req_set_id,
        "node_type": node_type,
        "parent_id": parent_id,
        "sort_order": sort_order,
    }
    resp = sb.table("course_req_nodes").insert(payload).execute()
    row = sb_one(resp, "insert course_req_nodes")
    return int(row["id"])

def insert_atom_course(sb, node_id: int, required_course_id: int, min_grade: Optional[str]) -> None:
    payload = {
        "node_id": node_id,
        "atom_type": "COURSE",
        "required_course_id": required_course_id,
        "min_grade": min_grade,
    }
    resp = sb.table("course_req_atoms").insert(payload).execute()
    if getattr(resp, "error", None):
        raise RuntimeError(f"insert course atom node_id={node_id}: {resp.error}")

def insert_atom_consent(sb, node_id: int) -> None:
    payload = {"node_id": node_id, "atom_type": "CONSENT"}
    resp = sb.table("course_req_atoms").insert(payload).execute()
    if getattr(resp, "error", None):
        raise RuntimeError(f"insert consent atom node_id={node_id}: {resp.error}")

def insert_atom_group(sb, node_id: int, subject: str, lo: int, hi: int) -> None:
    payload = {
        "node_id": node_id,
        "atom_type": "COURSE_GROUP",
        "group_subject": subject,
        "group_min_level": lo,
        "group_max_level": hi,
    }
    resp = sb.table("course_req_atoms").insert(payload).execute()
    if getattr(resp, "error", None):
        raise RuntimeError(f"insert group atom node_id={node_id}: {resp.error}")

def insert_atom_test_score(sb, node_id: int, test_name: str, min_score: float) -> None:
    payload = {
        "node_id": node_id,
        "atom_type": "TEST_SCORE",
        "test_name": test_name,
        "min_score": min_score,
    }
    resp = sb.table("course_req_atoms").insert(payload).execute()
    if getattr(resp, "error", None):
        raise RuntimeError(f"insert test score atom node_id={node_id}: {resp.error}")

def insert_atom_min_gpa(sb, node_id: int, min_gpa: float) -> None:
    payload = {
        "node_id": node_id,
        "atom_type": "MIN_GPA",
        "min_gpa": min_gpa,
    }
    resp = sb.table("course_req_atoms").insert(payload).execute()
    if getattr(resp, "error", None):
        raise RuntimeError(f"insert min gpa atom node_id={node_id}: {resp.error}")

def insert_tree(sb, course_id: int, expr: Expr, eval_policy: str, note: str) -> None:
    delete_existing_prereqs(sb, course_id)
    req_set_id = insert_req_set(sb, course_id, eval_policy, note)

    def add_node(parent_id: Optional[int], node: Expr, sort_order: int) -> int:
        node_type = "ATOM" if node.op == "ATOM" else node.op
        node_id = insert_node(sb, req_set_id, node_type, parent_id, sort_order)

        if node_type == "ATOM" and node.atom:
            a = node.atom
            if a.kind == "CONSENT":
                insert_atom_consent(sb, node_id)
            elif a.kind == "COURSE" and a.course:
                req_course_id = ensure_course_id(sb, a.course.subject, a.course.number)
                insert_atom_course(sb, node_id, req_course_id, a.course.min_grade)
            elif a.kind == "COURSE_GROUP":
                insert_atom_group(sb, node_id, a.group_subject, a.group_min_level, a.group_max_level)
            elif a.kind == "TEST_SCORE":
                insert_atom_test_score(sb, node_id, a.test_name, a.min_score)
            elif a.kind == "MIN_GPA":
                insert_atom_min_gpa(sb, node_id, a.min_gpa)
        else:
            for idx, child in enumerate(node.children):
                add_node(node_id, child, idx)

        return node_id

    add_node(None, expr, 0)


# ----------------------------
# Main
# ----------------------------

def main() -> None:
    sb = get_connection()

    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--source",
        default="auto",
        choices=["auto", "courses", "log"],
        help="Source of prereq text: courses (courses.prereq_text), log (prereq_parse_log), or auto.",
    )
    ap.add_argument(
        "--cleanup-log",
        action="store_true",
        help="If set and source is log, delete prereq_parse_log rows after successful parse.",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional max number of rows to process (0 = no limit).",
    )
    ap.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Optional row offset for pagination (default 0).",
    )
    ap.add_argument(
        "--progress-every",
        type=int,
        default=50,
        help="Print progress every N rows (default 50).",
    )
    args = ap.parse_args()

    def fetch_from_courses() -> List[dict]:
        query = (
            sb.table("courses")
            .select("id, subject, number, prereq_text")
            .not_.is_("prereq_text", "null")
        )
        if args.limit and args.limit > 0:
            query = query.range(args.offset, args.offset + args.limit - 1)
        resp = query.execute()
        if getattr(resp, "error", None):
            raise RuntimeError(f"fetch courses: {resp.error}")
        return resp.data or []

    def fetch_from_log() -> List[dict]:
        query = sb.table("prereq_parse_log").select("course_id, prereq_text")
        if args.limit and args.limit > 0:
            query = query.range(args.offset, args.offset + args.limit - 1)
        resp = query.execute()
        if getattr(resp, "error", None):
            raise RuntimeError(f"fetch prereq_parse_log: {resp.error}")
        rows = resp.data or []
        out = []
        for r in rows:
            out.append(
                {
                    "id": r["course_id"],
                    "subject": None,
                    "number": None,
                    "prereq_text": r.get("prereq_text"),
                }
            )
        return out

    rows: List[dict] = []
    if args.source == "courses":
        rows = fetch_from_courses()
    elif args.source == "log":
        rows = fetch_from_log()
    else:
        try:
            rows = fetch_from_courses()
        except RuntimeError:
            rows = fetch_from_log()
    built = 0
    skipped = 0

    for idx, r in enumerate(rows, start=1):
        course_id = int(r["id"])
        prereq_text = (r.get("prereq_text") or "").strip()

        if not prereq_text or prereq_text.lower().startswith("none"):
            continue

        tokens = prereq_to_tokens(prereq_text)
        expr = parse_expr(tokens)
        if expr is None:
            skipped += 1
            continue

        eval_policy = detect_eval_policy(prereq_text)
        insert_tree(sb, course_id, expr, eval_policy, prereq_text)
        built += 1

        if args.cleanup_log and args.source in ("log", "auto"):
            sb.table("prereq_parse_log").delete().eq("course_id", course_id).execute()

        if args.progress_every and idx % args.progress_every == 0:
            print(f"Processed {idx}/{len(rows)} rows (built={built}, skipped={skipped})")

    print(f"Built prereq trees for {built} courses. Skipped {skipped} (couldn't parse).")


if __name__ == "__main__":
    main()
