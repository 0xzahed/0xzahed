#!/usr/bin/env python3
"""Refresh the auto-generated (terminal-style) sections of README.md from the GitHub API."""
import json
import os
import re
import urllib.request
from datetime import datetime, timedelta, timezone

USER = "0xzahed"
EXCLUDE = {USER, "chorcha-security-audit"}
# Hand-written one-liners; repos not listed fall back to their GitHub description.
BLURBS = {
    "portfolio": "Cinematic personal site",
    "banglacaption": "Bangla caption generator",
    "leadghar": "Lead management platform",
    "travelbook": "Travel booking experience",
    "clinicq": "Clinic queue system",
    "restaruant": "Restaurant web app",
}
NOT_LANGS = {"Makefile", "Jupyter Notebook", "Dockerfile", "Shell", "Batchfile", "Blade"}
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


def total_contributions(created_year):
    """All-time contributions (public + private) since the account was created."""
    now = datetime.now(timezone.utc)
    total = 0
    for y in range(created_year, now.year + 1):
        end = now.strftime("%Y-%m-%dT%H:%M:%SZ") if y == now.year else f"{y}-12-31T23:59:59Z"
        u = gql(
            f'{{user(login:"{USER}"){{contributionsCollection(from:"{y}-01-01T00:00:00Z",to:"{end}")'
            "{contributionCalendar{totalContributions}}}}"
        )
        total += u["contributionsCollection"]["contributionCalendar"]["totalContributions"]
    return total


def current_streak():
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=364)).strftime("%Y-%m-%dT00:00:00Z")
    u = gql(
        f'{{user(login:"{USER}"){{contributionsCollection(from:"{start}",to:"{now.strftime("%Y-%m-%dT%H:%M:%SZ")}")'
        "{contributionCalendar{weeks{contributionDays{date contributionCount}}}}}}"
    )
    days = [d for w in u["contributionsCollection"]["contributionCalendar"]["weeks"] for d in w["contributionDays"]]
    counts = [d["contributionCount"] for d in days if d["date"] <= now.strftime("%Y-%m-%d")]
    if counts and counts[-1] == 0:  # today not contributed yet: streak is still alive
        counts.pop()
    streak = 0
    for c in reversed(counts):
        if c == 0:
            break
        streak += 1
    return streak


def language_share(repos, top=4):
    sizes = {}
    for r in repos:
        if r["fork"] or r["name"] in EXCLUDE:
            continue
        for lang, n in get(f"/repos/{USER}/{r['name']}/languages").items():
            if lang not in NOT_LANGS:
                sizes[lang] = sizes.get(lang, 0) + n
    total = sum(sizes.values()) or 1
    return [(k, v / total * 100) for k, v in sorted(sizes.items(), key=lambda x: -x[1])[:top]]


def ago(iso):
    secs = (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds()
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return f"{int(secs // size)}{unit} ago"
    return "just now"


def stats_block(user, repos, total, streak, langs):
    lines = ["```text"]
    for name, pct in langs:
        filled = round(pct / 5)
        lines.append(f"{name:<12} {'█' * filled}{'░' * (20 - filled)} {pct:>3.0f}%")
    lines.append("```")
    cells = [(f"{total:,}", "contributions"), (str(streak), "day streak"),
             (str(user["public_repos"]), "repos"), (str(user["followers"]), "followers")]
    head = "| " + " | ".join(f"**{v}**" for v, _ in cells) + " |"
    sub = "| " + " | ".join(l for _, l in cells) + " |"
    table = [head, "|" + ":-:|" * 4, sub]  # numbers on top, labels below
    return "\n".join(lines) + "\n\n" + "\n".join(table)


def projects_block(repos, n=6):
    picked = [r for r in repos if not r["fork"] and not r["archived"] and r["name"] not in EXCLUDE][:n]
    cells = []
    for r in picked:
        desc = BLURBS.get(r["name"]) or (r["description"] or "").strip() or "Work in progress"
        lang = f"● {r['language']}" if r["language"] else "● —"
        cells.append(
            f'<td valign="top" width="33%"><b>▸ <a href="{r["html_url"]}">{r["name"]}</a></b><br/>'
            f"<sub>{desc}</sub><br/><sub>{lang} · {ago(r['pushed_at'])}</sub></td>"
        )
    while len(cells) % 3:
        cells.append('<td width="33%"></td>')
    rows = [f"  <tr>{''.join(cells[i:i + 3])}</tr>" for i in range(0, len(cells), 3)]
    return "<table>\n" + "\n".join(rows) + "\n</table>"


def activity_block(events, n=6):
    verbs = {"PushEvent": "push", "PullRequestEvent": "pr", "IssuesEvent": "issue", "ReleaseEvent": "release",
             "ForkEvent": "fork", "WatchEvent": "star"}
    lines, seen = [], set()
    for e in events:
        name = e["repo"]["name"]
        if name.split("/")[-1] in EXCLUDE:
            continue
        t = e["type"]
        verb = "create" if t == "CreateEvent" and e["payload"].get("ref_type") == "repository" else verbs.get(t)
        if not verb or (verb, name) in seen:
            continue
        seen.add((verb, name))
        lines.append(f"{verb:<8} {name:<34} {ago(e['created_at'])}")
        if len(lines) == n:
            break
    return "```text\n" + ("\n".join(lines) or "no recent public activity") + "\n```"


def replace(text, name, body):
    pattern = re.compile(rf"(<!--{name}:START-->).*?(<!--{name}:END-->)", re.S)
    if not pattern.search(text):
        raise SystemExit(f"marker {name} missing in README.md")
    return pattern.sub(lambda m: f"{m.group(1)}\n{body}\n{m.group(2)}", text)


def main():
    user = get(f"/users/{USER}")
    repos = get(f"/users/{USER}/repos?per_page=100&sort=pushed&type=owner")
    events = get(f"/users/{USER}/events/public?per_page=50")
    total = total_contributions(int(user["created_at"][:4]))
    with open("README.md", encoding="utf-8") as f:
        text = f.read()
    text = replace(text, "STATS", stats_block(user, repos, total, current_streak(), language_share(repos)))
    text = replace(text, "PROJECTS", projects_block(repos))
    text = replace(text, "ACTIVITY", activity_block(events))
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    main()
