#!/usr/bin/env python3
"""Tkinter frontend for selecting commits and running git-cp-pr."""

import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Dict, List, Optional, Tuple


COMMIT_SEPARATOR = "\x1f"
COMMIT_PATTERN = re.compile(
    r"^(?P<graph>[ |\\/*]+)?(?P<hash>[0-9a-f]{40})"
    + re.escape(COMMIT_SEPARATOR)
    + r"(?P<short>[0-9a-f]+)"
    + re.escape(COMMIT_SEPARATOR)
    + r"(?P<date>[^\x1f]*)"
    + re.escape(COMMIT_SEPARATOR)
    + r"(?P<author>[^\x1f]*)"
    + re.escape(COMMIT_SEPARATOR)
    + r"(?P<subject>.*)$"
)


class Tooltip:
    def __init__(self, widget: tk.Widget, text: str) -> None:
        self.widget = widget
        self.text = text
        self.window: Optional[tk.Toplevel] = None
        self.after_id: Optional[str] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _schedule(self, _event: tk.Event) -> None:
        self._hide()
        self.after_id = self.widget.after(500, self._show)

    def _show(self) -> None:
        if self.window is not None:
            return
        self.window = tk.Toplevel(self.widget)
        self.window.wm_overrideredirect(True)
        self.window.attributes("-topmost", True)
        label = tk.Label(
            self.window,
            text=self.text,
            justify="left",
            background="#fff8dc",
            relief="solid",
            borderwidth=1,
            padx=6,
            pady=4,
        )
        label.pack()
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.window.geometry(f"+{x}+{y}")

    def _hide(self, _event: Optional[tk.Event] = None) -> None:
        if self.after_id is not None:
            self.widget.after_cancel(self.after_id)
            self.after_id = None
        if self.window is not None:
            self.window.destroy()
            self.window = None


class CommitPicker(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("git-cp-pr commit picker")
        self.geometry("1100x720")
        self.minsize(800, 520)
        self._window_icon = self._load_window_icon()
        self.repo_dir = Path.cwd()
        self.cli_script = Path(__file__).resolve().with_name("git_cp_pr.py")
        self.commits: Dict[str, Dict[str, str]] = {}
        self.output_queue: queue.Queue = queue.Queue()
        self.running = False

        self.base_branch = tk.StringVar()
        self.branch_name = tk.StringVar()
        self.update_base = tk.BooleanVar()
        self.all_branches = tk.BooleanVar(value=False)
        self.mode = tk.StringVar(value="gh")
        self.draft = tk.BooleanVar()
        self.editor = tk.BooleanVar()
        self.dry_run = tk.BooleanVar()
        self.displayed_history = tk.StringVar(value="Loading...")
        self.status = tk.StringVar(value="Loading commits...")

        self._configure_style()
        self._build_ui()
        self._refresh_repository()
        self.after(100, self._poll_output)

    def _load_window_icon(self):
        icon_directories = (
            Path(__file__).resolve().parent,
            Path(sys.prefix) / "share" / "git-cp-pr",
        )
        if sys.platform.startswith("win"):
            for directory in icon_directories:
                icon_path = directory / "icon.ico"
                if not icon_path.is_file():
                    continue
                try:
                    self.iconbitmap(default=str(icon_path))
                    break
                except tk.TclError:
                    continue

        for directory in icon_directories:
            icon_path = directory / "icon.png"
            if not icon_path.is_file():
                continue
            try:
                icon = tk.PhotoImage(file=icon_path)
                self.iconphoto(True, icon)
                return icon
            except tk.TclError:
                continue
        return None

    def _configure_style(self) -> None:
        self.configure(background="#f4f1ea")
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#f4f1ea")
        style.configure("Header.TFrame", background="#173b4d")
        style.configure("Header.TLabel", background="#173b4d", foreground="#f8f4e8", font=("TkDefaultFont", 18, "bold"))
        style.configure("Subheader.TLabel", background="#173b4d", foreground="#c8d9d8", font=("TkDefaultFont", 10))
        style.configure("Section.TLabelframe", background="#f4f1ea", bordercolor="#d8d0c2")
        style.configure("Section.TLabelframe.Label", background="#f4f1ea", foreground="#173b4d", font=("TkDefaultFont", 10, "bold"))
        style.configure("TLabel", background="#f4f1ea", foreground="#263238")
        style.configure("Muted.TLabel", background="#f4f1ea", foreground="#6b7476")
        style.configure("Warning.TLabel", background="#f4f1ea", foreground="#9a4b2d", font=("TkDefaultFont", 9, "bold"))
        style.configure("Accent.TButton", background="#d96c43", foreground="#ffffff", padding=(14, 8), font=("TkDefaultFont", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#bd5632"), ("disabled", "#c8b9ae")])
        style.configure("Treeview", background="#fffdf8", fieldbackground="#fffdf8", foreground="#263238", rowheight=28, bordercolor="#d8d0c2")
        style.configure("Treeview.Heading", background="#e5ded1", foreground="#173b4d", font=("TkDefaultFont", 10, "bold"), padding=(6, 7))
        style.map("Treeview", background=[("selected", "#c8d9d8")], foreground=[("selected", "#173b4d")])

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(4, weight=1)

        header = ttk.Frame(self, style="Header.TFrame", padding=(20, 16))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="Cherry-pick workspace", style="Header.TLabel").pack(anchor="w")
        ttk.Label(header, text=str(self.repo_dir), style="Subheader.TLabel").pack(anchor="w", pady=(4, 0))

        controls = ttk.Frame(self, padding=12)
        controls.grid(row=1, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(3, weight=1)

        base_label = ttk.Label(controls, text="PR base (target)")
        base_label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.base_combo = ttk.Combobox(controls, textvariable=self.base_branch, state="readonly")
        self.base_combo.grid(row=0, column=1, sticky="ew", padx=(0, 16))
        branch_label = ttk.Label(controls, text="New branch")
        branch_label.grid(row=0, column=2, sticky="w", padx=(0, 8))
        branch_entry = ttk.Entry(controls, textvariable=self.branch_name)
        branch_entry.grid(row=0, column=3, sticky="ew")

        options = ttk.Frame(controls)
        options.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        all_branches_check = ttk.Checkbutton(options, text="All branches in tree (view only)", variable=self.all_branches, command=self._load_commits)
        all_branches_check.pack(side="left")
        update_base_check = ttk.Checkbutton(options, text="Update base", variable=self.update_base)
        update_base_check.pack(side="left")
        ttk.Label(options, text="PR mode:").pack(side="left", padx=(20, 6))
        github_mode_radio = ttk.Radiobutton(options, text="GitHub CLI", variable=self.mode, value="gh")
        github_mode_radio.pack(side="left")
        markdown_mode_radio = ttk.Radiobutton(options, text="Markdown file", variable=self.mode, value="md")
        markdown_mode_radio.pack(side="left", padx=(8, 0))
        draft_check = ttk.Checkbutton(options, text="Draft", variable=self.draft)
        draft_check.pack(side="left", padx=(20, 0))
        editor_check = ttk.Checkbutton(options, text="Open editor", variable=self.editor)
        editor_check.pack(side="left", padx=(12, 0))
        dry_run_check = ttk.Checkbutton(options, text="Dry run", variable=self.dry_run)
        dry_run_check.pack(side="left", padx=(12, 0))

        ttk.Label(controls, text="Displayed history").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(10, 0))
        displayed_label = ttk.Label(controls, textvariable=self.displayed_history)
        displayed_label.grid(row=2, column=1, columnspan=3, sticky="w", pady=(10, 0))

        toolbar = ttk.Frame(self, padding=(12, 0, 12, 8))
        toolbar.grid(row=3, column=0, sticky="ew")
        refresh_button = ttk.Button(toolbar, text="Refresh", command=self._refresh_repository)
        refresh_button.pack(side="left")
        select_all_button = ttk.Button(toolbar, text="Select all", command=self._select_all)
        select_all_button.pack(side="left", padx=(8, 0))
        clear_button = ttk.Button(toolbar, text="Clear selection", command=self._clear_selection)
        clear_button.pack(side="left", padx=(8, 0))
        help_button = ttk.Button(toolbar, text="Help", command=self._show_help)
        help_button.pack(side="left", padx=(8, 0))
        ttk.Label(toolbar, textvariable=self.status).pack(side="right")

        tree_frame = ttk.Frame(self, padding=(12, 0, 12, 8))
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("selected", "graph", "hash", "date", "author", "subject"),
            show="headings",
            selectmode="browse",
        )
        headings = {
            "selected": "Pick",
            "graph": "Tree",
            "hash": "Commit",
            "date": "Date",
            "author": "Author",
            "subject": "Subject",
        }
        widths = {"selected": 52, "graph": 100, "hash": 90, "date": 100, "author": 160, "subject": 460}
        for column, heading in headings.items():
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=widths[column], anchor="w", stretch=column == "subject")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.tag_configure("picked", background="#e0efe8", foreground="#173b4d")
        self.tree.bind("<Button-1>", self._toggle_row)
        Tooltip(base_label, "Branch the new PR will target. This is not the history currently displayed.")
        Tooltip(self.base_combo, "Select the base branch used by the cherry-pick command and PR.")
        Tooltip(branch_label, "Optional name for the new cherry-pick branch.")
        Tooltip(branch_entry, "Optional name for the new cherry-pick branch.")
        Tooltip(refresh_button, "Reload branches and commits from the launch-directory repository.")
        Tooltip(select_all_button, "Select every commit currently displayed.")
        Tooltip(clear_button, "Clear all commit selections.")
        Tooltip(help_button, "Show an explanation of the GUI workflow and branch scopes.")
        Tooltip(self.tree, "Click a commit row to select or deselect it for cherry-picking.")
        Tooltip(all_branches_check, "Only expands the displayed Git tree to local and remote branches. It does not select or add commits to the cherry-pick.")
        Tooltip(update_base_check, "Pull the selected PR base branch before cherry-picking.")
        Tooltip(github_mode_radio, "Create the PR with the GitHub CLI.")
        Tooltip(markdown_mode_radio, "Write PR details to a Markdown file instead of submitting with gh.")
        Tooltip(draft_check, "Pass --draft when creating the GitHub PR.")
        Tooltip(editor_check, "Pass --editor to gh so you can edit the PR before submission.")
        Tooltip(dry_run_check, "Create the new branch only. Do not cherry-pick commits or push anything.")

        output_frame = ttk.LabelFrame(self, text="Command output", style="Section.TLabelframe", padding=8)
        output_frame.grid(row=4, column=0, sticky="nsew", padx=12, pady=(0, 8))
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        self.output = tk.Text(output_frame, height=7, wrap="word", state="disabled")
        self.output.grid(row=0, column=0, sticky="nsew")
        output_scrollbar = ttk.Scrollbar(output_frame, orient="vertical", command=self.output.yview)
        output_scrollbar.grid(row=0, column=1, sticky="ns")
        self.output.configure(yscrollcommand=output_scrollbar.set)

        footer = ttk.Frame(self, padding=(12, 0, 12, 12))
        footer.grid(row=5, column=0, sticky="ew")
        warning_label = ttk.Label(
            footer,
            text="Warning: this checks out branches, changes the worktree, cherry-picks, and pushes the new branch.",
            style="Warning.TLabel",
            justify="left",
            wraplength=720,
        )
        warning_label.pack(side="left", fill="x", expand=True, padx=(0, 16))
        self.run_button = ttk.Button(footer, text="Cherry-pick selected commits", style="Accent.TButton", command=self._run_cli)
        self.run_button.pack(side="right")

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.repo_dir,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Git command failed")
        return result.stdout

    def _refresh_repository(self) -> None:
        try:
            branches = [branch.strip() for branch in self._git("branch", "--format=%(refname:short)").splitlines()]
            current = self._git("branch", "--show-current").strip()
            self.displayed_history.set(
                "All local and remote branches in tree" if self.all_branches.get() else (current or "Detached HEAD")
            )
            self.base_combo["values"] = branches
            if self.base_branch.get() not in branches:
                default_base = next(
                    (branch for branch in ("master", "main") if branch in branches),
                    current or (branches[0] if branches else ""),
                )
                self.base_branch.set(default_base)
            self._load_commits()
        except (OSError, RuntimeError) as error:
            self.status.set("Repository unavailable")
            messagebox.showerror("Unable to load repository", str(error))

    def _load_commits(self) -> None:
        log_args = ["log"]
        if self.all_branches.get():
            log_args.extend(["--branches", "--remotes"])
        log_args.extend([
            "--date=short",
            "--graph",
            "--decorate",
            "--pretty=format:%H" + COMMIT_SEPARATOR + "%h" + COMMIT_SEPARATOR + "%ad" + COMMIT_SEPARATOR + "%an" + COMMIT_SEPARATOR + "%s",
        ])
        raw = self._git(*log_args)
        self.tree.delete(*self.tree.get_children())
        self.commits.clear()
        for line in raw.splitlines():
            match = COMMIT_PATTERN.match(line)
            if not match:
                continue
            commit = match.groupdict()
            commit_hash = commit["hash"]
            self.commits[commit_hash] = commit
            self.tree.insert(
                "",
                "end",
                iid=commit_hash,
                values=("☐", commit["graph"].strip(), commit["short"], commit["date"], commit["author"], commit["subject"]),
            )
        self.status.set(f"{len(self.commits)} commits loaded")

    def _show_help(self) -> None:
        messagebox.showinfo(
            "git-cp-pr GUI Help",
            "Select commits by clicking their rows, then choose the PR options and run the workflow.\n\n"
            "Displayed history is the checked-out branch by default. Enable All branches in tree to view commits reachable from local and remote branches. This only changes what is displayed; it does not select or add any commits to the cherry-pick.\n\n"
            "PR base (target) is the branch the new PR will merge into; it is independent from the displayed commit history.\n\n"
            "Before running, make sure the worktree is clean and the selected commits apply cleanly. The workflow needs a writable repository and remote; GitHub CLI mode also needs an authenticated gh installation. Conflicts or cancellation remove the temporary branch, while successful runs keep it and return to the original branch.",
        )

    def _toggle_row(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            return
        values = list(self.tree.item(row, "values"))
        values[0] = "☑" if values[0] == "☐" else "☐"
        self.tree.item(row, values=values, tags=("picked",) if values[0] == "☑" else ())
        return "break"

    def _set_selection(self, selected: bool) -> None:
        for row in self.tree.get_children():
            values = list(self.tree.item(row, "values"))
            values[0] = "☑" if selected else "☐"
            self.tree.item(row, values=values, tags=("picked",) if selected else ())

    def _select_all(self) -> None:
        self._set_selection(True)

    def _clear_selection(self) -> None:
        self._set_selection(False)

    def _selected_commits(self) -> List[str]:
        return [
            row
            for row in self.tree.get_children()
            if self.tree.item(row, "values")[0] == "☑"
        ]

    def _build_command(self, selected: List[str]) -> List[str]:
        command = [sys.executable, str(self.cli_script)]
        if self.base_branch.get():
            command.extend(["--base", self.base_branch.get()])
        if self.branch_name.get().strip():
            command.extend(["--name", self.branch_name.get().strip()])
        if self.update_base.get():
            command.append("--update-base")
        command.extend(["--mode", self.mode.get()])
        if self.draft.get():
            command.append("--draft")
        if self.editor.get():
            command.append("--editor")
        if self.dry_run.get():
            command.append("--dry-run")
        command.extend(selected)
        return command

    def _run_cli(self) -> None:
        selected = self._selected_commits()
        if not selected:
            messagebox.showwarning("No commits selected", "Select at least one commit to cherry-pick.")
            return
        if self.running:
            return
        if self.dry_run.get():
            confirmation_message = (
                "This will create the cherry-pick branch and apply the selected commits. It will not push anything.\n\n"
                "The new branch will remain available, and you will return to the original branch. Continue?"
            )
        else:
            confirmation_message = (
                "This will check out the PR base, change the worktree, cherry-pick the selected commits, and push a new branch.\n\n"
                "A conflict or cancellation will abort the cherry-pick and remove the temporary branch. Continue?"
            )
        confirmed = messagebox.askyesno(
            "Confirm cherry-pick workflow",
            confirmation_message,
            icon="warning",
        )
        if not confirmed:
            return
        command = self._build_command(selected)
        self._append_output("$ " + " ".join(command) + "\n")
        self.run_button.configure(state="disabled")
        self.running = True
        threading.Thread(target=self._execute_cli, args=(command,), daemon=True).start()

    def _execute_cli(self, command: List[str]) -> None:
        try:
            process = subprocess.Popen(
                command,
                cwd=self.repo_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            if process.stdout is not None:
                for line in process.stdout:
                    self.output_queue.put(("output", line))
            return_code = process.wait()
            self.output_queue.put(("done", return_code))
        except OSError as error:
            self.output_queue.put(("error", str(error)))

    def _poll_output(self) -> None:
        try:
            while True:
                event, value = self.output_queue.get_nowait()
                if event == "output":
                    self._append_output(value)
                elif event == "done":
                    self.running = False
                    self.run_button.configure(state="normal")
                    self.status.set("Completed" if value == 0 else f"Command failed ({value})")
                else:
                    self.running = False
                    self.run_button.configure(state="normal")
                    self.status.set("Command failed")
                    self._append_output(str(value) + "\n")
        except queue.Empty:
            pass
        self.after(100, self._poll_output)

    def _append_output(self, text: str) -> None:
        self.output.configure(state="normal")
        self.output.insert("end", text)
        self.output.see("end")
        self.output.configure(state="disabled")


def main() -> None:
    CommitPicker().mainloop()


if __name__ == "__main__":
    main()
