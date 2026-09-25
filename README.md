# Deluxe Sticky Notes

Simple desktop sticky notes for GNOME (GTK4 + libadwaita, Python).
Every note opens in its own small window; the main window shows all notes as cards.

The interface is in **English** and **Turkish** (Türkçe). It follows your system language;
force one with `STICKYNOTES_LANG=en` or `STICKYNOTES_LANG=tr`.

## Features

- **Notes:** bold / italic / underline / strikethrough, bullet lists, clickable to-do lists (a checked item
  is struck through), text size for the selected text (A− / A+, Ctrl +/−), 6 colors, autosave.
- **Windows:** collapse a note to its title (double-click the title or use ▲); the buttons appear when
  you click a note and disappear when focus moves elsewhere; notes remember their position and size.
- **Alarms:** date + time, repeat (daily / weekly), "Snooze 5 min", sound; the note shakes when it rings.
- **Background:** keeps running after the main window is closed; a top-bar icon (left click: all notes,
  right click: menu); autostart at login; optional global shortcuts (Ctrl+Alt+N new note, Ctrl+Alt+A all notes).
- **Safety:** daily backups (last 7), recovery from a corrupt file, trash (30 days), Markdown export.
- **Lock:** right-click a note → "Lock note" makes it untouchable like a wallpaper: it can't be moved, resized,
  closed, collapsed/expanded or edited, and it stays exactly as it is (open or title-only). Unlock from the
  right-click menu (or the card menu in the main window). Locked notes can't be deleted.
- **More:** search (Turkish İ/ı aware), pinning, "always on top" / "always at the bottom" layer,
  right-click menus on notes and cards, "Suggest to the developers" (email or clipboard).

## Run

```sh
python3 -m stickynotes
```

To get the app menu entry with its icon (no Flatpak needed):

```sh
./install-local.sh          # remove with: ./install-local.sh --remove
```

Data lives in `~/.local/share/io.github.vex.StickyNotes/` (`notes.json`, `settings.json`, `backups/`).

## X11 / Wayland note

GNOME/Wayland does not let apps position their own windows. To remember note positions, offer the
"always on top / at the bottom" layer and keep notes out of the dock, the app runs through XWayland
(X11); without X11 it falls back to Wayland (those features turn off).
Pure Wayland: `STICKYNOTES_WAYLAND=1 python3 -m stickynotes`.

## Tests

```sh
python3 -m unittest discover -s tests -v     # GUI tests need a display and are skipped without one
```

Tests use temporary directories and never touch your real notes. They open real windows on screen,
so do not type into them while they run.

## Translations

Source strings are English, wrapped in `_()`. After changing UI text run:

```sh
./tools/update-translations.sh    # extracts strings, updates po/tr.po, compiles locale/tr/.../sticky-notes.mo
```

then translate the new entries in `po/tr.po` and run the script again. A test fails if any string is
untranslated, if the compiled `.mo` is stale, or if untranslated text is left in the source.
Add a language: `msginit -i po/sticky-notes.pot -o po/<lang>.po -l <lang>`.

## Flatpak

See `io.github.vex.StickyNotes.yml`.

```sh
flatpak install --user flathub org.flatpak.Builder org.gnome.Sdk//50
flatpak run org.flatpak.Builder --user --install --force-clean build-dir io.github.vex.StickyNotes.yml
flatpak run io.github.vex.StickyNotes
```

The Flatpak version keeps its data in `~/.var/app/io.github.vex.StickyNotes/`; use the main menu's
"Import old (non-Flatpak) notes" to bring your existing notes over.

## Files

- `stickynotes/` app code · `data/` icons, desktop entry, metainfo · `po/` + `locale/` translations
- `tests/` tests · `tools/` helper scripts · `old-extension/` the first GNOME Shell extension attempt (unused)

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
