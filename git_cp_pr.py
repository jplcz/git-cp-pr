#!/usr/bin/env python3
import atexit
import argparse
import re
import subprocess
import sys
import time
from typing import List, Dict, Tuple

__version__ = "1.0.6"

class Color:
    # Use ANSI codes, checking if terminal supports color (enabled by default)
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    CYAN = "\033[0;36m"
    RESET = "\033[0m"

# Must use emojis everywhere 😂
def print_status(emoji: str, message: str, color: str = Color.BLUE) -> None:
    """Prints a formatted, emoji-prefixed status message with colors."""
    print(f"{color}{emoji} {message}{Color.RESET}")

def run_command(cmd: str, check: bool = True) -> str:
    """Runs a shell command safely and captures output."""
    result = subprocess.run(cmd, shell=True, text=True, capture_output=True)
    if check and result.returncode != 0:
        print_status("❌", f"Command failed: {cmd}\nError: {result.stderr.strip()}", Color.RED)
        sys.exit(1)
    return result.stdout.strip()

class CommitFormatter:
    """Handles parsing, cleaning, formatting of commit messages, and trailer merging."""
    
    def __init__(self, commit_hashes: List[str], base_branch: str, compare_branch: str):
        self.commit_hashes = commit_hashes
        self.base_branch = base_branch
        self.compare_branch = compare_branch
        self.commits_data: List[Dict[str, str]] = []
        self._load_commits()

    def _load_commits(self) -> None:
        for h in self.commit_hashes:
            subject = run_command(f"git log -1 --pretty=%s {h}")
            raw_body = run_command(f"git log -1 --pretty=%b {h}")
            
            # Clean and parse metadata
            cleaned_body, trailers = self._extract_and_clean_body(raw_body)
            
            self.commits_data.append({
                "hash": h,
                "subject": subject,
                "body": cleaned_body,
                "trailers": trailers
            })

    def _extract_and_clean_body(self, raw_body: str) -> Tuple[str, List[str]]:
        """Cleans up raw markdown formatting and extracts Git trailers (Co-Authored-By, Signed-Off-By)."""
        lines = raw_body.splitlines()
        clean_lines = []
        trailers = []
        
        # Regex to match Git trailers
        trailer_pattern = re.compile(r"^(Co-authored-by|Signed-off-by):.*$", re.IGNORECASE)

        for line in lines:
            stripped = line.strip()
            if trailer_pattern.match(stripped):
                trailers.append(stripped)
            else:
                # Clean inner markdown formatting issues (e.g., weird spacing, broken lists)
                cleaned_line = self._fix_markdown_quirks(line)
                clean_lines.append(cleaned_line)

        # Reconstruct body and remove excess blank lines
        body_text = "\n".join(clean_lines).strip()
        return body_text, trailers

    def _fix_markdown_quirks(self, line: str) -> str:
        """Standardizes inner text markdown for a clean, consistent look."""
        # Fix broken bolding spacing or stray tags if present
        line = re.sub(r"\s{3,}", "  ", line)  # Collapse excessive spaces
        return line

    def generate_pr_payload(self) -> Tuple[str, str]:
        """Generates final PR title and structured body based on single or multiple commits."""
        if not self.commits_data:
            return "", ""

        # Collect and deduplicate all unique trailers globally
        all_trailers = []
        seen_trailers = set()
        for c in self.commits_data:
            for t in c["trailers"]:
                if t not in seen_trailers:
                    seen_trailers.add(t)
                    all_trailers.append(t)

        # Single commit format
        if len(self.commits_data) == 1:
            commit = self.commits_data[0]
            pr_title = commit["subject"]
            pr_body = commit["body"]
            if not pr_body:
                pr_body = f"Cherry-picked commit `{commit['hash']}` onto `{self.base_branch}`."
        
        # Multiple commits format
        else:
            first_subject = self.commits_data[0]["subject"]
            pr_title = f"Cherry-pick {len(self.commits_data)} commits (e.g., {first_subject})"
            
            body_commits_list = []
            body_details = []

            for commit in self.commits_data:
                body_commits_list.append(f"* {commit['subject']}")
                
                detail_block = f"### {commit['subject']}\n\n"
                if commit["body"]:
                    detail_block += f"{commit['body']}\n\n"
                else:
                    detail_block += "*No additional details provided.*\n\n"
                body_details.append(detail_block)

            pr_body = "## Cherry picked commits\n" + "\n".join(body_commits_list) + "\n\n"
            pr_body += "## Cherry picked commit details\n\n" + "".join(body_details)
            pr_body = pr_body.strip()

        # Append merged trailers at the very bottom if any exist
        if all_trailers:
            pr_body += "\n\n---\n" + "\n".join(all_trailers)

        return pr_title, pr_body

def main():
    parser = argparse.ArgumentParser(
        description="Cherry-pick commits, create a custom branch, and open a PR via GitHub CLI or generate a Markdown file.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("commits", nargs="+", help="Commit hash(es) or range(s) (e.g., abc1234 or a..b)")
    parser.add_argument("-b", "--base", default="master", help="Specify base branch (default: master)")
    parser.add_argument("-n", "--name", default="", help="Specify custom branch name")
    parser.add_argument("-u", "--update-base", action="store_true", help="Update/pull the base branch from remote (default: disabled)")
    parser.add_argument("--mode", choices=["gh", "md"], help="Force PR creation mode: 'gh' (GitHub CLI) or 'md' (Markdown file)")
    parser.add_argument("--draft", action="store_true", help="Create the pull request as a draft")
    parser.add_argument("-e", "--editor", "--edit", action="store_true", help="Open an editor to edit the PR title and body before GitHub CLI submission")
    parser.add_argument("--dry-run", action="store_true", help="Create the cherry-pick branch only; do not cherry-pick or push")
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {__version__}")

    args = parser.parse_args()

    # Verify Git repository workspace
    if subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True).returncode != 0:
        print_status("❌", "Current directory is not a valid Git repository.", Color.RED)
        sys.exit(1)

    original_branch = run_command("git branch --show-current", check=False)
    branch_created = False
    remove_branch_on_exit = False

    def restore_original_branch() -> None:
        if not branch_created:
            return
        if remove_branch_on_exit:
            print_status("🧹", f"Cleaning up failed cherry-pick branch '{custom_branch}'...")
            subprocess.run(["git", "cherry-pick", "--abort"], capture_output=True, text=True)
        if not original_branch:
            return
        print_status("↩️", f"Returning to original branch '{original_branch}'...")
        result = subprocess.run(["git", "checkout", original_branch], capture_output=True, text=True)
        if result.returncode != 0:
            print_status("❌", f"Could not return to original branch '{original_branch}': {result.stderr.strip()}", Color.RED)
            return
        if remove_branch_on_exit:
            result = subprocess.run(["git", "branch", "-D", custom_branch], capture_output=True, text=True)
            if result.returncode != 0:
                print_status("❌", f"Could not delete failed branch '{custom_branch}': {result.stderr.strip()}", Color.RED)

    atexit.register(restore_original_branch)

    print_status("🔍", f"Checking out base branch '{args.base}'...")
    run_command(f"git checkout {args.base}")

    if args.update_base:
        print_status("🔄", f"Updating base branch '{args.base}' from remote...")
        run_command(f"git pull origin {args.base}")
    else:
        print_status("⏭️", f"Skipping update of base branch '{args.base}' as requested.", Color.YELLOW)

    # Parse and validate commits safely
    expanded_commits = []
    for c in args.commits:
        # If it's a range (contains '..'), expand it
        if ".." in c:
            rev_list = run_command(f"git rev-list --reverse {c}")
            if rev_list:
                expanded_commits.extend([line.strip() for line in rev_list.splitlines() if line.strip()])
        else:
            # Otherwise, treat it as a single commit or ref, get its full hash
            full_hash = run_command(f"git rev-parse --verify {c}")
            if full_hash:
                expanded_commits.append(full_hash)

    if not expanded_commits:
        print_status("❌", f"No valid commits found for input: {' '.join(args.commits)}", Color.RED)
        sys.exit(1)

    # Safety check to prevent accidental massive batch picks
    if len(expanded_commits) > 50:
        print_status("❌", f"Safety abort: Attempting to cherry-pick {len(expanded_commits)} commits looks incorrect. Please check your commit arguments.", Color.RED)
        sys.exit(1)

    # Generate automatic branch name if not provided
    custom_branch = args.name
    if not custom_branch:
        clean_name = args.commits[0].replace("/", "-").replace(".", "-")
        custom_branch = f"cherry-pick-{clean_name}-{int(time.time())}"

    print_status("🌿", f"Creating and switching to branch '{custom_branch}'...")
    run_command(f"git checkout -b {custom_branch}")
    branch_created = True
    remove_branch_on_exit = True

    if args.dry_run:
        remove_branch_on_exit = False
        print_status("🧪", f"Dry run complete. Branch '{custom_branch}' was created; no commits were cherry-picked or pushed.", Color.GREEN)
        return

    print_status("🍒", f"Cherry-picking {len(expanded_commits)} commit(s)...")
    cp_cmd = ["git", "cherry-pick"] + args.commits
    cp_result = subprocess.run(cp_cmd)
    if cp_result.returncode != 0:
        print_status("❌", "Cherry-pick failed. The temporary branch will be removed.", Color.RED)
        sys.exit(1)

    remove_branch_on_exit = False

    print_status("🚀", "Pushing branch to remote origin...")
    run_command(f"git push -u origin {custom_branch}")

    # Format the PR using cleaned commit bodies and merged trailers.
    formatter = CommitFormatter(expanded_commits, args.base, custom_branch)
    pr_title, pr_body = formatter.generate_pr_payload()

    # Determine execution mode (gh vs md)
    run_mode = args.mode
    if not run_mode:
        gh_installed = subprocess.run(["which", "gh"], capture_output=True).returncode == 0
        run_mode = "gh" if gh_installed else "md"

    if run_mode == "gh":
        print_status("🌐", "Creating Pull Request via 'gh' tool...")
        gh_cmd = ["gh", "pr", "create", "--base", args.base, "--title", pr_title, "--body", pr_body]
        if args.draft:
            gh_cmd.append("--draft")
        if args.editor:
            gh_cmd.append("--editor")
        gh_process = subprocess.run(gh_cmd)
        if gh_process.returncode == 0:
            print_status("✨", "Successfully created Pull Request via GitHub CLI! 🎉", Color.GREEN)
        else:
            print_status("❌", "Failed to create PR via GitHub CLI.", Color.RED)
            sys.exit(1)
    else:
        md_file = f"pull_request_{int(time.time())}.md"
        print_status("📝", f"Generating Markdown PR file: '{md_file}'...")
        
        markdown_content = f"""# Pull Request Details

- **Base Branch:** `{args.base}`
- **Compare Branch:** `{custom_branch}`
- **Title:** {pr_title}

{pr_body}
"""
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
            
        print_status("✨", f"Markdown file successfully generated at: {md_file} 📄", Color.GREEN)

if __name__ == "__main__":
    main()
