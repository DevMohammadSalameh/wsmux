#!/usr/bin/env python3
"""
mux — Workspace launcher for macOS.

Usage:
    mux .                Open workspace defined in .mux.json
    mux /path/to/dir     Open workspace in that directory
    mux -s .             Save current state to .mux.json, then close
    mux -ss .            Quick close (no config update)
    mux -c .             Capture current desktop into .mux.json
    mux -l .             List what would be opened (dry run)
    mux --init .         Create a starter .mux.json
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

CONFIG_NAMES = [".mux.json", "mux.json"]
STATE_DIR = Path.home() / ".mux" / "states"
REGISTRY_FILE = Path.home() / ".mux" / "projects.json"
IGNORE_FILE = Path.home() / ".mux" / "ignore.json"

# ─────────────────────────────────────────────────
#  Shared constants
# ─────────────────────────────────────────────────

EDITOR_APP_NAMES = {
    "code": "Visual Studio Code",
    "code-insiders": "Visual Studio Code - Insiders",
    "cursor": "Cursor",
}

EDITOR_PROCESS_NAMES = {
    "code": "Code",
    "code-insiders": "Code - Insiders",
    "cursor": "Cursor",
}

KNOWN_EDITORS = {
    "Code": {"app_name": "Visual Studio Code", "command": "code"},
    "Code - Insiders": {"app_name": "Visual Studio Code - Insiders", "command": "code-insiders"},
    "Cursor": {"app_name": "Cursor", "command": "cursor"},
}

KNOWN_BROWSERS = {
    "Microsoft Edge": "Microsoft Edge",
    "Google Chrome": "Google Chrome",
    "Safari": "Safari",
    "Google Chrome Canary": "Google Chrome Canary",
    "Firefox": None,
    "Arc": None,
}

SKIP_APPS = {
    "Finder", "SystemUIServer", "Dock", "Spotlight", "Control Center",
    "WindowManager", "NotificationCenter", "AirPlayUIAgent",
    "TextInputMenuAgent", "universalAccessAuthWarn", "Keychain Access",
    "System Preferences", "System Settings", "loginwindow", "talagent",
    "WiFiAgent", "CoreServicesUIAgent", "UserNotificationCenter",
    "AXVisualSupportAgent", "OSDUIHelper",
}


# ─────────────────────────────────────────────────
#  Config loading
# ─────────────────────────────────────────────────

def find_config(directory: str) -> Path | None:
    d = Path(directory).resolve()
    for name in CONFIG_NAMES:
        p = d / name
        if p.exists():
            return p
    return None


def load_config(config_path: Path) -> dict:
    with open(config_path) as f:
        return json.load(f)


# ─────────────────────────────────────────────────
#  Project registry — open projects by name from anywhere
# ─────────────────────────────────────────────────

def _load_registry() -> dict:
    if REGISTRY_FILE.exists():
        with open(REGISTRY_FILE) as f:
            return json.load(f)
    return {}


def _save_registry(registry: dict):
    with open(REGISTRY_FILE, "w") as f:
        json.dump(registry, f, indent=2)


def resolve_directory(name_or_path: str) -> str:
    """Resolve a project name or path to an actual directory.
    If it's a registered project name, return its path.
    If it's a filesystem path (., .., /, ~, or existing dir), use it directly.
    """
    # Filesystem paths: ".", "..", "/something", "~", "./relative", or existing dirs
    if name_or_path in (".", "..") or name_or_path.startswith(("/", "~", "./")):
        return name_or_path

    # Check if it's an existing directory first
    if Path(name_or_path).is_dir():
        return name_or_path

    # Look up in registry
    registry = _load_registry()
    if name_or_path in registry:
        return registry[name_or_path]

    # Not found — could be a typo. Show suggestions.
    print(f"✗ '{name_or_path}' is not a registered project or valid directory")
    if registry:
        print(f"  Registered projects: {', '.join(sorted(registry.keys()))}")
    else:
        print(f"  No projects registered. Use: mux --add <name> [directory]")
    sys.exit(1)


def cmd_add_project(name: str, directory: str):
    """Register a project name pointing to a directory."""
    target = Path(directory).resolve()

    # Verify .mux.json exists there
    if not find_config(str(target)):
        print(f"⚠ No .mux.json found in {target}")
        print(f"  Create one first: mux --init {target}")
        return

    registry = _load_registry()
    registry[name] = str(target)
    _save_registry(registry)
    print(f"✓ Registered '{name}' → {target}")
    print(f"  Now you can use: mux {name}")


def cmd_remove_project(name: str):
    """Remove a project from the registry."""
    registry = _load_registry()
    if name in registry:
        del registry[name]
        _save_registry(registry)
        print(f"✓ Removed '{name}' from registry")
    else:
        print(f"✗ '{name}' is not registered")
        if registry:
            print(f"  Registered: {', '.join(sorted(registry.keys()))}")


def cmd_list_projects():
    """List all registered projects."""
    registry = _load_registry()
    if not registry:
        print(f"\nNo projects registered.")
        print(f"  Use: mux --add <name> [directory]\n")
        return

    print(f"\n📋 Registered projects:\n")
    for name, path in sorted(registry.items()):
        has_config = "✓" if find_config(path) else "✗"
        print(f"  {has_config} {name:20s} → {path}")
    print()


# ─────────────────────────────────────────────────
#  Global ignore list
# ─────────────────────────────────────────────────

def _load_ignore() -> dict:
    """Load the global ignore list.
    Format: {"apps": ["Slack", "Discord"], "urls": ["chatgpt.com"], "paths": []}
    """
    if IGNORE_FILE.exists():
        with open(IGNORE_FILE) as f:
            return json.load(f)
    return {"apps": [], "urls": [], "paths": []}


def _is_ignored(entry_type: str, entry: dict, ignore: dict) -> bool:
    """Check if a captured entry should be ignored."""
    ignored_apps = ignore.get("apps", [])
    ignored_urls = ignore.get("urls", [])
    ignored_paths = ignore.get("paths", [])

    if entry_type == "app":
        name = entry.get("name", "")
        return any(ig.lower() in name.lower() for ig in ignored_apps)

    if entry_type == "browser":
        urls = entry.get("urls", [])
        return all(
            any(ig.lower() in url.lower() for ig in ignored_urls)
            for url in urls
        )

    if entry_type in ("vscode", "editor"):
        paths = entry.get("paths", [])
        return all(
            any(ig.lower() in p.lower() for ig in ignored_paths)
            for p in paths
        )

    return False


def _init_ignore_file():
    """Create a starter ignore file if it doesn't exist."""
    if IGNORE_FILE.exists():
        return
    starter = {
        "_comment": "Apps, URLs, and paths to always ignore when capturing",
        "apps": [],
        "urls": ["chatgpt.com", "claude.ai"],
        "paths": []
    }
    with open(IGNORE_FILE, "w") as f:
        json.dump(starter, f, indent=2)


def _add_to_ignore(entry: dict):
    """Add an entry to the global ignore list based on its type."""
    ignore = _load_ignore()
    t = entry.get("type", "")

    if t == "app":
        name = entry.get("name", "")
        if name and name not in ignore.get("apps", []):
            ignore.setdefault("apps", []).append(name)
            print(f"      ✗ Ignored forever: app '{name}'")

    elif t == "browser":
        urls = entry.get("urls", [])
        # Extract domains from URLs to ignore
        for url in urls:
            # Get domain from URL (e.g., "https://example.com/path" → "example.com")
            domain = url.split("://")[-1].split("/")[0].split("?")[0]
            if domain and domain not in ignore.get("urls", []):
                ignore.setdefault("urls", []).append(domain)
                print(f"      ✗ Ignored forever: URL pattern '{domain}'")

    elif t in ("vscode", "editor"):
        paths = entry.get("paths", [])
        for p in paths:
            if p not in ignore.get("paths", []):
                ignore.setdefault("paths", []).append(p)
                print(f"      ✗ Ignored forever: path '{p}'")

    elif t == "terminal":
        # For terminals, ignore by the tab names
        tabs = entry.get("tabs", [])
        for tab in tabs:
            cwd = tab.get("cwd", "")
            if cwd and cwd not in ignore.get("paths", []):
                ignore.setdefault("paths", []).append(cwd)
                print(f"      ✗ Ignored forever: path '{cwd}'")

    _save_ignore(ignore)


def _save_ignore(ignore: dict):
    with open(IGNORE_FILE, "w") as f:
        json.dump(ignore, f, indent=2)


# ─────────────────────────────────────────────────
#  Diff & prompt — ask before saving new entries
# ─────────────────────────────────────────────────

def _describe_entry(entry: dict) -> str:
    """One-line description of a config entry for display."""
    t = entry.get("type", "")
    if t in ("vscode", "editor"):
        paths = entry.get("paths", [])
        cmd = entry.get("command", "code")
        return f"[{cmd}] {', '.join(paths)}"
    elif t == "browser":
        app = entry.get("app", "browser")
        urls = entry.get("urls", [])
        if len(urls) <= 2:
            return f"[{app}] {', '.join(urls)}"
        return f"[{app}] {urls[0]} + {len(urls)-1} more tabs"
    elif t == "terminal":
        tabs = entry.get("tabs", [])
        names = [tab.get("name", "?") for tab in tabs]
        return f"[Terminal] tabs: {', '.join(names)}"
    elif t == "app":
        return f"[App] {entry.get('name', '?')}"
    elif t == "docker":
        svcs = entry.get("services", [])
        return f"[Docker] {' '.join(svcs) or 'all'}"
    elif t == "script":
        return f"[Script] {entry.get('command', '?')}"
    return f"[{t}] ?"


def _entry_key(entry: dict) -> str:
    """Generate a comparison key for an entry to detect new vs existing."""
    t = entry.get("type", "")
    if t in ("vscode", "editor"):
        return f"vscode:{','.join(sorted(entry.get('paths', [])))}"
    elif t == "browser":
        return f"browser:{entry.get('app', '')}:{','.join(sorted(entry.get('urls', [])))}"
    elif t == "terminal":
        tabs = entry.get("tabs", [])
        names = sorted(tab.get("name", "") for tab in tabs)
        return f"terminal:{','.join(names)}"
    elif t == "app":
        return f"app:{entry.get('name', '')}"
    elif t == "docker":
        return f"docker:{','.join(sorted(entry.get('services', [])))}"
    elif t == "script":
        return f"script:{entry.get('command', '')}"
    return f"{t}:unknown"


def _diff_and_prompt(existing_config: dict | None, new_config: dict) -> dict:
    """Compare existing and new config. Keep existing entries (with updated geometry),
    prompt user for each genuinely new entry.
    """
    if not existing_config:
        return new_config

    existing_entries = existing_config.get("apps", [])
    new_entries = new_config.get("apps", [])

    # Build keys for existing entries
    existing_keys = {_entry_key(e) for e in existing_entries}

    # Separate new entries into: matching existing (update geometry) vs genuinely new
    kept_entries = []
    new_candidates = []

    for entry in new_entries:
        key = _entry_key(entry)
        if key in existing_keys:
            # Existing entry — keep with updated geometry
            kept_entries.append(entry)
        else:
            new_candidates.append(entry)

    # Also keep existing entries that weren't in the new capture
    # (docker, script — non-detectable types)
    new_keys = {_entry_key(e) for e in new_entries}
    for entry in existing_entries:
        key = _entry_key(entry)
        if key not in new_keys and entry.get("type") in ("docker", "script"):
            kept_entries.append(entry)

    # Prompt for genuinely new entries
    if new_candidates:
        print(f"\n  New entries detected:\n")
        for entry in new_candidates:
            desc = _describe_entry(entry)
            answer = input(f"    + {desc}  [y/n/i] (yes/no/ignore forever): ").strip().lower()
            if answer in ("y", "yes"):
                kept_entries.append(entry)
                print(f"      ✓ Added")
            elif answer in ("i", "ignore"):
                _add_to_ignore(entry)
            else:
                print(f"      ✗ Skipped")

    return {"name": new_config.get("name", ""), "apps": kept_entries}


# ─────────────────────────────────────────────────
#  State management
# ─────────────────────────────────────────────────

def state_file_for(directory: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    key = Path(directory).resolve().as_posix().replace("/", "_")
    return STATE_DIR / f"{key}.json"


def save_state(directory: str, opened: list[dict]):
    sf = state_file_for(directory)
    with open(sf, "w") as f:
        json.dump({"dir": str(Path(directory).resolve()), "opened": opened, "ts": time.time()}, f, indent=2)


def load_state(directory: str) -> dict | None:
    sf = state_file_for(directory)
    if sf.exists():
        with open(sf) as f:
            return json.load(f)
    return None


def clear_state(directory: str):
    sf = state_file_for(directory)
    if sf.exists():
        sf.unlink()


# ─────────────────────────────────────────────────
#  Window geometry helpers
# ─────────────────────────────────────────────────

def _run_osascript(script: str) -> str:
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
    return result.stdout.strip()


def _get_window_geometry(process_name: str, app_name: str) -> list[dict]:
    """Get position and size of all windows for an app.
    Returns [{"title": str, "position": [x,y], "size": [w,h]}]
    """
    output = _run_osascript(f'''
tell application "{app_name}" to activate
delay 0.5
tell application "System Events"
    tell process "{process_name}"
        set output to ""
        repeat with w in windows
            set wTitle to name of w
            set wPos to position of w
            set wSize to size of w
            set output to output & wTitle & "|||" & (item 1 of wPos) & "," & (item 2 of wPos) & "|||" & (item 1 of wSize) & "," & (item 2 of wSize) & ">>>"
        end repeat
        return output
    end tell
end tell''')

    result = []
    for entry in output.split(">>>"):
        entry = entry.strip()
        if not entry or "|||" not in entry:
            continue
        parts = entry.split("|||")
        if len(parts) < 3:
            continue
        title = parts[0].strip()
        try:
            pos = [int(x) for x in parts[1].split(",")]
            size = [int(x) for x in parts[2].split(",")]
            result.append({"title": title, "position": pos, "size": size})
        except (ValueError, IndexError):
            result.append({"title": title, "position": None, "size": None})

    return result


def _set_window_geometry(process_name: str, title_match: str, position: list | None, size: list | None) -> bool:
    """Set position and/or size of a window matching the title. Returns True if found."""
    pos_line = f'set position of w to {{{position[0]}, {position[1]}}}' if position else ""
    size_line = f'set size of w to {{{size[0]}, {size[1]}}}' if size else ""
    if not pos_line and not size_line:
        return True

    result = _run_osascript(f'''
tell application "System Events"
    tell process "{process_name}"
        repeat with w in windows
            if name of w contains "{title_match}" then
                {pos_line}
                {size_line}
                return "ok"
            end if
        end repeat
        return "not_found"
    end tell
end tell''')
    return result == "ok"


def _wait_and_position_window(process_name: str, app_name: str, title_match: str,
                               position: list | None, size: list | None, timeout: float = 5.0):
    """Poll for a window to appear, then position it."""
    if position is None and size is None:
        return

    # Activate first (Electron apps need this)
    _run_osascript(f'tell application "{app_name}" to activate')
    time.sleep(0.5)

    start = time.time()
    while time.time() - start < timeout:
        if _set_window_geometry(process_name, title_match, position, size):
            return
        time.sleep(0.3)

    print(f"  ⚠ Could not position window: {title_match} (timeout)")


# ─────────────────────────────────────────────────
#  Openers — one per app type
# ─────────────────────────────────────────────────

def open_vscode(entry: dict, base_dir: Path) -> list[dict]:
    """Open VS Code windows for each path, with optional positioning."""
    opened = []
    paths = entry.get("paths", [])
    if "path" in entry:
        paths = [entry["path"]] + paths

    cmd = entry.get("command", "code")
    process_name = EDITOR_PROCESS_NAMES.get(cmd, "Code")
    app_name = EDITOR_APP_NAMES.get(cmd, "Visual Studio Code")
    window_geom = entry.get("windows", {})  # {"./path": {"position": [...], "size": [...]}}

    for p in paths:
        full = (base_dir / p).resolve()
        if not full.exists():
            print(f"  ⚠ Path not found: {full}")
            continue
        subprocess.Popen([cmd, str(full)])
        print(f"  ✓ {cmd} → {full}")
        opened.append({"type": "vscode", "command": cmd, "path": str(full)})

        # Position the window if geometry is configured
        geom = window_geom.get(p)
        if geom:
            folder_name = Path(full).name
            _wait_and_position_window(
                process_name, app_name, folder_name,
                geom.get("position"), geom.get("size")
            )

    return opened


def open_browser(entry: dict, base_dir: Path) -> list[dict]:
    """Open browser in a new isolated window with tabs, with optional positioning."""
    opened = []
    app = entry.get("app", "Google Chrome")
    urls = entry.get("urls", [])
    window_geom = entry.get("window")  # {"position": [...], "size": [...]}

    if not urls:
        print(f"  ⚠ No URLs configured for browser")
        return opened

    # Use AppleScript to create an isolated new window with all tabs
    if app in ("Microsoft Edge", "Google Chrome", "Google Chrome Canary"):
        _open_chromium_window(app, urls, window_geom)
    elif app == "Safari":
        _open_safari_window(urls, window_geom)
    else:
        # Fallback for unsupported browsers
        for i, url in enumerate(urls):
            cmd = ["open", "-a", app]
            if i == 0:
                cmd.append("-n")
            cmd.append(url)
            subprocess.Popen(cmd)
            time.sleep(0.3)

    for url in urls:
        print(f"  ✓ {app} → {url}")

    opened.append({"type": "browser", "app": app, "url_count": len(urls)})
    return opened


def _open_chromium_window(app: str, urls: list[str], geom: dict | None):
    """Open a new Chrome/Edge window with tabs via AppleScript."""
    # Build tab creation lines
    tab_lines = ""
    for url in urls[1:]:
        tab_lines += f'\n        make new tab at end of tabs of newWindow with properties {{URL:"{url}"}}'

    # Build positioning lines
    pos_lines = ""
    if geom:
        pos = geom.get("position")
        sz = geom.get("size")
        if pos or sz:
            pos_lines = f'''
tell application "System Events"
    tell process "{app}"
        delay 0.3'''
            if pos:
                pos_lines += f'\n        set position of front window to {{{pos[0]}, {pos[1]}}}'
            if sz:
                pos_lines += f'\n        set size of front window to {{{sz[0]}, {sz[1]}}}'
            pos_lines += '''
    end tell
end tell'''

    script = f'''
tell application "{app}"
    set newWindow to make new window
    set URL of active tab of newWindow to "{urls[0]}"
    {tab_lines}
end tell
{pos_lines}'''

    _run_osascript(script)


def _open_safari_window(urls: list[str], geom: dict | None):
    """Open a new Safari window with tabs."""
    tab_lines = ""
    for url in urls[1:]:
        tab_lines += f'\n        make new tab in newDoc with properties {{URL:"{url}"}}'

    pos_lines = ""
    if geom:
        pos = geom.get("position")
        sz = geom.get("size")
        if pos or sz:
            pos_lines = '''
tell application "System Events"
    tell process "Safari"
        delay 0.3'''
            if pos:
                pos_lines += f'\n        set position of front window to {{{pos[0]}, {pos[1]}}}'
            if sz:
                pos_lines += f'\n        set size of front window to {{{sz[0]}, {sz[1]}}}'
            pos_lines += '''
    end tell
end tell'''

    script = f'''
tell application "Safari"
    set newDoc to make new document with properties {{URL:"{urls[0]}"}}
    {tab_lines}
end tell
{pos_lines}'''

    _run_osascript(script)


def open_terminal_tabs(entry: dict, base_dir: Path) -> list[dict]:
    """Open terminal tabs with commands, with optional positioning."""
    opened = []
    tabs = entry.get("tabs", [])
    terminal_app = entry.get("app", "Terminal")

    for i, tab in enumerate(tabs):
        name = tab.get("name", f"tab-{i}")
        command = tab.get("command", "")
        cwd = str((base_dir / tab.get("cwd", ".")).resolve()) if "cwd" in tab else str(base_dir)
        window_geom = tab.get("window")  # {"position": [...], "size": [...]}

        if terminal_app == "iTerm" or terminal_app == "iTerm2":
            script = _iterm_tab_script(command, cwd, name, is_first=(i == 0), geom=window_geom)
        else:
            script = _terminal_tab_script(command, cwd, name, is_first=(i == 0), geom=window_geom)

        subprocess.run(["osascript", "-e", script], check=False)
        print(f"  ✓ {terminal_app} tab [{name}] → {command or cwd}")
        opened.append({"type": "terminal", "app": terminal_app, "name": name})

    return opened


def _terminal_tab_script(command: str, cwd: str, name: str, is_first: bool,
                          geom: dict | None = None) -> str:
    cd_cmd = f'cd {cwd}'
    full_cmd = f'{cd_cmd} && {command}' if command else cd_cmd

    # Position lines (only for new windows, i.e. is_first)
    pos_lines = ""
    if geom and is_first:
        pos = geom.get("position")
        sz = geom.get("size")
        if pos or sz:
            pos_lines = '''
tell application "System Events"
    tell process "Terminal"'''
            if pos:
                pos_lines += f'\n        set position of front window to {{{pos[0]}, {pos[1]}}}'
            if sz:
                pos_lines += f'\n        set size of front window to {{{sz[0]}, {sz[1]}}}'
            pos_lines += '''
    end tell
end tell'''

    if is_first:
        return f'''
tell application "Terminal"
    activate
    do script "{full_cmd}" in (do script "")
    set custom title of front window to "{name}"
end tell
{pos_lines}'''
    else:
        return f'''
tell application "Terminal"
    activate
    tell application "System Events" to keystroke "t" using command down
    delay 0.3
    do script "{full_cmd}" in front window
end tell'''


def _iterm_tab_script(command: str, cwd: str, name: str, is_first: bool,
                       geom: dict | None = None) -> str:
    cd_cmd = f'cd {cwd}'
    full_cmd = f'{cd_cmd} && {command}' if command else cd_cmd

    pos_lines = ""
    if geom and is_first:
        pos = geom.get("position")
        sz = geom.get("size")
        if pos or sz:
            pos_lines = '''
tell application "System Events"
    tell process "iTerm2"'''
            if pos:
                pos_lines += f'\n        set position of front window to {{{pos[0]}, {pos[1]}}}'
            if sz:
                pos_lines += f'\n        set size of front window to {{{sz[0]}, {sz[1]}}}'
            pos_lines += '''
    end tell
end tell'''

    if is_first:
        return f'''
tell application "iTerm"
    activate
    set newWindow to (create window with default profile)
    tell current session of newWindow
        set name to "{name}"
        write text "{full_cmd}"
    end tell
end tell
{pos_lines}'''
    else:
        return f'''
tell application "iTerm"
    tell current window
        set newTab to (create tab with default profile)
        tell current session of newTab
            set name to "{name}"
            write text "{full_cmd}"
        end tell
    end tell
end tell'''


def open_app(entry: dict, base_dir: Path) -> list[dict]:
    """Open a generic macOS app."""
    opened = []
    name = entry.get("name", "")
    args = entry.get("args", [])

    if not name:
        print(f"  ⚠ No app name specified")
        return opened

    cmd = ["open", "-a", name]
    if args:
        cmd.append("--args")
        cmd.extend(args)

    subprocess.Popen(cmd)
    print(f"  ✓ {name}")
    opened.append({"type": "app", "name": name})
    return opened


def open_docker(entry: dict, base_dir: Path) -> list[dict]:
    """Run docker compose commands."""
    opened = []
    compose_file = entry.get("file")
    services = entry.get("services", [])
    cwd = str((base_dir / entry.get("cwd", ".")).resolve()) if "cwd" in entry else str(base_dir)

    cmd = ["docker", "compose"]
    if compose_file:
        cmd.extend(["-f", compose_file])
    cmd.append("up")
    cmd.append("-d")
    if services:
        cmd.extend(services)

    subprocess.Popen(cmd, cwd=cwd)
    svc_str = " ".join(services) if services else "all"
    print(f"  ✓ docker compose up -d {svc_str}")
    opened.append({"type": "docker", "cwd": cwd, "services": services})
    return opened


def open_script(entry: dict, base_dir: Path) -> list[dict]:
    """Run a custom shell command."""
    opened = []
    command = entry.get("command", "")
    cwd = str((base_dir / entry.get("cwd", ".")).resolve()) if "cwd" in entry else str(base_dir)

    if not command:
        print(f"  ⚠ No command specified for script entry")
        return opened

    subprocess.Popen(command, shell=True, cwd=cwd)
    print(f"  ✓ script → {command}")
    opened.append({"type": "script", "command": command})
    return opened


OPENERS = {
    "vscode": open_vscode,
    "editor": open_vscode,
    "browser": open_browser,
    "terminal": open_terminal_tabs,
    "app": open_app,
    "docker": open_docker,
    "script": open_script,
}


# ─────────────────────────────────────────────────
#  Closers
# ─────────────────────────────────────────────────

def close_workspace(directory: str, config: dict):
    """Close apps that were opened for this workspace."""
    base_dir = Path(directory).resolve()
    entries = config.get("apps", [])
    print(f"\n⏹  Stopping workspace: {config.get('name', base_dir.name)}\n")

    for entry in entries:
        t = entry.get("type", "")
        close_entry(entry, t, base_dir)

    clear_state(directory)
    print(f"\n✓ Workspace stopped.\n")


def close_entry(entry: dict, entry_type: str, base_dir: Path):
    if entry_type in ("vscode", "editor"):
        paths = entry.get("paths", [])
        if "path" in entry:
            paths = [entry["path"]] + paths

        cmd = entry.get("command", "code")
        app_name = EDITOR_APP_NAMES.get(cmd, "Visual Studio Code")
        process_name = EDITOR_PROCESS_NAMES.get(cmd, "Code")

        folder_names = []
        for p in paths:
            full = str((base_dir / p).resolve())
            folder_names.append(Path(full).name)

        if not folder_names:
            return

        folder_checks = " or ".join(
            f'windowTitle contains "{fn}"' for fn in folder_names
        )
        script = f'''
tell application "System Events"
    if not (exists process "{process_name}") then return "not_running"
end tell

tell application "{app_name}" to activate
delay 0.5

tell application "System Events"
    tell process "{process_name}"
        set windowCount to count of windows
        set closedNames to {{}}
        repeat with i from windowCount to 1 by -1
            set w to window i
            set windowTitle to name of w
            if {folder_checks} then
                click button 1 of w
                set end of closedNames to windowTitle
                delay 0.3
            end if
        end repeat
        return closedNames
    end tell
end tell
'''
        result = subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
        output = result.stdout.decode().strip()

        if output == "not_running":
            print(f"  ℹ {app_name} is not running")
        elif result.returncode == 0:
            if output:
                print(f"  ✓ Closed {cmd} windows: {output}")
            else:
                print(f"  ℹ No matching {cmd} windows found")
        else:
            err = result.stderr.decode().strip()
            print(f"  ⚠ Could not close {cmd} windows — {err}")

    elif entry_type == "browser":
        app = entry.get("app", "Google Chrome")
        urls = entry.get("urls", [])
        if urls and app in ("Microsoft Edge", "Google Chrome", "Google Chrome Canary"):
            close_chromium_tabs(app, urls)
        elif urls and app == "Safari":
            close_safari_tabs(urls)
        else:
            quit_app(app)

    elif entry_type == "terminal":
        app = entry.get("app", "Terminal")
        tabs = entry.get("tabs", [])
        if app in ("Terminal", "Terminal.app"):
            close_terminal_tabs(tabs, base_dir)
        elif app in ("iTerm", "iTerm2"):
            close_iterm_tabs(tabs, base_dir)
        else:
            print(f"  ℹ Manual close needed for {app} tabs")

    elif entry_type == "app":
        name = entry.get("name", "")
        if name:
            quit_app(name)

    elif entry_type == "docker":
        cwd = str((base_dir / entry.get("cwd", ".")).resolve()) if "cwd" in entry else str(base_dir)
        compose_file = entry.get("file")
        services = entry.get("services", [])
        cmd = ["docker", "compose"]
        if compose_file:
            cmd.extend(["-f", compose_file])
        cmd.append("down")
        if services:
            cmd.extend(services)
        subprocess.run(cmd, cwd=cwd, check=False)
        print(f"  ✓ docker compose down")

    elif entry_type == "script":
        stop_cmd = entry.get("stop_command")
        if stop_cmd:
            subprocess.run(stop_cmd, shell=True, check=False)
            print(f"  ✓ stop script → {stop_cmd}")
        else:
            print(f"  ℹ No stop_command for script entry")


def close_terminal_tabs(tabs: list[dict], base_dir: Path):
    """Close Terminal.app windows that were opened by mux."""
    for tab in tabs:
        name = tab.get("name", "")
        cwd = str((base_dir / tab.get("cwd", ".")).resolve()) if "cwd" in tab else str(base_dir)
        folder = Path(cwd).name

        script = f'''
tell application "Terminal"
    set windowCount to count of windows
    set closed to 0
    repeat with i from windowCount to 1 by -1
        set w to window i
        set wName to name of w
        if wName starts with "{folder}" then
            do script "kill %% 2>/dev/null; exit" in w
            delay 0.5
            try
                close w saving no
            end try
            set closed to closed + 1
        end if
    end repeat
    return closed
end tell'''
        result = subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
        stdout = result.stdout.decode().strip()
        try:
            closed_count = int(stdout) if stdout else 0
        except ValueError:
            closed_count = 0

        if closed_count > 0:
            print(f"  ✓ Closed Terminal window: {name} ({folder})")
        else:
            print(f"  ⚠ Terminal close failed for: {name} ({folder})")


def close_iterm_tabs(tabs: list[dict], base_dir: Path):
    """Close iTerm2 tabs by matching session name."""
    for tab in tabs:
        name = tab.get("name", "")
        if not name:
            continue
        script = f'''
tell application "iTerm"
    repeat with w in windows
        repeat with t in tabs of w
            repeat with s in sessions of t
                if name of s contains "{name}" then
                    close s
                end if
            end repeat
        end repeat
    end repeat
end tell'''
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
        print(f"  ✓ Closed iTerm tab: {name}")


def close_chromium_tabs(app: str, urls: list[str]):
    """Close specific tabs in Chrome/Edge by matching URLs."""
    for url in urls:
        script = f'''
tell application "{app}"
    set windowList to every window
    repeat with w in windowList
        set tabList to every tab of w
        repeat with t in tabList
            if URL of t contains "{url}" then
                close t
            end if
        end repeat
        if (count of tabs of w) is 0 then
            close w
        end if
    end repeat
end tell'''
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
        print(f"  ✓ Closed {app} tab: {url}")


def close_safari_tabs(urls: list[str]):
    """Close specific tabs in Safari by matching URLs."""
    for url in urls:
        script = f'''
tell application "Safari"
    set windowList to every window
    repeat with w in windowList
        set tabList to every tab of w
        repeat with t in tabList
            if URL of t contains "{url}" then
                close t
            end if
        end repeat
    end repeat
end tell'''
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
        print(f"  ✓ Closed Safari tab: {url}")


def quit_app(app_name: str):
    script = f'tell application "{app_name}" to quit'
    subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
    print(f"  ✓ Quit {app_name}")


# ─────────────────────────────────────────────────
#  Commands
# ─────────────────────────────────────────────────

def cmd_open(directory: str):
    config_path = find_config(directory)
    if not config_path:
        print(f"✗ No .mux.json found in {Path(directory).resolve()}")
        print(f"  Run: mux --init . to create one")
        sys.exit(1)

    config = load_config(config_path)
    base_dir = config_path.parent
    entries = config.get("apps", [])
    name = config.get("name", base_dir.name)

    print(f"\n▶  Opening workspace: {name}\n")

    all_opened = []
    for entry in entries:
        t = entry.get("type", "")
        opener = OPENERS.get(t)
        if opener:
            opened = opener(entry, base_dir)
            all_opened.extend(opened)
        else:
            print(f"  ⚠ Unknown type: {t}")

    save_state(directory, all_opened)
    print(f"\n✓ Workspace ready. ({len(all_opened)} items opened)\n")


def cmd_stop(directory: str):
    config_path = find_config(directory)
    if not config_path:
        print(f"✗ No .mux.json found in {Path(directory).resolve()}")
        sys.exit(1)

    config = load_config(config_path)
    close_workspace(directory, config)


def cmd_stop_and_save(directory: str):
    """Capture current state, prompt for new entries, then close."""
    config_path = find_config(directory)
    target_dir = Path(directory).resolve()

    existing_config = None
    if config_path:
        existing_config = load_config(config_path)

    print(f"\n📸 Scanning workspace...\n")
    captured_config = _build_capture(target_dir, existing_config)

    # Diff against existing — prompt user for each new entry
    final_config = _diff_and_prompt(existing_config, captured_config)

    target_file = target_dir / ".mux.json"
    with open(target_file, "w") as f:
        json.dump(final_config, f, indent=2)
    print(f"\n✓ Updated {target_file} ({len(final_config['apps'])} entries)")

    close_workspace(directory, final_config)


def cmd_list(directory: str):
    config_path = find_config(directory)
    if not config_path:
        print(f"✗ No .mux.json found in {Path(directory).resolve()}")
        sys.exit(1)

    config = load_config(config_path)
    base_dir = config_path.parent
    name = config.get("name", base_dir.name)

    print(f"\n📋 Workspace: {name}\n")
    for entry in config.get("apps", []):
        t = entry.get("type", "")
        if t in ("vscode", "editor"):
            paths = entry.get("paths", [])
            if "path" in entry:
                paths = [entry["path"]] + paths
            cmd = entry.get("command", "code")
            window_geom = entry.get("windows", {})
            for p in paths:
                geom = window_geom.get(p)
                geom_str = ""
                if geom:
                    pos = geom.get("position", [])
                    sz = geom.get("size", [])
                    if pos and sz:
                        geom_str = f" @ ({pos[0]}, {pos[1]}) {sz[0]}x{sz[1]}"
                print(f"  [{t}] {cmd} → {(base_dir / p).resolve()}{geom_str}")
        elif t == "browser":
            app = entry.get("app", "Chrome")
            geom = entry.get("window")
            geom_str = ""
            if geom:
                pos = geom.get("position", [])
                sz = geom.get("size", [])
                if pos and sz:
                    geom_str = f" @ ({pos[0]}, {pos[1]}) {sz[0]}x{sz[1]}"
            for url in entry.get("urls", []):
                print(f"  [browser] {app} → {url}{geom_str}")
                geom_str = ""  # only show geometry on first URL
        elif t == "terminal":
            app = entry.get("app", "Terminal")
            for tab in entry.get("tabs", []):
                geom = tab.get("window")
                geom_str = ""
                if geom:
                    pos = geom.get("position", [])
                    sz = geom.get("size", [])
                    if pos and sz:
                        geom_str = f" @ ({pos[0]}, {pos[1]}) {sz[0]}x{sz[1]}"
                print(f"  [terminal] {app} tab [{tab.get('name', '?')}] → {tab.get('command', '')}{geom_str}")
        elif t == "app":
            print(f"  [app] {entry.get('name', '?')}")
        elif t == "docker":
            svcs = entry.get("services", ["all"])
            print(f"  [docker] compose up → {' '.join(svcs)}")
        elif t == "script":
            print(f"  [script] {entry.get('command', '?')}")
    print()


def cmd_init(directory: str):
    target = Path(directory).resolve() / ".mux.json"
    if target.exists():
        print(f"✗ {target} already exists")
        sys.exit(1)

    starter = {
        "name": Path(directory).resolve().name,
        "apps": [
            {
                "type": "vscode",
                "paths": ["."],
                "_comment": "Opens VS Code with this project. Use 'command': 'cursor' for Cursor editor"
            },
            {
                "type": "browser",
                "app": "Microsoft Edge",
                "urls": [
                    "http://localhost:3000",
                    "https://github.com"
                ]
            },
            {
                "type": "terminal",
                "app": "Terminal",
                "_comment": "Change to 'iTerm' or 'iTerm2' if you use iTerm",
                "tabs": [
                    {
                        "name": "dev",
                        "command": "echo 'ready!'",
                        "cwd": "."
                    }
                ]
            },
            {
                "type": "docker",
                "services": ["postgres", "redis"],
                "_comment": "Runs docker compose up -d with these services"
            },
            {
                "type": "app",
                "name": "Postman",
                "_comment": "Opens any macOS app by name"
            }
        ]
    }

    with open(target, "w") as f:
        json.dump(starter, f, indent=2)

    print(f"✓ Created {target}")
    print(f"  Edit it, then run: mux .")


# ─────────────────────────────────────────────────
#  Capture — snapshot current desktop into .mux.json
# ─────────────────────────────────────────────────

def _capture_running_apps() -> list[str]:
    """Get list of all foreground app process names."""
    output = _run_osascript('''
tell application "System Events"
    set appNames to name of every process whose background only is false
    set output to ""
    repeat with a in appNames
        set output to output & a & "|||"
    end repeat
    return output
end tell''')
    return [a for a in output.split("|||") if a.strip()]


def _capture_editor_windows(process_name: str, app_name: str) -> list[dict]:
    """Get project folder paths AND geometry from a VS Code-like editor.
    Returns [{"path": str, "position": [x,y], "size": [w,h]}]
    """
    # Activate first (Electron needs it), get window titles + geometry
    output = _run_osascript(f'''
tell application "{app_name}" to activate
delay 0.5
tell application "System Events"
    tell process "{process_name}"
        set output to ""
        repeat with w in windows
            set wTitle to name of w
            set wPos to position of w
            set wSize to size of w
            set output to output & wTitle & "|||" & (item 1 of wPos) & "," & (item 2 of wPos) & "|||" & (item 1 of wSize) & "," & (item 2 of wSize) & ">>>"
        end repeat
        return output
    end tell
end tell''')

    # Parse into title + geometry
    window_info = []
    for entry in output.split(">>>"):
        entry = entry.strip()
        if not entry or "|||" not in entry:
            continue
        parts = entry.split("|||")
        if len(parts) < 3:
            continue
        title = parts[0].strip()
        folder = title.split(" — ")[0].strip() if " — " in title else title
        try:
            pos = [int(x) for x in parts[1].split(",")]
            sz = [int(x) for x in parts[2].split(",")]
        except (ValueError, IndexError):
            pos, sz = None, None
        window_info.append({"folder": folder, "position": pos, "size": sz})

    # Resolve full paths via lsof
    lsof_result = subprocess.run(
        ["lsof", "-c", process_name.replace(" ", "\\x20")],
        capture_output=True, text=True, check=False
    )
    cwd_paths = []
    for line in lsof_result.stdout.splitlines():
        if "cwd" in line and "/" in line:
            path = line.split()[-1]
            if path != "/":
                cwd_paths.append(path)

    # Match folder names to full paths and attach geometry
    result = []
    for winfo in window_info:
        folder = winfo["folder"]
        resolved_path = None

        for cwd in cwd_paths:
            if cwd.endswith("/" + folder) or Path(cwd).name == folder:
                resolved_path = cwd
                break

        if not resolved_path:
            resolved_path = _find_in_vscode_storage(folder)

        if resolved_path:
            result.append({
                "path": resolved_path,
                "position": winfo["position"],
                "size": winfo["size"],
            })

    return result


def _find_in_vscode_storage(folder_name: str) -> str | None:
    """Try to find a folder path from VS Code's recent workspaces storage."""
    storage_path = Path.home() / "Library/Application Support/Code/User/globalStorage/storage.json"
    if not storage_path.exists():
        return None
    try:
        with open(storage_path) as f:
            data = json.load(f)
        backup = data.get("backupWorkspaces", {})
        for entry in backup.get("folders", []):
            uri = entry.get("folderUri", "")
            if uri.startswith("file://") and uri.endswith("/" + folder_name):
                return uri.replace("file://", "")
    except (json.JSONDecodeError, KeyError):
        pass
    return None


def _capture_browser_windows(app_name: str) -> list[dict]:
    """Get URLs per-window with geometry from a Chromium browser.
    Returns [{"urls": [...], "position": [x,y], "size": [w,h]}]
    """
    # Get URLs grouped by window
    url_output = _run_osascript(f'''
tell application "{app_name}"
    set output to ""
    repeat with w in windows
        set urlList to ""
        repeat with t in tabs of w
            set urlList to urlList & URL of t & "|||"
        end repeat
        set output to output & urlList & ">>>"
    end repeat
    return output
end tell''')

    # Get geometry via System Events
    geom_output = _run_osascript(f'''
tell application "System Events"
    tell process "{app_name}"
        set output to ""
        repeat with w in windows
            set wPos to position of w
            set wSize to size of w
            set output to output & (item 1 of wPos) & "," & (item 2 of wPos) & "|||" & (item 1 of wSize) & "," & (item 2 of wSize) & ">>>"
        end repeat
        return output
    end tell
end tell''')

    # Parse URLs per window
    url_windows = []
    for win_entry in url_output.split(">>>"):
        win_entry = win_entry.strip()
        if not win_entry:
            continue
        urls = [u.strip() for u in win_entry.split("|||") if u.strip()]
        if urls:
            url_windows.append(urls)

    # Parse geometry per window
    geom_windows = []
    for geom_entry in geom_output.split(">>>"):
        geom_entry = geom_entry.strip()
        if not geom_entry or "|||" not in geom_entry:
            continue
        parts = geom_entry.split("|||")
        try:
            pos = [int(x) for x in parts[0].split(",")]
            sz = [int(x) for x in parts[1].split(",")]
            geom_windows.append({"position": pos, "size": sz})
        except (ValueError, IndexError):
            geom_windows.append({"position": None, "size": None})

    # Combine (same window order)
    result = []
    for i, urls in enumerate(url_windows):
        geom = geom_windows[i] if i < len(geom_windows) else {"position": None, "size": None}
        result.append({
            "urls": urls,
            "position": geom["position"],
            "size": geom["size"],
        })

    return result


def _capture_terminal_windows() -> list[dict]:
    """Get Terminal.app window info with working directories and geometry."""
    # Get window name, tty, position, size
    output = _run_osascript('''
tell application "Terminal"
    set info to ""
    repeat with w in windows
        set wName to name of w
        set tabCount to count of tabs of w
        repeat with j from 1 to tabCount
            set t to tab j of w
            set ttyPath to tty of t
            set info to info & wName & "|||" & ttyPath & ">>>"
        end repeat
    end repeat
    return info
end tell''')

    # Get geometry separately via System Events
    geom_output = _run_osascript('''
tell application "System Events"
    tell process "Terminal"
        set output to ""
        repeat with w in windows
            set wName to name of w
            set wPos to position of w
            set wSize to size of w
            set output to output & wName & "|||" & (item 1 of wPos) & "," & (item 2 of wPos) & "|||" & (item 1 of wSize) & "," & (item 2 of wSize) & ">>>"
        end repeat
        return output
    end tell
end tell''')

    # Parse geometry into a dict keyed by window name
    geom_by_name = {}
    for entry in geom_output.split(">>>"):
        entry = entry.strip()
        if not entry or "|||" not in entry:
            continue
        parts = entry.split("|||")
        if len(parts) >= 3:
            wname = parts[0].strip()
            try:
                pos = [int(x) for x in parts[1].split(",")]
                sz = [int(x) for x in parts[2].split(",")]
                geom_by_name[wname] = {"position": pos, "size": sz}
            except (ValueError, IndexError):
                pass

    windows = []
    for entry in output.split(">>>"):
        entry = entry.strip()
        if not entry or "|||" not in entry:
            continue
        parts = entry.split("|||")
        win_name = parts[0].strip()
        tty = parts[1].strip() if len(parts) > 1 else ""

        # Get working directory from shell PID on this tty
        cwd = ""
        if tty:
            tty_short = tty.replace("/dev/", "")
            ps_result = subprocess.run(
                ["ps", "-t", tty_short, "-o", "pid=,comm="],
                capture_output=True, text=True, check=False
            )
            for line in ps_result.stdout.splitlines():
                line = line.strip()
                if any(sh in line for sh in ("zsh", "bash", "fish")):
                    pid = line.split()[0]
                    lsof_result = subprocess.run(
                        ["lsof", "-p", pid], capture_output=True, text=True, check=False
                    )
                    for l in lsof_result.stdout.splitlines():
                        if "cwd" in l:
                            cwd = l.split()[-1]
                            break
                    break

        geom = geom_by_name.get(win_name, {})
        windows.append({
            "name": win_name, "tty": tty, "cwd": cwd,
            "position": geom.get("position"),
            "size": geom.get("size"),
        })

    return windows


def _capture_docker_containers() -> list[dict]:
    """Get running docker compose projects and their services."""
    result = subprocess.run(
        ["docker", "compose", "ls", "--format", "json"],
        capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return []

    projects = []
    try:
        data = json.loads(result.stdout)
        for proj in data:
            name = proj.get("Name", "")
            config = proj.get("ConfigFiles", "")
            svc_result = subprocess.run(
                ["docker", "compose", "-f", config, "ps", "--format", "json"],
                capture_output=True, text=True, check=False
            )
            services = []
            if svc_result.returncode == 0:
                for line in svc_result.stdout.strip().splitlines():
                    try:
                        svc = json.loads(line)
                        services.append(svc.get("Service", ""))
                    except json.JSONDecodeError:
                        pass
            projects.append({
                "name": name,
                "config_file": config,
                "services": [s for s in services if s],
            })
    except json.JSONDecodeError:
        pass

    return projects


def _build_capture(target_dir: Path, existing_config: dict | None = None) -> dict:
    """Capture current desktop state into a config dict with geometry."""
    ignore = _load_ignore()
    running_apps = _capture_running_apps()
    apps_config = []
    captured_apps = set()

    # 1. Capture editors with geometry
    for process_name, editor_info in KNOWN_EDITORS.items():
        if process_name in running_apps:
            editor_windows = _capture_editor_windows(process_name, editor_info["app_name"])
            if editor_windows:
                rel_paths = []
                windows_geom = {}
                for ew in editor_windows:
                    p = ew["path"]
                    try:
                        rel = os.path.relpath(p, target_dir)
                        if not rel.startswith("../.."):
                            rel_paths.append(rel)
                            key = rel
                        else:
                            rel_paths.append(p)
                            key = p
                    except ValueError:
                        rel_paths.append(p)
                        key = p

                    if ew["position"] and ew["size"]:
                        windows_geom[key] = {"position": ew["position"], "size": ew["size"]}

                entry = {"type": "vscode", "paths": rel_paths}
                if editor_info["command"] != "code":
                    entry["command"] = editor_info["command"]
                if windows_geom:
                    entry["windows"] = windows_geom
                apps_config.append(entry)
                print(f"  ✓ {editor_info['app_name']}: {len(editor_windows)} windows")
            captured_apps.add(process_name)

    # 2. Capture browsers per-window with geometry (filter ignored URLs)
    ignored_urls = ignore.get("urls", [])
    for process_name, app_name in KNOWN_BROWSERS.items():
        if process_name in running_apps and app_name:
            browser_windows = _capture_browser_windows(app_name)
            for bw in browser_windows:
                # Filter out ignored URLs
                filtered_urls = [
                    url for url in bw["urls"]
                    if not any(ig.lower() in url.lower() for ig in ignored_urls)
                ]
                if not filtered_urls:
                    continue
                entry = {
                    "type": "browser",
                    "app": app_name,
                    "urls": filtered_urls,
                }
                if bw["position"] and bw["size"]:
                    entry["window"] = {"position": bw["position"], "size": bw["size"]}
                apps_config.append(entry)
                skipped = len(bw["urls"]) - len(filtered_urls)
                skip_str = f" ({skipped} ignored)" if skipped else ""
                print(f"  ✓ {app_name}: {len(filtered_urls)} tabs{skip_str}")
            captured_apps.add(process_name)

    # 3. Preserve docker/script entries from existing config
    if existing_config:
        for entry in existing_config.get("apps", []):
            if entry.get("type") in ("docker", "script"):
                apps_config.append(entry)
                t = entry.get("type")
                if t == "docker":
                    svcs = entry.get("services", [])
                    print(f"  ✓ Docker (kept): {' '.join(svcs) or 'all'}")
                elif t == "script":
                    print(f"  ✓ Script (kept): {entry.get('command', '?')}")

    # 4. Capture Terminal windows with geometry
    our_tty = os.ttyname(sys.stdin.fileno()) if sys.stdin.isatty() else ""
    term_windows = _capture_terminal_windows()
    term_tabs = []
    for tw in term_windows:
        if tw["tty"] == our_tty:
            continue
        if "claude" in tw["name"].lower():
            continue
        if not tw["cwd"] or tw["cwd"] == "/":
            continue

        try:
            rel_cwd = os.path.relpath(tw["cwd"], target_dir)
        except ValueError:
            rel_cwd = tw["cwd"]

        short_name = tw["name"].split(" — ")[0].strip()
        tab_entry = {"name": short_name, "cwd": rel_cwd}
        if tw.get("position") and tw.get("size"):
            tab_entry["window"] = {"position": tw["position"], "size": tw["size"]}
        term_tabs.append(tab_entry)

    if term_tabs:
        apps_config.append({
            "type": "terminal",
            "app": "Terminal",
            "tabs": term_tabs
        })
        print(f"  ✓ Terminal: {len(term_tabs)} windows")

    # 5. Capture other running apps
    skip_all = SKIP_APPS | captured_apps | {"Terminal"}
    for editor_info in KNOWN_EDITORS.values():
        skip_all.add(editor_info["app_name"])
    for browser_name in KNOWN_BROWSERS:
        skip_all.add(browser_name)

    ignored_apps = ignore.get("apps", [])
    other_apps = [a for a in running_apps if a not in skip_all]
    for app_name in other_apps:
        if any(ig.lower() in app_name.lower() for ig in ignored_apps):
            continue
        apps_config.append({"type": "app", "name": app_name})
        print(f"  ✓ App: {app_name}")

    name = target_dir.name
    if existing_config and "name" in existing_config:
        name = existing_config["name"]

    return {"name": name, "apps": apps_config}


def cmd_capture(directory: str):
    target_dir = Path(directory).resolve()
    target_file = target_dir / ".mux.json"

    if target_file.exists():
        print(f"⚠ {target_file} already exists. Overwrite? [y/N] ", end="", flush=True)
        answer = input().strip().lower()
        if answer not in ("y", "yes"):
            print("Cancelled.")
            return

    print(f"\n📸 Capturing current workspace...\n")
    config = _build_capture(target_dir)

    with open(target_file, "w") as f:
        json.dump(config, f, indent=2)

    print(f"\n✓ Saved to {target_file}")
    print(f"  {len(config['apps'])} entries captured")
    print(f"  Review and edit, then run: mux .\n")


# ─────────────────────────────────────────────────
#  CLI
# ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="mux",
        description="Workspace launcher — open/close all your project tools at once",
        epilog="Config: .mux.json in your project root. Use project names after --add."
    )
    parser.add_argument("directory", nargs="?", default=".",
                        help="Project name or directory (default: current dir)")
    parser.add_argument("-s", "--stop", action="count", default=0,
                        help="Stop workspace: -s saves then closes, -ss quick close")
    parser.add_argument("-l", "--list", action="store_true",
                        help="List what would be opened (dry run)")
    parser.add_argument("--init", action="store_true",
                        help="Create a starter .mux.json")
    parser.add_argument("-c", "--capture", action="store_true",
                        help="Snapshot current open apps into .mux.json")
    parser.add_argument("--add", metavar="NAME",
                        help="Register current dir (or specified dir) as a named project")
    parser.add_argument("--remove", metavar="NAME",
                        help="Remove a project from the registry")
    parser.add_argument("--projects", action="store_true",
                        help="List all registered projects")

    args = parser.parse_args()

    # Handle registry commands first (no directory resolution needed)
    if args.projects:
        cmd_list_projects()
        return
    if args.remove:
        cmd_remove_project(args.remove)
        return
    if args.add:
        # `mux --add amsa .` or `mux --add amsa /path`
        # directory arg is the path (defaults to ".")
        cmd_add_project(args.add, args.directory)
        return

    # Resolve directory: could be a path or a registered project name
    directory = resolve_directory(args.directory)

    if args.capture:
        cmd_capture(directory)
    elif args.init:
        cmd_init(directory)
    elif args.stop >= 2:
        cmd_stop(directory)
    elif args.stop == 1:
        cmd_stop_and_save(directory)
    elif args.list:
        cmd_list(directory)
    else:
        cmd_open(directory)


if __name__ == "__main__":
    main()
