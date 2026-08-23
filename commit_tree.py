"""Native Tk commit list with graphical Git history markers."""

import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, Optional, Sequence, Tuple


class CommitTree(ttk.Treeview):
    """Use Treeview's native columns and text markers for Git history."""

    def __init__(self, master: tk.Misc, columns: Sequence[str], **kwargs: Any) -> None:
        self._logical_columns = tuple(columns)
        self._graph_values: Dict[str, str] = {}
        kwargs.pop("background", None)
        kwargs.setdefault("show", ("tree", "headings"))
        kwargs.setdefault("selectmode", "browse")
        native_columns = tuple(column for column in columns if column != "graph")
        super().__init__(master, columns=native_columns, **kwargs)

    def heading(self, column: str, **kwargs: Any) -> None:
        super().heading("#0" if column == "graph" else column, **kwargs)

    def column(self, column: str, **kwargs: Any) -> None:
        super().column("#0" if column == "graph" else column, **kwargs)

    def insert(self, parent: str, index: str, iid: str, values: Sequence[str], **kwargs: Any) -> str:
        graph, native_values = self._split_values(values)
        self._graph_values[iid] = graph
        return super().insert(parent, index, iid=iid, values=native_values, text=self._graph_marker(graph, False), **kwargs)

    def delete(self, *items: str) -> None:
        for iid in items:
            self._graph_values.pop(iid, None)
        super().delete(*items)

    def item(self, iid: str, option: Optional[str] = None, **kwargs: Any) -> Any:
        if "values" in kwargs:
            graph, native_values = self._split_values(kwargs["values"])
            kwargs["values"] = native_values
            tags = kwargs.get("tags", super().item(iid, "tags"))
            self._replace_graph_text(iid, graph, "picked" in tags)
        result = super().item(iid, option, **kwargs)
        if option == "values":
            native_values = tuple(result)
            graph = self._graph_text(iid)
            return self._join_values(graph, native_values)
        if option is None and isinstance(result, dict) and "values" in result:
            result["values"] = self._join_values(self._graph_text(iid), tuple(result["values"]))
        return result

    def _split_values(self, values: Sequence[str]) -> Tuple[str, Tuple[str, ...]]:
        values = tuple(values)
        graph_index = self._logical_columns.index("graph")
        return str(values[graph_index]), values[:graph_index] + values[graph_index + 1:]

    def _join_values(self, graph: str, native_values: Tuple[str, ...]) -> Tuple[str, ...]:
        graph_index = self._logical_columns.index("graph")
        return native_values[:graph_index] + (graph,) + native_values[graph_index:]

    def _graph_text(self, iid: str) -> str:
        return self._graph_values.get(iid, "")

    def _replace_graph_text(self, iid: str, graph: str, picked: bool) -> None:
        self._graph_values[iid] = graph
        super().item(iid, text=self._graph_marker(graph, picked))

    @staticmethod
    def _graph_marker(graph: str, picked: bool) -> str:
        """Translate Git's ASCII graph into compact native text markers."""
        commit_marker = "🟠" if picked else "🔵"
        markers = {"*": commit_marker, "|": "│", "\\": "╲", "/": "╱", "-": "─"}
        return "".join(markers.get(character, character) for character in graph) or commit_marker
