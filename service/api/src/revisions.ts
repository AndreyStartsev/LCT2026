/**
 * Изменения между редакциями одного документа (#19, #81): то, что воркер положил в таблицу
 * revision_changes при разборе.
 *
 * Указатель (`revisionIndex`) — пары и их страницы без подробностей: по нему реестр файлов
 * показывает «что изменилось» и число листов без отметки, а карточка находки узнаёт, менялся
 * ли лист доказательства. Подробности пары (`pairDetails`) — что изменилось на странице, рамки
 * мест изменений и отметка — отдельным запросом по файлу новой редакции: у томов проекта
 * страниц сотни, и в указатель они не нужны.
 */

export interface RevisionRow {
  pair_id: string;
  chain_id: string | null;
  stage_group: string | null;
  old_file_id: string;
  new_file_id: string;
  old_revision: string | null;
  new_revision: string | null;
  summary: Record<string, any> | null;
  pages: Record<string, any>[] | null;
}

const COUNTS = ["old_pages", "new_pages", "same", "changed", "added", "removed", "unreadable", "no_text"] as const;

function head(row: RevisionRow) {
  const summary = row.summary ?? {};
  const pages = Array.isArray(row.pages) ? row.pages : [];
  const registration = summary.registration ?? null;
  return {
    pair_id: row.pair_id,
    chain_id: row.chain_id,
    stage_group: row.stage_group,
    mark: summary.mark ?? null,
    old_file_id: row.old_file_id,
    new_file_id: row.new_file_id,
    old_revision: row.old_revision,
    new_revision: row.new_revision,
    old_document: summary.old_document ?? null,
    new_document: summary.new_document ?? null,
    counts: Object.fromEntries(COUNTS.map((k) => [k, Number(summary[k] ?? 0)])),
    looks_like_revision: summary.looks_like_revision ?? null,
    // страницы, где изменилось содержание, а не только служебные поля (#81)
    content_changed: pages.filter((p) => p.content_changed === true).length,
    service_only: pages.filter((p) => p.content_changed === false).length,
    // отметка проверяется только у рабочей документации: null — не проверялась
    checked: registration !== null,
    introduced: Array.isArray(registration?.introduced) ? registration.introduced : [],
    unmarked: pages.filter((p) => p.registration?.status === "UNREGISTERED").length,
  };
}

export function revisionIndex(rows: RevisionRow[]) {
  return rows.map((row) => ({
    ...head(row),
    pages: (Array.isArray(row.pages) ? row.pages : []).map((p) => ({
      old_page: p.old_page ?? null,
      new_page: p.new_page ?? null,
      sheet: p.sheet ?? null,
      status: p.status,
      content_changed: p.content_changed ?? null,
      registration: p.registration?.status ?? null,
    })),
  }));
}

export function pairDetails(row: RevisionRow) {
  return {
    ...head(row),
    pages: (Array.isArray(row.pages) ? row.pages : []).map((p) => ({
      old_page: p.old_page ?? null,
      new_page: p.new_page ?? null,
      sheet: p.sheet ?? null,
      old_sheet: p.old_sheet ?? null,
      status: p.status,
      what: p.what ?? null,
      content_changed: p.content_changed ?? null,
      numbers: Array.isArray(p.numbers) ? p.numbers : [],
      changes: Array.isArray(p.changes) ? p.changes : [],
      place: p.place ?? null,
      registration: p.registration ?? null,
      rendered_old: p.rendered_old === true,
      rendered_new: p.rendered_new === true,
    })),
  };
}
