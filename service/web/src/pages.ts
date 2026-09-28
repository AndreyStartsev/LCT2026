// Картинки страниц-доказательств. Запрос идёт с токеном, поэтому <img src> не годится:
// картинка забирается fetch и отдаётся элементам как object URL вместе с размером.
import { useEffect, useState } from "react";
import { authHeader, pageUrl } from "./api";

export interface LoadedPage {
  src: string;
  w: number;
  h: number;
}

const cache = new Map<string, Promise<LoadedPage | null>>();
const MAX_CACHED = 60;

async function fetchPage(url: string): Promise<LoadedPage | null> {
  const response = await fetch(url, { headers: authHeader() });
  if (!response.ok) return null;
  const blob = await response.blob();
  const bitmap = await createImageBitmap(blob);
  const page = { src: URL.createObjectURL(blob), w: bitmap.width, h: bitmap.height };
  bitmap.close();
  return page;
}

function load(url: string): Promise<LoadedPage | null> {
  const hit = cache.get(url);
  if (hit) return hit;
  const promise = fetchPage(url)
    .catch(() => null)
    .then((page) => {
      // неудача не запоминается: страница может появиться после пересборки протокола
      if (!page) cache.delete(url);
      return page;
    });
  cache.set(url, promise);
  if (cache.size > MAX_CACHED) {
    const [oldest] = cache.keys();
    cache.get(oldest)?.then((page) => page && URL.revokeObjectURL(page.src));
    cache.delete(oldest);
  }
  return promise;
}

export type PageImage = { state: "loading" } | { state: "missing" } | ({ state: "ready" } & LoadedPage);

export function usePageImage(processId: string, fileId: string | undefined, page: number | undefined): PageImage {
  const [image, setImage] = useState<PageImage>({ state: "loading" });
  useEffect(() => {
    if (!fileId || !page) {
      setImage({ state: "missing" });
      return;
    }
    let alive = true;
    setImage({ state: "loading" });
    load(pageUrl(processId, fileId, page)).then((loaded) => {
      if (alive) setImage(loaded ? { state: "ready", ...loaded } : { state: "missing" });
    });
    return () => {
      alive = false;
    };
  }, [processId, fileId, page]);
  return image;
}
