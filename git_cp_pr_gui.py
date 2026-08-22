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


class CommitPicker(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("git-cp-pr commit picker")
        self.geometry("1100x720")
        self.minsize(800, 520)
        self.project_dir = Path(__file__).resolve().parent
        self.commits: Dict[str, Dict[str, str]] = {}
        self.output_queue: queue.Queue = queue.Queue()
        self.running = False

        self.base_branch = tk.StringVar()
        self.branch_name = tk.StringVar()
        self.update_base = tk.BooleanVar()
        self.mode = tk.StringVar(value="gh")
        self.draft = tk.BooleanVar()
        self.editor = tk.BooleanVar()
        self.status = tk.StringVar(value="Loading commits...")

        self._build_ui()
        self._refresh_repository()
        self.after(100, self._poll_output)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.rowconfigure(3, weight=1)

        controls = ttk.Frame(self, padding=12)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(3, weight=1)

        ttk.Label(controls, text="Base branch").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.base_combo = ttk.Combobox(controls, textvariable=self.base_branch, state="readonly")
        self.base_combo.grid(row=0, column=1, sticky="ew", padx=(0, 16))
        ttk.Label(controls, text="New branch").grid(row=0, column=2, sticky="w", padx=(0, 8))
        ttk.Entry(controls, textvariable=self.branch_name).grid(row=0, column=3, sticky="ew")

        options = ttk.Frame(controls)
        options.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        ttk.Checkbutton(options, text="Update base", variable=self.update_base).pack(side="left")
        ttk.Label(options, text="PR mode:").pack(side="left", padx=(20, 6))
        ttk.Radiobutton(options, text="GitHub CLI", variable=self.mode, value="gh").pack(side="left")
        ttk.Radiobutton(options, text="Markdown file", variable=self.mode, value="md").pack(side="left", padx=(8, 0))
        ttk.Checkbutton(options, text="Draft", variable=self.draft).pack(side="left", padx=(20, 0))
        ttk.Checkbutton(options, text="Open editor", variable=self.editor).pack(side="left", padx=(12, 0))

        toolbar = ttk.Frame(self, padding=(12, 0, 12, 8))
        toolbar.grid(row=2, column=0, sticky="ew")
        ttk.Button(toolbar, text="Refresh", command=self._refresh_repository).pack(side="left")
        ttk.Button(toolbar, text="Select all", command=self._select_all).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="Clear selection", command=self._clear_selection).pack(side="left", padx=(8, 0))
        ttk.Label(toolbar, textvariable=self.status).pack(side="right")

        tree_frame = ttk.Frame(self, padding=(12, 0, 12, 8))
        tree_frame.grid(row=1, column=0, sticky="nsew")
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
        self.tree.bind("<Button-1>", self._toggle_row)

        output_frame = ttk.LabelFrame(self, text="Command output", padding=8)
        output_frame.grid(row=3, column=0, sticky="nsew", padx=12, pady=(0, 8))
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        self.output = tk.Text(output_frame, height=7, wrap="word", state="disabled")
        self.output.grid(row=0, column=0, sticky="nsew")
        output_scrollbar = ttk.Scrollbar(output_frame, orient="vertical", command=self.output.yview)
        output_scrollbar.grid(row=0, column=1, sticky="ns")
        self.output.configure(yscrollcommand=output_scrollbar.set)

        footer = ttk.Frame(self, padding=(12, 0, 12, 12))
        footer.grid(row=4, column=0, sticky="ew")
        self.run_button = ttk.Button(footer, text="Cherry-pick selected commits", command=self._run_cli)
        self.run_button.pack(side="right")

    def _git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.project_dir,
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
            self.base_combo["values"] = branches
            if current in branches:
                self.base_branch.set(current)
            elif branches and not self.base_branch.get():
                self.base_branch.set(branches[0])
            self._load_commits()
        except (OSError, RuntimeError) as error:
            self.status.set("Repository unavailable")
            messagebox.showerror("Unable to load repository", str(error))

    def _load_commits(self) -> None:
        raw = self._git(
            "log",
            "--all",
            "--date=short",
            "--graph",
            "--decorate",
            "--pretty=format:%H" + COMMIT_SEPARATOR + "%h" + COMMIT_SEPARATOR + "%ad" + COMMIT_SEPARATOR + "%an" + COMMIT_SEPARATOR + "%s",
        )
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

    def _toggle_row(self, event: tk.Event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            return
        values = list(self.tree.item(row, "values"))
        values[0] = "☑" if values[0] == "☐" else "☐"
        self.tree.item(row, values=values)
        return "break"

    def _set_selection(self, selected: bool) -> None:
        for row in self.tree.get_children():
            values = list(self.tree.item(row, "values"))
            values[0] = "☑" if selected else "☐"
            self.tree.item(row, values=values)

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
        command = [sys.executable, str(self.project_dir / "git_cp_pr.py")]
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
        command.extend(selected)
        return command

    def _run_cli(self) -> None:
        selected = self._selected_commits()
        if not selected:
            messagebox.showwarning("No commits selected", "Select at least one commit to cherry-pick.")
            return
        if self.running:
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
                cwd=self.project_dir,
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
