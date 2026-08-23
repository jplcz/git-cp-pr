"""Native Tk commit list used by the graphical commit picker."""

import tkinter as tk
from tkinter import ttk
from typing import Any, Sequence


class CommitTree(ttk.Treeview):
    """Keep native Treeview layout while providing the commit-list boundary."""

    def __init__(self, master: tk.Misc, columns: Sequence[str], **kwargs: Any) -> None:
        kwargs.pop("background", None)
        kwargs.setdefault("show", "headings")
        kwargs.setdefault("selectmode", "browse")
        super().__init__(master, columns=tuple(columns), **kwargs)
