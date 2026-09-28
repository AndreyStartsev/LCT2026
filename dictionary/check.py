#!/usr/bin/env python3
"""Проверка словаря по корпусу. Задача #5.

Отвечает на два вопроса:

  сколько записей словаря реально встречаются в документах — мёртвые записи
  видно сразу, и их надо либо чинить, либо убирать;

  какие частые предметные слова корпуса словарь НЕ покрывает — это очередь
  на пополнение, и она важнее первой половины.

  python dictionary/check.py --object OBJ-TYUMENSKAYA-5-GOLD-SEED
  python dictionary/check.py --object ... --gaps 30
"""
import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import match  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TERMS = os.path.join(ROOT, "dictionary", "terms.jsonl")

# Термины, вокруг которых крутятся эталонные нарушения. Если словарь их не ловит,
# он бесполезен независимо от общего размера.
MUST_COVER = ["приточная установка", "вытяжная вентиляция", "тёплый пол", "венткамера"]

STOP = set("""и в во не что он на я с со как а то все она так его но да ты к у же вы за бы
по только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если уже
или ни быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей может они тут
где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет
ж тогда кто этот того потому этого какой совсем ним здесь этом один почти мой тем чтобы нее
сейчас были куда зачем всех никогда можно при наконец два об другой хоть после над больше
том через эти нас про всего них какая много разве три эту моя впрочем хорошо свою этой
перед иногда лучше чуть том нельзя такой им более всегда конечно всю между
лист листов изм кол дата подпись формат стадия проверил разраб согласовано инв подл
наименование примечание таблица рисунок страница раздел том пункт номер шифр""".split())

WORD = re.compile(r"[а-яё]{5,}", re.I)


def load_terms():
    return [json.loads(l) for l in open(TERMS, encoding="utf-8") if l.strip()]


def load_pages(object_id):
    p = os.path.join(ROOT, "build", object_id, "pages.jsonl")
    if not os.path.exists(p):
        sys.exit(f"нет индекса: {p}")
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--object", required=True)
    ap.add_argument("--gaps", type=int, default=20, help="сколько непокрытых слов показать")
    args = ap.parse_args()

    terms = load_terms()
    pages = load_pages(args.object)
    texts = [p.get("text") or "" for p in pages]
    # основы страницы считаются один раз: их переиспользуют все термины
    page_stems = [match.index_page(t) for t in texts]

    hits, dead = {}, []
    for t in terms:
        n = sum(1 for ps, tx in zip(page_stems, texts)
                if match.term_matches(t, ps, tx))
        hits[t["term_id"]] = n
        if n == 0:
            dead.append(t)

    alive = len(terms) - len(dead)
    print(f"страниц в индексе: {len(pages)}")
    print(f"записей словаря: {len(terms)}, встречается в корпусе: {alive} "
          f"({alive/len(terms):.0%})")

    print("\nтермины эталонных нарушений:")
    for m in MUST_COVER:
        found = [t for t in terms
                 if any(match.fold(m) == match.fold(v) for v in t["variants"])]
        pages_with = sum(1 for ps in page_stems if match.variant_matches(m, ps))
        mark = "OK " if found else "НЕТ"
        print(f"  {mark} {m:24} в словаре: {found[0]['term_id'] if found else '—':22}"
              f" на страницах: {pages_with}")

    if dead:
        print(f"\nне встретились в этом объекте ({len(dead)}), первые 10:")
        for t in dead[:10]:
            print(f"   {t['kind']:18} {t['canonical'][:52]}")

    # чего словарь не покрывает
    covered = set()
    for t in terms:
        for v in t["variants"]:
            covered.update(match.stems(v))
    stop_stems = {match.stem(w) for w in STOP}
    freq = collections.Counter()
    for ps in page_stems:                    # по страницам, а не по вхождениям
        for s_ in ps:
            if len(s_) >= 5 and s_ not in stop_stems and s_ not in covered:
                freq[s_] += 1
    print(f"\nчастые слова, которых нет в словаре (топ {args.gaps}):")
    for w, n in freq.most_common(args.gaps):
        print(f"   {w:28} на {n} страницах")


if __name__ == "__main__":
    main()
