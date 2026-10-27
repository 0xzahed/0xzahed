#!/usr/bin/env python3
"""Refresh the auto-generated sections of README.md from the GitHub API."""
import json
import os
import re
import urllib.request
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


def ago(iso):
    secs = (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds()
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if secs >= size:
            return f"{int(secs // size)}{unit} ago"
    return "just now"


def link(repo):
    return f"[{repo.split('/')[-1]}](https://github.com/{repo})"


def latest_repos(repos, n=6):
    picked = [r for r in repos if not r["fork"] and not r["archived"] and r["name"] not in EXCLUDE][:n]
    rows = ["| Project | Stack | Updated |", "|---|---|---|"]
    for r in picked:
        desc = (r["description"] or "").strip()
        name = f"**[{r['name']}]({r['html_url']})**" + (f"<br/><sub>{desc}</sub>" if desc else "")
        rows.append(f"| {name} | {r['language'] or '—'} | {ago(r['pushed_at'])} |")
    return "\n".join(rows)


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


def overview(user, repos):
    stars = sum(r["stargazers_count"] for r in repos)
    langs = {}
    for r in repos:
        if r["language"] and not r["fork"]:
            langs[r["language"]] = langs.get(r["language"], 0) + 1
    top = ", ".join(f"{k} ({v})" for k, v in sorted(langs.items(), key=lambda x: -x[1])[:4])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"📦 **{user['public_repos']}** public repos · 👥 **{user['followers']}** followers · "
        f"⭐ **{stars}** stars · 🔤 Top languages: {top}<br/><sub>Last refreshed: {now}</sub>"
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
    text = replace(text, "OVERVIEW", overview(user, repos))
    text = replace(text, "PROJECTS", latest_repos(repos))
    text = replace(text, "ACTIVITY", activity(events))
    with open("README.md", "w", encoding="utf-8") as f:
        f.write(text)


if __name__ == "__main__":
    main()
