"""Arayüz testleri: uygulama gerçek pencereleriyle (X11/XWayland ya da Wayland) bir kez çalıştırılır,
senaryo adım adım yürütülür, sonuçlar test metotlarında doğrulanır. Ekran yoksa atlanır."""
import time
import unittest

from tests import helpers

R = {}          # senaryonun topladığı sonuçlar
ERROR = []      # senaryo sırasında oluşan istisna


def scenario(app, Gtk, winpos, GLib):
    store = app.store

    class Gest:
        def __init__(self, button=1):
            self.claimed, self.button = False, button

        def set_state(self, *_):
            self.claimed = True

        def get_current_button(self):
            return self.button

    def find_close(win):
        found = []

        def walk(x):
            c = x.get_first_child()
            while c:
                if isinstance(c, Gtk.Button) and c.has_css_class("close"):
                    found.append(c)
                walk(c)
                c = c.get_next_sibling()
        walk(win._header)
        return found[0] if found else None

    # ---- not oluşturma, biçimlendirme ----
    app.new_note()
    w = next(iter(app.note_windows.values()))
    buf = w.buffer
    buf.insert_at_cursor("Alışveriş listesi\nsüt\nekmek")
    yield 0.5

    # bekleyen kalın: ctrl+B sonra yazılan kalın olur, tekrar kapatınca düz
    buf.place_cursor(buf.get_end_iter())
    w.toggle_format("bold")
    buf.insert_at_cursor(" KALIN")
    w.toggle_format("bold")
    buf.insert_at_cursor(" düz")
    tags = store.notes[w.note_id]["tags"]
    R["pending_bold"] = [t for t in tags if t[0] == "bold"]
    R["text_after_typing"] = store.notes[w.note_id]["text"]

    # ---- liste ----
    buf.select_range(buf.get_iter_at_line(1)[1], buf.get_end_iter())
    w.toggle_list("check")
    R["check_text"] = w._text().split("\n")[1:]
    R["glyph_tags"] = len([t for t in store.notes[w.note_id]["tags"] if t[0] == "glyph"])
    yield 0.4

    class Fake:
        def set_state(self, *_):
            pass

    def bounds_in_view(widget):
        ok, b = widget.compute_bounds(w._view)
        return b.get_x() + 3, b.get_y() + 3

    def click_glyph(line):
        rect = w.textview.get_iter_location(w._line_start(line))
        x, y = w.textview.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, rect.x + 2, rect.y + 2)
        w._on_click_pressed(Fake(), 1, x, y)

    click_glyph(1)
    R["after_click"] = w._text().split("\n")[1]
    done = buf.get_tag_table().lookup("done")
    line = w._line_start(1)
    line.forward_chars(2)
    R["done_tag_after_click"] = line.has_tag(done)
    yield 0.4
    click_glyph(1)
    R["after_second_click"] = w._text().split("\n")[1]

    # Enter ile devam ve boş satırda listeden çıkış
    buf.place_cursor(buf.get_end_iter())
    w._continue_list()
    R["enter_continues"] = w._text().endswith("\n☐ ")
    w._continue_list()
    R["enter_exits_list"] = w._text().endswith("düz\n")

    # ---- yazı boyutu, renk ----
    full = w._text()
    i = full.index("süt")
    buf.select_range(buf.get_iter_at_offset(i), buf.get_iter_at_offset(i + 3))
    w.change_font_size(1)
    w.change_font_size(1)
    R["selection_size_tags"] = [t for t in store.notes[w.note_id]["tags"] if t[0].startswith("size-")]
    R["selection_range"] = (i, i + 3)
    R["base_font_unchanged"] = w.font_size
    for _ in range(30):
        w.change_font_size(-1)
    R["font_min_tag"] = [t[0] for t in store.notes[w.note_id]["tags"] if t[0].startswith("size-")]
    buf.place_cursor(buf.get_end_iter())
    w.set_color("blue")
    R["color_saved"] = store.notes[w.note_id]["color"]

    # ---- düğmelerin görünürlüğü: nota tıklayınca gelir, odak gidince gider ----
    def chrome():
        return (w._header.get_show_end_title_buttons(), w._new_btn.get_visible(), w._bar.get_visible())
    w.is_active = lambda: True
    w._chrome_on = False
    w._update_chrome()
    R["chrome_hidden_before_click"] = chrome()
    w._on_press(Gest(), 1, 100, 200)                 # metin alanına tıklama
    R["chrome_after_click"] = chrome()
    w.is_active = lambda: False
    w._schedule_chrome()
    yield 0.6
    R["chrome_after_focus_loss"] = chrome()
    w.is_active = lambda: True
    w._chrome_on = True
    w._update_chrome()

    # ---- odak başka uygulamaya geçince açık menüler kapanır ve düğmeler gizlenir ----
    # Gerçek popover'lar bu test ortamında (fare/yakalama yok) kendiliğinden kapanabildiği için menüler
    # kayıt tutan sahte nesnelerle değiştirilir; sınanan şey bizim kapatma mantığımızdır.
    class FakePopover:
        def __init__(self):
            self.visible, self.popdowns = True, 0

        def get_visible(self):
            return self.visible

        def popdown(self):
            self.popdowns += 1
            self.visible = False

    real = (w._popover, w._alarm_popover, w._context_popover)
    fakes = (FakePopover(), FakePopover(), FakePopover())
    w._popover, w._alarm_popover, w._context_popover = fakes
    w.is_active = lambda: True
    w._chrome_on = True
    w._update_chrome()
    w._schedule_chrome()
    yield 0.5
    R["menus_kept_while_focused"] = all(f.visible and f.popdowns == 0 for f in fakes)
    w.is_active = lambda: False
    w._schedule_chrome()
    yield 0.6
    R["menus_closed_on_focus_loss"] = all(not f.visible and f.popdowns == 1 for f in fakes)
    R["chrome_hidden_on_focus_loss"] = not w._bar.get_visible()
    w._popover, w._alarm_popover, w._context_popover = real
    w.is_active = lambda: True
    w._chrome_on = True
    w._update_chrome()

    # ---- başlığa basış: düzen hemen değişmez; çift tıklama ikinci basışı bozmaz ----
    w.is_active = lambda: True
    w._chrome_on = False
    w._update_chrome()
    hx, hy = bounds_in_view(w.title_label)
    w._on_press(Gest(), 1, hx, hy)
    R["header_press_keeps_layout"] = not w._bar.get_visible() and w._show_id != 0
    yield 0.6
    R["header_press_shows_later"] = w._bar.get_visible()
    w._chrome_on = False
    w._update_chrome()
    w._on_press(Gest(), 1, hx, hy)
    w._on_header_pressed(Gest(), 2, hx, hy, w._header)            # çift tıklama
    R["double_click_collapses"] = w._collapsed and w._show_id == 0
    swallowed = Gest()
    w._on_press(swallowed, 3, hx, hy)                               # üçüncü tıklama
    R["third_click_swallowed"] = swallowed.claimed
    yield 0.9
    w._on_header_pressed(Gest(), 2, hx, hy, w._header)
    R["double_click_expands_again"] = not w._collapsed
    yield 0.9

    # ---- alarm sallanırken ✕ yerinde durur, basış düzeni bozmaz ----
    w.is_active = lambda: True
    w._chrome_on = False
    w.ring()
    yield 0.2
    w._pointer_inside = True
    yield 0.5
    R["shake_pauses_under_pointer"] = not (w._view.has_css_class("shake-a") or w._view.has_css_class("shake-b"))
    close = find_close(w)
    R["close_visible_during_ring"] = close is not None and close.get_mapped()
    cx, cy = bounds_in_view(close)
    w._on_press(Gest(), 1, cx, cy)
    R["close_press_keeps_layout"] = w._header.get_show_end_title_buttons()
    R["ring_stopped_by_press"] = not w._ringing
    w._pointer_inside = False
    w._chrome_on = True
    w._update_chrome()
    yield 0.6

    # ---- küçültme ----
    w.set_collapsed(True)
    R["collapsed_chrome"] = (w._header.get_show_end_title_buttons(), w._new_btn.get_visible(),
                             w._collapse_btn.get_visible(), w._scrolled.get_visible())
    yield 0.6
    w.set_collapsed(False)
    R["expanded_content"] = w._scrolled.get_visible()
    yield 0.4

    # ---- alarm: tekrar, erteleme ----
    w.hour.set_value(23)
    w.minute.set_value(59)
    w.repeat.set_selected(1)
    w._on_alarm_set(None)
    R["alarm_set_repeat"] = store.notes[w.note_id]["alarm_repeat"]
    R["alarm_pill_class"] = w.alarm_btn.has_css_class("alarm-set")
    w.calendar.set_date(GLib.DateTime.new_now_local().add_days(-1))
    w._on_alarm_set(None)
    R["past_rejected"] = w.alarm_msg.get_visible()
    store.update(w.note_id, touch=False, alarm=time.time() - 3, alarm_repeat="daily")
    app._check_alarms()
    note = store.notes[w.note_id]
    R["repeat_advanced"] = note["alarm"] > time.time() + 3600
    R["ringing"] = w._ringing
    R["snooze_btn_visible"] = w._snooze_btn.get_visible()
    yield 0.3
    app.snooze_note(w.note_id)
    note = store.notes[w.note_id]
    R["snoozed"] = note["snooze"] is not None and note["alarm"] is not None
    R["ring_stopped_by_snooze"] = not w._ringing
    alarm_before = note["alarm"]
    store.update(w.note_id, touch=False, snooze=time.time() - 2)
    app._check_alarms()
    note = store.notes[w.note_id]
    R["snooze_fired_keeps_alarm"] = note["snooze"] is None and note["alarm"] == alarm_before
    w.stop_ring()
    store.update(w.note_id, touch=False, alarm=time.time() - 2, alarm_repeat=None)
    app._check_alarms()
    R["one_shot_cleared"] = store.notes[w.note_id]["alarm"] is None
    w.stop_ring()

    # ---- katman ----
    R["layer_supported"] = winpos.supported(w)
    if R["layer_supported"]:
        w._layer_buttons["above"].set_active(True)
        yield 0.5
        R["layer_above"] = any("ABOVE" in s for s in winpos.wm_states(w))
        w._layer_buttons["below"].set_active(True)
        yield 0.5
        states = winpos.wm_states(w)
        R["layer_below"] = any("BELOW" in s for s in states) and not any("ABOVE" in s for s in states)
        R["skip_taskbar"] = any("SKIP_TASKBAR" in s for s in states)
        w._layer_buttons["normal"].set_active(True)

    # ---- konum ----
    if R["layer_supported"]:
        winpos.set_position(w, 431, 217)
        yield 0.6
        R["position"] = winpos.get_position(w)

    # ---- ana pencere: arama, silme/çöp, geri yükleme ----
    other = store.create()
    store.update(other["id"], text="Toplantı İSTANBUL")
    other["open"] = False
    app.show_main()
    main = app.main
    yield 0.6
    main.entry.set_text("istanbul")
    main._rebuild()
    count = 0
    child = main.flow.get_first_child()
    while child:
        count += 1
        child = child.get_next_sibling()
    R["search_matches"] = count
    main.entry.set_text("")
    main._rebuild()

    app.delete_note(other["id"])
    R["in_trash"] = other["id"] in store.trash and other["id"] not in store.notes
    app.show_trash()
    yield 0.6
    dialog = main.get_visible_dialog()
    rows, row = 0, dialog.listbox.get_first_child()
    while row:
        rows += 1
        row = row.get_next_sibling()
    R["trash_dialog_rows"] = rows
    store.trash_restore(other["id"])
    R["restored_from_trash"] = other["id"] in store.notes
    dialog.force_close()
    yield 0.4

    # ---- kilit: dokunulmaz, taşınamaz, kapanamaz, düzenlenemez; hali olduğu gibi kalır ----
    nid = w.note_id
    w.is_active = lambda: True
    text_before, size_before = w._text(), (w.get_width(), w.get_height())
    pos_before = winpos.get_position(w)
    app.set_note_locked(nid, True)
    yield 0.8
    R["lock_saved"] = store.notes[nid].get("locked") is True
    R["lock_not_editable"] = not w.textview.get_editable()
    R["lock_strip_replaces_header"] = w._header.get_parent() is None and w._lock_strip.get_parent() is w._top
    R["lock_not_resizable"] = not w.get_resizable()
    R["lock_size_unchanged"] = (w.get_width(), w.get_height()) == size_before
    R["lock_position_unchanged"] = winpos.get_position(w) == pos_before
    R["lock_menu_label"] = w._lock_section.get_item_attribute_value(0, "label", None).get_string()
    R["lock_disabled_actions"] = all(not w.lookup_action(n).get_enabled()
                                     for n in ("delete", "color", "format", "list", "zoom"))
    R["lock_pin_still_enabled"] = w.lookup_action("pin").get_enabled()
    left, right = Gest(1), Gest(3)
    w._on_press(left, 1, 100, 200)
    w._on_press(right, 1, 100, 200)
    R["lock_left_click_swallowed"] = left.claimed
    R["lock_right_click_passes"] = not right.claimed
    w._on_click_pressed(Gest(), 1, 20, 40)
    R["lock_checkbox_ignored"] = w._text() == text_before
    was_collapsed = w._collapsed
    w.set_collapsed(not was_collapsed)
    R["lock_collapse_blocked"] = w._collapsed == was_collapsed
    R["lock_close_blocked"] = w._on_close() is True and nid in app.note_windows
    app.delete_note(nid)
    R["lock_delete_blocked"] = nid in store.notes
    if R["layer_supported"]:
        blocked = ("MOVE", "RESIZE", "CLOSE", "MAXIMIZE_HORZ", "MAXIMIZE_VERT")
        R["lock_wm_allows_nothing"] = not any(any(b in a for b in blocked) for a in winpos.allowed_actions(w))
    # kilitli notun küçültülmüş hali
    app.set_note_locked(nid, False)
    yield 0.6
    R["unlock_restores"] = (w.textview.get_editable() and w.get_resizable() and w._header.get_parent() is w._top
                            and w._lock_strip.get_parent() is None)
    w.set_collapsed(True)
    yield 0.8
    app.set_note_locked(nid, True)
    yield 0.6
    R["lock_keeps_collapsed"] = w._collapsed and w._locked
    w.set_collapsed(False)
    R["lock_collapsed_cannot_expand"] = w._collapsed
    app.set_note_locked(nid, False)
    yield 0.4
    w.set_collapsed(False)
    yield 0.8
    # kart menüsü: kilitliyse "Unlock note" ve silme yok
    app.set_note_locked(nid, True)
    app.show_main()
    yield 0.4
    app.main._on_card_right_click(None, 1, 5, 5, nid, app.main.flow.get_first_child().get_child())
    menu = app.main._card_popover.get_menu_model()
    labels = [menu.get_item_attribute_value(i, "label", None).get_string() for i in range(menu.get_n_items())]
    R["card_menu_locked_labels"] = labels
    app.set_note_locked(nid, False)

    # ---- arka plan: ana pencere kapanınca gizlenir ----
    app.set_background(True)
    R["main_hidden_on_close"] = app.handle_main_close(main) is True and not main.is_visible()
    R["app_holds"] = app._held
    app.set_background(False)


def run_app():
    import stickynotes  # noqa: F401  (GTK'dan ÖNCE içe aktarılmalı: X11 arka ucunu seçer)
    from gi.repository import GLib, Gio, Gtk
    from stickynotes import winpos
    from stickynotes.app import App

    app = App()
    app.set_flags(Gio.ApplicationFlags.NON_UNIQUE)
    steps = scenario(app, Gtk, winpos, GLib)

    def step():
        try:
            delay = next(steps)
        except StopIteration:
            app.quit_app()
            return False
        except Exception as exc:  # noqa: BLE001 - test altyapısı, hatayı kaydedip çık
            import traceback
            ERROR.append(traceback.format_exc())
            app.quit_app()
            return False
        GLib.timeout_add(int(delay * 1000), step)
        return False

    GLib.timeout_add(500, step)
    app.run([])


@unittest.skipUnless(helpers.has_display(), "ekran yok")
class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if helpers.screen_is_blank():
            raise unittest.SkipTest("Ekran koruyucu/kilit aktif: pencereler yerleşmez, arayüz testleri atlandı")
        helpers.isolate_dirs()
        run_app()
        if ERROR:
            raise AssertionError("Senaryo hata verdi:\n" + ERROR[0])

    def test_pending_format_applies_to_typed_text(self):
        bold = R["pending_bold"]
        self.assertEqual(len(bold), 1)
        text = R["text_after_typing"]
        start, end = bold[0][1], bold[0][2]
        self.assertEqual(text[start:end].strip(), "KALIN")

    def test_check_list_and_big_glyphs(self):
        self.assertEqual(R["check_text"][:2], ["☐ süt", "☐ ekmek KALIN düz"])
        self.assertEqual(R["glyph_tags"], 2)

    def test_checkbox_click_toggles_and_strikes(self):
        self.assertEqual(R["after_click"], "☑ süt")
        self.assertTrue(R["done_tag_after_click"])
        self.assertEqual(R["after_second_click"], "☐ süt")

    def test_enter_continues_and_exits_list(self):
        self.assertTrue(R["enter_continues"])
        self.assertTrue(R["enter_exits_list"])

    def test_font_size_applies_to_selection_only(self):
        tags = R["selection_size_tags"]
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0][0], "size-20")                       # 16 -> 18 -> 20
        self.assertEqual((tags[0][1], tags[0][2]), R["selection_range"])
        self.assertEqual(R["base_font_unchanged"], 16)
        self.assertEqual(R["font_min_tag"], ["size-11"])              # en küçük adımda durur

    def test_color_saved(self):
        self.assertEqual(R["color_saved"], "blue")

    def test_chrome_shows_on_click_and_hides_on_focus_loss(self):
        self.assertEqual(R["chrome_hidden_before_click"], (False, False, False))
        self.assertEqual(R["chrome_after_click"], (True, True, True))
        self.assertEqual(R["chrome_after_focus_loss"], (False, False, False))

    def test_open_menus_close_when_focus_leaves(self):
        self.assertTrue(R["menus_kept_while_focused"])
        self.assertTrue(R["menus_closed_on_focus_loss"])
        self.assertTrue(R["chrome_hidden_on_focus_loss"])

    def test_header_press_does_not_shift_layout_and_multiclick_is_safe(self):
        self.assertTrue(R["header_press_keeps_layout"])
        self.assertTrue(R["header_press_shows_later"])
        self.assertTrue(R["double_click_collapses"])
        self.assertTrue(R["third_click_swallowed"])
        self.assertTrue(R["double_click_expands_again"])

    def test_close_button_stays_put_while_alarm_rings(self):
        self.assertTrue(R["shake_pauses_under_pointer"])
        self.assertTrue(R["close_visible_during_ring"])
        self.assertTrue(R["close_press_keeps_layout"])
        self.assertTrue(R["ring_stopped_by_press"])

    def test_collapse_hides_close_plus_and_collapse_buttons(self):
        self.assertEqual(R["collapsed_chrome"], (False, False, False, False))
        self.assertTrue(R["expanded_content"])

    def test_alarm_repeat_snooze_and_pill(self):
        self.assertEqual(R["alarm_set_repeat"], "daily")
        self.assertTrue(R["alarm_pill_class"])
        self.assertTrue(R["past_rejected"])
        self.assertTrue(R["repeat_advanced"])
        self.assertTrue(R["ringing"])
        self.assertTrue(R["snooze_btn_visible"])
        self.assertTrue(R["snoozed"])
        self.assertTrue(R["ring_stopped_by_snooze"])
        self.assertTrue(R["snooze_fired_keeps_alarm"])
        self.assertTrue(R["one_shot_cleared"])

    def test_layer_position_and_taskbar_when_x11(self):
        if not R["layer_supported"]:
            self.skipTest("X11/XWayland yok")
        self.assertTrue(R["layer_above"])
        self.assertTrue(R["layer_below"])
        self.assertTrue(R["skip_taskbar"])
        self.assertEqual(R["position"], (431, 217))

    def test_locked_note_is_untouchable(self):
        for key in ("lock_saved", "lock_not_editable", "lock_strip_replaces_header", "lock_not_resizable",
                    "lock_size_unchanged", "lock_position_unchanged", "lock_disabled_actions",
                    "lock_pin_still_enabled", "lock_left_click_swallowed", "lock_right_click_passes",
                    "lock_checkbox_ignored", "lock_collapse_blocked", "lock_close_blocked",
                    "lock_delete_blocked"):
            self.assertTrue(R[key], key)
        self.assertEqual(R["lock_menu_label"], "Unlock note")

    def test_locked_note_window_manager_allows_nothing(self):
        if not R["layer_supported"]:
            self.skipTest("X11/XWayland yok")
        self.assertTrue(R["lock_wm_allows_nothing"])

    def test_unlock_restores_and_state_is_kept(self):
        self.assertTrue(R["unlock_restores"])
        self.assertTrue(R["lock_keeps_collapsed"])              # yalnız başlık halinde kilitlenirse öyle kalır
        self.assertTrue(R["lock_collapsed_cannot_expand"])

    def test_card_menu_for_locked_note(self):
        self.assertIn("Unlock note", R["card_menu_locked_labels"])
        self.assertNotIn("Delete", R["card_menu_locked_labels"])

    def test_search_trash_and_restore(self):
        self.assertEqual(R["search_matches"], 1)     # Türkçe İ/ı duyarsız arama
        self.assertTrue(R["in_trash"])
        self.assertEqual(R["trash_dialog_rows"], 1)
        self.assertTrue(R["restored_from_trash"])

    def test_closing_main_window_goes_to_background(self):
        self.assertTrue(R["main_hidden_on_close"])
        self.assertTrue(R["app_holds"])


if __name__ == "__main__":
    unittest.main()
