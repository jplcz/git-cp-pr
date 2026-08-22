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
  - Creates draft pull requests with `--draft`.
  - Opens the configured editor before GitHub CLI submission with `--editor` (or `--edit`).

## Prerequisites

- Python 3.6+
- Git
- [GitHub CLI (`gh`)](https://cli.github.com/) (Optional, used for direct PR creation)

## Installation

For a globally available command-line application, use **pipx**. It keeps the
application isolated from the system Python and avoids externally managed
Python restrictions.

On Ubuntu or Debian:

```bash
sudo apt update
sudo apt install pipx
pipx ensurepath
pipx install .
```

On macOS with Homebrew:

```bash
brew install pipx
pipx ensurepath
pipx install .
```

On Windows PowerShell:

```powershell
py -m pip install --user pipx
py -m pipx ensurepath
pipx install .
```

Open a new terminal after `ensurepath` if the `pipx` command is not found.

For development or a project-local installation, use a virtual environment.
This also works on systems where `pipx` is unavailable.

On macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
```

On Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .
```

## Upgrade

From the project directory, first update the source code:

```bash
git pull
```

For an installation created with `pipx install .`, reinstall from the updated
checkout:

```bash
pipx install --force .
```

If the package was installed from a package index instead, use:

```bash
pipx upgrade git-cp-pr
```

For a virtual environment installation, activate the existing environment and
install the updated project:

```bash
python -m pip install --upgrade -e .
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

Create a draft pull request and edit its title and body before submitting:

```bash
git-cp-pr --draft --editor abc1234
```

## How It Works

* **Checkout:** Switches to the specified base branch.
* **Branching:** Creates a new temporary branch named cherry-pick-<hash>-<timestamp>.
* **Cherry-pick:** Applies the requested commits using Git's native logic.
* **Format:** The CommitFormatter class parses the commit bodies, cleans markdown, extracts trailers, and merges them.
* **Publish:** Creates a PR via gh or saves a pull_request_<timestamp>.md file.

## Contributing

Pull requests are welcome! If you encounter issues, please check that your git environment is clean before running the script.
