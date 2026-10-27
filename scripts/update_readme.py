#!/usr/bin/env python3
"""Refresh the auto-generated sections of README.md from the GitHub API."""
import json
import os
import re
import urllib.request
from urllib.parse import quote
from datetime import datetime, timezone

USER = "0xzahed"
EXCLUDE = {USER, "chorcha-security-audit"}
API = "https://api.github.com"
TOKEN = os.environ.get("GITHUB_TOKEN", "")


def get(path):
    req = urllib.request.Request(API + path, headers={"Accept": "application/vnd.github+json"})
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)


def gql(query):
    req = urllib.request.Request(
        API + "/graphql", data=json.dumps({"query": query}).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)["data"]["user"]


def contributions(created_year):
    """Per-year totals (public + private) since the account was created."""
    now = datetime.now(timezone.utc)
    years = {}
    for y in range(created_year, now.year + 1):
        end = now.strftime("%Y-%m-%dT%H:%M:%SZ") if y == now.year else f"{y}-12-31T23:59:59Z"
        u = gql(
            f'{{user(login:"{USER}"){{contributionsCollection(from:"{y}-01-01T00:00:00Z",to:"{end}")'
            "{totalCommitContributions restrictedContributionsCount "
            "contributionCalendar{totalContributions}}}}"
        )["contributionsCollection"]
        years[y] = (u["contributionCalendar"]["totalContributions"], u["totalCommitContributions"] + u["restrictedContributionsCount"])
    return years


def contrib_section(years):
    total = sum(v[0] for v in years.values())
    peak = max(v[0] for v in years.values()) or 1
    this_year = years[max(years)][0]
    top = (
        f"<p align=\"center\">{badge('all-time contributions', f'{total:,}', '2B90FF', 'github')} "
        f"{badge(f'{max(years)}', f'{this_year:,}', '3C7DD9')} "
        f"{badge('active since', str(min(years)), '64A1F4')}</p>"
    )
    rows = ["| Year | Contributions | |", "|---|---:|:--|"]
    for y in sorted(years, reverse=True):
        n = years[y][0]
        bar = "█" * max(1, round(n / peak * 24)) if n else ""
        rows.append(f"| {y} | {n:,} | `{bar}` |")
    return top + "\n\n" + "\n".join(rows)


def ago(iso):
    secs = (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds()
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return f"{int(secs // size)}{unit} ago"
    return "just now"


def link(repo):
    return f"[{repo.split('/')[-1]}](https://github.com/{repo})"


LANG_COLORS = {
    "TypeScript": "3178C6", "JavaScript": "F7DF1E", "Python": "3776AB", "HTML": "E34F26",
    "Dart": "0175C2", "Go": "00ADD8", "EJS": "A91E50", "CSS": "1572B6",
}


def badge(label, message, color, logo=""):
    esc = lambda v: quote(v.replace("-", "--").replace("_", "__"), safe="")
    url = f"https://img.shields.io/badge/{esc(label)}-{esc(message)}-{color}?style=flat-square"
    return f'<img src="{url}{"&logo=" + logo if logo else ""}" alt="{label}" />'


def card(r):
    desc = (r["description"] or "").strip() or "Work in progress"
    tags = [badge("", r["language"], LANG_COLORS.get(r["language"], "555555"))] if r["language"] else []
    tags.append(badge("updated", ago(r["pushed_at"]), "2B90FF"))
    if r["stargazers_count"]:
        tags.append(badge("stars", str(r["stargazers_count"]), "E3B341", "github"))
    site = r.get("homepage")
    links = f'<a href="{r["html_url"]}">Repository</a>' + (f' · <a href="{site}">Live demo</a>' if site else "")
    return (
        '<td valign="top" width="50%">'
        f'<b><a href="{r["html_url"]}">📁 {r["name"]}</a></b><br/>'
        f'<sub>{desc}</sub><br/><br/>{" ".join(tags)}<br/><sub>{links}</sub></td>'
    )


def latest_repos(repos, n=6):
    picked = [r for r in repos if not r["fork"] and not r["archived"] and r["name"] not in EXCLUDE][:n]
    cards = [card(r) for r in picked]
    if len(cards) % 2:
        cards.append('<td width="50%"></td>')
    rows = [f"  <tr>{cards[i]}{cards[i + 1]}</tr>" for i in range(0, len(cards), 2)]
    return "<table>\n" + "\n".join(rows) + "\n</table>"


def activity(events, n=8):
    lines, seen = [], set()
    for e in events:
        repo, t, p = e["repo"]["name"], e["type"], e.get("payload", {})
        if repo.split("/")[-1] in EXCLUDE:
            continue
        if t == "PushEvent":
            text = f"⬆️ Pushed to {link(repo)}"
        elif t == "PullRequestEvent":
            text = f"🔀 {p.get('action', 'updated').capitalize()} PR in {link(repo)}"
        elif t == "IssuesEvent":
            text = f"🐞 {p.get('action', 'updated').capitalize()} issue in {link(repo)}"
        elif t == "CreateEvent" and p.get("ref_type") == "repository":
            text = f"✨ Created {link(repo)}"
        elif t == "ReleaseEvent":
            text = f"🚀 Released {link(repo)}"
        elif t == "ForkEvent":
            text = f"🍴 Forked {link(repo)}"
        elif t == "WatchEvent":
            text = f"⭐ Starred {link(repo)}"
        else:
            continue
        if text in seen:
            continue
        seen.add(text)
        lines.append(f"- {text} · <sub>{ago(e['created_at'])}</sub>")
        if len(lines) == n:
            break
    return "\n".join(lines) or "- No recent public activity"


def overview(user, repos, total):
    stars = sum(r["stargazers_count"] for r in repos)
    langs = {}
    for r in repos:
        if r["language"] and not r["fork"]:
            langs[r["language"]] = langs.get(r["language"], 0) + 1
    top = ", ".join(f"{k} ({v})" for k, v in sorted(langs.items(), key=lambda x: -x[1])[:4])
    return (
        f"📦 **{user['public_repos']}** public repos · 👥 **{user['followers']}** followers · "
        f"🔥 **{total:,}** contributions · ⭐ **{stars}** stars · 🔤 Top languages: {top}"
    )


def replace(text, name, body):
    pattern = re.compile(rf"(<!--{name}:START-->).*?(<!--{name}:END-->)", re.S)
    if not pattern.search(text):
        raise SystemExit(f"marker {name} missing in README.md")
    return pattern.sub(lambda m: f"{m.group(1)}\n{body}\n{m.group(2)}", text)


def main():
    user = get(f"/users/{USER}")
    repos = get(f"/users/{USER}/repos?per_page=100&sort=pushed&type=owner")
    events = get(f"/users/{USER}/events/public?per_page=50")
    with open("README.md", encoding="utf-8") as f:
        text = f.read()
    years = contributions(int(user["created_at"][:4]))
    text = replace(text, "OVERVIEW", overview(user, repos, sum(v[0] for v in years.values())))
    text = replace(text, "CONTRIB", contrib_section(years))
    text = replace(text, "PROJECTS", latest_repos(repos))
    text = replace(text, "ACTIVITY", activity(events))
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    main()
