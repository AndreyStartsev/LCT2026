"""Отпечаток кода разбора: кеш стареет вместе с кодом, а не с номером, который надо помнить.

Раньше кеш кандидатов и кеш текста держались на двух числах — `CANDIDATES_VERSION` и
`TEXT_CACHE_VERSION`, — и их поднимали руками. Это ломалось двумя способами. Забыл поднять —
кеш отдаёт разбор прежнего кода. Поднял в двух ветках до одного номера — общий кеш отдаёт
одной ветке кандидатов другой (#99; 24.09 так столкнулись #98 и #112 на номере 23). И каждое
поднятие сбрасывало разбор всего корпуса, хотя правка касалась одного вида правил.

Здесь номер заменён отпечатком: хешем синтаксического дерева кода (без комментариев и
строк документации — их правка разбор не меняет). Отпечаток считается для каждого вида
правила отдельно: ветка `extract` этого вида, функции `matrix_rules`, до которых она
дотягивается, и модули конвейера, которые они зовут, со всеми их импортами. Правка
`elements.py` старит кеш только правил по элементам, правка `fire_doors.py` — только
предела огнестойкости.

Что отпечаток не видит — данные вне кода, которые разбор читает сам. Для этого остаётся
ручная эпоха (`matrix_rules.CANDIDATES_VERSION`): поднимать её нужно, только если разбор
стал зависеть от внешнего файла. Файл прохода модели по чертежам учтён отдельно
(`matrix_rules.vlm_digest`).
"""
import ast
import functools
import hashlib
import os

PIPELINE = os.path.dirname(os.path.abspath(__file__))
# Настройки путей и объектов разбор не меняют: без этого исключения правка перечня объектов
# сбрасывала бы кеш всего корпуса
SKIP_MODULES = {"config"}


def _strip_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
                    and isinstance(body[0].value.value, str):
                node.body = body[1:] or [ast.Pass()]
    return tree


def _dump(node):
    return ast.dump(node, annotate_fields=False, include_attributes=False)


@functools.lru_cache(maxsize=None)
def _parsed(module):
    path = os.path.join(PIPELINE, module + ".py")
    with open(path, encoding="utf-8") as f:
        return _strip_docstrings(ast.parse(f.read()))


def _pipeline_imports(nodes):
    """Модули конвейера, которые импортируют эти узлы: {локальное имя: модуль}."""
    out = {}
    for node in nodes:
        for n in ast.walk(node):
            if isinstance(n, ast.ImportFrom):
                if n.module == "pipeline" or (n.level == 1 and n.module is None):
                    for a in n.names:
                        out[a.asname or a.name] = a.name
                elif n.module and n.module.startswith("pipeline."):
                    out.setdefault("__from__" + n.module, n.module.split(".", 1)[1])
                elif n.level == 1 and n.module:
                    out.setdefault("__from__" + n.module, n.module)
            elif isinstance(n, ast.Import):
                for a in n.names:
                    if a.name.startswith("pipeline."):
                        out[a.asname or a.name.split(".")[-1]] = a.name.split(".", 1)[1]
    return {k: v for k, v in out.items() if os.path.exists(os.path.join(PIPELINE, v + ".py"))}


@functools.lru_cache(maxsize=None)
def module_digest(module):
    """Отпечаток модуля конвейера вместе со всеми модулями конвейера, которые он импортирует."""
    seen, stack, h = set(), [module], hashlib.sha256()
    while stack:
        m = stack.pop()
        if m in seen or m in SKIP_MODULES:
            continue
        seen.add(m)
        tree = _parsed(m)
        stack.extend(_pipeline_imports([tree]).values())
    for m in sorted(seen):
        h.update(m.encode())
        h.update(_dump(_parsed(m)).encode())
    return h.hexdigest()[:16]


def _top_level(tree):
    """Имена верхнего уровня модуля: функции, классы и присваивания."""
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for t in targets:
                for n in ast.walk(t):
                    if isinstance(n, ast.Name):
                        out.setdefault(n.id, node)
    return out


def top_level(module):
    """Имена верхнего уровня модуля конвейера: {имя: узел}."""
    return _top_level(_parsed(module))


def _names(nodes):
    got = set()
    for node in nodes:
        for n in ast.walk(node):
            if isinstance(n, ast.Name):
                got.add(n.id)
    return got


def closure_digest(module, nodes, skip=()):
    """Отпечаток узлов модуля вместе со всем, до чего они дотягиваются.

    Имена верхнего уровня того же модуля разворачиваются рекурсивно; модули конвейера —
    целиком, с их импортами (`module_digest`). Имена из `skip` не разворачиваются: функция
    разбора зовётся из `_extract_document`, и без этого в отпечаток каждого вида попали бы
    ветки всех видов разом.
    """
    tree = _parsed(module)
    top = _top_level(tree)
    imported = _pipeline_imports([tree])
    seen_nodes, modules, stack = [], set(), list(nodes)
    seen_ids = set()
    while stack:
        node = stack.pop()
        if id(node) in seen_ids:
            continue
        seen_ids.add(id(node))
        seen_nodes.append(node)
        modules.update(_pipeline_imports([node]).values())
        for name in _names([node]):
            if name in imported:
                modules.add(imported[name])
            elif name in top and name not in skip:
                stack.append(top[name])
    h = hashlib.sha256()
    for text in sorted(_dump(n) for n in seen_nodes):
        h.update(text.encode())
    for m in sorted(modules - SKIP_MODULES):
        h.update(m.encode())
        h.update(module_digest(m).encode())
    return h.hexdigest()[:16]


def _kind_test(test, constants):
    """Виды правила, которые проверяет условие ветки, или None — условие не о виде."""
    def is_kind(expr):
        # rule.get("kind") или rule["kind"]
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute) and expr.func.attr == "get" \
                and expr.args and isinstance(expr.args[0], ast.Constant) and expr.args[0].value == "kind":
            return True
        return isinstance(expr, ast.Subscript) and isinstance(expr.slice, ast.Constant) \
            and expr.slice.value == "kind"

    if not (isinstance(test, ast.Compare) and len(test.ops) == 1 and is_kind(test.left)):
        return None
    op, right = test.ops[0], test.comparators[0]
    if isinstance(op, ast.Eq) and isinstance(right, ast.Constant) and isinstance(right.value, str):
        return {right.value}
    if isinstance(op, ast.In):
        if isinstance(right, (ast.Tuple, ast.List, ast.Set)) and \
                all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in right.elts):
            return {e.value for e in right.elts}
        if isinstance(right, ast.Name) and isinstance(constants.get(right.id), (set, frozenset, tuple, list)):
            return set(constants[right.id])
    return None


def kind_digests(module, entry, common_entries=(), constants=None):
    """Отпечаток кода разбора по видам правил: {вид: отпечаток, "*": для вида без своей ветки}.

    `entry` — функция разбора (`extract`): её тело — цепочка веток «если вид такой-то».
    Всё, что не ветка вида (начало функции, общий хвост), входит в отпечаток каждого вида.
    `common_entries` — функции, через которые проходит разбор любого вида (`_extract_document`).
    `constants` — значения констант модуля, если ветка проверяет вид по множеству (`ROOM_KINDS`).
    """
    tree = _parsed(module)
    top = _top_level(tree)
    fn = top[entry]
    common, branches = [], {}

    def walk(stmts):
        for stmt in stmts:
            kinds = _kind_test(stmt.test, constants or {}) if isinstance(stmt, ast.If) else None
            if kinds is None:
                common.append(stmt)
                continue
            for k in kinds:
                branches.setdefault(k, []).extend(stmt.body)
            walk(stmt.orelse)

    walk(fn.body)
    base = [top[name] for name in common_entries if name in top]
    # сигнатура функции разбора — тоже код разбора: значение по умолчанию меняет вызовы
    head = fn.args
    skip = {entry}
    out = {"*": closure_digest(module, base + common + [head], skip)}
    for kind, body in branches.items():
        out[kind] = closure_digest(module, base + common + [head] + body, skip)
    return out
