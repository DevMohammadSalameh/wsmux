# wsmux

Workspace launcher for macOS. Open and close entire project environments with one command.

**One config file. One command. Your entire workspace — editors, browsers, terminals, docker, apps — opens exactly where you left it.**

## Install

```bash
pip install wsmux
```

Or install from source:

```bash
git clone https://github.com/safeersoft/wsmux.git
cd wsmux
pip install .
```

The CLI command is `mux`.

## Quick Start

```bash
# Create a config in your project
cd ~/my-project
mux --init .

# Edit .mux.json to match your setup, then:
mux .                # Open everything
mux -s .             # Save window positions + close
mux .                # Reopen — everything is where you left it
```

## Commands

| Command | What it does |
|---------|-------------|
| `mux .` | Open workspace from `.mux.json` |
| `mux -s .` | Save current state (new tabs, positions) then close |
| `mux -ss .` | Quick close — no config update |
| `mux -c .` | Capture current desktop into `.mux.json` |
| `mux -l .` | Dry run — show what would open |
| `mux --init .` | Create a starter `.mux.json` |

## Named Projects

Register projects to open them from anywhere:

```bash
mux --add myapp ~/projects/myapp    # Register
mux myapp                            # Open from anywhere
mux -s myapp                         # Save + close from anywhere
mux --projects                       # List registered projects
mux --remove myapp                   # Unregister
```

## Config Format

`.mux.json` in your project root:

```json
{
  "name": "My Project",
  "apps": [
    {
      "type": "vscode",
      "paths": ["./frontend", "./backend"],
      "windows": {
        "./frontend": {"position": [0, 0], "size": [960, 1080]},
        "./backend": {"position": [960, 0], "size": [960, 1080]}
      }
    },
    {
      "type": "browser",
      "app": "Microsoft Edge",
      "urls": ["http://localhost:3000", "https://github.com/me/repo"],
      "window": {"position": [1920, 0], "size": [1680, 1050]}
    },
    {
      "type": "terminal",
      "app": "Terminal",
      "tabs": [
        {
          "name": "server",
          "command": "npm run dev",
          "cwd": "./backend",
          "window": {"position": [0, 600], "size": [800, 400]}
        }
      ]
    },
    {
      "type": "docker",
      "services": ["postgres", "redis"],
      "cwd": "./backend"
    },
    {
      "type": "app",
      "name": "Postman"
    }
  ]
}
```

### Entry Types

| Type | What it opens | Key fields |
|------|--------------|------------|
| `vscode` | VS Code / Cursor windows | `paths`, `command` (`"cursor"`), `windows` (geometry) |
| `browser` | Browser with tabs in isolated window | `app`, `urls`, `window` (geometry) |
| `terminal` | Terminal.app / iTerm2 tabs | `tabs[].name`, `tabs[].command`, `tabs[].cwd`, `tabs[].window` |
| `docker` | Docker Compose services | `services`, `cwd`, `file` |
| `app` | Any macOS app | `name`, `args` |
| `script` | Shell command | `command`, `cwd`, `stop_command` |

## Window Positions

Mux remembers where every window was — position, size, and which monitor.

- **Auto-capture**: `mux -s` saves current positions before closing
- **Manual capture**: `mux -c` snapshots your current desktop
- **Restore**: `mux .` reopens windows at their saved positions
- **Multi-monitor**: positions use macOS unified coordinates, so windows restore to the correct monitor

## Save Behavior (`mux -s`)

When closing with `-s`, mux compares your current desktop against the saved config:

- **Existing entries**: geometry is updated silently
- **New entries** (new browser tabs, apps): you're prompted for each one:

```
New entries detected:

    + [App] Postman  [y/n/i] (yes/no/ignore forever): y
      ✓ Added

    + [Microsoft Edge] reddit.com + 2 more tabs  [y/n/i] (yes/no/ignore forever): i
      ✗ Ignored forever: URL pattern 'reddit.com'
```

- `y` — add to config
- `n` — skip this time
- `i` — skip and add to global ignore (never captured again)

## Global Ignore

`~/.mux/ignore.json` — patterns that are never captured:

```json
{
  "apps": ["Slack"],
  "urls": ["chatgpt.com", "claude.ai", "reddit.com"],
  "paths": []
}
```

## Browser Isolation

Each project opens its browser tabs in a **new isolated window**. Running `mux` for two different projects won't mix their tabs together.

## Requirements

- macOS (uses AppleScript for window management)
- Python 3.10+
- Terminal needs Accessibility permission (System Settings > Privacy & Security > Accessibility) for window positioning

## Data Files

All stored in `~/.mux/`:

| File | Purpose |
|------|---------|
| `projects.json` | Named project registry |
| `ignore.json` | Global ignore patterns |
| `states/` | Last-opened state per project |

## License

MIT
