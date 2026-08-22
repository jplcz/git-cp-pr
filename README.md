# Git Cherry-Pick PR tool

An automated Python tool to cherry-pick specific commits or commit ranges, 
create a feature branch, and generate a structured Pull Request (PR) automatically. 

## What does it do ?

- **Cherry-picking:** Cherry-picks single commits or ranges (`A..B`) into a new branch.
- **Commit Formatting:**
  - Extracts and merges `Co-authored-by` and `Signed-off-by` trailers.
  - Cleans up inner Markdown
  - Uses original commit messages (subject/body) for single commits or structured templates for multiple commits.
- **Optionally:**
  - Updates the base branch before picking.
  - Choice between direct GitHub PR creation (`gh`) or generating a structured `.md` file.

## Prerequisites

- Python 3.6+
- Git
- [GitHub CLI (`gh`)](https://cli.github.com/) (Optional, used for direct PR creation)

## Installation

The recommended way to install and run this tool globally is using **pipx** (which runs the tool in an isolated environment and adds `git-cp-pr` to your system path):

```bash
pipx install .
```

Alternatively, you can install it locally using `pip`:

```bash
python3 -m pip install --user .
```

Or you can use the provided automated installation script:

```bash
chmod +x install.sh
./install.sh
```

Or you can use:

1. Copy the `git_cp_pr.py` script somewhere into your `$PATH`.
2. Ensure it is executable:

```bash
chmod +x git_cp_pr.py
```

## Examples

Cherry-pick a single commit to `master`:

```bash
git-cp-pr abc1234
```

Cherry-pick a range to `main` and output a Markdown file:

```bash
git-cp-pr -b main --mode md abc1234..def5678
```

## How It Works

* **Checkout:** Switches to the specified base branch.
* **Branching:** Creates a new temporary branch named cherry-pick-<hash>-<timestamp>.
* **Cherry-pick:** Applies the requested commits using Git's native logic.
* **Format:** The CommitFormatter class parses the commit bodies, cleans markdown, extracts trailers, and merges them.
* **Publish:** Creates a PR via gh or saves a pull_request_<timestamp>.md file.
