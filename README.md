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

1. Copy the `git-cp-pr.py` script into your project root or a directory in your `$PATH`.
2. Ensure it is executable:
   ```bash
   chmod +x git-cp-pr.py
