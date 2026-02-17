#!/usr/bin/env python3
from __future__ import annotations

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
    kind: str  # COURSE | CONSENT | COURSE_GROUP
    course: Optional[CourseRef] = None
    group_subject: Optional[str] = None
    group_min_level: Optional[int] = None
    group_max_level: Optional[int] = None


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

def normalize_text(s: str) -> str:
    s = (s or "").replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def detect_eval_policy(prereq_text: str) -> str:
    if re.search(r"\bconcurrent\b", prereq_text or "", flags=re.IGNORECASE):
        return "BEFORE_OR_CONCURRENT"
    return "BEFORE_ONLY"

def extract_min_grade(prereq_text: str) -> Optional[str]:
    m = re.search(r"\b([A-DF][+-]?)\s*or\s*better\b", prereq_text or "", flags=re.IGNORECASE)
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

    # UWP-style semicolons usually mean AND
    t = t.replace(";", " AND ")

    # Normalize "and in" -> AND
    t = re.sub(r"\band\s+in\b", " AND ", t, flags=re.IGNORECASE)

    # Normalize consent/permission phrases
    t = re.sub(r"\b(consent of instructor|instructor permission|permission of instructor)\b",
               " CONSENT ", t, flags=re.IGNORECASE)
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
    if min_grade:
        tokens = [tok + f":MIN_GRADE={min_grade}" if tok.startswith("COURSE(") else tok for tok in tokens]

    return [tok for tok in tokens if tok]

def parse_expr(tokens: List[str]) -> Optional[Expr]:
    """
    Shunting-yard parser with precedence AND > OR.
    """
    if not tokens:
        return None

    def is_atom(tok: str) -> bool:
        return tok.startswith("COURSE(") or tok == "CONSENT" or tok.startswith("GROUP(")

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
        "prereq_text": None,
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

    # Fetch all courses with prereq_text
    resp = (
        sb.table("courses")
        .select("id, subject, number, prereq_text")
        .not_.is_("prereq_text", "null")
        .execute()
    )
    if getattr(resp, "error", None):
        raise RuntimeError(f"fetch courses: {resp.error}")

    rows = resp.data or []
    built = 0
    skipped = 0

    for r in rows:
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

    print(f"Built prereq trees for {built} courses. Skipped {skipped} (couldn't parse).")


if __name__ == "__main__":
    main()
