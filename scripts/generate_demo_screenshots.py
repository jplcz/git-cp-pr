#!/usr/bin/env python3
"""Create a demo Git repository and capture screenshots of the GUI."""

import argparse
import importlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from PIL import ImageGrab
except ImportError as error:
    raise SystemExit("This script requires Pillow. Install it with: python3 -m pip install Pillow") from error

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
from git_cp_pr_gui import CommitPicker  # noqa: E402


def start_linux_display():
    if not sys.platform.startswith("linux"):
        return None
    try:
        display_type = importlib.import_module("pyvirtualdisplay").Display
    except ImportError as error:
        raise SystemExit(
            "Linux screenshot generation requires PyVirtualDisplay and Xvfb. "
            "Run: sudo apt install python3-tk xvfb && "
            "python -m pip install -r scripts/requirements-screenshots.txt"
        ) from error
    try:
        display = display_type(visible=0, size=(1280, 900), backend="xvfb")
        display.start()
        return display
    except Exception as error:
        raise SystemExit(
            "Could not start Xvfb. Install it with: sudo apt install xvfb"
        ) from error


class DemoRepository:
    def __init__(self, path: Path) -> None:
        self.path = path

    def run(self, *args: str) -> None:
        subprocess.run(["git", *args], cwd=self.path, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def commit(self, filename: str, content: str, message: str) -> None:
        (self.path / filename).write_text(content, encoding="utf-8")
        self.run("add", filename)
        self.run("commit", "-m", message)

    def create(self) -> None:
        self.run("init", "-b", "master")
        self.run("config", "user.name", "git-cp-pr demo")
        self.run("config", "user.email", "demo@example.com")
        self.commit("README.md", "# Demo project\n", "Document demo project")
        self.commit("app.txt", "stable behavior\n", "Improve stable behavior")
        self.run("checkout", "-b", "feature/fast-path")
        self.commit("feature.txt", "experimental path\n", "Add experimental path")
        self.commit("feature.txt", "experimental path\nready for review\n", "Refine experimental path")
        self.run("checkout", "master")
        self.commit("release.txt", "next release\n", "Prepare next release")


def select_first_commit(app: CommitPicker) -> None:
    rows = app.tree.get_children()
    if not rows:
        return
    row = rows[0]
    values = list(app.tree.item(row, "values"))
    values[0] = "☑"
    app.tree.item(row, values=values, tags=("picked",))


def capture(app: CommitPicker, output_path: Path) -> None:
    app.deiconify()
    try:
        app.attributes("-topmost", True)
        topmost_enabled = True
    except Exception:
        topmost_enabled = False
    app.lift()
    app.focus_force()
    app.update_idletasks()
    app.update()
    x = app.winfo_rootx()
    y = app.winfo_rooty()
    width = app.winfo_width()
    height = app.winfo_height()
    if width <= 0 or height <= 0:
        raise RuntimeError(f"GUI window has invalid size: {width}x{height}")
    try:
        image = ImageGrab.grab(
            bbox=(x, y, x + width, y + height),
            include_layered_windows=False,
        )
        image.save(output_path)
        print(f"Wrote {output_path}")
    finally:
        if topmost_enabled:
            app.attributes("-topmost", False)


def generate(output_dir: Path, keep_repo: bool) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    display = start_linux_display()
    temp_context = tempfile.TemporaryDirectory(prefix="git-cp-pr-demo-")
    demo_path = Path(temp_context.name)
    try:
        DemoRepository(demo_path).create()
        original_directory = Path.cwd()
        previous_env = {
            "LANG": os.environ.get("LANG"),
            "LC_ALL": os.environ.get("LC_ALL"),
            "LC_MESSAGES": os.environ.get("LC_MESSAGES"),
            "LANGUAGE": os.environ.get("LANGUAGE"),
            "XDG_CONFIG_HOME": os.environ.get("XDG_CONFIG_HOME"),
        }
        os.environ["LANG"] = "en_US.UTF-8"
        os.environ["LC_ALL"] = "en_US.UTF-8"
        os.environ["LC_MESSAGES"] = "en_US.UTF-8"
        os.environ["LANGUAGE"] = "en_US:en"
        isolated_config = demo_path / ".config"
        isolated_config.mkdir(parents=True, exist_ok=True)
        os.environ["XDG_CONFIG_HOME"] = str(isolated_config)
        os.chdir(demo_path)
        try:
            app = CommitPicker()
            app.after(700, lambda: select_first_commit(app))
            app.after(1000, lambda: capture(app, output_dir / "gui-current-branch.png"))

            def capture_all_branches() -> None:
                app.all_branches.set(True)
                app._load_commits()
                capture(app, output_dir / "gui-all-branches.png")
                app.after(200, app.destroy)

            app.after(1400, capture_all_branches)
            app.mainloop()
        finally:
            os.chdir(original_directory)
            for key, value in previous_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        if keep_repo:
            retained_path = output_dir / "demo-repository"
            if retained_path.exists():
                raise RuntimeError(f"Refusing to replace existing path: {retained_path}")
            demo_path.rename(retained_path)
            print(f"Kept demo repository at {retained_path}")
            temp_context.cleanup()
            temp_context = None
    finally:
        if temp_context is not None:
            temp_context.cleanup()
        if display is not None:
            display.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate demo Git repositories and GUI screenshots.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=SCRIPT_DIR / "docs" / "screenshots",
        help="Directory for generated screenshots (default: docs/screenshots)",
    )
    parser.add_argument("--keep-repo", action="store_true", help="Keep the generated demo repository in the output directory")
    args = parser.parse_args()
    generate(args.output_dir.resolve(), args.keep_repo)


if __name__ == "__main__":
    main()
