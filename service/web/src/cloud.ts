// Облако изменений из макета docs/design/inspector-screen.html.
// На чертеже изменённую зону обводят облаком из дуг; здесь оно заменяет цветную подсветку.

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

export function revisionCloud(x: number, y: number, w: number, h: number, r: number): string {
  const pts: [number, number][] = [];
  const push = (x1: number, y1: number, x2: number, y2: number) => {
    const len = Math.hypot(x2 - x1, y2 - y1);
    const n = Math.max(2, Math.round(len / (r * 1.45)));
    for (let i = 0; i < n; i++) {
      pts.push([x1 + ((x2 - x1) * i) / n, y1 + ((y2 - y1) * i) / n]);
    }
  };
  push(x, y, x + w, y);
  push(x + w, y, x + w, y + h);
  push(x + w, y + h, x, y + h);
  push(x, y + h, x, y);
  let d = `M ${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`;
  for (let i = 1; i <= pts.length; i++) {
    const p = pts[i % pts.length];
    d += ` A ${r.toFixed(1)} ${r.toFixed(1)} 0 0 1 ${p[0].toFixed(1)} ${p[1].toFixed(1)}`;
  }
  return d;
}

function union(a: Box, b: Box): Box {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  return { x, y, w: Math.max(a.x + a.w, b.x + b.w) - x, h: Math.max(a.y + a.h, b.y + b.h) - y };
}

function overlaps(a: Box, b: Box): boolean {
  return a.x <= b.x + b.w && b.x <= a.x + a.w && a.y <= b.y + b.h && b.y <= a.y + a.h;
}

/**
 * Зоны облаков в пикселях картинки w × h по прямоугольникам места в долях страницы.
 * Прямоугольники с полями, которые касаются друг друга, сливаются в одну зону:
 * строки ведомости, из которых сложено значение, обводятся одним облаком, как на чертеже.
 */
export function zonesFor(highlights: number[][], w: number, h: number): Box[] {
  const pad = Math.max(w, h) * 0.007;
  const zones = highlights.map(([x0, y0, x1, y1]) => {
    const x = Math.max(0, x0 * w - pad);
    const y = Math.max(0, y0 * h - pad);
    return { x, y, w: Math.min(w, x1 * w + pad) - x, h: Math.min(h, y1 * h + pad) - y };
  });
  // после слияния зона растёт и может задеть уже проверенные, поэтому проход повторяется
  let merged = true;
  while (merged) {
    merged = false;
    for (let i = 0; i < zones.length && !merged; i++) {
      for (let j = i + 1; j < zones.length && !merged; j++) {
        if (overlaps(zones[i], zones[j])) {
          zones[i] = union(zones[i], zones[j]);
          zones.splice(j, 1);
          merged = true;
        }
      }
    }
  }
  return zones;
}

export function cloudPath(zone: Box, w: number, h: number): string {
  const r = Math.max(Math.max(w, h) * 0.006, Math.min(zone.w, zone.h) / 3.2);
  return revisionCloud(zone.x, zone.y, zone.w, zone.h, r);
}

/**
 * Фрагмент страницы вокруг облаков с полями для контекста, в пропорции aspect.
 * Карточка показывает фрагмент, а не весь лист: на уменьшенном листе А1 облако
 * и цифры в нём не читаются. Null — облаков нет или фрагмент не меньше листа.
 */
export function fragmentOf(zones: Box[], w: number, h: number, aspect = 1.5): Box | null {
  if (zones.length === 0) return null;
  const u = zones.reduce(union);
  const long = Math.max(w, h);
  const margin = Math.max(u.w, u.h) * 0.5 + long * 0.03;
  let fw = Math.max(u.w + 2 * margin, long * 0.24);
  let fh = Math.max(u.h + 2 * margin, fw / aspect);
  fw = Math.max(fw, fh * aspect);
  if (fw >= w * 0.9 && fh >= h * 0.9) return null;
  fw = Math.min(fw, w);
  fh = Math.min(fh, h);
  const x = Math.min(Math.max(u.x + u.w / 2 - fw / 2, 0), w - fw);
  const y = Math.min(Math.max(u.y + u.h / 2 - fh / 2, 0), h - fh);
  return { x, y, w: fw, h: fh };
}
