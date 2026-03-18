import pathlib
import sys


# Ensure project root and src are on the import path
ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from class_scrapper import (  # noqa: E402
    _clean_offered_text,
    _clean_prereq_text,
    discover_course_links,
    fetch_html,
    is_course_descriptions_index,
    parse_courseblock,
    parse_courses,
    parse_offered_terms,
    sql_escape_literal,
)


def test_parse_courses_from_courseblocks():
    html = """
    <html>
      <body>
        <div class="courseblock">
          <p class="courseblocktitle">CSCI 241 | Computer Science I | 5 cr</p>
          <div class="courseblockdesc">
            <p>Introduction to programming.</p>
            <p>Prerequisites: CSCI 140 and MATH 221.</p>
            <p>Offered: Fall, Spring.</p>
          </div>
        </div>
        <div class="courseblock">
          <p class="courseblocktitle">CSCI 300 | Topics | 3 cr</p>
          <div class="courseblockdesc">
            <p>Special topics.</p>
            <p><strong>Prerequisites:</strong> Consent of instructor.</p>
          </div>
        </div>
      </body>
    </html>
    """

    courses = parse_courses(html)
    assert len(courses) == 2

    c1 = courses[0]
    assert c1.subject == "CSCI"
    assert c1.number == "241"
    assert c1.title == "Computer Science I"
    assert c1.credits == 5.0
    assert "Introduction to programming." in c1.description
    assert c1.prereq_text == "CSCI 140 and MATH 221."
    assert c1.offered_text == "Fall, Spring."

    c2 = courses[1]
    assert c2.subject == "CSCI"
    assert c2.number == "300"
    assert c2.title == "Topics"
    assert c2.credits == 3.0
    assert "Special topics." in c2.description
    assert c2.prereq_text == "Consent of instructor."
    assert c2.offered_text is None


def test_parse_courses_new_uwp_layout():
    html = """
    <div class="courseblock">
      <div class="cols noindent">
        <span class="text detail-titlerow">
          <h4>
            <span class="detail-code text--semibold">CSCI 105</span> |
            <span class="detail-title text--semibold">Introduction to Computers</span> |
            <span class="detail-hours_html text--semibold">3 cr</span>
          </h4>
        </span>
      </div>
      <div class="noindent">
        <p class="courseblockextra noindent">Explores computer components.</p>
      </div>
      <div class="noindent">
        <p class="courseblockextra noindent">
          <span><strong>Prerequisites:</strong> None.</span>
        </p>
      </div>
      <div class="noindent">
        <p class="courseblockextra noindent">Offered: Occasionally.</p>
      </div>
    </div>
    """

    courses = parse_courses(html)
    assert len(courses) == 1
    c = courses[0]
    assert c.subject == "CSCI"
    assert c.number == "105"
    assert c.title == "Introduction to Computers"
    assert c.credits == 3.0
    assert "Explores computer components." in c.description
    assert c.prereq_text == "None."
    assert c.offered_text == "Occasionally."


def test_parse_courseblock_returns_none_for_unmatched_header():
    html = """
    <div class="courseblock">
      <p class="courseblocktitle">Not a real header</p>
      <div class="courseblockdesc"><p>Some text.</p></div>
    </div>
    """

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    block = soup.select_one(".courseblock")
    assert parse_courseblock(block) is None


def test_sql_escape_literal_quotes():
    assert sql_escape_literal("O'Reilly") == "O''Reilly"


def test_parse_offered_terms_handles_special_cases_and_even_odd():
    assert parse_offered_terms("Fall (odd years), Spring (even years), Winterim, Yearly, Occasionally.") == [
        "OCCASIONALLY",
        "YEARLY",
        "WINTERIM",
        "FALL_ODD",
        "SPRING_EVEN",
    ]
    assert parse_offered_terms("Fall, Spring, Summer.") == ["FALL", "SPRING", "SUMMER"]
    assert parse_offered_terms(None) == []


def test_discover_course_links_and_index_detection():
    html = """
    <a href="/course-descriptions/csci/">CSCI</a>
    <a href="https://catalog.uwp.edu/course-descriptions/math/">MATH</a>
    <a href="/not-course-descriptions/">Ignore</a>
    <a href="mailto:test@example.com">Mail</a>
    <a href="/course-descriptions/csci/">Duplicate</a>
    """
    links = discover_course_links("https://catalog.uwp.edu/course-descriptions/", html)
    assert links == [
        "https://catalog.uwp.edu/course-descriptions/csci/",
        "https://catalog.uwp.edu/course-descriptions/math/",
    ]
    assert is_course_descriptions_index("https://catalog.uwp.edu/course-descriptions/")
    assert not is_course_descriptions_index("https://catalog.uwp.edu/course-descriptions/csci/")


def test_clean_text_helpers():
    assert _clean_prereq_text(" none ") is None
    assert _clean_prereq_text(" CSCI 241 ") == "CSCI 241"
    assert _clean_offered_text("  Fall, Spring.  ") == "Fall, Spring."
    assert _clean_offered_text("   ") is None


def test_parse_courses_fallback_header_parser_and_dedupes():
    html = """
    <html><body>
      <div>CSCI 241 | Computer Science I | 5 cr</div>
      <div>CSCI 241 | Computer Science I | 5 cr</div>
      <div>MATH 221 | Calculus I | 5 cr</div>
    </body></html>
    """
    courses = parse_courses(html)
    assert len(courses) == 2
    assert {(c.subject, c.number) for c in courses} == {("CSCI", "241"), ("MATH", "221")}


@pytest.mark.integration
def test_parse_live_uwp_catalog():
    url = "https://catalog.uwp.edu/course-descriptions/csci/"
    html = fetch_html(url, timeout=30)
    courses = parse_courses(html)
    assert len(courses) > 0
