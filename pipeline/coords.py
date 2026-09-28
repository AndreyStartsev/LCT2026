"""Модуль работы с системами координат прямоугольников. Задача #35.

В конвейере «Инспектор ИИ» и данных организатора используются три системы координат:

1. Внутренняя система конвейера (`INTERNAL`):
   - Область: видимая страница после учёта поворота (`page.rect`).
   - Диапазон: [0.0, 1.0] x [0.0, 1.0].
   - Начало: левый верхний угол (0, 0).
   - Ось X: слева направо (0 -> 1).
   - Ось Y: сверху вниз (0 -> 1), как в PyMuPDF, браузерах и экранной вёрстке.
   - Поле: `bbox` или `bbox_norm`.

2. Внешняя система ТЗ и формата сдачи (`TZ_SUBMISSION`):
   - Стандарт: ТЗ, раздел 9.1, пункт 4 (координаты относительно видимой области
     страницы после учёта CropBox, MediaBox и Rotate).
   - Область: видимая страница после учёта поворота (`page.rect`).
   - Диапазон: [0.0, 1.0] x [0.0, 1.0].
   - Начало: левый нижний угол (0, 0).
   - Ось X: слева направо (0 -> 1).
   - Ось Y: снизу вверх (0 -> 1), классическая геометрия PDF.
   - Связь с внутренней системой: x_tz = x_int, y_tz = 1.0 - y_int.
   - Поле: `bbox_tz` (внутреннее) / `bbox` (в JSON сдачи).

3. Система разметки организатора (`ORGANIZER`):
   - Специфика: неповёрнутое пространство MediaBox с осью Y снизу, делённое
     на размеры повёрнутой страницы (`vis.width`, `vis.height`).
   - На неповёрнутых листах (0°) совпадает с системой ТЗ.
   - На повёрнутых листах (90°, 270°) координаты делятся на переставленные
     габариты (W <-> H) и выходят за пределы листа [0.0, 1.0].
   - Является артефактом инструмента разметки организатора, а не соглашением.
"""
from typing import List, Optional, Tuple, Union


# Пункт PDF — 1/72 дюйма. Размеры листа в пунктах приходят со страницей (width_pt,
# height_pt), а расстояния разбора задаются в миллиметрах листа: доля листа зависит
# от формата, и подобранное на А3 «рядом» на А1 растягивается вдвое (#41).
PT_PER_MM = 72 / 25.4


def page_mm(page_size):
    """Размер листа в миллиметрах или None, если он неизвестен."""
    if not page_size:
        return None
    width_pt, height_pt = page_size
    if not width_pt or not height_pt:
        return None
    return width_pt / PT_PER_MM, height_pt / PT_PER_MM


def clamp_bbox(bbox: List[float], min_val: float = 0.0, max_val: float = 1.0) -> List[float]:
    """Ограничить координаты прямоугольника допустимым диапазоном [min_val, max_val]."""
    x0, y0, x1, y1 = bbox
    cx0 = max(min_val, min(max_val, x0))
    cy0 = max(min_val, min(max_val, y0))
    cx1 = max(min_val, min(max_val, x1))
    cy1 = max(min_val, min(max_val, y1))
    return [min(cx0, cx1), min(cy0, cy1), max(cx0, cx1), max(cy0, cy1)]


def internal_to_tz(bbox: List[float], round_digits: int = 5) -> List[float]:
    """Перевод прямоугольника из внутренней системы (Y сверху) в систему ТЗ (Y снизу).

    Формула: [x0, 1 - y1, x1, 1 - y0].
    """
    x0, y0, x1, y1 = bbox
    res = [float(x0), 1.0 - float(y1), float(x1), 1.0 - float(y0)]
    return [round(v, round_digits) for v in res]


def tz_to_internal(bbox: List[float], round_digits: int = 5) -> List[float]:
    """Перевод прямоугольника из системы ТЗ (Y снизу) во внутреннюю систему (Y сверху).

    Операция обращения оси Y инволютивна: [x0, 1 - y1, x1, 1 - y0].
    """
    return internal_to_tz(bbox, round_digits=round_digits)


def organizer_to_internal(bbox_norm: List[float], page, round_digits: int = 5) -> List[float]:
    """Перевод разметки организатора во внутреннюю систему видимой страницы.

    Использует page.rotation_matrix и page.mediabox без условных ветвлений по углу.
    """
    import pymupdf

    ox0, oy0, ox1, oy1 = bbox_norm
    mb = page.mediabox
    vis = page.rect
    w_vis, h_vis = vis.width or 1.0, vis.height or 1.0

    # Восстанавливаем координаты исходного пространства PDF (MediaBox, Y сверху для Rect PyMuPDF)
    x0_raw = ox0 * w_vis
    x1_raw = ox1 * w_vis
    y1_raw = mb.height - oy0 * h_vis
    y0_raw = mb.height - oy1 * h_vis

    r_raw = pymupdf.Rect(x0_raw, min(y0_raw, y1_raw), x1_raw, max(y0_raw, y1_raw))

    # Перевод в координаты видимой страницы через матрицу поворота
    r_vis = r_raw * page.rotation_matrix if page.rotation else r_raw

    res = [
        r_vis.x0 / w_vis,
        r_vis.y0 / h_vis,
        r_vis.x1 / w_vis,
        r_vis.y1 / h_vis,
    ]
    return [round(v, round_digits) for v in res]


def internal_to_organizer(bbox: List[float], page, round_digits: int = 5) -> List[float]:
    """Перевод прямоугольника из внутренней системы в формат разметки организатора.

    Использует обратную матрицу поворота ~page.rotation_matrix.
    """
    import pymupdf

    vx0, vy0, vx1, vy1 = bbox
    mb = page.mediabox
    vis = page.rect
    w_vis, h_vis = vis.width or 1.0, vis.height or 1.0

    r_vis = pymupdf.Rect(vx0 * w_vis, vy0 * h_vis, vx1 * w_vis, vy1 * h_vis)

    # Обратное преобразование в неповёрнутое пространство PDF
    r_raw = r_vis * (~page.rotation_matrix) if page.rotation else r_vis

    res = [
        r_raw.x0 / w_vis,
        (mb.height - r_raw.y1) / h_vis,
        r_raw.x1 / w_vis,
        (mb.height - r_raw.y0) / h_vis,
    ]
    return [round(v, round_digits) for v in res]


def iou(box_a: List[float], box_b: List[float]) -> float:
    """Вычисление Intersection over Union (IoU) для двух прямоугольников [x0, y0, x1, y1]."""
    ax0, ay0, ax1, ay1 = box_a
    bx0, by0, bx1, by1 = box_b

    inter_x0 = max(ax0, bx0)
    inter_y0 = max(ay0, by0)
    inter_x1 = min(ax1, bx1)
    inter_y1 = min(ay1, by1)

    inter_w = max(0.0, inter_x1 - inter_x0)
    inter_h = max(0.0, inter_y1 - inter_y0)
    inter_area = inter_w * inter_h

    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)

    union_area = area_a + area_b - inter_area
    if union_area <= 0.0:
        return 0.0
    return inter_area / union_area
