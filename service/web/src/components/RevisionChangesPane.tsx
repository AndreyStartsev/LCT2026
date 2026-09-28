import { useEffect, useMemo, useState } from "react";
import { api, openInTab, sourceUrl, type Evidence, type FileChanges, type RevisionPage, type RevisionPairHead } from "../api";
import { LAYOUT_NOTE, PAGE_CHANGE, REGISTRATION } from "../labels";
import Tip from "./Tip";

/** Сравнение двух редакций одного листа во весь экран: что показать в `CompareViewer`. */
export interface RevisionCompare {
  title: string;
  note: string | null;
  labels: { pd: string; rd: string };
  left: Evidence[];
  right: Evidence[];
}

const revisionName = (revision: string | null, fallback: string) => revision || fallback;

/** Номер листа: «30 → 32», если в прежней редакции у листа был другой номер. */
function sheetsOf(page: Pick<RevisionPage, "sheet" | "old_sheet" | "old_page" | "new_page">): string {
  const old = page.old_sheet;
  return old != null && page.sheet != null && old !== page.sheet && page.old_page != null && page.new_page != null
    ? `${old} → ${page.sheet}`
    : String(page.sheet ?? old ?? "—");
}

/** Как лист сравнен по месту — если описание изменения этого ещё не сказало: у текста,
 * сдвинувшегося между страницами, сдвиг листа — часть того же перетекания. */
const layoutNote = (place: RevisionPage["place"]) =>
  place && !place.flowed_out && !place.flowed_in ? (LAYOUT_NOTE[place.layout] ?? null) : null;

/** Строка «что изменилось и отмечено ли» — под заголовком сравнения и в карточке находки. */
export function changeNote(page: Pick<RevisionPage, "what" | "registration" | "place">): string | null {
  const parts = [page.what];
  const layout = layoutNote(page.place);
  if (layout) parts.push(layout);
  const reg = page.registration ? REGISTRATION[page.registration.status] : null;
  if (reg && page.registration?.status !== "NOT_NEEDED") parts.push(`отметка: ${reg.label}`);
  return parts.filter(Boolean).join(" · ") || null;
}

/**
 * Страницы пары как доказательства: `CompareViewer` и `PageCard` рисуют их так же, как страницы
 * находки, а рамки мест изменений — теми же облаками (доли видимой страницы, Y сверху).
 */
export function comparePages(pair: RevisionPairHead, page: RevisionPage): RevisionCompare {
  const stage = pair.stage_group === "RD" ? "RD" : "PD";
  const side = (
    fileId: string,
    pageNo: number | null,
    zones: number[][] | undefined,
    revision: string | null,
    sheet: number | null,
  ): Evidence[] =>
    pageNo == null
      ? []
      : [
          {
            stage,
            file_id: fileId,
            pdf_page_number: pageNo,
            revision,
            document_sheet_number: sheet,
            highlights: zones ?? [],
            highlight_source: zones?.length ? "REVISION" : null,
            localization: zones?.length ? "BBOX" : "PAGE_LEVEL",
          },
        ];
  const oldName = revisionName(pair.old_revision, "прежняя редакция");
  const newName = revisionName(pair.new_revision, "новая редакция");
  // у прежней редакции свой номер листа: в записке страницы сдвигаются, лист 30 становится листом 32
  const oldSheet = page.old_sheet !== undefined ? page.old_sheet : page.sheet;
  return {
    title: `${pair.mark ? `${pair.mark}, ` : ""}${page.sheet != null ? `лист ${sheetsOf(page)}` : `стр. ${page.new_page ?? page.old_page}`}: ${oldName} → ${newName}`,
    note: changeNote(page),
    labels: { pd: oldName, rd: newName },
    left: side(pair.old_file_id, page.old_page, page.place?.zones_old, pair.old_revision, oldSheet ?? null),
    right: side(pair.new_file_id, page.new_page, page.place?.zones_new, pair.new_revision, page.sheet),
  };
}

type Filter = "all" | "content" | "unmarked" | "service";

interface Props {
  processId: string;
  fileId: string;
  title: string;
  onClose: () => void;
  onCompare: (compare: RevisionCompare) => void;
  onError: (message: string) => void;
}

/**
 * Что изменилось в этой редакции относительно предыдущей. Задача #81.
 *
 * Открывается из реестра файлов, отбор «Редакции», по образцу «что прочитано»: отдельного
 * раздела у сравнения редакций нет, оно — свойство файла. По строке на изменённый лист:
 * что изменилось (числа «было → стало» — те, что стоят на одном месте), отмечено ли
 * изменение в штампе листа и в ведомости. Лист, где сменились только дата выдачи или
 * подписи или текст записки лишь сдвинулся на соседние страницы, отделён: в отборе «содержание»
 * его нет.
 */
export default function RevisionChangesPane({ processId, fileId, title, onClose, onCompare, onError }: Props) {
  const [data, setData] = useState<FileChanges | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter | null>(null);

  useEffect(() => {
    let alive = true;
    setError(null);
    setData(null);
    setFilter(null);
    api
      .fileChanges(processId, fileId)
      .then((got) => alive && setData(got))
      .catch((e: Error) => alive && setError(e.message));
    return () => {
      alive = false;
    };
  }, [processId, fileId]);

  const counts = useMemo(() => {
    const pages = data?.pages ?? [];
    return {
      all: pages.length,
      content: pages.filter((p) => p.content_changed !== false).length,
      unmarked: pages.filter((p) => p.registration?.status === "UNREGISTERED").length,
      service: pages.filter((p) => p.content_changed === false).length,
    };
  }, [data]);
  const current: Filter = filter ?? (counts.unmarked ? "unmarked" : counts.content ? "content" : "all");
  const rows = useMemo(
    () =>
      (data?.pages ?? []).filter((p) =>
        current === "content"
          ? p.content_changed !== false
          : current === "unmarked"
            ? p.registration?.status === "UNREGISTERED"
            : current === "service"
              ? p.content_changed === false
              : true,
      ),
    [data, current],
  );

  const pagesOf = (p: RevisionPage) =>
    p.old_page == null ? `— → ${p.new_page}` : p.new_page == null ? `${p.old_page} → —` : `${p.old_page} → ${p.new_page}`;

  return (
    <>
      <div className="pane-head">
        <h2>Что изменилось: {title}</h2>
        <button type="button" className="link" onClick={onClose}>
          закрыть
        </button>
      </div>
      <div className="card-body">
        {error && (
          <div className="empty-state">
            {error}
            {error.includes("ещё не сравнил") && " Запустите разбор заново и откройте снова."}
          </div>
        )}
        {!data && !error && <div className="empty-state">Сравнение загружается…</div>}
        {data && (
          <>
            <p className="lede">
              <b>{revisionName(data.old_revision, "прежняя редакция")}</b> → <b>{revisionName(data.new_revision, "эта редакция")}</b>
              <span className="mono small muted">
                {" "}
                {data.old_file_id} → {data.new_file_id}
              </span>
            </p>
            <p className="small">
              Страниц {data.counts.old_pages} → {data.counts.new_pages}: изменено {data.counts.changed + (data.counts.unreadable ?? 0)}
              {data.service_only > 0 &&
                `, из них содержание то же у ${data.service_only} (служебные поля или текст, сдвинувшийся между страницами)`}
              ; добавлено {data.counts.added}, удалено{" "}
              {data.counts.removed}
              {data.counts.no_text > 0 && `; без текста, сравнить нельзя — ${data.counts.no_text}`}.
              <br />
              {data.checked
                ? data.introduced.length
                  ? `Новые изменения: ${data.introduced.join(", ")}. ` +
                    (data.unmarked
                      ? `Без отметки изменено листов: ${data.unmarked} — номера изменения нет ни в штампе листа, ни в ведомости.`
                      : "Все листы с изменённым содержанием отмечены в штампе или в ведомости.")
                  : "В этой редакции нет отметок об изменениях ни в штампах, ни в ведомости: отмеченность проверить нельзя."
                : "Отметка изменения проверяется у рабочей документации; переиздание тома проекта отмечают по тому."}
            </p>

            <div className="filters" role="group" aria-label="Отбор листов">
              {(
                [
                  ["content", `Изменилось содержание — ${counts.content}`],
                  ...(data.checked ? [["unmarked", `Без отметки — ${counts.unmarked}`]] : []),
                  ["service", `Содержание не изменилось — ${counts.service}`],
                  ["all", `Все — ${counts.all}`],
                ] as [Filter, string][]
              ).map(([key, label]) => (
                <button key={key} type="button" className="btn" aria-current={current === key} onClick={() => setFilter(key)}>
                  {label}
                </button>
              ))}
            </div>

            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th className="num">Лист</th>
                    <th>Стр.</th>
                    <th>Что изменилось</th>
                    {data.checked && <th>Отметка</th>}
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((p) => {
                    const reg = p.registration ? REGISTRATION[p.registration.status] : null;
                    const layout = layoutNote(p.place);
                    const drawn = (p.old_page == null || p.rendered_old) && (p.new_page == null || p.rendered_new);
                    return (
                      <tr key={`${p.old_page}-${p.new_page}`}>
                        <td className="num mono small">{sheetsOf(p)}</td>
                        <td className="mono small">{pagesOf(p)}</td>
                        <td>
                          <div className="small">{p.what ?? PAGE_CHANGE[p.status] ?? p.status}</div>
                          {layout && <div className="small muted">{layout}</div>}
                        </td>
                        {data.checked && (
                          <td>
                            {reg ? (
                              <Tip text={p.registration?.why ?? reg.hint}>
                                <span className={p.registration?.status === "UNREGISTERED" ? "tag tag-clarify" : "tag"}>{reg.label}</span>
                              </Tip>
                            ) : (
                              <span className="small muted">—</span>
                            )}
                          </td>
                        )}
                        <td>
                          {drawn ? (
                            <button type="button" className="link" onClick={() => onCompare(comparePages(data, p))}>
                              сравнить
                            </button>
                          ) : (
                            <Tip text="Картинки этих страниц не готовились: у томов проекта рисуется ограниченное число страниц. Откроется исходный файл на этой странице">
                              <button
                                type="button"
                                className="link"
                                onClick={() =>
                                  openInTab(sourceUrl(processId, p.new_page == null ? data.old_file_id : data.new_file_id),
                                    `#page=${p.new_page ?? p.old_page}`).catch((e) => onError(`Исходный файл не открылся: ${(e as Error).message}`))
                                }
                              >
                                открыть файл
                              </button>
                            </Tip>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                  {rows.length === 0 && (
                    <tr>
                      <td colSpan={data.checked ? 5 : 4} className="small muted">
                        В этом отборе листов нет
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </>
  );
}
