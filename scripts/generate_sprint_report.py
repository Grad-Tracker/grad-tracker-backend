#!/usr/bin/env python3
import argparse
import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request


def iso_day_start(date_str: str) -> str:
    return f"{date_str}T00:00:00Z"


def iso_day_end(date_str: str) -> str:
    return f"{date_str}T23:59:59Z"


def http_get_json(url: str, token: str):
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def paginate_search(token: str, url: str):
    items = []
    page = 1
    while True:
        page_url = f"{url}&per_page=100&page={page}"
        data = http_get_json(page_url, token)
        items.extend(data.get("items", []))
        if len(data.get("items", [])) < 100:
            break
        page += 1
    return items


def paginate_commits(token: str, url: str):
    items = []
    page = 1
    while True:
        page_url = f"{url}&per_page=100&page={page}"
        data = http_get_json(page_url, token)
        if not isinstance(data, list):
            break
        items.extend(data)
        if len(data) < 100:
            break
        page += 1
    return items


def fetch_pr_details(token: str, owner: str, repo: str, number: int):
    pr = http_get_json(f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}", token)
    reviews = http_get_json(
        f"https://api.github.com/repos/{owner}/{repo}/pulls/{number}/reviews",
        token,
    )
    reviewers = []
    if isinstance(reviews, list):
        seen = set()
        for r in reviews:
            user = (r.get("user") or {}).get("login")
            if user and user not in seen:
                reviewers.append(user)
                seen.add(user)
    if not reviewers:
        requested = pr.get("requested_reviewers") or []
        reviewers = [r.get("login") for r in requested if r.get("login")]
    return pr, reviewers


def main():
    parser = argparse.ArgumentParser(description="Generate Sprint GitHub Report (.md).")
    parser.add_argument("--owner", required=True, help="GitHub org/user, e.g. Grad-Tracker")
    parser.add_argument("--repo", required=True, help="GitHub repo, e.g. grad-tracker-backend")
    parser.add_argument("--username", required=True, help="GitHub username to filter")
    parser.add_argument("--name", required=True, help="Display name for report title")
    parser.add_argument("--sprint", required=True, type=int, help="Sprint number")
    parser.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    parser.add_argument("--out", required=True, help="Output .md path")
    args = parser.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Missing GITHUB_TOKEN env var", file=sys.stderr)
        sys.exit(1)

    repo_url = f"https://github.com/{args.owner}/{args.repo}"

    merged_query = (
        f"is:pr is:merged repo:{args.owner}/{args.repo} "
        f"author:{args.username} merged:{args.start}..{args.end}"
    )
    search_url = (
        "https://api.github.com/search/issues?q="
        + urllib.parse.quote(merged_query)
    )
    prs = paginate_search(token, search_url)

    pr_rows = []
    for pr in prs:
        number = pr.get("number")
        if number is None:
            continue
        pr_data, reviewers = fetch_pr_details(token, args.owner, args.repo, number)
        pr_rows.append(
            {
                "title": pr_data.get("title"),
                "html_url": pr_data.get("html_url"),
                "author": (pr_data.get("user") or {}).get("login"),
                "reviewers": reviewers,
                "merged_at": pr_data.get("merged_at"),
            }
        )

    pr_rows.sort(key=lambda r: r.get("merged_at") or "")

    commit_url = (
        f"https://api.github.com/repos/{args.owner}/{args.repo}/commits"
        f"?author={urllib.parse.quote(args.username)}"
        f"&since={iso_day_start(args.start)}"
        f"&until={iso_day_end(args.end)}"
    )
    commits = paginate_commits(token, commit_url)
    commit_dates = []
    for c in commits:
        date_str = ((c.get("commit") or {}).get("author") or {}).get("date")
        if date_str:
            commit_dates.append(date_str)

    commit_dates.sort()
    date_range = "N/A"
    if commit_dates:
        first = commit_dates[0][:10]
        last = commit_dates[-1][:10]
        date_range = f"{first} to {last}"

    lines = []
    lines.append(f"# Sprint {args.sprint} GitHub Report - {args.name}")
    lines.append("")
    lines.append(f"Repository URL: {repo_url}")
    lines.append("")
    lines.append(f"PRs Merged During Sprint ({args.start} to {args.end})")
    lines.append("")
    if pr_rows:
        for pr in pr_rows:
            lines.append(f"- PR Title: {pr['title']}")
            lines.append(f"- PR Link: {pr['html_url']}")
            lines.append(f"- Author: {pr['author']}")
            lines.append(
                f"- Reviewers: {', '.join(pr['reviewers']) if pr['reviewers'] else 'None'}"
            )
            lines.append(f"- Merge Date: {pr['merged_at'][:10] if pr['merged_at'] else 'N/A'}")
            lines.append("")
    else:
        lines.append("- None")
        lines.append("")

    lines.append("Commit Activity (Author: " + args.username + ")")
    lines.append("")
    lines.append(f"- Total number of commits: {len(commits)}")
    lines.append(f"- Date range: {date_range}")
    lines.append("")

    out_path = args.out
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")

    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
