#!/usr/bin/env python3
"""Tkinter frontend for selecting commits and running git-cp-pr."""

import json
import ast
import gettext
import locale
import os
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Dict, List, Optional, Pattern, Tuple

from commit_tree import CommitTree
from git_cp_pr import __version__
from progressive_commit_loader import ProgressiveCommitLoader


PROJECT_PAGE_URL = "https://jplcz.github.io/git-cp-pr/"
SUPPORTED_LANGUAGES = ("en", "pl", "ko")
GETTEXT_DOMAIN = "git_cp_pr_gui"
LOCALE_DIRS = (
    Path(__file__).resolve().with_name("locale"),
    Path(sys.prefix) / "share" / "git-cp-pr" / "locale",
)


class PoFileTranslations(gettext.NullTranslations):
    def __init__(self, catalog: Dict[str, str]) -> None:
        super().__init__()
        self.catalog = catalog

    def gettext(self, message: str) -> str:
        return self.catalog.get(message, message)
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
        self.language = tk.StringVar(value=self._detect_language())
        self.translations: gettext.NullTranslations = gettext.NullTranslations()
        self._load_translations()
        self.title(self._tr("git-cp-pr commit picker"))
        self.geometry("1100x720")
        self.minsize(800, 520)
        self.repo_dir = Path.cwd()
        self.commit_loader = ProgressiveCommitLoader(self._git, page_size=200)
        self.loading_commits = False
        self._window_icon = self._load_window_icon()
        self.cli_script = Path(__file__).resolve().with_name("git_cp_pr.py")
        self.commits: Dict[str, Dict[str, str]] = {}
        self.commit_diffs: Dict[str, str] = {}
        self.output_queue: queue.Queue = queue.Queue()
        self.running = False

        self.base_branch = tk.StringVar()
        self.branch_name = tk.StringVar()
        self.update_base = tk.BooleanVar()
        self.all_branches = tk.BooleanVar(value=False)
        self.mode = tk.StringVar(value="gh")
        self.draft = tk.BooleanVar()
        self.dry_run = tk.BooleanVar()
        self.search_query = tk.StringVar()
        self.search_regex = tk.BooleanVar()
        self.search_pattern: Optional[Pattern[str]] = None
        self.searching = False
        self.displayed_history = tk.StringVar(value=self._tr("Loading..."))
        self.status = tk.StringVar(value=self._tr("Loading commits..."))
        self.diff_status = tk.StringVar(value=self._tr("Select a commit checkbox to preview its diff"))

        self._load_preferences()
        self.title(self._tr("git-cp-pr commit picker"))
        self.displayed_history.set(self._tr("Loading..."))
        self.status.set(self._tr("Loading commits..."))
        self.diff_status.set(self._tr("Select a commit checkbox to preview its diff"))
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._configure_style()
        self._build_ui()
        self._refresh_repository()
        self.after(100, self._poll_output)

    def _normalize_language(self, language: str) -> str:
        normalized = (language or "").split(".", 1)[0].split("_", 1)[0].split("-", 1)[0].lower()
        return normalized if normalized in SUPPORTED_LANGUAGES else "en"

    def _parse_po_file(self, file_path: Path) -> Dict[str, str]:
        def unescape_po(value: str) -> str:
            # Parse PO-quoted text without mangling UTF-8 characters.
            return ast.literal_eval(f'"{value}"')

        catalog: Dict[str, str] = {}
        current_msgid: Optional[str] = None
        current_msgstr: Optional[str] = None
        active_field: Optional[str] = None

        for raw_line in file_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("msgid "):
                if current_msgid is not None and current_msgstr is not None and current_msgid:
                    catalog[current_msgid] = current_msgstr
                current_msgid = unescape_po(line[6:].strip().strip('"'))
                current_msgstr = ""
                active_field = "msgid"
                continue
            if line.startswith("msgstr "):
                current_msgstr = unescape_po(line[7:].strip().strip('"'))
                active_field = "msgstr"
                continue
            if line.startswith('"') and line.endswith('"') and active_field:
                value = unescape_po(line.strip('"'))
                if active_field == "msgid" and current_msgid is not None:
                    current_msgid += value
                elif active_field == "msgstr" and current_msgstr is not None:
                    current_msgstr += value

        if current_msgid is not None and current_msgstr is not None and current_msgid:
            catalog[current_msgid] = current_msgstr
        return catalog

    def _load_translations(self) -> None:
        language = self._normalize_language(self.language.get())
        language_po = next(
            (
                locale_dir / language / "LC_MESSAGES" / f"{GETTEXT_DOMAIN}.po"
                for locale_dir in LOCALE_DIRS
                if (locale_dir / language / "LC_MESSAGES" / f"{GETTEXT_DOMAIN}.po").is_file()
            ),
            None,
        )

        try:
            if language == "en" or language_po is None:
                self.translations = gettext.NullTranslations()
            else:
                self.translations = PoFileTranslations(self._parse_po_file(language_po))
        except OSError:
            self.translations = gettext.NullTranslations()

    def _detect_language(self) -> str:
        for candidate in (
            os.environ.get("LC_ALL"),
            os.environ.get("LC_MESSAGES"),
            os.environ.get("LANG"),
            locale.getlocale()[0],
            locale.getdefaultlocale()[0] if hasattr(locale, "getdefaultlocale") else None,
        ):
            if not candidate:
                continue
            normalized = self._normalize_language(candidate)
            if normalized in SUPPORTED_LANGUAGES:
                return normalized
        return "en"

    def _tr(self, key: str, **kwargs: object) -> str:
        text = self.translations.gettext(key)
        return text.format(**kwargs) if kwargs else text

    def _preferences_path(self) -> Path:
        if sys.platform.startswith("win"):
            config_dir = Path.home() / "AppData" / "Roaming"
        else:
            config_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        return config_dir / "git-cp-pr" / "settings.json"

    def _load_preferences(self) -> None:
        try:
            preferences = json.loads(self._preferences_path().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(preferences, dict):
            return
        self.base_branch.set(str(preferences.get("base_branch", "")))
        self.branch_name.set(str(preferences.get("branch_name", "")))
        for name, variable in (
            ("update_base", self.update_base),
            ("all_branches", self.all_branches),
            ("draft", self.draft),
            ("dry_run", self.dry_run),
        ):
            value = preferences.get(name)
            if isinstance(value, bool):
                variable.set(value)
        language = preferences.get("language")
        if isinstance(language, str):
            self.language.set(self._normalize_language(language))
            self._load_translations()
        mode = preferences.get("mode")
        if mode in ("gh", "md"):
            self.mode.set(mode)

    def _save_preferences(self) -> None:
        preferences = {
            "base_branch": self.base_branch.get(),
            "branch_name": self.branch_name.get(),
            "update_base": self.update_base.get(),
            "all_branches": self.all_branches.get(),
            "mode": self.mode.get(),
            "draft": self.draft.get(),
            "dry_run": self.dry_run.get(),
            "language": self.language.get(),
        }
        path = self._preferences_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(preferences, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass

    def _close(self) -> None:
        self._save_preferences()
        self.destroy()

    def _open_project_page(self) -> None:
        webbrowser.open(PROJECT_PAGE_URL)

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
        style.configure("Link.TLabel", background="#f4f1ea", foreground="#b95332", font=("TkDefaultFont", 10, "underline"))
        style.configure("Warning.TLabel", background="#f4f1ea", foreground="#9a4b2d", font=("TkDefaultFont", 9, "bold"))
        style.configure("Accent.TButton", background="#d96c43", foreground="#ffffff", padding=(14, 8), font=("TkDefaultFont", 10, "bold"))
        style.map("Accent.TButton", background=[("active", "#bd5632"), ("disabled", "#c8b9ae")])
        style.configure("Treeview", background="#fffdf8", fieldbackground="#fffdf8", foreground="#263238", rowheight=28, bordercolor="#d8d0c2")
        style.configure("Treeview.Heading", background="#e5ded1", foreground="#173b4d", font=("TkDefaultFont", 10, "bold"), padding=(6, 7))
        style.map("Treeview", background=[("selected", "#c8d9d8")], foreground=[("selected", "#173b4d")])

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.rowconfigure(5, weight=1)

        header = ttk.Frame(self, style="Header.TFrame", padding=(20, 16))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text=self._tr("Cherry-pick workspace"), style="Header.TLabel").pack(anchor="w")
        ttk.Label(header, text=str(self.repo_dir), style="Subheader.TLabel").pack(anchor="w", pady=(4, 0))

        controls = ttk.Frame(self, padding=12)
        controls.grid(row=1, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(3, weight=1)

        base_label = ttk.Label(controls, text=self._tr("PR base (target)"))
        base_label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.base_combo = ttk.Combobox(controls, textvariable=self.base_branch, state="readonly")
        self.base_combo.grid(row=0, column=1, sticky="ew", padx=(0, 16))
        branch_label = ttk.Label(controls, text=self._tr("New branch"))
        branch_label.grid(row=0, column=2, sticky="w", padx=(0, 8))
        branch_entry = ttk.Entry(controls, textvariable=self.branch_name)
        branch_entry.grid(row=0, column=3, sticky="ew")

        options = ttk.Frame(controls)
        options.grid(row=1, column=0, columnspan=4, sticky="ew", pady=(12, 0))
        all_branches_check = ttk.Checkbutton(options, text=self._tr("All branches in tree (view only)"), variable=self.all_branches, command=self._load_commits)
        all_branches_check.pack(side="left")
        update_base_check = ttk.Checkbutton(options, text=self._tr("Update base"), variable=self.update_base)
        update_base_check.pack(side="left")
        ttk.Label(options, text=self._tr("PR mode:")).pack(side="left", padx=(20, 6))
        github_mode_radio = ttk.Radiobutton(options, text=self._tr("GitHub CLI"), variable=self.mode, value="gh")
        github_mode_radio.pack(side="left")
        markdown_mode_radio = ttk.Radiobutton(options, text=self._tr("Markdown file"), variable=self.mode, value="md")
        markdown_mode_radio.pack(side="left", padx=(8, 0))
        draft_check = ttk.Checkbutton(options, text=self._tr("Draft"), variable=self.draft)
        draft_check.pack(side="left", padx=(20, 0))
        dry_run_check = ttk.Checkbutton(options, text=self._tr("Dry run"), variable=self.dry_run)
        dry_run_check.pack(side="left", padx=(12, 0))

        ttk.Label(controls, text=self._tr("Displayed history")).grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(10, 0))
        displayed_label = ttk.Label(controls, textvariable=self.displayed_history)
        displayed_label.grid(row=2, column=1, columnspan=3, sticky="w", pady=(10, 0))

        toolbar = ttk.Frame(self, padding=(12, 0, 12, 8))
        toolbar.grid(row=3, column=0, sticky="ew")
        refresh_button = ttk.Button(toolbar, text=self._tr("Refresh"), command=self._refresh_repository)
        refresh_button.pack(side="left")
        select_all_button = ttk.Button(toolbar, text=self._tr("Select all"), command=self._select_all)
        select_all_button.pack(side="left", padx=(8, 0))
        clear_button = ttk.Button(toolbar, text=self._tr("Clear selection"), command=self._clear_selection)
        clear_button.pack(side="left", padx=(8, 0))
        help_button = ttk.Button(toolbar, text=self._tr("Help"), command=self._show_help)
        help_button.pack(side="left", padx=(8, 0))
        ttk.Label(toolbar, textvariable=self.status).pack(side="right")

        search_toolbar = ttk.Frame(self, padding=(12, 0, 12, 8))
        search_toolbar.grid(row=4, column=0, sticky="ew")
        ttk.Label(search_toolbar, text=self._tr("Search commits:")).pack(side="left", padx=(0, 6))
        search_entry = ttk.Entry(search_toolbar, textvariable=self.search_query, width=28)
        search_entry.pack(side="left", fill="x", expand=True)
        search_entry.bind("<Return>", lambda _event: self._start_commit_search())
        regex_check = ttk.Checkbutton(search_toolbar, text=self._tr("Regexp"), variable=self.search_regex)
        regex_check.pack(side="left", padx=(6, 0))
        search_button = ttk.Button(search_toolbar, text=self._tr("Search"), command=self._start_commit_search)
        search_button.pack(side="left", padx=(6, 0))
        clear_search_button = ttk.Button(search_toolbar, text=self._tr("Clear search"), command=self._clear_search)
        clear_search_button.pack(side="left", padx=(6, 0))

        tree_frame = ttk.Frame(self, padding=(12, 0, 12, 8))
        tree_frame.grid(row=2, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.tree = CommitTree(
            tree_frame,
            columns=("selected", "graph", "hash", "date", "author", "subject"),
            background="#fffdf8",
        )
        headings = {
            "selected": self._tr("Pick"),
            "graph": self._tr("Tree"),
            "hash": self._tr("Commit"),
            "date": self._tr("Date"),
            "author": self._tr("Author"),
            "subject": self._tr("Subject"),
        }
        widths = {"selected": 52, "graph": 100, "hash": 90, "date": 100, "author": 160, "subject": 460}
        for column, heading in headings.items():
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=widths[column], anchor="w", stretch=column == "subject")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree_yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.tag_configure("picked", background="#e0efe8", foreground="#173b4d")
        self.tree.bind("<Button-1>", self._toggle_row)
        self.tree.bind("<MouseWheel>", self._on_tree_scroll, add="+")
        self.tree.bind("<Button-4>", self._on_tree_scroll, add="+")
        self.tree.bind("<Button-5>", self._on_tree_scroll, add="+")
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        Tooltip(base_label, self._tr("Branch the new PR will target. This is not the history currently displayed."))
        Tooltip(self.base_combo, self._tr("Select the base branch used by the cherry-pick command and PR."))
        Tooltip(branch_label, self._tr("Optional name for the new cherry-pick branch."))
        Tooltip(branch_entry, self._tr("Optional name for the new cherry-pick branch."))
        Tooltip(refresh_button, self._tr("Reload branches and commits from the launch-directory repository."))
        Tooltip(select_all_button, self._tr("Select every commit currently displayed."))
        Tooltip(clear_button, self._tr("Clear all commit selections."))
        Tooltip(help_button, self._tr("Show an explanation of the GUI workflow and branch scopes."))
        Tooltip(search_entry, self._tr("Search loaded commits by subject, description, author, hash, or date."))
        Tooltip(regex_check, self._tr("Treat the search text as a regular expression."))
        Tooltip(search_button, self._tr("Search the complete displayed history."))
        Tooltip(clear_search_button, self._tr("Clear the search and show all loaded commits."))
        Tooltip(self.tree, self._tr("Click the Pick checkbox to select or deselect a commit for cherry-picking."))
        Tooltip(all_branches_check, self._tr("Only expands the displayed Git tree to local and remote branches. It does not select or add commits to the cherry-pick."))
        Tooltip(update_base_check, self._tr("Pull the selected PR base branch before cherry-picking."))
        Tooltip(github_mode_radio, self._tr("Create the PR with the GitHub CLI."))
        Tooltip(markdown_mode_radio, self._tr("Write PR details to a Markdown file instead of submitting with gh."))
        Tooltip(draft_check, self._tr("Pass --draft when creating the GitHub PR."))
        Tooltip(dry_run_check, self._tr("Create the new branch only. Do not cherry-pick commits or push anything."))

        self.bottom_tabs = ttk.Notebook(self)
        self.bottom_tabs.grid(row=5, column=0, sticky="nsew", padx=12, pady=(0, 8))

        preview_frame = ttk.Frame(self.bottom_tabs, padding=8)
        self.bottom_tabs.add(preview_frame, text=self._tr("Diff preview"))
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(1, weight=1)
        ttk.Label(preview_frame, textvariable=self.diff_status, style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.diff_preview = tk.Text(preview_frame, height=12, wrap="none", state="disabled", font=("TkFixedFont", 10))
        self.diff_preview.grid(row=1, column=0, sticky="nsew")
        self.diff_preview.tag_configure("diff_meta", foreground="#5f6368")
        self.diff_preview.tag_configure("diff_hunk", foreground="#0b5394")
        self.diff_preview.tag_configure("diff_add", foreground="#1b5e20")
        self.diff_preview.tag_configure("diff_del", foreground="#8b1e1e")
        self.diff_preview.tag_configure("diff_file", foreground="#173b4d", font=("TkFixedFont", 10, "bold"))
        preview_y_scrollbar = ttk.Scrollbar(preview_frame, orient="vertical", command=self.diff_preview.yview)
        preview_y_scrollbar.grid(row=1, column=1, sticky="ns")
        preview_x_scrollbar = ttk.Scrollbar(preview_frame, orient="horizontal", command=self.diff_preview.xview)
        preview_x_scrollbar.grid(row=2, column=0, sticky="ew")
        self.diff_preview.configure(yscrollcommand=preview_y_scrollbar.set, xscrollcommand=preview_x_scrollbar.set)

        self.output_tab = ttk.Frame(self.bottom_tabs, padding=8)
        self.bottom_tabs.add(self.output_tab, text=self._tr("Command output"))
        self.bottom_tabs.tab(self.output_tab, state="hidden")
        output_frame = ttk.Frame(self.output_tab)
        output_frame.grid(row=0, column=0, sticky="nsew")
        self.output_tab.columnconfigure(0, weight=1)
        self.output_tab.rowconfigure(0, weight=1)
        output_frame.columnconfigure(0, weight=1)
        output_frame.rowconfigure(0, weight=1)
        self.output = tk.Text(output_frame, height=7, wrap="word", state="disabled")
        self.output.grid(row=0, column=0, sticky="nsew")
        output_scrollbar = ttk.Scrollbar(output_frame, orient="vertical", command=self.output.yview)
        output_scrollbar.grid(row=0, column=1, sticky="ns")
        self.output.configure(yscrollcommand=output_scrollbar.set)

        footer = ttk.Frame(self, padding=(12, 0, 12, 12))
        footer.grid(row=6, column=0, sticky="ew")
        footer_details = ttk.Frame(footer)
        footer_details.pack(side="left", fill="x", expand=True, padx=(0, 16))
        warning_label = ttk.Label(
            footer_details,
            text=self._tr("Warning: this checks out branches, changes the worktree, cherry-picks, and pushes the new branch."),
            style="Warning.TLabel",
            justify="left",
            wraplength=720,
        )
        warning_label.pack(anchor="w", fill="x")
        footer_meta = ttk.Frame(footer_details)
        footer_meta.pack(anchor="w", fill="x", pady=(6, 0))
        ttk.Label(footer_meta, text=self._tr("Version {version}", version=__version__), style="Muted.TLabel").pack(side="left")
        project_link = ttk.Label(footer_meta, text=self._tr("Project page"), style="Link.TLabel", cursor="hand2")
        project_link.pack(side="left", padx=(14, 0))
        project_link.bind("<Button-1>", lambda _event: self._open_project_page())
        Tooltip(project_link, self._tr("Open the GitHub Pages project site."))

        language_frame = ttk.Frame(footer)
        language_frame.pack(side="right", padx=(0, 12))
        ttk.Label(language_frame, text=self._tr("Language:")).pack(side="left", padx=(0, 6))
        language_selector = ttk.Combobox(
            language_frame,
            state="readonly",
            width=9,
            values=list(SUPPORTED_LANGUAGES),
            textvariable=self.language,
        )
        language_selector.pack(side="left")
        language_selector.bind("<<ComboboxSelected>>", self._on_language_change)

        self.run_button = ttk.Button(footer, text=self._tr("Cherry-pick selected commits"), style="Accent.TButton", command=self._run_cli)
        self.run_button.pack(side="right")

    def _on_language_change(self, _event: tk.Event) -> None:
        self.language.set(self._normalize_language(self.language.get()))
        self._load_translations()
        self._save_preferences()
        self.title(self._tr("git-cp-pr commit picker"))
        for child in self.winfo_children():
            child.destroy()
        self._build_ui()
        self._refresh_repository()

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
                self._tr("All local and remote branches in tree") if self.all_branches.get() else (current or self._tr("Detached HEAD"))
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
            self.status.set(self._tr("Repository unavailable"))
            messagebox.showerror(self._tr("Unable to load repository"), str(error))

    def _load_commits(self) -> None:
        self.searching = False
        self.search_pattern = None
        self.tree.delete(*self.tree.get_children())
        self.commits.clear()
        self.commit_diffs.clear()
        self.commit_loader.reset(self.all_branches.get())
        self._load_next_commits()
        self._set_diff_preview_text(self._tr("Select a commit checkbox to preview its diff") + "\n")
        self.diff_status.set(self._tr("Select a commit checkbox to preview its diff"))

    def _load_next_commits(self) -> None:
        if self.loading_commits or self.commit_loader.exhausted:
            return
        self.loading_commits = True
        try:
            page = self.commit_loader.load_next()
            descriptions = self._load_commit_descriptions(page)
            for commit in page:
                commit_hash = commit["hash"]
                if commit_hash in self.commits:
                    continue
                commit["description"] = descriptions.get(commit_hash, "")
                self.commits[commit_hash] = commit
                if self.search_pattern is None or self._commit_matches(commit):
                    self._insert_commit(commit)
            self.status.set(self._tr("{count} commits loaded", count=len(self.commits)))
        except (OSError, RuntimeError) as error:
            self.status.set(self._tr("Repository unavailable"))
            messagebox.showerror(self._tr("Unable to load commits"), str(error))
        finally:
            self.loading_commits = False

    def _load_commit_descriptions(self, commits: List[Dict[str, str]]) -> Dict[str, str]:
        if not commits:
            return {}
        raw = self._git(
            "log",
            "--no-walk",
            "--format=%H\x1f%B\x1e",
            *(commit["hash"] for commit in commits),
        )
        descriptions: Dict[str, str] = {}
        for record in raw.split("\x1e"):
            if "\x1f" not in record:
                continue
            commit_hash, description = record.split("\x1f", 1)
            descriptions[commit_hash.strip()] = description.strip()
        return descriptions

    def _tree_yview(self, *args: str) -> None:
        self.tree.yview(*args)
        self.after_idle(self._load_more_if_needed)

    def _on_tree_scroll(self, _event: tk.Event) -> None:
        self.after_idle(self._load_more_if_needed)

    def _load_more_if_needed(self) -> None:
        if not self.searching and self.tree.yview()[1] >= 0.95:
            self._load_next_commits()

    def _insert_commit(self, commit: Dict[str, str]) -> None:
        self.tree.insert(
            "",
            "end",
            iid=commit["hash"],
            values=("☐", commit["graph"].strip(), commit["short"], commit["date"], commit["author"], commit["subject"]),
        )

    def _commit_matches(self, commit: Dict[str, str]) -> bool:
        searchable = " ".join(commit[field] for field in ("hash", "short", "date", "author", "subject", "description"))
        return self.search_pattern.search(searchable) is not None if self.search_pattern else True

    def _start_commit_search(self) -> None:
        query = self.search_query.get()
        if not query:
            self.searching = False
            self.search_pattern = None
            self.tree.delete(*self.tree.get_children())
            for commit in self.commits.values():
                self._insert_commit(commit)
            self.status.set(self._tr("{count} commits loaded", count=len(self.commits)))
            return
        try:
            self.search_pattern = re.compile(query if self.search_regex.get() else re.escape(query), re.IGNORECASE)
        except re.error as error:
            self.status.set(self._tr("Invalid regular expression: {error}", error=str(error)))
            return
        self.searching = True
        self.tree.delete(*self.tree.get_children())
        for commit in self.commits.values():
            if self._commit_matches(commit):
                self._insert_commit(commit)
        self.status.set(self._tr("Searching commits..."))
        self.after_idle(self._continue_commit_search)

    def _clear_search(self) -> None:
        self.search_query.set("")
        self._start_commit_search()

    def _continue_commit_search(self) -> None:
        if not self.searching:
            return
        if self.commit_loader.exhausted:
            self.searching = False
            self.status.set(self._tr("{count} matching commits", count=len(self.tree.get_children())))
            return
        self._load_next_commits()
        self.after(1, self._continue_commit_search)

    def _show_help(self) -> None:
        messagebox.showinfo(
            self._tr("git-cp-pr GUI Help"),
            self._tr("Select commits using the Pick checkboxes, then choose the PR options and run the workflow.\n\nDisplayed history is the checked-out branch by default. Enable All branches in tree to view commits reachable from local and remote branches. This only changes what is displayed; it does not select or add any commits to the cherry-pick.\n\nPR base (target) is the branch the new PR will merge into; it is independent from the displayed commit history.\n\nBefore running, make sure the worktree is clean and the selected commits apply cleanly. The workflow needs a writable repository and remote; GitHub CLI mode also needs an authenticated gh installation. Conflicts or cancellation remove the temporary branch, while successful runs keep it and return to the original branch."),
        )

    def _toggle_row(self, event: tk.Event) -> None:
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return None
        row = self.tree.identify_row(event.y)
        if not row:
            return None
        self.tree.selection_set(row)
        column = self.tree.identify_column(event.x)
        if column != "#1":
            return "break"
        values = list(self.tree.item(row, "values"))
        values[0] = "☑" if values[0] == "☐" else "☐"
        self.tree.item(row, values=values, tags=("picked",) if values[0] == "☑" else ())
        self._update_diff_preview(row)
        return "break"

    def _on_tree_select(self, _event: tk.Event) -> None:
        selected_rows = self.tree.selection()
        self._update_diff_preview(selected_rows[0] if selected_rows else None)

    def _set_selection(self, selected: bool) -> None:
        for row in self.tree.get_children():
            values = list(self.tree.item(row, "values"))
            values[0] = "☑" if selected else "☐"
            self.tree.item(row, values=values, tags=("picked",) if selected else ())
        selected_rows = self.tree.selection()
        if selected_rows:
            self._update_diff_preview(selected_rows[0])
            return
        if selected:
            rows = self.tree.get_children()
            self._update_diff_preview(rows[0] if rows else None)
        else:
            self._update_diff_preview(None)

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

    def _set_diff_preview_text(self, text: str) -> None:
        self.diff_preview.configure(state="normal")
        self.diff_preview.delete("1.0", "end")
        for line in text.splitlines(keepends=True):
            tags = self._diff_tags_for_line(line)
            self.diff_preview.insert("end", line, tags)
        self.diff_preview.see("1.0")
        self.diff_preview.configure(state="disabled")

    def _diff_tags_for_line(self, line: str) -> Tuple[str, ...]:
        if line.startswith("diff --git ") or line.startswith("--- ") or line.startswith("+++ "):
            return ("diff_file",)
        if line.startswith("@@ "):
            return ("diff_hunk",)
        if line.startswith("+") and not line.startswith("+++"):
            return ("diff_add",)
        if line.startswith("-") and not line.startswith("---"):
            return ("diff_del",)
        if line.startswith(("commit ", "Author:", "Date:", "index ")):
            return ("diff_meta",)
        return ()

    def _commit_diff(self, commit_hash: str) -> str:
        cached = self.commit_diffs.get(commit_hash)
        if cached is not None:
            return cached
        result = subprocess.run(
            ["git", "show", "--no-color", commit_hash],
            cwd=self.repo_dir,
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Unable to load commit diff")
        self.commit_diffs[commit_hash] = result.stdout
        return result.stdout

    def _update_diff_preview(self, preferred_commit: Optional[str]) -> None:
        rows = set(self.tree.get_children())
        commit_hash: Optional[str] = None
        if preferred_commit and preferred_commit in rows:
            commit_hash = preferred_commit
        else:
            selected_rows = self.tree.selection()
            if selected_rows:
                commit_hash = selected_rows[0]
            else:
                picked = self._selected_commits()
                if picked:
                    commit_hash = picked[0]

        if commit_hash is None:
            self.diff_status.set(self._tr("Select a commit row or checkbox to preview its diff"))
            self._set_diff_preview_text(self._tr("Select a commit row or checkbox to preview its diff") + "\n")
            return

        picked_count = len(self._selected_commits())
        commit_meta = self.commits.get(commit_hash, {})
        summary = f"{commit_meta.get('short', commit_hash[:8])} - {commit_meta.get('subject', '')}".strip()
        if picked_count > 1:
            self.diff_status.set(self._tr("Showing {summary} ({count} commits checked)", summary=summary, count=picked_count))
        else:
            self.diff_status.set(self._tr("Showing {summary}", summary=summary))

        try:
            self._set_diff_preview_text(self._commit_diff(commit_hash))
        except (OSError, RuntimeError) as error:
            self._set_diff_preview_text(self._tr("Failed to load diff for {commit}: {error}\n", commit=commit_hash, error=error))

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
        if self.dry_run.get():
            command.append("--dry-run")
        command.extend(selected)
        return command

    def _run_cli(self) -> None:
        selected = self._selected_commits()
        if not selected:
            messagebox.showwarning(self._tr("No commits selected"), self._tr("Select at least one commit to cherry-pick."))
            return
        if self.running:
            return
        if self.dry_run.get():
            confirmation_message = self._tr("This will create the cherry-pick branch and apply the selected commits. It will not push anything.\n\nThe new branch will remain available, and you will return to the original branch. Continue?")
        else:
            confirmation_message = self._tr("This will check out the PR base, change the worktree, cherry-pick the selected commits, and push a new branch.\n\nA conflict or cancellation will abort the cherry-pick and remove the temporary branch. Continue?")
        confirmed = messagebox.askyesno(
            self._tr("Confirm cherry-pick workflow"),
            confirmation_message,
            icon="warning",
        )
        if not confirmed:
            return
        self._save_preferences()
        command = self._build_command(selected)
        self._show_output_tab()
        self._append_output("$ " + " ".join(command) + "\n")
        self.run_button.configure(state="disabled")
        self.running = True
        threading.Thread(target=self._execute_cli, args=(command,), daemon=True).start()

    def _show_output_tab(self) -> None:
        self.bottom_tabs.tab(self.output_tab, state="normal")
        self.bottom_tabs.select(self.output_tab)

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
                    self.status.set(self._tr("Completed") if value == 0 else self._tr("Command failed ({code})", code=value))
                else:
                    self.running = False
                    self.run_button.configure(state="normal")
                    self.status.set(self._tr("Command failed"))
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
