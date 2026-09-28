import { useEffect, useMemo, useState } from "react";
import { api, type FileText } from "../api";
import { PAGE_KIND, TEXT_SOURCE } from "../labels";

interface Props {
  processId: string;
  fileId: string;
  title: string;
  onClose: () => void;
}

const WINDOW = 25;

/**
 * Что система прочитала в файле. Задача #52.
 *
 * На сканах текст даёт распознавание, и с 18.09 по нему принимаются решения правил
 * Матрицы. Инспектор видел этот текст только обрывком в цитате доказательства, а знать
 * ему нужно другое: прочитан ли документ вообще и чем именно. Поэтому здесь текст
 * страниц целиком, у каждой сказано, чем она прочитана, и сводка по файлу.
 *
 * Текст показывается как есть, без правки: «Жензобетонноя cmena B30» — это и есть то,
 * что прочитала машина, и по нему видно, почему правило не нашло значение.
 */
export default function FileTextPane({ processId, fileId, title, onClose }: Props) {
  const [data, setData] = useState<FileText | null>(null);
  const [from, setFrom] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let alive = true;
    setBusy(true);
    setError(null);
    api
      .fileText(processId, fileId, from, WINDOW)
      .then((got) => alive && setData(got))
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setBusy(false));
    return () => {
      alive = false;
    };
  }, [processId, fileId, from]);

  const pages = useMemo(() => {
    if (!data) return [];
    const needle = query.trim().toLowerCase();
    return needle ? data.pages.filter((p) => p.text.toLowerCase().includes(needle)) : data.pages;
  }, [data, query]);

  const recognized = data ? (data.sources.TESSERACT ?? 0) + (data.sources.UNION ?? 0) + (data.sources.MODEL ?? 0) : 0;
  const unread = data ? (data.sources.NONE ?? 0) : 0;
  const last = data ? Math.min(from + WINDOW - 1, data.total_pages) : from;

  return (
    <>
      <div className="pane-head">
        <h2>Что прочитано: {title}</h2>
        <button type="button" className="link" onClick={onClose}>
          закрыть
        </button>
      </div>
      <div className="card-body">
        {error && (
          <div className="empty-state">
            {error}
            {error.includes("не прочитан") && " Запустите разбор и откройте снова."}
          </div>
        )}
        {data && (
          <>
            <p className="small muted">
              Страниц {data.total_pages}; распознаванием прочитано {recognized}
              {unread ? `, не прочитано ${unread}` : ""}. Текст показан как есть: по нему работают правила Матрицы,
              и по нему видно, почему значение нашлось или не нашлось.
            </p>
            <div className="text-sources">
              {Object.entries(data.sources)
                .sort((a, b) => b[1] - a[1])
                .map(([code, n]) => (
                  <span key={code} className="chip">
                    {TEXT_SOURCE[code] ?? code} <b>{n}</b>
                  </span>
                ))}
            </div>
            <input
              className="text-search"
              type="search"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="искать в тексте этих страниц, например В30"
              aria-label="Искать в прочитанном тексте"
            />

            <div className="page-texts">
              {pages.map((p) => (
                <article key={p.page} className="page-text">
                  <header>
                    <b>Страница {p.page}</b>
                    <span className="mono small">{TEXT_SOURCE[p.text_source ?? "NONE"] ?? p.text_source}</span>
                    {p.kind && <span className="small muted">{PAGE_KIND[p.kind] ?? p.kind}</span>}
                    <span className="small muted">{p.chars} знаков</span>
                  </header>
                  {p.text.trim() ? (
                    <pre>{p.text}</pre>
                  ) : (
                    <div className="small muted">
                      Текста нет: страница не прочитана ни слоем, ни распознаванием. Правила на ней молчат.
                    </div>
                  )}
                </article>
              ))}
              {pages.length === 0 && (
                <div className="empty-state">
                  {query ? "В этом окне страниц с таким текстом нет" : "Страниц нет"}
                </div>
              )}
            </div>

            <div className="text-pager">
              <button type="button" className="link" disabled={busy || from <= 1} onClick={() => setFrom(Math.max(1, from - WINDOW))}>
                ← предыдущие
              </button>
              <span className="small muted">
                страницы {from}–{last} из {data.total_pages}
              </span>
              <button
                type="button"
                className="link"
                disabled={busy || last >= data.total_pages}
                onClick={() => setFrom(from + WINDOW)}
              >
                следующие →
              </button>
            </div>
          </>
        )}
      </div>
    </>
  );
}
