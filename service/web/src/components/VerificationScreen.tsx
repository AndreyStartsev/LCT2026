import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  api,
  ApiFailure,
  authHeader,
  download,
  openInTab,
  type AuditEntry,
  type Evidence,
  type FileItem,
  type Finding,
  type Limits,
  type Notification,
  type ProcessStatus,
  type RevisionPageRef,
  type RevisionPair,
  type Session,
} from "../api";
import { keyAction } from "../keys";
import { auditLine, bytes, criticalityWeight, plural, PROCESS_STATUS, SCENARIO, STAGE_NAME, STEP, when } from "../labels";
import {
  isCandidate,
  isHypothesis,
  matrixShort,
  pendingEdits,
  stageLoads,
  syncShort,
  tableOf,
  TABLES,
  type StageLoad,
  type TableKey,
} from "../protocol";
import FilesPane, { type Filter as FileFilter } from "./FilesPane";
import ProcessLog from "./ProcessLog";
import FileTextPane from "./FileTextPane";
import RevisionChangesPane, { comparePages, type RevisionCompare } from "./RevisionChangesPane";
import FindingCard from "./FindingCard";
import CompareViewer from "./CompareViewer";
import PageCard from "./PageCard";
import { dropFailed, useUploads } from "../uploads";
import ConfirmDialog from "./ConfirmDialog";
import HeadIcon from "./HeadIcon";
import Tip from "./Tip";
import PageViewer from "./PageViewer";
import ProtocolColumn from "./ProtocolColumn";
import UploadPanel from "./UploadPanel";

interface Props {
  processId: string;
  session: Session;
  limits: Limits | null;
  onChanged: () => void;
  /** Перейти в реестр объектов: там видно, какие обработки идут прямо сейчас (#74). */
  onObjects: () => void;
  /** Открыть сразу на этой записи: переход со щелчка по клетке дашборда (#83). */
  initialFindingId?: string;
  /** Открыть на этой таблице протокола: переход с дашборда (#83). */
  initialTable?: string;
}

type Center = "finding" | "files" | "audit" | "reupload" | "text" | "changes";
const STEPS = ["parse", "compare", "protocol"];

const STAGE_SHORT: Record<StageLoad["stage"], string> = { PD: "ПД", RD: "РД", ID: "ИД" };

/** Загрузка стадии словами — для подсказки ячейки «Документы». */
function loadText(l: StageLoad): string {
  if (l.state === "MISSING") return `${STAGE_SHORT[l.stage]}: не загружена`;
  return `${STAGE_SHORT[l.stage]}: ${l.files} ${plural(l.files, "файл", "файла", "файлов")}${l.state === "PARTIAL" ? ", загружена частично" : ""}`;
}

export default function VerificationScreen({
  processId,
  session,
  limits,
  onChanged,
  onObjects,
  initialFindingId,
  initialTable,
}: Props) {
  const [status, setStatus] = useState<ProcessStatus | null>(null);
  const [files, setFiles] = useState<FileItem[]>([]);
  // какой файл открыт на экране «что прочитано» (#52)
  const [textFile, setTextFile] = useState<{ fileId: string; title: string } | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [table, setTable] = useState<TableKey | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [center, setCenter] = useState<Center>("finding");
  // Отбор реестра задаёт левая колонка: «не приняты» и «без раздела» открываются одним щелчком (#74).
  const [filesFilter, setFilesFilter] = useState<FileFilter>("all");
  // Разбор заново — работа на минуты, поэтому сначала подтверждение, а не запуск с нажатия (#74).
  const [ask, setAsk] = useState<null | "retry" | "rebuild" | "start">(null);
  // Журнал обработки (#83): открывается и отсюда — там, где раньше висело наблюдение о качестве
  const [logOpen, setLogOpen] = useState(false);
  // Сравнение редакций (#81): пары цепочек, открытый файл «что изменилось» и сравнение листа
  const [revisions, setRevisions] = useState<RevisionPair[]>([]);
  const [changesFile, setChangesFile] = useState<{ fileId: string; title: string } | null>(null);
  const [revCompare, setRevCompare] = useState<RevisionCompare | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [alerts, setAlerts] = useState<Notification[]>([]);
  // страница крупно: какая сторона открыта; какая страница — берётся из pageIndex (п. 13)
  const [viewer, setViewer] = useState<{ side: "PD" | "RD"; title: string } | null>(null);
  // Какая страница-доказательство показана на каждой стороне (п. 13). null — страница, где
  // место обведено. Карточка страниц, «во весь экран», сопоставление и строки источников
  // в карточке находки открывают одну и ту же страницу; у новой записи — заново.
  const [pageIndex, setPageIndex] = useState<{ PD: number | null; RD: number | null }>({ PD: null, RD: null });
  // сопоставление листов во весь экран (#74): в правой колонке штампы и спецификации не читаются
  const [compare, setCompare] = useState(false);
  // Окно подтверждения финализации: единственное действие инспектора, которое он сам не отменит
  const [finalizing, setFinalizing] = useState(false);
  const finalizeOpener = useRef<HTMLElement | null>(null);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // последнее сообщение об отказе из run(): окно финализации показывает его после перечитывания
  const errorRef = useRef<string | null>(null);
  // чем выгруженный файл сдачи отличается от находок автоматики (#63)
  const [exported, setExported] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // последнее решение можно вернуть прямо из строки уведомления: решённый кандидат уходит из списка
  const [undo, setUndo] = useState<{ id: string; code: string } | null>(null);
  const [unfinalizing, setUnfinalizing] = useState(false);
  const [reason, setReason] = useState("");
  // Черновики комментариев по записям (п. 8): клавиши 1 и 3 отправляют набранное вместе
  // с решением, а при листании ↑ ↓ черновик не пропадает — вернулся к записи, текст на месте.
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const processing = status?.processing.state === "QUEUED" || status?.processing.state === "RUNNING";
  // Страницы, на которых модель не ответила: зацикливание, обрыв, отказ провайдера (#74, п. 4.2)
  const silentPages = (status?.readiness?.model_calls ?? 0) - (status?.readiness?.model_answered ?? 0);

  // silent — фоновый опрос: не стирает сообщение об отказе действия, которое инспектор ещё не прочитал
  const loadStatus = useCallback(async (silent = false) => {
    try {
      const s = await api.status(processId);
      setStatus(s);
      if (!silent) setError(null);
      return s;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, [processId]);

  const loadDetails = useCallback(async () => {
    try {
      const [f, g, n] = await Promise.all([api.files(processId), api.findings(processId), api.notifications()]);
      setFiles(f.files);
      setFindings(g.findings);
      // сравнение редакций (#81) — отдельно: без него экран работает как прежде
      api.revisions(processId).then(
        (r) => setRevisions(r.pairs),
        () => setRevisions([]),
      );
      // уведомления по этому процессу: о готовности протокола и о решениях, которые надо пересмотреть
      // Наблюдения о качестве разбора на рабочем экране не показываем (#83): инспектор читал
      // их как дефект объекта. Они собраны в журнале обработки — кнопка «Лог» в реестре объектов.
      // Из остальных берём по одной свежей записи каждого вида: иначе экран занимают копии
      // «протокол версии N сформирован» от каждой пересборки.
      const seen = new Set<string>();
      setAlerts(
        n.notifications
          .filter((x) => x.process_id === processId && x.category !== "QUALITY")
          .filter((x) => {
            const kind = x.category ?? "INFO";
            if (seen.has(kind)) return false;
            seen.add(kind);
            return true;
          })
          .slice(0, 2),
      );
    } catch (e) {
      setError((e as Error).message);
    }
  }, [processId]);

  useEffect(() => {
    loadStatus();
    loadDetails();
  }, [loadStatus, loadDetails]);

  // Pull-модель ТЗ: пока идёт обработка, статус опрашивается
  useEffect(() => {
    if (!processing) return;
    const timer = window.setInterval(async () => {
      const s = await loadStatus(true);
      if (s && s.processing.state !== "QUEUED" && s.processing.state !== "RUNNING") {
        await loadDetails();
        onChanged();
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [processing, loadStatus, loadDetails, onChanged]);

  // Передача в ИАИС «РиН» идёт в фоне: пока она ждёт попытки, статус обновляется
  // Загрузка в этот процесс из этого же окна: пока она идёт, экран не предлагает «Начать разбор
  // с принятыми» и вторую дозагрузку — иначе следующий пакет получил бы отказ «идёт обработка»
  const uploads = useUploads();
  const ownUpload = uploads.find((u) => u.processId === processId && !u.error) ?? null;
  const ownFailed = uploads.find((u) => u.processId === processId && !!u.error && !!u.resume) ?? null;
  const hadUpload = useRef(false);
  useEffect(() => {
    // загрузка кончилась — перечитать: разбор уже поставлен, экран должен это увидеть
    if (hadUpload.current && !ownUpload) {
      loadStatus();
      loadDetails();
    }
    hadUpload.current = !!ownUpload;
  }, [ownUpload, loadStatus, loadDetails]);
  // Загрузка не закончена, но идёт не отсюда (другая вкладка, другой инспектор): поглядывать,
  // не пришёл ли последний пакет
  const waitingUpload =
    !!status && status.protocol_version === null && status.status === "PENDING" && (status.processing.state ?? "IDLE") === "IDLE" && !ownUpload;
  useEffect(() => {
    if (!waitingUpload) return;
    const timer = window.setInterval(() => loadStatus(true), 10000);
    return () => window.clearInterval(timer);
  }, [waitingUpload, loadStatus]);

  const syncWaiting = status?.sync?.status === "PENDING_SYNC" && !!status.sync.next_attempt_at;
  useEffect(() => {
    if (!syncWaiting) return;
    const timer = window.setInterval(() => loadStatus(true), 5000);
    return () => window.clearInterval(timer);
  }, [syncWaiting, loadStatus]);

  const byTable = useMemo(() => {
    const out: Record<TableKey, Finding[]> = { completeness: [], candidates: [], confirmed: [], negatives: [], hypotheses: [] };
    findings.forEach((f) => {
      const t = tableOf(f);
      if (t) out[t].push(f);
    });
    // Кандидаты — по риску: критические выше существенных, нерешённые выше решённых.
    // Инспектор идёт по списку сверху вниз, и самое важное должно попасть в начало.
    const risk = (f: Finding) => (criticalityWeight(f.criticality) === "high" ? 0 : criticalityWeight(f.criticality) === "mid" ? 1 : 2);
    out.candidates.sort(
      (a, b) =>
        Number(a.verification_status !== "PENDING") - Number(b.verification_status !== "PENDING") ||
        risk(a) - risk(b) ||
        (a.parameter_code ?? "").localeCompare(b.parameter_code ?? "") ||
        (a.location ?? "").localeCompare(b.location ?? ""),
    );
    // Вид, который специалист решил не показывать, — в конце таблицы гипотез: по решению пользователя
    // такие записи не скрываются, но смотреть их стоит последними (Р-108). Остальной порядок прежний
    out.hypotheses.sort((a, b) => Number(a.specialist?.verdict === "drop") - Number(b.specialist?.verdict === "drop"));
    return out;
  }, [findings]);
  const counts = useMemo(
    () =>
      Object.fromEntries(TABLES.map((t) => [t.key, byTable[t.key].length])) as Record<TableKey, number>,
    [byTable],
  );
  const rejectedFiles = files.filter((f) => f.status === "REJECTED");
  const loads = status ? stageLoads(status, files) : [];

  // Таблица по умолчанию — кандидаты, если они есть, иначе первая непустая
  useEffect(() => {
    if (table !== null || findings.length === 0) return;
    // Пришли со щелчка по клетке дашборда: открываем таблицу этой записи и саму запись
    const target = initialFindingId ? findings.find((f) => f.id === initialFindingId) : undefined;
    const home = target ? tableOf(target) : null;
    if (target && home) {
      setTable(home);
      setActiveId(target.id);
      setCenter("finding");
      return;
    }
    const asked = TABLES.find((t) => t.key === initialTable)?.key;
    const first = asked ?? (byTable.candidates.length ? "candidates" : TABLES.find((t) => byTable[t.key].length)?.key ?? "candidates");
    setTable(first);
  }, [byTable, findings, table, initialFindingId, initialTable]);

  const rows = table ? byTable[table] : [];
  const active = findings.find((f) => f.id === activeId) ?? null;
  const draft = active ? drafts[active.id] ?? "" : "";
  // у новой записи — свои страницы: просмотр прежней закрывается, иначе он показал бы чужую
  // страницу под старым заголовком или, скрытый, держал бы клавиши экрана
  useEffect(() => {
    setPageIndex({ PD: null, RD: null });
    setViewer(null);
  }, [activeId]);
  const sideItems = useMemo(
    () => ({
      PD: active ? active.evidence.filter((e) => e.stage === "PD") : [],
      RD: active ? active.evidence.filter((e) => e.stage === "RD" || e.stage === "ID") : [],
    }),
    [active],
  );
  const markedOf = (items: Evidence[]) => Math.max(items.findIndex((e) => e.highlights?.length), 0);
  const shownIndex = (side: "PD" | "RD") => {
    const items = sideItems[side];
    const i = pageIndex[side] ?? markedOf(items);
    return Math.min(i, Math.max(items.length - 1, 0));
  };
  const showPage = (side: "PD" | "RD", i: number) => setPageIndex((p) => ({ ...p, [side]: i }));
  // строка источника в карточке находки: показать эту страницу справа, в карточке своей стороны
  const pickSource = (e: Evidence) => {
    const side = e.stage === "PD" ? "PD" : "RD";
    // сначала то самое доказательство: на одной странице их бывает несколько, с разными облаками
    const same = sideItems[side].indexOf(e);
    const i = same >= 0 ? same : sideItems[side].findIndex((x) => x.file_id === e.file_id && x.pdf_page_number === e.pdf_page_number);
    if (i >= 0) showPage(side, i);
  };

  // Решения по прежним значениям (п. 9): после дозагрузки значения записи изменились, и решение
  // надо пересмотреть. Их видно в списке, а шапка панели «Протокол» ведёт к первой из них.
  const revisitRows = useMemo(
    () => findings.filter((f) => f.changed_after_decision && ["CONFIRMED_VIOLATION", "NEGATIVE_VERIFIED", "CLARIFICATION_REQUIRED"].includes(f.verification_status)),
    [findings],
  );
  const openRevisit = () => {
    const first = revisitRows[0];
    const home = first ? tableOf(first) : null;
    if (!first || !home) return;
    setTable(home);
    setActiveId(first.id);
    setCenter("finding");
    setRejectOpen(false);
  };

  // Листов рабочей документации, изменённых без отметки (#81): строка в левой колонке
  const unmarkedTotal = useMemo(() => revisions.reduce((n, p) => n + p.unmarked, 0), [revisions]);

  // Лист доказательства изменён в последней редакции (#81): строка под его страницами. Это и есть
  // «ссылка на согласованное изменение» ТЗ: было ли изменение отмечено, видно тут же.
  const revisionHints = useMemo(() => {
    const out: Partial<Record<"PD" | "RD", { pair: RevisionPair; page: RevisionPageRef }>> = {};
    if (!active) return out;
    for (const e of active.evidence) {
      const stage = e.stage === "PD" ? "PD" : "RD";
      if (out[stage]) continue;
      const pair = revisions.find((p) => p.new_file_id === e.file_id);
      const page = pair?.pages.find((p) => p.new_page === e.pdf_page_number && p.content_changed !== false);
      if (pair && page) out[stage] = { pair, page };
    }
    return out;
  }, [active, revisions]);

  const openRevisionCompare = useCallback(
    async (pair: RevisionPair, ref: RevisionPageRef) => {
      try {
        const details = await api.fileChanges(processId, pair.new_file_id);
        const page = details.pages.find((p) => p.new_page === ref.new_page && p.old_page === ref.old_page);
        if (page) setRevCompare(comparePages(details, page));
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [processId],
  );

  const revisionHint = (stage: "PD" | "RD") => {
    const hint = revisionHints[stage];
    if (!hint) return null;
    const { pair, page } = hint;
    return (
      <div className={page.registration === "UNREGISTERED" ? "alert rev-hint" : "note-line rev-hint"}>
        {page.status === "ADDED" ? "Лист добавлен в " : "Лист изменён в "}
        {pair.new_revision ?? "новой редакции"}
        {page.registration === "UNREGISTERED" && " без отметки: номера изменения нет ни в штампе, ни в ведомости"}
        {page.registration === "REGISTERED" && ", изменение отмечено"}
        {page.status !== "ADDED" && (
          <>
            {" · "}
            <button type="button" className="link" onClick={() => openRevisionCompare(pair, page)}>
              сравнить с {pair.old_revision ?? "прежней редакцией"}
            </button>
          </>
        )}
      </div>
    );
  };

  useEffect(() => {
    if (!table) return;
    if (!rows.some((f) => f.id === activeId)) {
      setActiveId(rows[0]?.id ?? null);
    }
  }, [table, rows, activeId]);

  const editable = !!status && ["READY", "VERIFYING", "COMPLETED"].includes(status.status) && !processing;

  const run = useCallback(
    async (action: () => Promise<unknown>, success: string) => {
      setBusy(true);
      setError(null);
      setNotice(null);
      setUndo(null);
      try {
        await action();
        setNotice(success);
        await Promise.all([loadStatus(), loadDetails()]);
        onChanged();
        return true;
      } catch (e) {
        errorRef.current = (e as ApiFailure).message;
        setError(errorRef.current);
        return false;
      } finally {
        setBusy(false);
      }
    },
    [loadStatus, loadDetails, onChanged],
  );

  const decide = useCallback(
    async (action: "CONFIRM" | "REJECT" | "CLARIFY" | "RESET" | "PROMOTE" | "DISPUTE", reasonCode?: string, comment?: string) => {
      if (!active) return;
      const index = rows.findIndex((f) => f.id === active.id);
      const words = {
        CONFIRM: "Нарушение подтверждено",
        REJECT: "Кандидат отклонён",
        // запись только помечается и финализацию не держит — «отправлено» обещало бы то, чего нет (п. 10)
        CLARIFY: "Отмечено: требует уточнения",
        RESET: "Возвращено в кандидаты",
        PROMOTE: "Гипотеза взята в кандидаты",
        DISPUTE: "Запись возвращена в кандидаты: автоматическая проверка оспорена",
      };
      // где был фокус, когда решение отправили: если за время запроса инспектор ушёл в другое место
      // (щёлкнул в поле, открыл страницу), фокус у него не отбирается
      const before = document.activeElement;
      const ok = await run(() => api.decide(active.id, action, reasonCode, comment), words[action]);
      if (ok) {
        setRejectOpen(false);
        setDrafts((d) => {
          const { [active.id]: _sent, ...rest } = d;
          return rest;
        });
        // Фокус — на заголовок карточки, а не в поле комментария: следующая «1» принимает
        // решение, а не печатается в комментарий следующей записи (п. 7).
        window.requestAnimationFrame(() => {
          const now = document.activeElement;
          if (now !== before && now !== document.body && now !== null) return;
          if (document.querySelector('[role="dialog"]')) return;
          document.getElementById("finding-card-title")?.focus({ preventScroll: true });
        });
        if (action === "PROMOTE" || action === "DISPUTE") {
          // запись ушла из таблицы 5 или 4 в кандидаты, за ней и переходим
          setTable("candidates");
          return;
        }
        if (action !== "RESET") {
          const code = active.parameter_code ?? active.finding_id;
          // у частей разделённой записи код один, различает их локация
          setUndo({ id: active.id, code: active.origin === "INSPECTOR_SPLIT" ? `${code} · ${active.locations.join(", ")}` : code });
        }
        // после решения — к следующему нерешённому кандидату, чтобы протокол проходился подряд
        if (action !== "RESET" && table === "candidates") {
          const next = rows.slice(index + 1).find((f) => f.verification_status === "PENDING" && f.id !== active.id);
          if (next) setActiveId(next.id);
        }
      }
    },
    [active, rows, run, table],
  );

  const split = useCallback(
    async (locations: string[]) => {
      if (!active) return;
      await run(() => api.split(active.id, locations), `Запись разделена на ${locations.length} кандидата`);
    },
    [active, run],
  );

  // Листание записей выбранной таблицы: кандидаты, гипотезы, отклонённые — что открыто, то и листается.
  const rowIndex = rows.findIndex((f) => f.id === activeId);
  const move = (step: number) => {
    const next = rows[rowIndex + step];
    if (next) setActiveId(next.id);
  };

  // Клавиши: стрелки — по списку, 1 — подтвердить, 2 — отклонить, 3 — уточнить, Esc — отмена.
  // Решение принимается только по открытой карточке кандидата и без модификаторов: разбор — в `keys.ts`.
  const candidateOpen =
    !!active && editable && !busy && active.verification_status === "PENDING" && isCandidate(active) && !isHypothesis(active);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const action = keyAction({
        key: e.key,
        ctrl: e.ctrlKey,
        meta: e.metaKey,
        alt: e.altKey,
        shift: e.shiftKey,
        tag: (e.target as HTMLElement | null)?.tagName,
        center,
        viewer: !!viewer || !!revCompare,
        overlay: compare || logOpen || !!ask || finalizing,
        repeat: e.repeat,
        formOpen: rejectOpen || unfinalizing,
        candidateOpen,
        busy,
      });
      if (!action) return;
      if (action === "next") {
        e.preventDefault();
        move(1);
      } else if (action === "prev") {
        e.preventDefault();
        move(-1);
      } else if (action === "confirm") {
        decide("CONFIRM", undefined, draft.trim() || undefined);
      } else if (action === "reject") {
        setRejectOpen(true);
      } else if (action === "clarify") {
        decide("CLARIFY", undefined, draft.trim() || undefined);
      } else if (action === "escape") {
        setRejectOpen(false);
        setUnfinalizing(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, activeId, candidateOpen, busy, center, decide, viewer, revCompare, compare, logOpen, ask, finalizing, rejectOpen, unfinalizing, draft]);

  // Дозагрузка без протокола кончилась разбором: панель закрываем, иначе после разбора экран
  // открылся бы на ней, а не на карточке
  useEffect(() => {
    if (processing && center === "reupload" && status?.protocol_version === null) setCenter("finding");
  }, [processing, center, status?.protocol_version]);

  // Сопоставление листов открыто для конкретной записи: сменилась запись — окно закрывается,
  // а не показывает молча листы другой
  useEffect(() => setCompare(false), [activeId]);

  // Окно финализации показывает свежую сводку: другой инспектор, вторая вкладка или дозагрузка
  // могли поменять решения и файлы, а экран с протоколом в простое ничего не опрашивает
  async function openFinalize() {
    // значок гаснет на время перечитывания и теряет фокус: запоминаем его, чтобы вернуть фокус после окна
    finalizeOpener.current = document.activeElement as HTMLElement | null;
    setBusy(true);
    const [s] = await Promise.all([loadStatus(), loadDetails()]);
    setBusy(false);
    if (!s) return;
    if ((s.findings?.pending ?? 0) > 0) {
      setError(`Финализировать нельзя: ждут решения ${s.findings?.pending ?? 0} кандидатов.`);
      return;
    }
    setFinalizing(true);
  }

  /**
   * Печать протокола (#74): инспектору нужен один бумажный документ для руководства и
   * предписания. PDF собирает сервер — тот же, что в выгрузке, — и открывается в соседней
   * вкладке, где печать делает браузер. Отдельная кнопка потому, что «Выгрузить» читается
   * как выгрузка данных, а не как печать.
   */
  async function printProtocol() {
    // Через тот же путь, что исходный файл: вкладка открывается сразу по нажатию и показывает,
    // что документ готовится, — сборка PDF по большому объекту занимает секунды (#83).
    try {
      await openInTab(`/api/v1/process/${processId}/report.pdf`);
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function exportAs(kind: "pdf" | "docx" | "json" | "xml" | "submission") {
    const base = `/api/v1/process/${processId}`;
    const name = `protocol-${status?.object_id ?? processId}-v${status?.protocol_version ?? ""}`;
    const target = {
      pdf: [`${base}/report.pdf`, `${name}.pdf`],
      docx: [`${base}/report.docx`, `${name}.docx`],
      json: [`${base}/report`, `${name}.json`],
      xml: [`${base}/report.xml`, `${name}.xml`],
      submission: [`${base}/protocol`, `submission-${status?.object_id ?? processId}-v${status?.protocol_version ?? ""}.json`],
    }[kind];
    try {
      const headers = await download(target[0], target[1]);
      // Файл сдачи собирается по решениям на момент выгрузки (#63): инспектор должен
      // видеть, чем он отличается от того, что нашла автоматика
      if (kind === "submission" && headers) {
        const rejected = Number(headers.get("x-checks-rejected") ?? 0);
        const promoted = Number(headers.get("x-checks-promoted") ?? 0);
        const undecided = Number(headers.get("x-checks-undecided") ?? 0);
        setExported(
          `Файл сдачи собран по решениям: отклонённых записей убрано ${rejected}, ` +
          `подтверждённых гипотез добавлено ${promoted}, без решения осталось ${undecided}.`,
        );
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function openAudit() {
    try {
      setAudit((await api.audit(processId)).entries);
      setCenter("audit");
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!status) {
    return (
      <div className="frame">
        {error ? <div className="alert">{error}</div> : <div className="empty-state">Процесс загружается…</div>}
      </div>
    );
  }

  const c = status.findings;
  const sync = status.sync;
  // автоматические повторы исчерпаны или внешняя система отклонила запрос
  const syncStuck = !!sync && (sync.status === "REJECTED" || (sync.status === "PENDING_SYNC" && !sync.next_attempt_at));
  const iais = syncShort(status);
  // ручные правки файлов, сделанные после сборки протокола: в него они ещё не вошли (п. 11)
  const waitingEdits = pendingEdits(files, status.protocol?.created_at);
  const hasProtocol = status.protocol_version !== null;
  const canFinalize = editable && hasProtocol && (c?.pending ?? 0) === 0 && !ownUpload;
  // Загрузка не закончена: часть пакетов принята, последнего нет, разбор не поставлен.
  // Файлы оборвавшейся загрузки в браузере уже не живы — догрузить или начать разбор с тем, что есть.
  const receiving =
    !hasProtocol && status.status === "PENDING" && (status.processing.state ?? "IDLE") === "IDLE" && status.files.accepted > 0;
  // Для окна финализации — что стоит поправить до неё. «Пересмотреть» и правки файлов — по тем
  // же правилам, что счётчик панели «Протокол» и отметки в списке (revisitRows, pendingEdits).
  const builtAt = status.protocol?.created_at ? Date.parse(status.protocol.created_at) : NaN;
  const stale = revisitRows.length;
  const editsAfter = waitingEdits.length;
  // файлы, принятые после сборки (дозагрузка не закончена или разбор не запускался), в протокол не вошли
  const addedAfter = Number.isNaN(builtAt)
    ? 0
    : files.filter((f) => f.status === "ACCEPTED" && !!f.uploaded_at && Date.parse(f.uploaded_at) > builtAt).length;
  const emptyText =
    table === "candidates" && c && c.candidates > 0
      ? `Все кандидаты рассмотрены: подтверждено ${c.confirmed}, отклонено ${c.rejected}. Решения — в таблицах 3 и 4, из карточки записи её можно вернуть в кандидаты.${canFinalize ? " Протокол можно финализировать." : ""}`
      : TABLES.find((t) => t.key === table)?.empty ?? "Выберите запись";

  return (
    <div className="frame">
      <header className="sheet-head verify-head">
        <div>
          <h1>Экран верификации</h1>
          <div className="sub">Сверка ПД · РД · ИД</div>
        </div>
        {/* Данные объекта — одной строкой с начала средней колонки до значков. Сценарий
            проверки отдельной графой не стоит: его говорят «Документы» по стадиям, словами —
            в подсказке. Передача в ИАИС «РиН» (ТЗ 9.6) видна всегда, коротко; номер во внешней
            системе и попытки — в подсказке. Если строке тесно, первым укорачивается название
            объекта, а на экране уже 1400 px у протокола остаётся только номер версии. */}
        <div className="head-meta">
          <div className="head-cell head-object">
            <span className="k">Объект</span>
            <span className="v" title={`${status.object_name ?? ""} · ${status.object_id}`}>
              {status.object_name ?? status.object_id}
            </span>
          </div>
          <div className="head-cell">
            <span className="k">Статус</span>
            <span className="v">
              {status.processing.state === "FAILED" ? "Сбой обработки" : PROCESS_STATUS[status.status] ?? status.status}
            </span>
          </div>
          <div className="head-cell">
            <span className="k">Ждут решения</span>
            <span className="v" title={c?.clarification ? `На уточнении: ${c.clarification} — к ним ещё вернутся` : undefined}>
              {c ? c.pending : 0} из {c ? c.candidates : 0}
              {c?.clarification ? ` · уточн. ${c.clarification}` : ""}
            </span>
          </div>
          <div className="head-cell">
            <span className="k">Документы</span>
            <span
              className="v"
              title={[
                `Сценарий проверки: ${status.scenario ? SCENARIO[status.scenario] ?? status.scenario : "—"}`,
                ...loads.map(loadText),
              ].join("\n")}
            >
              {loads.map((l, i) => (
                <span key={l.stage}>
                  {i > 0 && " · "}
                  <span className={l.state === "PARTIAL" ? "head-part" : l.state === "MISSING" ? "head-missing" : undefined}>
                    {STAGE_SHORT[l.stage]} {l.state === "MISSING" ? "—" : l.files}
                  </span>
                </span>
              ))}
            </span>
          </div>
          <div className="head-cell">
            <span className="k">Протокол</span>
            <span
              className="v"
              title={
                status.protocol
                  ? `Правила Матрицы: ${status.protocol.matrix_version ?? "—"}\nКонвейер: ${status.protocol.model_version ?? "—"}`
                  : undefined
              }
            >
              {status.protocol ? (
                <>
                  v{status.protocol.version}
                  <span className="head-queues"> · {matrixShort(status.protocol.matrix_version)}</span>
                </>
              ) : (
                "не сформирован"
              )}
            </span>
          </div>
          <div className={`head-cell${syncStuck ? " head-warn" : ""}`}>
            <span className="k">ИАИС «РиН»</span>
            <span className="v" title={iais.title}>
              {iais.text}
            </span>
          </div>
        </div>
        <div className="head-actions">
          <Tip text="Выгрузить: протокол в PDF, DOCX, JSON или XML и файл сдачи организатору">
          <details className="menu">
            <summary className={`btn btn-icon${hasProtocol ? "" : " disabled"}`} aria-disabled={!hasProtocol} aria-label="Выгрузить">
              <HeadIcon name="export" />
            </summary>
            {hasProtocol && (
              <div className="menu-list" role="menu">
                <button type="button" role="menuitem" onClick={() => exportAs("pdf")}>
                  Протокол, PDF
                </button>
                <button type="button" role="menuitem" onClick={() => exportAs("docx")}>
                  Протокол, DOCX
                </button>
                <button type="button" role="menuitem" onClick={() => exportAs("json")}>
                  Протокол, JSON
                </button>
                <button type="button" role="menuitem" onClick={() => exportAs("xml")}>
                  Протокол, XML
                </button>
                <button type="button" role="menuitem" onClick={() => exportAs("submission")}>
                  Файл сдачи организатору, JSON
                </button>
              </div>
            )}
          </details>
          </Tip>
          {hasProtocol && (
            <Tip text="Печать: протокол одним документом для печати или сохранения в PDF">
              <button type="button" className="btn btn-icon" aria-label="Печать" onClick={printProtocol}>
                <HeadIcon name="print" />
              </button>
            </Tip>
          )}
          {status.status !== "FINALIZED" && !processing && !ownUpload && (
            <Tip text="Дозагрузить: недостающие тома или новые редакции листов — пересчитываются только затронутые параметры">
              <button
                type="button"
                className="btn btn-icon"
                aria-label="Дозагрузить"
                aria-pressed={center === "reupload"}
                onClick={() => setCenter(center === "reupload" ? "finding" : "reupload")}
              >
                <HeadIcon name="reupload" />
              </button>
            </Tip>
          )}
          {session.role === "admin" && (
            <Tip text="Журнал аудита: кто, когда и какое решение принял по записям протокола">
              <button type="button" className="btn btn-icon" aria-label="Журнал аудита" aria-pressed={center === "audit"} onClick={openAudit}>
                <HeadIcon name="journal" />
              </button>
            </Tip>
          )}
          {session.role === "admin" && status.status === "FINALIZED" && syncStuck && (
            <Tip text="Повторить передачу в ИАИС «РиН»: автоматические попытки исчерпаны или запрос отклонён">
              <button
                type="button"
                className="btn btn-icon"
                aria-label="Повторить передачу в ИАИС «РиН»"
                disabled={busy}
                onClick={() => run(() => api.retrySync(processId), "Передача в ИАИС «РиН» поставлена заново")}
              >
                <HeadIcon name="resync" />
              </button>
            </Tip>
          )}
          {status.status === "FINALIZED" ? (
            session.role === "admin" && (
              <Tip text="Отменить финализацию: протокол снова открыт для решений, причина пишется в журнал" place="below">
                <button type="button" className="btn btn-icon" aria-label="Отменить финализацию" onClick={() => setUnfinalizing(true)}>
                  <HeadIcon name="unfinalize" />
                </button>
              </Tip>
            )
          ) : (
            <Tip
              text={
                canFinalize
                  ? "Финализировать протокол: верификация завершается, правки закрываются, запись уходит в ИАИС «РиН»"
                  : ownUpload
                    ? "Идёт дозагрузка из этого окна: финализировать можно после неё"
                    : "Финализировать протокол можно после решения по всем кандидатам"
              }
              place="below"
            >
              <button
                type="button"
                className="btn btn-primary btn-icon"
                aria-label="Финализировать протокол"
                disabled={!canFinalize || busy}
                onClick={openFinalize}
              >
                <HeadIcon name="finalize" />
              </button>
            </Tip>
          )}
        </div>
      </header>

      {error && <div className="alert">{error}</div>}
      {exported && !error && <div className="note-line">{exported}</div>}
      {/* своя дозагрузка в объект с протоколом: пока она идёт, финализация и пересборка недоступны */}
      {ownUpload && hasProtocol && (
        <div className="note-line" role="status">
          Идёт дозагрузка из этого окна: пакет {ownUpload.batchIndex} из {ownUpload.batchCount}, {bytes(ownUpload.sent)} из{" "}
          {bytes(ownUpload.total)}. Финализация и пересборка — после неё: протокол пересоберётся сам.
        </div>
      )}
      {alerts.map((a) => (
        <div key={a.id} className={a.level === "ERROR" || a.level === "WARNING" ? "alert" : "note-line"}>
          {a.message}
          <span className="mono small muted"> {when(a.created_at)}</span>
          {/* решения по прежним значениям: из уведомления — сразу к первому из них (п. 9) */}
          {a.category === "ACTION" && a.message.startsWith("После дозагрузки изменились значения") && revisitRows.length > 0 && (
            <>
              {" · "}
              <button type="button" className="link" onClick={openRevisit}>
                к первой записи ({revisitRows.length})
              </button>
            </>
          )}
        </div>
      ))}
      {notice && !error && (
        <div className="note-line">
          {notice}
          {undo && editable && (
            <>
              {" · "}
              <button
                type="button"
                className="link"
                disabled={busy}
                onClick={async () => {
                  const target = undo;
                  if (await run(() => api.decide(target.id, "RESET"), `${target.code} возвращён в кандидаты`)) {
                    setTable("candidates");
                    setActiveId(target.id);
                  }
                }}
              >
                вернуть {undo.code} в кандидаты
              </button>
            </>
          )}
        </div>
      )}
      {/* Перечитывание запускает разбор заново и занимает минуты, поэтому сначала говорим,
          что именно произойдёт, и только по согласию ставим в очередь. */}
      {logOpen && (
        <ProcessLog
          processId={processId}
          title={status.object_name ?? status.object_id}
          onClose={() => setLogOpen(false)}
        />
      )}

      {ask && (
        <ConfirmDialog
          title={
            ask === "retry"
              ? "Перечитать страницы, на которых модель не ответила?"
              : ask === "start"
                ? "Начать разбор с принятыми файлами?"
                : "Пересобрать протокол?"
          }
          confirmLabel={ask === "retry" ? "Перечитать" : ask === "start" ? "Начать разбор" : "Пересобрать"}
          busy={busy}
          onCancel={() => setAsk(null)}
          onConfirm={async () => {
            const kind = ask;
            setAsk(null);
            const ok = await run(
              () => api.start(processId),
              kind === "retry"
                ? "Перечитывание поставлено в очередь: ход виден в разделе «Объекты»"
                : kind === "start"
                  ? "Разбор поставлен в очередь: ход виден здесь и в разделе «Объекты»"
                  : "Пересборка протокола поставлена в очередь: ход виден в разделе «Объекты»",
            );
            if (ok && kind === "start") {
              // разбор по принятым запущен: оборвавшаяся загрузка больше не продолжается
              dropFailed(processId);
              setCenter("finding");
            }
          }}
        >
          <p>
            {ask === "start" ? (
              <>
                Загрузка не закончена: принято файлов {status.files.accepted}. Разбор пойдёт по ним. Недостающие тома
                можно догрузить потом — протокол пересоберётся новой версией.
              </>
            ) : ask === "retry" ? (
              <>
                Разбор запустится заново, но модель позовут только на {silentPages} страницах, где её ответа нет:
                остальное возьмётся из кеша чтения. Это минуты работы модели, и на части страниц ответа снова
                может не быть.
              </>
            ) : (
              <>
                Разбор запустится заново: файлы и прочитанный текст возьмутся из кеша, заново посчитаются сравнение
                и протокол. Заданные вручную стадии, разделы и выбранные редакции вступят в силу.
              </>
            )}
          </p>
          {ask === "rebuild" && waitingEdits.length > 0 && (
            <div className="small">
              В протокол войдут правки файлов ({waitingEdits.length}):
              <ul className="edit-list">
                {waitingEdits.slice(0, 8).map((f) => (
                  <li key={f.relative_path}>{f.relative_path.split("/").pop()}</li>
                ))}
                {waitingEdits.length > 8 && <li className="muted">и ещё {waitingEdits.length - 8}</li>}
              </ul>
            </div>
          )}
          {ask !== "start" && (
            <p className="small muted">
              Протокол пересоберётся: решения инспектора, возвраты в кандидаты и взятые гипотезы сохранятся. Пока идёт
              обработка, решать записи нельзя. Работа идёт в фоне — её ход виден в разделе «Объекты», экран проверки
              можно закрыть.
            </p>
          )}
        </ConfirmDialog>
      )}

      {/* Финализация — единственное действие инспектора, которое он сам не отменит: отменяет
          администратор, а протокол сразу встаёт в очередь передачи в ИАИС «РиН». Поэтому
          сначала сводка того, что уходит, и предупреждения о том, что стоит поправить. */}
      {finalizing && c && (
        <ConfirmDialog
          title="Финализировать протокол?"
          confirmLabel="Финализировать"
          busy={busy}
          returnTo={finalizeOpener.current}
          onCancel={() => setFinalizing(false)}
          onConfirm={async () => {
            const ok = await run(() => api.finalize(processId), "Протокол финализирован");
            setFinalizing(false);
            // Отказ (например, запись вернули в кандидаты с другого места): окно закрываем,
            // чтобы причина не осталась под подложкой, и перечитываем состояние — шапка и сводка
            // должны показать, что изменилось. Сообщение об отказе сохраняем: загрузка его стёрла бы.
            if (!ok) {
              const message = errorRef.current;
              const [s] = await Promise.all([loadStatus(), loadDetails()]);
              // ответ потерялся, а сервер успел финализировать: не пугать ошибкой
              if (s?.status === "FINALIZED") {
                setNotice("Протокол финализирован");
                onChanged();
              } else if (message) {
                setError(message);
              }
            }
          }}
        >
          <p>
            Протокол версии {status.protocol_version ?? "—"} будет зафиксирован: решения по записям больше не изменить, протокол
            уйдёт в ИАИС «РиН». Отменить финализацию может только администратор.
          </p>
          <dl className="kv finalize-sum">
            <dt>Подтверждено нарушений</dt>
            <dd>{c.confirmed}</dd>
            <dt>Отклонено</dt>
            <dd>{c.rejected}</dd>
            <dt>Требуют уточнения</dt>
            <dd>{c.clarification}</dd>
            {c.hypotheses > 0 && (
              <>
                <dt>Гипотез не взято в кандидаты</dt>
                <dd>{c.hypotheses} — в итоги нарушений не входят</dd>
              </>
            )}
          </dl>
          {stale > 0 && (
            <div className="alert">
              Решений по записям, у которых после дозагрузки изменились значения: {stale}. Их стоит пересмотреть до
              финализации — в карточке такой записи стоит «Пересмотрите решение».
            </div>
          )}
          {editsAfter > 0 && (
            <div className="alert">
              Ручных правок стадии, раздела или редакции после сборки протокола: {editsAfter}. В протокол они не вошли —
              чтобы вошли, пересоберите протокол перед финализацией.
            </div>
          )}
          {addedAfter > 0 && (
            <div className="alert">
              Файлов, принятых после сборки протокола: {addedAfter}. В протокол они не вошли — догрузите оставшиеся
              пакеты или пересоберите протокол перед финализацией.
            </div>
          )}
        </ConfirmDialog>
      )}

      {unfinalizing && (
        <div className="inline-form">
          <label className="field">
            <span className="k">Причина отмены финализации — обязательна</span>
            <input id="unfinalize-reason" value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <button
            type="button"
            className="btn"
            disabled={reason.trim().length < 5 || busy}
            onClick={async () => {
              if (await run(() => api.unfinalize(processId, reason.trim()), "Финализация отменена")) {
                setUnfinalizing(false);
                setReason("");
              }
            }}
          >
            Отменить финализацию
          </button>
          <button type="button" className="btn" onClick={() => setUnfinalizing(false)}>
            Закрыть
          </button>
        </div>
      )}

      {/* Пока протокол есть, идущая обработка не занимает экран инспектора собой: работа идёт
          в фоне, её состояние — строкой, а полный ход — в разделе «Объекты» (#74). */}
      {processing && hasProtocol && status.processing.state !== "FAILED" && (
        <div className="note-line job-line">
          {/* Воркер берёт задания по одному: пока этот объект ждёт, «идёт обработка» была бы неправдой */}
          <span>
            {status.processing.state === "QUEUED"
              ? "Объект стоит в очереди на обработку: задания обрабатываются по одному."
              : `Идёт обработка: ${STEP[status.processing.step ?? ""] ?? status.processing.step ?? "разбор"}` +
                (status.progress?.total ? ` — ${status.progress.done ?? 0} из ${status.progress.total}.` : ".")}{" "}
            Протокол обновится, когда она закончится; решения сохранятся.
          </span>
          <button type="button" className="link" onClick={onObjects}>
            очередь обработки
          </button>
        </div>
      )}

      {((processing && !hasProtocol) || status.processing.state === "FAILED" || !hasProtocol) && (
        <section className="pane processing">
          <div className="pane-head">
            <h2>{hasProtocol ? "Пересборка протокола" : "Обработка документов"}</h2>
            <span className="count">
              {status.files.accepted} принято · {status.files.rejected} отклонено
            </span>
          </div>
          <ol className="steps">
            {STEPS.map((step) => {
              const current = STEPS.indexOf(status.processing.step ?? "");
              const index = STEPS.indexOf(step);
              const state =
                status.processing.state === "DONE" || (hasProtocol && !processing && status.processing.state !== "FAILED")
                  ? "done"
                  : index < current
                    ? "done"
                    : index === current
                      ? status.processing.state === "FAILED"
                        ? "failed"
                        : "active"
                      : "todo";
              return (
                <li key={step} className={`step step-${state}`}>
                  {STEP[step]}
                </li>
              );
            })}
          </ol>
          {processing && (
            <div className="progress">
              <div className="progress-label">
                {status.progress?.message ?? "В очереди"}
                {status.progress?.total ? ` — ${status.progress.done ?? 0} из ${status.progress.total}` : ""}
              </div>
              <div className="bar">
                <div
                  className={`bar-fill${status.progress?.total ? "" : " bar-indeterminate"}`}
                  style={status.progress?.total ? { width: `${Math.round(((status.progress.done ?? 0) / status.progress.total) * 100)}%` } : undefined}
                />
              </div>
            </div>
          )}
          {receiving && ownUpload && (
            <div className="note-line" role="status">
              Идёт загрузка из этого окна: пакет {ownUpload.batchIndex} из {ownUpload.batchCount}, {bytes(ownUpload.sent)} из{" "}
              {bytes(ownUpload.total)}. Разбор начнётся после последнего пакета.
            </div>
          )}
          {receiving && !ownUpload && (
            <div className="alert receiving">
              Загрузка не закончена: принято файлов {status.files.accepted}, последний пакет не пришёл
              {status.updated_at ? ` (последний принят ${when(status.updated_at)})` : ""}, разбор не запущен.{" "}
              {ownFailed
                ? ownFailed.failedBatch
                  ? `Загрузка из этого окна оборвалась на пакете ${ownFailed.failedBatch} — её можно продолжить.`
                  : "Файлы из этого окна приняты, но разбор не запустился — запустите его ещё раз."
                : "Если загрузка идёт из другой вкладки, дождитесь её; иначе догрузите недостающие файлы или начните разбор с принятыми."}
              <span className="receiving-actions">
                {ownFailed?.resume && (
                  <button type="button" className="btn btn-primary" disabled={busy} onClick={ownFailed.resume}>
                    {(ownFailed.resumeLabel ?? "продолжить").replace(/^./, (c) => c.toUpperCase())}
                  </button>
                )}
                <button type="button" className="btn" disabled={busy} onClick={() => setCenter("reupload")}>
                  Догрузить файлы
                </button>
                <button type="button" className="btn" disabled={busy} onClick={() => setAsk("start")}>
                  Начать разбор с принятыми
                </button>
              </span>
            </div>
          )}
          {status.processing.state === "FAILED" && (
            <div className="alert">
              Обработка остановлена на шаге «{STEP[status.processing.step ?? ""] ?? status.processing.step}»: {status.processing.error}.
              Администратор уведомлён.{" "}
              <button
                type="button"
                className="btn"
                disabled={busy || !!ownUpload}
                title={ownUpload ? "Идёт загрузка из этого окна: разбор начнётся после последнего пакета" : undefined}
                onClick={() => run(() => api.start(processId), "Разбор запущен заново")}
              >
                Запустить заново
              </button>
            </div>
          )}
        </section>
      )}

      {/* Дозагрузка без протокола: загрузка оборвалась или не закончена — панель та же, что
          в работе с протоколом, но блока работы ещё нет */}
      {!hasProtocol && !processing && center === "reupload" && limits && (
        <section className="pane reupload-solo">
          <div className="pane-head">
            <h2>Дозагрузка документов</h2>
            <span className="count">разбор начнётся после последнего пакета</span>
            <button type="button" className="link" onClick={() => setCenter("finding")}>
              закрыть
            </button>
          </div>
          <div className="card-body">
            <UploadPanel
              limits={limits}
              objects={[]}
              processId={processId}
              title={status.object_name ?? status.object_id}
              submitLabel="Догрузить и начать разбор"
              onUploaded={() => {
                setCenter("finding");
                loadStatus();
                onChanged();
              }}
            />
          </div>
        </section>
      )}

      {hasProtocol && (
        <div className={`work${center === "finding" ? "" : " work-two"}${processing ? " work-locked" : ""}`}>
          <ProtocolColumn
            table={table ?? "candidates"}
            counts={counts}
            rows={rows}
            empty={emptyText}
            activeId={center === "finding" ? activeId : null}
            loads={loads}
            rejectedFiles={rejectedFiles}
            readiness={status.readiness}
            recompute={status.recompute}
            onTable={(t) => {
              setTable(t);
              setCenter("finding");
              setRejectOpen(false);
            }}
            onSelect={(id) => {
              setActiveId(id);
              setCenter("finding");
              setRejectOpen(false);
            }}
            onRejectedFiles={() => {
              setFilesFilter("rejected");
              setCenter("files");
            }}
            onFiles={(filter) => {
              setFilesFilter(filter ?? "all");
              setCenter("files");
            }}
            canRetryRead={
              session.role === "admin" &&
              editable &&
              !ownUpload &&
              (status.readiness?.model_calls ?? 0) > (status.readiness?.model_answered ?? 0)
            }
            onRetryRead={() => setAsk("retry")}
            onLog={() => setLogOpen(true)}
            unmarked={unmarkedTotal}
            revisit={revisitRows.length}
            onRevisit={openRevisit}
            pendingEdits={editable ? waitingEdits.length : 0}
            onRebuild={editable ? () => setAsk("rebuild") : undefined}
            finished={
              editable && c && c.candidates > 0 && c.pending === 0 && status.status !== "FINALIZED"
                ? { confirmed: c.confirmed, rejected: c.rejected, clarification: c.clarification, revisit: revisitRows.length }
                : null
            }
            onToFinalize={
              canFinalize
                ? () => document.querySelector<HTMLElement>('[aria-label="Финализировать протокол"]')?.focus()
                : undefined
            }
          />

          <div className="col">
            <section className="pane grow">
              {center === "finding" && (
                <>
                  <div className="pane-head">
                    <h2>Карточка находки</h2>
                    {/* Сопоставление листов — одно на запись, а не по значку на каждой странице:
                        стоит в шапке карточки перед листанием записей */}
                    {active && (sideItems.PD.length > 0 || sideItems.RD.length > 0) && (
                      <span className="head-compare">
                        <Tip
                          text="Сопоставить листы ПД и РД во весь экран: масштаб колесом мыши, лист двигается перетаскиванием"
                          place="below"
                        >
                          <button
                            type="button"
                            className="step-btn"
                            aria-label="Сопоставить листы во весь экран"
                            onClick={() => setCompare(true)}
                          >
                            <HeadIcon name="compare" />
                          </button>
                        </Tip>
                      </span>
                    )}
                    <div className="step-nav">
                      <button
                        type="button"
                        className="step-btn"
                        aria-label="Предыдущая запись"
                        title="Предыдущая запись — клавиши ↑ и K"
                        disabled={rowIndex <= 0}
                        onClick={() => move(-1)}
                      >
                        ↑
                      </button>
                      <span className="count">{active ? `${rowIndex + 1} из ${rows.length}` : "—"}</span>
                      <button
                        type="button"
                        className="step-btn"
                        aria-label="Следующая запись"
                        title="Следующая запись — клавиши ↓ и J"
                        disabled={rowIndex < 0 || rowIndex >= rows.length - 1}
                        onClick={() => move(1)}
                      >
                        ↓
                      </button>
                    </div>
                  </div>
                  {active ? (
                    <FindingCard
                      finding={active}
                      editable={editable}
                      busy={busy}
                      rejectOpen={rejectOpen}
                      onRejectOpen={setRejectOpen}
                      onDecide={decide}
                      onSplit={split}
                      comment={draft}
                      onComment={(text) => setDrafts((d) => ({ ...d, [active.id]: text }))}
                      onPickSource={pickSource}
                      processId={processId}
                      onOpenFinding={(id) => {
                        const target = findings.find((f) => f.id === id);
                        const home = target ? tableOf(target) : null;
                        if (!target || !home) return;
                        setTable(home);
                        setActiveId(id);
                        setRejectOpen(false);
                      }}
                      onError={setError}
                    />
                  ) : (
                    <div className="empty-state">{emptyText}</div>
                  )}
                </>
              )}
              {center === "files" && (
                <FilesPane
                  processId={processId}
                  files={files}
                  editable={editable}
                  busy={busy}
                  onChanged={loadDetails}
                  onRebuild={() => setAsk("rebuild")}
                  rebuildBlocked={ownUpload ? "Идёт загрузка из этого окна: протокол пересоберётся после последнего пакета" : null}
                  onError={setError}
                  onShowText={(fileId, title) => {
                    setTextFile({ fileId, title });
                    setCenter("text");
                  }}
                  filter={filesFilter}
                  onFilter={setFilesFilter}
                  onAudit={session.role === "admin" ? openAudit : undefined}
                  revisions={revisions}
                  builtAt={status.protocol?.created_at}
                  onShowChanges={(fileId, title) => {
                    setChangesFile({ fileId, title });
                    setCenter("changes");
                  }}
                />
              )}
              {center === "changes" && changesFile && (
                <RevisionChangesPane
                  processId={processId}
                  fileId={changesFile.fileId}
                  title={changesFile.title}
                  onClose={() => setCenter("files")}
                  onCompare={setRevCompare}
                  onError={setError}
                />
              )}
              {center === "text" && textFile && (
                <FileTextPane
                  processId={processId}
                  fileId={textFile.fileId}
                  title={textFile.title}
                  onClose={() => setCenter("files")}
                />
              )}
              {center === "audit" && (
                <>
                  <div className="pane-head">
                    <h2>Журнал аудита</h2>
                    <span className="count">{audit.length}</span>
                  </div>
                  <div className="card-body">
                    <table className="table audit">
                      <tbody>
                        {audit.map((a) => {
                          const line = auditLine(a.action, a.details);
                          return (
                            <tr key={a.id}>
                              <td className="mono small">{when(a.timestamp)}</td>
                              <td className="mono small">{a.user_id}</td>
                              <td>
                                {line.title}
                                <span className="mono small muted"> {a.action}</span>
                                {line.detail && <div className="small">{line.detail}</div>}
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                </>
              )}
              {center === "reupload" && limits && (
                <>
                  <div className="pane-head">
                    <h2>Дозагрузка документов</h2>
                    <span className="count">протокол пересоберётся новой версией</span>
                  </div>
                  <div className="card-body">
                    <UploadPanel
                      limits={limits}
                      objects={[]}
                      processId={processId}
                      title={status.object_name ?? status.object_id}
                      onUploaded={() => {
                        setCenter("finding");
                        loadStatus();
                        onChanged();
                      }}
                    />
                  </div>
                </>
              )}
            </section>
          </div>

          {/* Страницы нужны карточке находки; в реестре файлов и в тексте пустая заштрихованная
              плашка только занимала место, поэтому колонка убирается совсем (#74). */}
          {center === "finding" && (
          <div className="col col-pages">
            {active ? (
              <>
                <PageCard
                  processId={processId}
                  stage="PD"
                  items={sideItems.PD}
                  value={active.pd_value}
                  index={shownIndex("PD")}
                  onIndex={(i) => showPage("PD", i)}
                  onOpen={() => setViewer({ side: "PD", title: `${STAGE_NAME.PD}: ${active.title ?? active.parameter_code}` })}
                  onError={setError}
                />
                {revisionHint("PD")}
                <PageCard
                  processId={processId}
                  stage="RD"
                  items={sideItems.RD}
                  value={active.rd_value}
                  idValue={active.id_value ?? null}
                  index={shownIndex("RD")}
                  onIndex={(i) => showPage("RD", i)}
                  onOpen={() => setViewer({ side: "RD", title: `${STAGE_NAME.RD}: ${active.title ?? active.parameter_code}` })}
                  onError={setError}
                />
                {revisionHint("RD")}
              </>
            ) : (
              <div className="page-card">
                <div className="plan plan-absent hatched">
                  <span>Страницы появятся, когда выбрана запись протокола</span>
                </div>
              </div>
            )}
          </div>
          )}
        </div>
      )}


      {viewer && active && sideItems[viewer.side].length > 0 && (() => {
        // В карточке РД листаются и страницы ИД: заголовок и значение — стадии показанной страницы,
        // а не стороны, с которой окно открыли
        const shownEvidence = sideItems[viewer.side][shownIndex(viewer.side)];
        const shownValue =
          shownEvidence.stage === "ID" ? (active.id_value ?? null) : viewer.side === "PD" ? active.pd_value : active.rd_value;
        return (
          <PageViewer
            processId={processId}
            evidence={shownEvidence}
            title={`${STAGE_NAME[shownEvidence.stage] ?? STAGE_NAME[viewer.side]}: ${active.title ?? active.parameter_code}`}
            value={shownValue}
            onClose={() => setViewer(null)}
            pager={{
              index: shownIndex(viewer.side),
              total: sideItems[viewer.side].length,
              onIndex: (i) => showPage(viewer.side, i),
            }}
          />
        );
      })()}

      {compare && active && (
        <CompareViewer
          // у другой записи — свои страницы: стороны открываются заново, со страниц из карточки
          key={active.id}
          processId={processId}
          title={active.title ?? active.parameter_code ?? "Сопоставление листов"}
          pd={sideItems.PD}
          rd={sideItems.RD}
          index={{ pd: shownIndex("PD"), rd: shownIndex("RD") }}
          onIndex={(side, i) => showPage(side === "pd" ? "PD" : "RD", i)}
          values={{ PD: active.pd_value, RD: active.rd_value, ID: active.id_value ?? null }}
          onClose={() => setCompare(false)}
          onError={setError}
        />
      )}

      {revCompare && (
        <CompareViewer
          processId={processId}
          title={revCompare.title}
          pd={revCompare.left}
          rd={revCompare.right}
          labels={revCompare.labels}
          note={revCompare.note}
          onClose={() => setRevCompare(null)}
          onError={setError}
        />
      )}
    </div>
  );
}
