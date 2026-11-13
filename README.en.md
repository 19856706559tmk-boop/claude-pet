# Claude Desktop Pet

A pixel-art Claude crab that lives in the Claude desktop app window. It wanders around, idles, and does little moves on its own. While you work with Claude, it acts along with what Claude is doing, and you can check your 5-hour and 7-day (weekly) quota at any time.

**Windows only** (it uses tkinter plus a few Win32 APIs). You need [Python 3](https://www.python.org/downloads/) (standard library only, no extra dependencies) and the Claude desktop app. 中文说明见 [README.md](README.md)。

## What it does

All of its speech and the tags above its head are in Chinese.

**Idle (random)**: walks around, sometimes strolls over to your mouse; sits down, looks around, waves, hops, dances, stretches, yawns. Its eyes follow the mouse and it blinks. A few fancier moves:

| Move | What it looks like |
|---|---|
| Spin | Eyes slide to one side, turns to its back, comes around the other side, gets dizzy afterwards |
| Juggling | Tosses and catches three colored balls, then catches them all at once |
| Chasing a butterfly | Eyes follow the butterfly, misses twice, and finally the butterfly lands on its head |
| Coffee | Holds the cup, takes a sip, then a relieved sigh; drinks "survival coffee" a lot more when quota is nearly used up |
| Sunglasses moonwalk | Sunglasses drop from above onto its face, then it glides backwards |

If nothing happens for over 10 minutes it lies down to sleep (with "zzz" bubbles); sleeping between 10 PM and 7 AM it wears a nightcap. Its greeting follows the time of day (good morning, good evening, it's late...).

**Following Claude's work**:

| What Claude is doing | The pet's action |
|---|---|
| You just sent a message, Claude is thinking | "Thinking..." bubble, looks up at the sky, scratches its head, taps its toes, occasionally shows question marks and a light bulb |
| Running a command (Bash / PowerShell) | Types on a little black terminal with green text |
| Reading files (Read) | Holds a page of a document, reads line by line, turns to the next page |
| Searching (Grep / Glob / tool lookup) | Sweeps a magnifying glass back and forth, eyes light up when it finds something |
| Web (WebSearch / WebFetch / browser tools) | Rides a surfboard bobbing on the waves |
| Writing code (Edit / Write / MultiEdit / NotebookEdit) | Turns sideways and writes on the ground line by line with a pencil, with `{ }`, `</>` symbols floating above its head |
| Planning (task-list tools) | Holds a clipboard and checks items off |
| Using a skill | Puts on a wizard hat and waves a wand with sparks |
| Dispatching sub-agents (Agent / Workflow) | Summons two little minions |
| **Claude is waiting for your answer** (a question or plan confirmation) | Plants a question-mark sign next to it, waves at you, hops once in a while, until you reply |
| Other tools (MCP etc.) | Swings a hammer at a gear; the gear ticks one notch per hit |
| Reply finished | Jumps up and cheers "Done!" |
| Interrupted or an error | Panics and sweats, "Huh?" |

While working, it shows what it's doing in Chinese above its head, e.g. "running a command", "editing code", "searching the web".

**Following the quota**:

- Each time some quota is used, a cookie drops from the sky; it catches it, eats it in three bites, then shows how much was used, e.g. `5h -0.7%`.
- At 50%, 80% and 90% usage it raises a little red flag and waves it hard.
- Above 80% it gets tired: walks slower, occasionally sweats, sits more, survives on coffee.
- When exhausted it lies down to sleep; click it and it tells you how long until recovery.
- When the quota resets, the battery above its head fills up cell by cell, then it jumps up and cheers "Quota restored!".

## How to interact

- **Left click**: toggle the quota panel. It shows the remaining 5-hour and 7-day quota, time until reset, and how long ago the data was updated.
- **Left drag**: pick it up. Release inside the Claude window and it lands back at the window's bottom; release outside and it roams free at the bottom of the screen (just above the taskbar).
- **Double click**: pat its head, hearts pop up.
- **Right click**: a menu with viewing quota, returning to the Claude window, putting it to sleep / waking it up, a dance, and quitting the pet.

## When it appears and disappears

- As soon as the Claude desktop app opens, the background watcher (see "Start with Claude" below) launches the pet; you don't need to enter a conversation first.
- Each time a conversation opens, the plugin also checks once and starts the pet if it isn't running. If it's already running, no second pet is spawned.
- After "Quit pet" from the right-click menu, the watcher won't bring it back for the rest of this Claude session; it returns the next time you open Claude or start a new conversation.
- At home (inside the Claude window) it always sticks to the Claude window's layer: it gets covered when other windows cover Claude, and hides when Claude is minimized.
- Dragged outside, it floats above all windows.
- After the Claude desktop app fully exits, the pet quits by itself within a few seconds.

## About the quota

Claude subscriptions have no "daily quota"; the shortest is the **5-hour window**, plus a **7-day (weekly) window** — the panel shows both. The data comes from the quota info attached to each Claude reply, so right after opening it may show "no quota data yet"; send a message and it appears once Claude replies.

When the numbers update:

- While Claude is working, the latest quota is read after every tool call and every completed reply; the panel updates as soon as the numbers change, without waiting for the whole turn.
- At reset time the panel switches to "restored" immediately, without waiting for the next reply.
- With several conversations open at once, the one that most recently received a reply wins; a freshly opened conversation won't overwrite newer numbers with stale ones.
- The "updated N ago" in the panel's corner is the true time of the data. Quota data only arrives with replies in Claude desktop Code conversations, so usage from the web, mobile or other devices shows up here only after the next reply arrives.

## Files

| File | Purpose |
|---|---|
| `pet.pyw` | The pet itself, also the watcher (run with `--watch`). Uses only Python's built-in tkinter and ctypes; no dependencies |
| `config.example.json` | Config template. Copy it to `config.json` and edit: `pythonw` is the path to your `pythonw.exe`, which the plugin uses to launch the pet — use forward slashes (`C:/Python/pythonw.exe`); a single backslash breaks the whole file and the pet won't auto-start. `pet_size`, `panel_size`: size multipliers for the pet and the quota panel (including the right-click menu), default 1.0 (e.g. 0.8 for smaller, 1.3 for larger). Restart the pet to apply |
| `mod/` | The Claude Code plugin `desk-pet-bridge`: writes quota and Claude's activity into the two files below, and starts the pet when a session begins |
| `.claude-plugin/marketplace.json` | Lets Claude Code install the plugin directly from this folder |
| `quota.json`, `activity.json` | Runtime-generated data files (gitignored), safe to delete any time |
| `bridge.json` | A heartbeat written by the plugin each time it loads in a session, to verify the plugin is running |
| `launch-error.json` | Written when the plugin fails to auto-launch the pet (doesn't exist normally) |
| `pet.log` | Error log |

## Installation (make the plugin run in every conversation)

1. Clone this repo (or download and extract the ZIP):

   ```bash
   git clone https://github.com/19856706559tmk-boop/claude-pet.git
   ```

2. Copy `config.example.json` to `config.json`, and set `pythonw` to the actual path of `pythonw.exe` on your machine. Use forward slashes (e.g. `C:/Users/me/AppData/Local/Programs/Python/Python313/pythonw.exe`); run `where.exe pythonw` in PowerShell to find the path.

3. Add the plugin folder to the `env` of `C:\Users\<you>\.claude\settings.json` (replace the path with wherever you cloned it):

   ```json
   "env": {
     "CLAUDE_CODE_PLUGIN_DIRS": "D:\\apps\\claude-pet\\mod"
   }
   ```

4. Fully quit Claude and reopen it.

Why not `claude plugin install`: plugins installed that way have their hook modules gated behind Claude Code's server-side flag `tengu_plugin_hooks_modules`. When that flag is off, the plugin shows as "enabled" but its hooks don't run. `CLAUDE_CODE_PLUGIN_DIRS` is the official way to load plugin folders for desktop sessions. `.claude-plugin/marketplace.json` is kept so this can switch back to the install method once the flag opens up.

## Start with Claude (the watcher)

The plugin only runs while a conversation is open, so on its own the pet would wait until you enter the first conversation. The watcher fills that gap: it starts in the background at Windows logon, checks every 2 seconds whether the Claude desktop app is open, and launches the pet as soon as it is. It has no window and does only this one job.

Register (one time only; registered in the current user's logon startup items under the name `ClaudeDeskPetWatcher`; replace `<project path>` with your clone location):

```bash
"<path to python.exe>" "<project path>\pet.pyw" --install-autostart
```

Takes effect from the next Windows logon. To take effect immediately, start the watcher once manually:

```bash
"<path to pythonw.exe>" "<project path>\pet.pyw" --watch
```

Unregister:

```bash
"<path to python.exe>" "<project path>\pet.pyw" --uninstall-autostart
```

You can also toggle it off in Task Manager's "Startup apps". If you move this folder or switch Python, register it again.

## Manual start

```bash
"<path to pythonw.exe>" "<project path>\pet.pyw"
```

Debug flags: `--keep` (don't quit even if Claude is closed), `--demo` (play through all actions), `--show-panel` (open the quota panel at startup).

## Uninstall

1. Choose "Quit pet" in the right-click menu.
2. Run the "Unregister" command above, then end the `pythonw.exe` running with `--watch` in Task Manager (or just log off once).
3. Remove the `CLAUDE_CODE_PLUGIN_DIRS` line from the `env` in `~/.claude/settings.json`.
4. Delete this folder.

## License

MIT — see [LICENSE](LICENSE).
