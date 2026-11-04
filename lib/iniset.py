#!/usr/bin/env python3
"""Modifie des clés dans un fichier .ini/.conf en préservant commentaires et ordre.

Usage : iniset.py [--sep " = "] FICHIER SECTION CLE VALEUR [CLE VALEUR ...]
  - SECTION vide ("") = clés avant la première section.
  - Une clé existante (active) est remplacée ; sinon on l'insère après sa
    version commentée (#CLE=…) si elle existe, sinon en fin de section.
"""
import os
import re
import sys
import tempfile


def main(argv):
    sep = " = "
    if len(argv) > 1 and argv[0] == "--sep":
        sep = argv[1]
        argv = argv[2:]
    if len(argv) < 4 or (len(argv) - 2) % 2:
        sys.exit(__doc__)
    path, section = argv[0], argv[1]
    pairs = list(zip(argv[2::2], argv[3::2]))

    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8", errors="surrogateescape") as f:
            lines = f.read().splitlines()

    for key, value in pairs:
        lines = set_key(lines, section, key, value, sep)

    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".iniset-")
    with os.fdopen(fd, "w", encoding="utf-8", errors="surrogateescape") as f:
        f.write("\n".join(lines).rstrip("\n") + "\n")
    if os.path.exists(path):
        st = os.stat(path)
        os.chmod(tmp, st.st_mode & 0o7777)
        try:
            os.chown(tmp, st.st_uid, st.st_gid)
        except PermissionError:
            pass
    os.replace(tmp, path)


SECTION_RE = re.compile(r"^\s*\[(.*)\]\s*$")


def section_bounds(lines, section):
    """Retourne (début, fin) des lignes de la section (début = 1re ligne après l'en-tête)."""
    if section == "":
        end = next((i for i, l in enumerate(lines) if SECTION_RE.match(l)), len(lines))
        return 0, end
    start = None
    for i, line in enumerate(lines):
        m = SECTION_RE.match(line)
        if m and start is None and m.group(1).strip() == section:
            start = i + 1
        elif m and start is not None:
            return start, i
    if start is None:
        return None
    return start, len(lines)


def set_key(lines, section, key, value, sep):
    new_line = f"{key}{sep}{value}"
    bounds = section_bounds(lines, section)
    if bounds is None:
        while lines and not lines[-1].strip():
            lines.pop()
        if lines:
            lines.append("")
        lines += [f"[{section}]", new_line]
        return lines
    start, end = bounds
    key_re = re.compile(r"^\s*" + re.escape(key) + r"\s*=")
    commented_re = re.compile(r"^\s*[#;]\s*" + re.escape(key) + r"\s*=")
    for i in range(start, end):
        if key_re.match(lines[i]):
            lines[i] = new_line
            return lines
    for i in range(start, end):
        if commented_re.match(lines[i]):
            lines.insert(i + 1, new_line)
            return lines
    insert_at = end
    while insert_at > start and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines.insert(insert_at, new_line)
    return lines


if __name__ == "__main__":
    main(sys.argv[1:])
