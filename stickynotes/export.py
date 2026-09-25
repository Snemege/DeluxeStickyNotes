"""Notları Markdown (.md) metnine çevirir."""
import os
import re

from .i18n import _

MARKERS = {"bold": "**", "italic": "*", "strikethrough": "~~"}


def note_title(note):
    text = note.get("text", "").strip().lstrip("•☐☑ ")
    return (text.split("\n", 1)[0].strip() if text else "") or _("Untitled note")


LIST_MD = {"• ": "- ", "☐ ": "- [ ] ", "☑ ": "- [x] "}


def note_to_markdown(note):
    """Kesişen biçim aralıkları bile geçerli Markdown olsun diye metin, aynı biçime sahip
    parçalara ayrılır ve her parça kendi içinde doğru iç içe sarılır."""
    text = note.get("text", "")
    styles = [set() for _ in text]
    for name, start, end in note.get("tags", []):
        if name in MARKERS:
            for i in range(max(0, start), min(end, len(text))):
                styles[i].add(name)

    out, pos = [], 0
    for line in text.split("\n"):
        line_start = pos
        pos += len(line) + 1
        prefix = LIST_MD.get(line[:2], "")
        body_start = line_start + (2 if prefix else 0)   # madde işareti biçimlenmez

        runs = []                                        # [metin, biçim kümesi]
        for i in range(body_start, line_start + len(line)):
            style = frozenset(styles[i])
            if runs and runs[-1][1] == style:
                runs[-1][0] += text[i]
            else:
                runs.append([text[i], style])

        rendered = ""
        for chunk, style in runs:
            core = chunk.strip(" ")
            if not style or not core:                    # "** metin **" geçersizdir; boşluklar dışarıda kalır
                rendered += chunk
                continue
            lead = chunk[:len(chunk) - len(chunk.lstrip(" "))]
            trail = chunk[len(chunk.rstrip(" ")):]
            wrapped = core
            for name in ("italic", "strikethrough", "bold"):   # içten dışa; kalın en dışta
                if name in style:
                    wrapped = MARKERS[name] + wrapped + MARKERS[name]
            rendered += lead + wrapped + trail
        out.append(prefix + rendered)
    return "\n".join(out).rstrip() + "\n"


def safe_filename(title, used):
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", title).strip(" .")[:60] or "not"
    candidate, n = name, 2
    while candidate.lower() in used:
        candidate = f"{name} ({n})"
        n += 1
    used.add(candidate.lower())
    return candidate + ".md"


def export_all(notes, folder):
    """Notları klasöre .md dosyaları olarak yazar; yazılan dosya sayısını döndürür."""
    os.makedirs(folder, exist_ok=True)
    used = set(n.lower()[:-3] for n in os.listdir(folder) if n.lower().endswith(".md"))
    for note in notes:
        filename = safe_filename(note_title(note), used)
        with open(os.path.join(folder, filename), "w", encoding="utf-8") as f:
            f.write(note_to_markdown(note))
    return len(notes)
