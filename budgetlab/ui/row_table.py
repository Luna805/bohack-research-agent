"""Read-only table for the workspace: a click highlights a row, a double click (or Enter) opens it.

``st.dataframe`` row selection always draws a checkbox column and has no double-click
event, so the file list and the experiment table use this small custom component instead.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import streamlit as st

_HTML = """
<div class="wrap">
  <table>
    <thead><tr></tr></thead>
    <tbody></tbody>
  </table>
  <div class="empty" hidden></div>
</div>
"""

_CSS = """
.wrap {
  overflow: auto;
  border: 1px solid var(--st-dataframe-border-color, var(--st-border-color));
  border-radius: var(--st-base-radius, 0.5rem);
  background: var(--st-background-color);
  color: var(--st-text-color);
  font-family: var(--st-font);
  font-size: 14px;
}
table { width: 100%; border-collapse: collapse; }
th {
  position: sticky;
  top: 0;
  z-index: 1;
  padding: 8px 12px;
  text-align: left;
  font-weight: 400;
  white-space: nowrap;
  color: var(--st-dataframe-header-text-color, var(--st-text-color));
  background: var(--st-dataframe-header-background-color, var(--st-secondary-background-color));
  border-bottom: 1px solid var(--st-dataframe-border-color, var(--st-border-color));
}
td {
  padding: 7px 12px;
  border-bottom: 1px solid var(--st-dataframe-border-color, var(--st-border-color));
}
td > div { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
tbody tr { cursor: default; user-select: none; }
tbody tr.openable { cursor: pointer; }
tbody tr:last-child td { border-bottom: none; }
tbody tr:hover td:not([data-tone]) { background: var(--st-secondary-background-color); }
tbody tr.selected td:not([data-tone]) {
  background: color-mix(in srgb, var(--st-primary-color) 16%, var(--st-background-color));
}
tbody tr.selected td:first-child { box-shadow: inset 3px 0 0 var(--st-primary-color); }
tbody tr:focus { outline: none; }
tbody tr:focus-visible { outline: 2px solid var(--st-primary-color); outline-offset: -2px; }
td[data-tone^="green"] {
  background: var(--st-green-background-color, #ECFDF3);
  color: var(--st-green-text-color, #05603A);
}
td[data-tone^="blue"] {
  background: var(--st-blue-background-color, #EEF3FF);
  color: var(--st-blue-text-color, #1D4ED8);
}
td[data-tone^="amber"] {
  background: var(--st-orange-background-color, #FFFAEB);
  color: var(--st-orange-text-color, #93370D);
}
td[data-tone^="red"] {
  background: var(--st-red-background-color, #FEF3F2);
  color: var(--st-red-text-color, #B42318);
}
td[data-tone$="-strong"] { font-weight: 600; }
.empty { padding: 14px 12px; opacity: 0.6; }
"""

_JS = """
export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const wrap = parentElement.querySelector(".wrap");
  const head = parentElement.querySelector("thead tr");
  const body = parentElement.querySelector("tbody");
  const empty = parentElement.querySelector(".empty");
  const columns = (data && data.columns) || [];
  const rows = (data && data.rows) || [];

  // Rebuild only when the data changes; keep the highlighted row across rebuilds.
  const signature = JSON.stringify(data);
  if (wrap.__signature !== signature) {
    wrap.__signature = signature;
    wrap.style.maxHeight = `${(data && data.max_height) || 520}px`;
    wrap.querySelector("table").style.tableLayout = data && data.fit ? "fixed" : "auto";
    head.replaceChildren(
      ...columns.map((column) => {
        const th = document.createElement("th");
        th.textContent = column.label;
        if (column.width) th.style.width = column.width;
        if (column.align) th.style.textAlign = column.align;
        return th;
      })
    );
    body.replaceChildren(
      ...rows.map((row) => {
        const tr = document.createElement("tr");
        tr.tabIndex = -1;
        tr.dataset.id = row.id;
        if (row.open) {
          tr.dataset.open = row.open;
          tr.classList.add("openable");
          tr.title = "双击打开";
        }
        row.cells.forEach((value, index) => {
          const text = value == null ? "" : String(value);
          const column = columns[index] || {};
          const td = document.createElement("td");
          const tone = row.tones && row.tones[index];
          if (tone) td.dataset.tone = tone;
          if (column.align) td.style.textAlign = column.align;
          const cell = document.createElement("div");
          cell.textContent = text;
          if (column.max) {
            cell.style.maxWidth = column.max;
            cell.title = text;
          }
          td.appendChild(cell);
          tr.appendChild(td);
        });
        return tr;
      })
    );
    const kept = [...body.children].find((tr) => tr.dataset.id === body.dataset.selected);
    if (kept) {
      kept.classList.add("selected");
      kept.tabIndex = 0;
    } else {
      delete body.dataset.selected;
      if (body.firstElementChild) body.firstElementChild.tabIndex = 0;
    }
    empty.textContent = (data && data.empty) || "";
    empty.hidden = rows.length > 0;
  }

  const select = (tr) => {
    for (const other of body.querySelectorAll("tr.selected")) {
      other.classList.remove("selected");
      other.tabIndex = -1;
    }
    tr.classList.add("selected");
    tr.tabIndex = 0;
    body.dataset.selected = tr.dataset.id;
    tr.focus({ preventScroll: true });
    tr.scrollIntoView({ block: "nearest" });
  };
  const open = (tr) => {
    if (tr.dataset.open) setTriggerValue("open", tr.dataset.open);
  };
  const rowOf = (event) => event.target.closest("tbody tr");

  body.onclick = (event) => {
    const tr = rowOf(event);
    if (tr) select(tr);
  };
  body.ondblclick = (event) => {
    const tr = rowOf(event);
    if (tr) open(tr);
  };
  body.onkeydown = (event) => {
    const tr = rowOf(event);
    if (!tr) return;
    if (event.key === "Enter") {
      event.preventDefault();
      open(tr);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const next = event.key === "ArrowDown" ? tr.nextElementSibling : tr.previousElementSibling;
      if (next) select(next);
    }
  };
}
"""

_row_table = st.components.v2.component("budgetlab_row_table", html=_HTML, css=_CSS, js=_JS)


def row_table(
    columns: list[dict[str, str]],
    rows: list[dict[str, Any]],
    *,
    key: str,
    on_open: Callable[[str], None],
    empty: str = "",
    max_height: int = 520,
    fit: bool = False,
) -> None:
    """Show a read-only table and call ``on_open(target)`` when a row is opened.

    ``columns``: ``label`` plus optional ``width``, ``align`` and ``max`` (CSS values;
    ``max`` truncates long cells and shows them in full on hover). ``fit`` pins the
    columns to their ``width`` and truncates instead of scrolling sideways.
    ``rows``: ``id`` (stable, keeps the highlight across refreshes), ``cells`` (strings),
    optional ``open`` (target passed to ``on_open``; rows without one do not open) and
    ``tones`` (one per cell: green, blue, amber or red, with ``-strong`` for bold).
    """

    def opened() -> None:
        target = (st.session_state.get(key) or {}).get("open")
        if target:
            on_open(target)

    _row_table(
        key=key,
        data={
            "columns": columns,
            "rows": rows,
            "empty": empty,
            "max_height": max_height,
            "fit": fit,
        },
        on_open_change=opened,
    )
