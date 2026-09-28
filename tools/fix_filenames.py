"""Восстановление имён файлов, приехавших в кодировке cp866.

Корпус приходит с именами, записанными в cp866 и прочитанными как cp1251 или
cp1252: они выглядят мусором. Скрипт подбирает исходную кодировку по каждому
имени и переименовывает. Карта отката пишется рядом.

Трогаются только имена с явными признаками порчи: чистая кириллица и латиница
не затрагиваются. Это важно, потому что попытка «улучшить» уже правильное имя
однажды превратила «18_Октябрьская_103» в нечитаемое.

  python tools/fix_filenames.py --root data/17_Изумрудная_12
  python tools/fix_filenames.py --root data/17_Изумрудная_12 --apply
"""
import argparse, os, sys, json, unicodedata

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
SKIP_EXT = {'.crdownload'}

GOOD = set("абвгдежзийклмнопрстуфхцчшщъыьэюяАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ"
           "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
           "0123456789 .,-_()[]№#+&'@!%=~;")
# chars that betray a mis-decoded cp866 string
BAD = set("ЂЃЄЅІЇЈЉЊЋЏђѓєѕіїјљњћџ‚„…†‡€‰‹‘’“”•–—™›¤¦§¨©ª«¬­®¯°±²³´µ¶·¸¹º»¼½¾¿×÷ƒˆ˜"
          "ŠŒŽšœžŸ¡¢£¥¨ª¯²³µ¶¹ºÀÁÂÃÄÅÆÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞßàáâãäåæçèéêëìíîïðñòóôõöøùúûüýþÿ"
          " ­")

LOWER = set("абвгдежзийклмнопрстуфхцчшщъыьэюя")
UPPER = set("АБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")

def score(s):
    g = sum(1 for c in s if c in GOOD)
    b = sum(1 for c in s if c in BAD)
    # a capital wedged between two lowercase letters means the codepage guess is wrong
    wedged = sum(1 for i in range(1, len(s)-1)
                 if s[i] in UPPER and s[i-1] in LOWER and s[i+1] in LOWER)
    return g - 2*b - 4*wedged

CYR = set("абвгдежзийклмнопрстуфхцчшщъыьэюяАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ")

def looks_mangled(s):
    # a name is a candidate only if it carries the tell-tale characters of a
    # mis-decoded cp866 string. Clean Cyrillic or ASCII names are left alone.
    return any(c in BAD for c in s)

def candidates(name):
    # macOS stores names in NFD; compose first or cp1251 encoding fails on combining marks
    nfc = unicodedata.normalize('NFC', name)
    yield nfc
    if not looks_mangled(nfc) or '\ufffd' in nfc:
        return
    for src in ('cp1251', 'cp1252', 'mac_cyrillic', 'cp1250', 'cp1257', 'cp932', 'latin-1'):
        try:
            yield unicodedata.normalize('NFC', nfc.encode(src).decode('cp866'))
        except Exception:
            pass

def best(name):
    return max(candidates(name), key=score)

def plan(root=ROOT):
    """deepest-first list of (old_abs, new_abs)"""
    items = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for n in filenames + dirnames:
            if n == '.DS_Store':
                continue
            if os.path.splitext(n)[1].lower() in SKIP_EXT:
                continue
            nb = best(n)
            if nb != n and score(nb) > score(n):
                items.append((os.path.join(dirpath, n), os.path.join(dirpath, nb)))
    return items

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=ROOT, help='каталог, который чиним')
    ap.add_argument('--apply', action='store_true', help='без него только показать план')
    ap.add_argument('--map', default='rename_map.json', help='куда писать карту отката')
    args = ap.parse_args()
    apply = args.apply
    items = plan(args.root)
    mapping, collisions, done = [], [], 0
    seen = {}
    for old, new in items:
        if os.path.exists(new) and os.path.normcase(old) != os.path.normcase(new):
            stem, ext = os.path.splitext(new)
            i = 2
            while os.path.exists(f"{stem} ({i}){ext}"):
                i += 1
            new = f"{stem} ({i}){ext}"
            collisions.append((old, new))
        mapping.append({"old": old, "new": new})
        if apply:
            os.rename(old, new); done += 1
    print(f"планируется переименований: {len(items)}   коллизий: {len(collisions)}")
    if apply:
        print(f"выполнено: {done}")
        with open(args.map, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=1)
        print(f"карта отката: {args.map}")
    else:
        for m in mapping[:25]:
            print("  ", os.path.basename(m['old'])[:52], "->", os.path.basename(m['new'])[:52])
        print("   ...")
        for m in mapping[-10:]:
            print("  ", os.path.basename(m['old'])[:52], "->", os.path.basename(m['new'])[:52])
        if collisions:
            print("\nКОЛЛИЗИИ (получат суффикс):")
            for o, n in collisions[:10]:
                print("  ", os.path.basename(o)[:45], "->", os.path.basename(n)[:45])
