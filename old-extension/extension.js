import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import St from 'gi://St';
import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

const COLORS = ['yellow', 'pink', 'blue', 'green'];

export default class StickyNotesExtension extends Extension {
    enable() {
        this._stylesheet = this.dir.get_child('stylesheet.css');
        this._theme = St.ThemeContext.get_for_stage(global.stage).get_theme();
        this._theme.load_stylesheet(this._stylesheet);
        this._file = Gio.File.new_for_path(GLib.build_filenamev([
            GLib.get_user_data_dir(), 'gnome-sticky-notes', 'notes.json',
        ]));
        this._notes = this._load();
        this._actors = new Map();
        this._chromeActors = new Set();
        this._dragState = null;
        this._captureId = global.stage.connect('captured-event',
            this._onCapturedEvent.bind(this));
        for (const note of this._notes)
            this._makeNote(note);
    }

    disable() {
        if (this._saveTimeout) {
            GLib.source_remove(this._saveTimeout);
            this._saveTimeout = 0;
        }
        this._save();
        if (this._captureId) {
            global.stage.disconnect(this._captureId);
            this._captureId = 0;
        }
        this._dragState = null;
        this._closeMenu();
        if (this._chromeActors) {
            for (const actor of this._chromeActors) {
                Main.layoutManager.removeChrome(actor);
                actor.destroy();
            }
        }
        this._chromeActors = null;
        this._actors = null;
        if (this._stylesheet && this._theme)
            this._theme.unload_stylesheet(this._stylesheet);
        this._theme = null;
    }

    _load() {
        try {
            const [ok, bytes] = this._file.load_contents(null);
            if (ok) {
                const notes = JSON.parse(new TextDecoder().decode(bytes));
                if (Array.isArray(notes))
                    return notes.map(note => ({
                        id: note.id ?? GLib.uuid_string_random(),
                        text: note.text ?? '',
                        collapsed: !!note.collapsed,
                        color: COLORS.includes(note.color) ? note.color : 'yellow',
                        x: Number(note.x) || 280,
                        y: Number(note.y) || 90,
                    }));
            }
        } catch (error) {
            if (!error.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.NOT_FOUND))
                logError(error, 'GNOME Sticky Notes: notlar okunamadı');
        }
        return [];
    }

    _save() {
        try {
            const json = JSON.stringify(this._notes, null, 2);
            const parent = this._file.get_parent();
            if (!parent.query_exists(null))
                parent.make_directory_with_parents(null);
            this._file.replace_contents(json, null, false,
                Gio.FileCreateFlags.REPLACE_DESTINATION, null);
        } catch (error) {
            logError(error, 'Could not save GNOME Sticky Notes');
        }
    }

    _addNote(x, y) {
        const note = {
            id: GLib.uuid_string_random(), text: '', color: 'yellow',
            collapsed: false, x: Math.round(x), y: Math.round(y),
        };
        this._notes.push(note);
        this._makeNote(note);
        this._save();
        this._actors.get(note.id).entry.grab_key_focus();
    }

    _showDesktopMenu(x, y) {
        this._closeMenu();
        const anchor = new St.Widget({x, y, width: 0, height: 0});
        Main.uiGroup.add_child(anchor);
        const menu = new PopupMenu.PopupMenu(anchor, 0.0, St.Side.TOP);
        const manager = new PopupMenu.PopupMenuManager(anchor);
        manager.addMenu(menu);
        Main.uiGroup.add_child(menu.actor);
        menu.addAction('Not ekle', () => this._addNote(x, y));
        menu.addAction('Arka planı değiştir…', () => {
            try {
                Gio.Subprocess.new(['gnome-control-center', 'background'],
                    Gio.SubprocessFlags.NONE);
            } catch (error) {
                logError(error, 'GNOME Sticky Notes');
            }
        });
        menu.connect('open-state-changed', (_menu, open) => {
            if (open)
                return;
            GLib.idle_add(GLib.PRIORITY_DEFAULT, () => {
                if (this._menu === menu)
                    this._closeMenu();
                return GLib.SOURCE_REMOVE;
            });
        });
        this._menu = menu;
        this._menuAnchor = anchor;
        this._menuManager = manager;
        menu.open();
    }

    _closeMenu() {
        if (!this._menu)
            return;
        const menu = this._menu;
        const anchor = this._menuAnchor;
        this._menu = null;
        this._menuAnchor = null;
        this._menuManager = null;
        menu.destroy();
        anchor.destroy();
    }

    _makeNote(note) {
        const card = new St.BoxLayout({
            vertical: true,
            style_class: `sticky-note sticky-${note.color}`,
            x: note.x, y: note.y,
            reactive: true,
        });
        card.set_width(250);
        const header = new St.BoxLayout({style_class: 'sticky-note-header'});
        const title = new St.Label({
            style_class: 'sticky-title',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        title.clutter_text.ellipsize = 3; // END
        header.add_child(title);
        const color = new St.Button({label: '●', style_class: 'sticky-tool-button'});
        const remove = new St.Button({label: '×', style_class: 'sticky-tool-button'});
        color.accessible_name = 'Rengi değiştir';
        remove.accessible_name = 'Notu sil';
        header.add_child(color);
        header.add_child(remove);
        card.add_child(header);

        const entry = new St.Entry({
            style_class: 'sticky-entry',
            text: note.text,
            can_focus: true,
            reactive: true,
            x_expand: true,
            y_expand: true,
        });
        entry.set_height(150);
        const text = entry.clutter_text;
        text.single_line_mode = false;
        text.line_wrap = true;
        text.activatable = false;
        entry.accessible_name = 'Not metni';
        card.add_child(entry);

        const refresh = () => {
            const first = note.text.split('\n').find(line => line.trim()) ?? '';
            title.text = first || 'Yeni not';
            entry.visible = !note.collapsed;
        };
        refresh();
        text.connect('text-changed', () => {
            note.text = text.text;
            refresh();
            this._queueSave();
        });
        color.connect('clicked', () => {
            note.color = COLORS[(COLORS.indexOf(note.color) + 1) % COLORS.length];
            for (const key of COLORS)
                card.remove_style_class_name(`sticky-${key}`);
            card.add_style_class_name(`sticky-${note.color}`);
            this._queueSave();
        });
        remove.connect('clicked', () => {
            this._notes = this._notes.filter(item => item.id !== note.id);
            this._actors.delete(note.id);
            if (this._dragState?.card === card)
                this._dragState = null;
            Main.layoutManager.removeChrome(card);
            this._chromeActors.delete(card);
            card.destroy();
            this._save();
        });
        Main.layoutManager.addChrome(card, {affectsStruts: false});
        this._chromeActors.add(card);
        this._actors.set(note.id, {card, entry, header, note, refresh});
    }

    _findNote(actor) {
        for (let a = actor; a; a = a.get_parent()) {
            for (const item of this._actors.values()) {
                if (item.card === a)
                    return item;
            }
        }
        return null;
    }

    _isInside(actor, ancestor) {
        for (let a = actor; a; a = a.get_parent()) {
            if (a === ancestor)
                return true;
        }
        return false;
    }

    _isDesktop(source) {
        const bg = Main.layoutManager._backgroundGroup;
        if (bg && this._isInside(source, bg))
            return true;
        // Boş masaüstünde olay doğrudan sahneye/uiGroup'a düşebilir.
        return source === global.stage || source === Main.uiGroup ||
            source === global.window_group;
    }

    _onCapturedEvent(_actor, event) {
        const type = event.type();

        if (type === Clutter.EventType.BUTTON_PRESS) {
            const source = event.get_source();
            const button = event.get_button();
            if (this._menu && !this._isInside(source, this._menu.actor))
                this._closeMenu();
            const item = this._actors && this._findNote(source);
            if (item && button === 1) {
                if (this._isInside(source, item.header) &&
                    !(source instanceof St.Button) &&
                    !(source.get_parent() instanceof St.Button) &&
                    event.get_click_count() === 2) {
                    item.note.collapsed = !item.note.collapsed;
                    item.refresh();
                    this._save();
                    return Clutter.EVENT_STOP;
                }
                if (source instanceof St.Button || source.get_parent() instanceof St.Button)
                    return Clutter.EVENT_PROPAGATE;
                const [x, y] = event.get_coords();
                const [cx, cy] = item.card.get_transformed_position();
                this._dragState = {
                    card: item.card, note: item.note,
                    startX: x, startY: y,
                    offsetX: x - cx, offsetY: y - cy,
                    moving: false,
                };
                return Clutter.EVENT_PROPAGATE;
            }
            if (!item && button === 3 && !Main.overview.visible &&
                this._isDesktop(source)) {
                const [x, y] = event.get_coords();
                try {
                    this._showDesktopMenu(x, y);
                } catch (error) {
                    logError(error, 'GNOME Sticky Notes: menü açılamadı');
                    this._closeMenu();
                    return Clutter.EVENT_PROPAGATE;
                }
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        }

        if (!this._dragState)
            return Clutter.EVENT_PROPAGATE;

        if (type === Clutter.EventType.MOTION) {
            const [x, y] = event.get_coords();
            const s = this._dragState;
            if (!s.moving && Math.hypot(x - s.startX, y - s.startY) < 5)
                return Clutter.EVENT_PROPAGATE;
            s.moving = true;
            s.card.set_position(Math.max(0, x - s.offsetX), Math.max(0, y - s.offsetY));
            return Clutter.EVENT_STOP;
        }
        if (type === Clutter.EventType.BUTTON_RELEASE) {
            const {card, note, moving} = this._dragState;
            this._dragState = null;
            if (!moving)
                return Clutter.EVENT_PROPAGATE;
            const [x, y] = card.get_position();
            note.x = x;
            note.y = y;
            this._save();
            return Clutter.EVENT_STOP;
        }
        return Clutter.EVENT_PROPAGATE;
    }

    _queueSave() {
        if (this._saveTimeout)
            GLib.source_remove(this._saveTimeout);
        this._saveTimeout = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 400, () => {
            this._saveTimeout = 0;
            this._save();
            return GLib.SOURCE_REMOVE;
        });
    }
}
