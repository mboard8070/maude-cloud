"""
GitHub tool implementations — repos, issues, PRs, branches, commits,
workflow runs, releases, and search via gh CLI.
"""

import subprocess
import json

from ..tool_registry import register_tool


def _run_gh(*args: str, timeout: int = 30) -> tuple[int, str]:
    """Run a gh CLI command and return (returncode, output)."""
    try:
        result = subprocess.run(
            ["gh", *args],
            capture_output=True, text=True, timeout=timeout,
        )
        output = result.stdout.strip() or result.stderr.strip()
        return result.returncode, output
    except FileNotFoundError:
        return 1, "Error: gh CLI not found. Install from https://cli.github.com/"
    except subprocess.TimeoutExpired:
        return 1, "Error: gh command timed out."


# ── Pull Requests ──────────────────────────────────────────────

@register_tool("github_list_prs")
def _dispatch_list_prs(args):
    repo = args.get("repo", "")
    state = args.get("state", "open")
    limit = args.get("limit", 10)
    gh_args = ["pr", "list", "--state", state, "--limit", str(limit), "--json",
               "number,title,state,author,headRefName,baseRefName,createdAt,mergeable"]
    if repo:
        gh_args.extend(["--repo", repo])
    rc, output = _run_gh(*gh_args)
    if rc != 0:
        return f"Error listing PRs: {output}"
    try:
        prs = json.loads(output)
    except json.JSONDecodeError:
        return f"Error parsing PR list: {output}"
    if not prs:
        return f"No {state} pull requests found."
    lines = []
    for pr in prs:
        author = pr.get("author", {}).get("login", "unknown")
        mergeable = pr.get("mergeable", "UNKNOWN")
        lines.append(
            f"#{pr['number']}  {pr['title']}\n"
            f"   {pr['headRefName']} -> {pr['baseRefName']}  by {author}  "
            f"state={pr['state']}  mergeable={mergeable}"
        )
    return "\n\n".join(lines)


@register_tool("github_view_pr")
def _dispatch_view_pr(args):
    pr_number = args.get("pr_number")
    repo = args.get("repo", "")
    gh_args = ["pr", "view", str(pr_number), "--json",
               "number,title,state,body,author,headRefName,baseRefName,"
               "mergeable,reviewDecision,statusCheckRollup,additions,deletions,changedFiles"]
    if repo:
        gh_args.extend(["--repo", repo])
    rc, output = _run_gh(*gh_args)
    if rc != 0:
        return f"Error viewing PR #{pr_number}: {output}"
    try:
        pr = json.loads(output)
    except json.JSONDecodeError:
        return f"Error parsing PR: {output}"
    author = pr.get("author", {}).get("login", "unknown")
    checks = pr.get("statusCheckRollup", []) or []
    check_summary = ""
    if checks:
        passed = sum(1 for c in checks if c.get("conclusion") == "SUCCESS")
        check_summary = f"  checks: {passed}/{len(checks)} passed"
    return (
        f"PR #{pr['number']}: {pr['title']}\n"
        f"  {pr['headRefName']} -> {pr['baseRefName']}  by {author}\n"
        f"  state: {pr['state']}  mergeable: {pr.get('mergeable', 'UNKNOWN')}\n"
        f"  review: {pr.get('reviewDecision') or 'NONE'}{check_summary}\n"
        f"  +{pr.get('additions', 0)} -{pr.get('deletions', 0)} in {pr.get('changedFiles', 0)} files\n"
        f"\n{pr.get('body') or '(no description)'}"
    )


@register_tool("github_create_pr")
def _dispatch_create_pr(args):
    title = args.get("title", "")
    gh_args = ["pr", "create", "--title", title]
    if args.get("body"):
        gh_args.extend(["--body", args["body"]])
    if args.get("base"):
        gh_args.extend(["--base", args["base"]])
    if args.get("head"):
        gh_args.extend(["--head", args["head"]])
    if args.get("draft"):
        gh_args.append("--draft")
    if args.get("repo"):
        gh_args.extend(["--repo", args["repo"]])
    rc, output = _run_gh(*gh_args)
    return f"Pull request created: {output}" if rc == 0 else f"Error creating PR: {output}"


@register_tool("github_merge_pr")
def _dispatch_merge_pr(args):
    pr_number = args.get("pr_number")
    method = args.get("method", "merge")
    if method not in ("merge", "squash", "rebase"):
        return f"Error: Invalid merge method '{method}'."
    gh_args = ["pr", "merge", str(pr_number), f"--{method}"]
    if args.get("delete_branch", True):
        gh_args.append("--delete-branch")
    if args.get("repo"):
        gh_args.extend(["--repo", args["repo"]])
    rc, output = _run_gh(*gh_args)
    return f"Successfully merged PR #{pr_number} via {method}.\n{output}" if rc == 0 else f"Error merging PR #{pr_number}: {output}"


@register_tool("github_close_pr")
def _dispatch_close_pr(args):
    pr_number = args.get("pr_number")
    repo = args.get("repo", "")
    if args.get("comment"):
        _run_gh("pr", "comment", str(pr_number), "--body", args["comment"],
                *(["--repo", repo] if repo else []))
    gh_args = ["pr", "close", str(pr_number)]
    if repo:
        gh_args.extend(["--repo", repo])
    rc, output = _run_gh(*gh_args)
    return f"PR #{pr_number} closed.\n{output}" if rc == 0 else f"Error closing PR #{pr_number}: {output}"


@register_tool("github_pr_diff")
def _dispatch_pr_diff(args):
    gh_args = ["pr", "diff", str(args.get("pr_number"))]
    if args.get("repo"):
        gh_args.extend(["--repo", args["repo"]])
    rc, output = _run_gh(*gh_args, timeout=60)
    if rc != 0:
        return f"Error getting PR diff: {output}"
    if len(output) > 8000:
        output = output[:8000] + "\n... (diff truncated)"
    return output


@register_tool("github_pr_comments")
def _dispatch_pr_comments(args):
    gh_args = ["pr", "view", str(args.get("pr_number")), "--json", "comments"]
    if args.get("repo"):
        gh_args.extend(["--repo", args["repo"]])
    rc, output = _run_gh(*gh_args)
    if rc != 0:
        return f"Error getting PR comments: {output}"
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return output
    comments = data.get("comments", [])
    if not comments:
        return f"No comments on PR #{args.get('pr_number')}."
    lines = []
    for c in comments:
        author = c.get("author", {}).get("login", "unknown")
        created = c.get("createdAt", "")[:10]
        body = c.get("body", "")[:200]
        lines.append(f"  {author} ({created}): {body}")
    return f"Comments on PR #{args.get('pr_number')}:\n" + "\n".join(lines)


@register_tool("github_comment_pr")
def _dispatch_comment_pr(args):
    gh_args = ["pr", "comment", str(args.get("pr_number")), "--body", args.get("body", "")]
    if args.get("repo"):
        gh_args.extend(["--repo", args["repo"]])
    rc, output = _run_gh(*gh_args)
    return f"Comment added to PR #{args.get('pr_number')}." if rc == 0 else f"Error: {output}"


# ── Issues ─────────────────────────────────────────────────────

@register_tool("github_list_issues")
def _dispatch_list_issues(args):
    gh_args = ["issue", "list", "--state", args.get("state", "open"), "--limit", str(args.get("limit", 10)),
               "--json", "number,title,state,author,labels,createdAt,assignees"]
    if args.get("labels"):
        gh_args.extend(["--label", args["labels"]])
    if args.get("repo"):
        gh_args.extend(["--repo", args["repo"]])
    rc, output = _run_gh(*gh_args)
    if rc != 0:
        return f"Error listing issues: {output}"
    try:
        issues = json.loads(output)
    except json.JSONDecodeError:
        return output
    if not issues:
        return f"No {args.get('state', 'open')} issues found."
    lines = []
    for iss in issues:
        author = iss.get("author", {}).get("login", "unknown")
        label_names = [l.get("name", "") for l in iss.get("labels", [])]
        label_str = f"  [{', '.join(label_names)}]" if label_names else ""
        lines.append(f"#{iss['number']}  {iss['title']}{label_str}  by {author}")
    return "\n".join(lines)


@register_tool("github_view_issue")
def _dispatch_view_issue(args):
    gh_args = ["issue", "view", str(args.get("issue_number")), "--json",
               "number,title,state,body,author,labels,assignees,comments,createdAt"]
    if args.get("repo"):
        gh_args.extend(["--repo", args["repo"]])
    rc, output = _run_gh(*gh_args)
    if rc != 0:
        return f"Error viewing issue: {output}"
    try:
        iss = json.loads(output)
    except json.JSONDecodeError:
        return output
    body = iss.get("body") or "(no description)"
    if len(body) > 3000:
        body = body[:3000] + "\n... (truncated)"
    return f"Issue #{iss['number']}: {iss['title']}\n  state: {iss['state']}\n\n{body}"


@register_tool("github_create_issue")
def _dispatch_create_issue(args):
    gh_args = ["issue", "create", "--title", args.get("title", "")]
    if args.get("body"):
        gh_args.extend(["--body", args["body"]])
    if args.get("labels"):
        gh_args.extend(["--label", args["labels"]])
    if args.get("repo"):
        gh_args.extend(["--repo", args["repo"]])
    rc, output = _run_gh(*gh_args)
    return f"Issue created: {output}" if rc == 0 else f"Error: {output}"


@register_tool("github_close_issue")
def _dispatch_close_issue(args):
    gh_args = ["issue", "close", str(args.get("issue_number"))]
    if args.get("repo"):
        gh_args.extend(["--repo", args["repo"]])
    rc, output = _run_gh(*gh_args)
    return f"Issue #{args.get('issue_number')} closed." if rc == 0 else f"Error: {output}"


@register_tool("github_comment_issue")
def _dispatch_comment_issue(args):
    gh_args = ["issue", "comment", str(args.get("issue_number")), "--body", args.get("body", "")]
    if args.get("repo"):
        gh_args.extend(["--repo", args["repo"]])
    rc, output = _run_gh(*gh_args)
    return f"Comment added." if rc == 0 else f"Error: {output}"


# ── Repos, Branches, Commits, Runs, Releases, Search, Notifications ──

@register_tool("github_list_repos")
def _dispatch_list_repos(args):
    gh_args = ["repo", "list"]
    if args.get("owner"):
        gh_args.append(args["owner"])
    gh_args.extend(["--limit", str(args.get("limit", 10)),
                     "--json", "name,description,visibility,updatedAt,primaryLanguage,stargazerCount"])
    rc, output = _run_gh(*gh_args)
    if rc != 0:
        return f"Error: {output}"
    try:
        repos = json.loads(output)
    except json.JSONDecodeError:
        return output
    lines = []
    for r in repos:
        pl = r.get("primaryLanguage") or {}
        lang = pl.get("name", "") if isinstance(pl, dict) else ""
        desc = (r.get("description") or "")[:60]
        parts = [r["name"]]
        if lang:
            parts.append(lang)
        if desc:
            parts.append(f"-- {desc}")
        lines.append("  ".join(parts))
    return "\n".join(lines) if lines else "No repositories found."


@register_tool("github_view_repo")
def _dispatch_view_repo(args):
    gh_args = ["repo", "view", "--json", "name,owner,description,url,visibility,defaultBranchRef,stargazerCount,forkCount"]
    if args.get("repo"):
        gh_args.insert(2, args["repo"])
    rc, output = _run_gh(*gh_args)
    if rc != 0:
        return f"Error: {output}"
    try:
        r = json.loads(output)
    except json.JSONDecodeError:
        return output
    owner = r.get("owner", {}).get("login", "unknown")
    branch = r.get("defaultBranchRef", {}).get("name", "main") if r.get("defaultBranchRef") else "main"
    return f"{owner}/{r.get('name')}\n  {r.get('description') or ''}\n  url: {r.get('url')}\n  branch: {branch}  stars: {r.get('stargazerCount', 0)}"


@register_tool("github_list_branches")
def _dispatch_list_branches(args):
    repo = args.get("repo", "")
    if repo:
        gh_args = ["api", f"repos/{repo}/branches", "--paginate", "--jq", '.[] | .name']
    else:
        gh_args = ["api", "repos/{owner}/{repo}/branches", "--paginate", "--jq", '.[] | .name']
    rc, output = _run_gh(*gh_args)
    if rc != 0:
        return f"Error: {output}"
    lines = output.strip().split("\n")[:args.get("limit", 20)]
    return "\n".join(lines) if lines else "No branches found."


@register_tool("github_list_commits")
def _dispatch_list_commits(args):
    limit = args.get("limit", 10)
    try:
        result = subprocess.run(["git", "log", f"--oneline", f"-{limit}"],
                                capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return "No commits found or not in a git repository."


@register_tool("github_list_runs")
def _dispatch_list_runs(args):
    gh_args = ["run", "list", "--limit", str(args.get("limit", 10)),
               "--json", "databaseId,name,status,conclusion,headBranch,event,createdAt"]
    if args.get("status"):
        gh_args.extend(["--status", args["status"]])
    if args.get("repo"):
        gh_args.extend(["--repo", args["repo"]])
    rc, output = _run_gh(*gh_args)
    if rc != 0:
        return f"Error: {output}"
    try:
        runs = json.loads(output)
    except json.JSONDecodeError:
        return output
    lines = []
    for r in runs:
        conclusion = r.get("conclusion", "") or r.get("status", "")
        lines.append(f"#{r['databaseId']}  {r['name']}  {conclusion}  branch={r.get('headBranch', '')}")
    return "\n".join(lines) if lines else "No workflow runs found."


@register_tool("github_view_run")
def _dispatch_view_run(args):
    gh_args = ["run", "view", str(args.get("run_id")),
               "--json", "databaseId,name,status,conclusion,headBranch,event,url,jobs"]
    if args.get("repo"):
        gh_args.extend(["--repo", args["repo"]])
    rc, output = _run_gh(*gh_args)
    if rc != 0:
        return f"Error: {output}"
    try:
        run = json.loads(output)
    except json.JSONDecodeError:
        return output
    return f"Run #{run.get('databaseId')}: {run.get('name')}\n  status: {run.get('status')}  conclusion: {run.get('conclusion') or 'in progress'}\n  url: {run.get('url', '')}"


@register_tool("github_rerun")
def _dispatch_rerun(args):
    gh_args = ["run", "rerun", str(args.get("run_id"))]
    if args.get("failed_only"):
        gh_args.append("--failed")
    if args.get("repo"):
        gh_args.extend(["--repo", args["repo"]])
    rc, output = _run_gh(*gh_args)
    return f"Re-triggered." if rc == 0 else f"Error: {output}"


@register_tool("github_list_releases")
def _dispatch_list_releases(args):
    gh_args = ["release", "list", "--limit", str(args.get("limit", 5))]
    if args.get("repo"):
        gh_args.extend(["--repo", args["repo"]])
    rc, output = _run_gh(*gh_args)
    return output if rc == 0 and output else "No releases found." if rc == 0 else f"Error: {output}"


@register_tool("github_create_release")
def _dispatch_create_release(args):
    gh_args = ["release", "create", args.get("tag", "")]
    if args.get("title"):
        gh_args.extend(["--title", args["title"]])
    if args.get("notes"):
        gh_args.extend(["--notes", args["notes"]])
    else:
        gh_args.append("--generate-notes")
    if args.get("draft"):
        gh_args.append("--draft")
    if args.get("repo"):
        gh_args.extend(["--repo", args["repo"]])
    rc, output = _run_gh(*gh_args)
    return f"Release created: {output}" if rc == 0 else f"Error: {output}"


@register_tool("github_search")
def _dispatch_search(args):
    query = args.get("query", "")
    search_type = args.get("type", "repos")
    limit = args.get("limit", 10)
    if search_type == "repos":
        gh_args = ["search", "repos", query, "--limit", str(limit),
                    "--json", "fullName,description,stargazersCount,language"]
        rc, output = _run_gh(*gh_args)
        if rc != 0:
            return f"Error: {output}"
        try:
            results = json.loads(output)
        except json.JSONDecodeError:
            return output
        lines = []
        for r in results:
            desc = (r.get("description") or "")[:60]
            lines.append(f"{r.get('fullName', '?')}  {r.get('language', '')}  -- {desc}")
        return "\n".join(lines) if lines else "No results."
    else:
        gh_args = ["search", search_type, query, "--limit", str(limit)]
        rc, output = _run_gh(*gh_args)
        return output if rc == 0 else f"Error: {output}"


@register_tool("github_notifications")
def _dispatch_notifications(args):
    gh_args = ["api", "notifications", "--method", "GET", "--jq",
               '.[] | "\\(.subject.type): \\(.subject.title)  [\\(.repository.full_name)]"',
               "-f", f"per_page={args.get('limit', 10)}"]
    rc, output = _run_gh(*gh_args)
    return output.strip() if rc == 0 and output.strip() else "No unread notifications." if rc == 0 else f"Error: {output}"
