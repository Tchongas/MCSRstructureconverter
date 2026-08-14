"""
Minimal TUI for schem_to_commands options.

Works on Windows (msvcrt) and Unix (tty/termios) with no dependencies.
Uses ANSI escape codes for colors and cursor movement.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional

# ── Platform-specific key reading ──────────────────────────────────────

if os.name == "nt":
    import msvcrt

    def _read_key() -> str:
        """Read a single keypress on Windows. Returns special strings
        for arrow keys, Enter, Escape, Backspace, Tab."""
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ext = msvcrt.getwch()
            return {
                "H": "UP", "P": "DOWN", "K": "LEFT", "M": "RIGHT",
            }.get(ext, "")
        if ch == "\r":
            return "ENTER"
        if ch == "\x1b":
            return "ESC"
        if ch == "\x08":
            return "BACKSPACE"
        if ch == "\t":
            return "TAB"
        return ch
else:
    import tty
    import termios

    def _read_key() -> str:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                seq = sys.stdin.read(2)
                return {"[A": "UP", "[B": "DOWN", "[C": "RIGHT", "[D": "LEFT"}.get(seq, "ESC")
            if ch == "\r" or ch == "\n":
                return "ENTER"
            if ch == "\x7f" or ch == "\x08":
                return "BACKSPACE"
            if ch == "\t":
                return "TAB"
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


# ── ANSI helpers ───────────────────────────────────────────────────────

_RST = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_CYAN = "\033[36m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_WHITE = "\033[97m"
_BG_CYAN = "\033[46m"
_BG_DARK = "\033[48;5;236m"
_MAGENTA = "\033[35m"
_RED = "\033[31m"
_CLEAR_SCREEN = "\033[2J\033[H"
_HIDE_CURSOR = "\033[?25l"
_SHOW_CURSOR = "\033[?25h"


def _clear():
    sys.stdout.write(_CLEAR_SCREEN)
    sys.stdout.flush()


def _enable_ansi():
    """Enable ANSI / VT100 sequences on Windows and set UTF-8 output."""
    if os.name == "nt":
        # Set console output to UTF-8
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # Enable virtual terminal processing for ANSI codes
            STD_OUTPUT_HANDLE = -11
            handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            kernel32.SetConsoleMode(handle, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
            # Set console code page to UTF-8
            kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass
    # Also reconfigure stdout for utf-8
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def _w(text: str):
    sys.stdout.write(text)


def _flush():
    sys.stdout.flush()


# ── Data types ─────────────────────────────────────────────────────────

@dataclass
class Options:
    # Position
    use_relative: bool = True        # True = ~ ~ ~ (player), False = absolute
    abs_coords: str = ""             # e.g. "10 100 -45"

    # Generation
    include_air: bool = False
    no_merge: bool = False
    slash: bool = False

    # Aggressive optimizations
    aggressive: bool = False         # strip block entity NBT, distance, age, level


# ── TUI rendering ─────────────────────────────────────────────────────

_BOX_TL = "\u250c"  # +
_BOX_TR = "\u2510"
_BOX_BL = "\u2514"
_BOX_BR = "\u2518"
_BOX_H  = "\u2500"  # -
_BOX_V  = "\u2502"  # |
_BOX_LT = "\u251c"  # |-
_BOX_RT = "\u2524"


def _box_line(width: int) -> str:
    return _BOX_H * width


def _center(text: str, width: int) -> str:
    stripped = text
    for esc in ("\033[0m", "\033[1m", "\033[2m", "\033[36m", "\033[32m",
                "\033[33m", "\033[97m", "\033[46m", "\033[35m", "\033[31m",
                "\033[48;5;236m"):
        stripped = stripped.replace(esc, "")
    pad = max(0, width - len(stripped))
    left = pad // 2
    right = pad - left
    return " " * left + text + " " * right


def _render(opts: Options, cursor: int, editing_coords: bool, coord_buf: str,
            schem_name: str, schem_info: str):
    """Render the full TUI screen."""
    W = 52

    _clear()

    # Title
    _w(f"  {_BOLD}{_CYAN}{_BOX_TL}{_box_line(W)}{_BOX_TR}{_RST}\n")
    title = f"{_BOLD}{_WHITE} SCHEMATIC CONVERTER {_RST}"
    _w(f"  {_BOLD}{_CYAN}{_BOX_V}{_RST}{_center(title, W)}{_BOLD}{_CYAN}{_BOX_V}{_RST}\n")
    _w(f"  {_BOLD}{_CYAN}{_BOX_LT}{_box_line(W)}{_BOX_RT}{_RST}\n")

    # File info
    file_line = f" {_DIM}File:{_RST} {_WHITE}{schem_name}{_RST}"
    _w(f"  {_BOLD}{_CYAN}{_BOX_V}{_RST}{_center(file_line, W)}{_BOLD}{_CYAN}{_BOX_V}{_RST}\n")
    info_line = f" {_DIM}{schem_info}{_RST}"
    _w(f"  {_BOLD}{_CYAN}{_BOX_V}{_RST}{_center(info_line, W)}{_BOLD}{_CYAN}{_BOX_V}{_RST}\n")
    _w(f"  {_BOLD}{_CYAN}{_BOX_LT}{_box_line(W)}{_BOX_RT}{_RST}\n")

    # Menu items
    items = _menu_items(opts, editing_coords, coord_buf)
    for i, (label, value, hint) in enumerate(items):
        is_sel = (i == cursor)
        prefix = f" {_CYAN}>{_RST} " if is_sel else "   "
        if is_sel:
            line = f"{prefix}{_BOLD}{_WHITE}{label}{_RST}  {value}"
        else:
            line = f"{prefix}{_DIM}{label}{_RST}  {value}"
        if hint:
            line += f"  {_DIM}{hint}{_RST}"

        _w(f"  {_BOLD}{_CYAN}{_BOX_V}{_RST}")
        # Pad to width
        stripped = line
        for esc in ("\033[0m", "\033[1m", "\033[2m", "\033[36m", "\033[32m",
                    "\033[33m", "\033[97m", "\033[46m", "\033[35m", "\033[31m",
                    "\033[48;5;236m"):
            stripped = stripped.replace(esc, "")
        pad = max(0, W - len(stripped))
        _w(f"{line}{' ' * pad}")
        _w(f"{_BOLD}{_CYAN}{_BOX_V}{_RST}\n")

    # Separator before actions
    _w(f"  {_BOLD}{_CYAN}{_BOX_LT}{_box_line(W)}{_BOX_RT}{_RST}\n")

    # Generate button
    gen_idx = len(items)
    is_sel = (cursor == gen_idx)
    if is_sel:
        btn = f" {_CYAN}>{_RST}  {_BOLD}{_GREEN}[ GENERATE ]{_RST}"
    else:
        btn = f"    {_DIM}[ GENERATE ]{_RST}"
    _w(f"  {_BOLD}{_CYAN}{_BOX_V}{_RST}{_center(btn, W)}{_BOLD}{_CYAN}{_BOX_V}{_RST}\n")

    # Cancel
    cancel_idx = gen_idx + 1
    is_sel = (cursor == cancel_idx)
    if is_sel:
        btn = f" {_CYAN}>{_RST}  {_BOLD}{_RED}[ CANCEL ]{_RST}"
    else:
        btn = f"    {_DIM}[ CANCEL ]{_RST}"
    _w(f"  {_BOLD}{_CYAN}{_BOX_V}{_RST}{_center(btn, W)}{_BOLD}{_CYAN}{_BOX_V}{_RST}\n")

    # Bottom border
    _w(f"  {_BOLD}{_CYAN}{_BOX_BL}{_box_line(W)}{_BOX_BR}{_RST}\n")

    # Help
    _w(f"\n  {_DIM}Up/Down: navigate   Enter/Space: toggle   Esc: cancel{_RST}\n")
    if editing_coords:
        _w(f"  {_YELLOW}Type coordinates (x y z), Enter to confirm, Esc to cancel{_RST}\n")

    _flush()


def _menu_items(opts: Options, editing_coords: bool, coord_buf: str):
    """Returns list of (label, formatted_value, hint)."""
    items = []

    # 1. Position mode
    if opts.use_relative:
        val = f"{_GREEN}~ ~ ~  (player){_RST}"
    else:
        if editing_coords:
            val = f"{_YELLOW}{coord_buf}_{_RST}"
        elif opts.abs_coords:
            val = f"{_MAGENTA}{opts.abs_coords}{_RST}"
        else:
            val = f"{_RED}not set{_RST}"
    items.append(("Position", val, ""))

    # 2. Aggressive optimizations
    ag = f"{_GREEN}ON{_RST}" if opts.aggressive else f"{_DIM}OFF{_RST}"
    items.append(("Aggressive optimizations", ag, "strips NBT data"))

    # 3. Include air
    air = f"{_GREEN}ON{_RST}" if opts.include_air else f"{_DIM}OFF{_RST}"
    items.append(("Include air blocks", air, ""))

    # 4. Fill merging
    merge_off = f"{_RED}OFF{_RST}" if opts.no_merge else f"{_GREEN}ON{_RST}"
    items.append(("Fill merging", merge_off, ""))

    # 5. Slash prefix
    sl = f"{_GREEN}ON{_RST}" if opts.slash else f"{_DIM}OFF{_RST}"
    items.append(("Prefix with /", sl, ""))

    return items


# ── Main TUI loop ─────────────────────────────────────────────────────

def run_tui(schem_name: str, schem_info: str) -> Optional[Options]:
    """Show the TUI and return the chosen Options, or None if cancelled."""
    _enable_ansi()

    opts = Options()
    cursor = 0
    editing_coords = False
    coord_buf = ""

    menu_count = 5       # number of option rows
    total_items = menu_count + 2  # + GENERATE + CANCEL

    _w(_HIDE_CURSOR)
    try:
        while True:
            _render(opts, cursor, editing_coords, coord_buf, schem_name, schem_info)
            key = _read_key()

            if editing_coords:
                if key == "ENTER":
                    editing_coords = False
                    opts.abs_coords = coord_buf.strip()
                    if not opts.abs_coords:
                        opts.use_relative = True
                elif key == "ESC":
                    editing_coords = False
                    if not opts.abs_coords:
                        opts.use_relative = True
                elif key == "BACKSPACE":
                    coord_buf = coord_buf[:-1]
                elif len(key) == 1 and (key.isdigit() or key in " -~"):
                    coord_buf += key
                continue

            if key == "UP":
                cursor = (cursor - 1) % total_items
            elif key == "DOWN":
                cursor = (cursor + 1) % total_items
            elif key == "ESC":
                return None
            elif key in ("ENTER", " "):
                if cursor == 0:
                    # Position toggle
                    if opts.use_relative:
                        opts.use_relative = False
                        editing_coords = True
                        coord_buf = opts.abs_coords
                    else:
                        opts.use_relative = True
                        opts.abs_coords = ""
                elif cursor == 1:
                    opts.aggressive = not opts.aggressive
                elif cursor == 2:
                    opts.include_air = not opts.include_air
                elif cursor == 3:
                    opts.no_merge = not opts.no_merge
                elif cursor == 4:
                    opts.slash = not opts.slash
                elif cursor == menu_count:      # GENERATE
                    if not opts.use_relative and not opts.abs_coords:
                        continue  # don't generate without coords
                    return opts
                elif cursor == menu_count + 1:  # CANCEL
                    return None
            elif key in ("q", "Q"):
                return None
    finally:
        _w(_SHOW_CURSOR)
        _flush()
