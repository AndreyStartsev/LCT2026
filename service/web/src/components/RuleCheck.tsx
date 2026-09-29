import { useEffect, useMemo, useState } from "react";
import {
  api,
  ApiFailure,
  currentLogin,
  type NumericKey,
  type ObjectItem,
  type RuleEstimate,
  type RuleItem,
  type RuleLogic,
  type RuleProposal,
  type RuleTest,
  type TestCandidate,
  type TestChange,
  type TestFinding,
  type TestResult,
  type TestTrace,
} from "../api";
import { LABEL, LOCATION_TYPE, VERDICT } from "../labels";

interface Props {
  item: RuleItem;
  /** правило, которое прогоняется: рабочее, а без него — черновик */
  logic: RuleLogic;
  objects: ObjectItem[];
  /** предложения правки этого правила: прогон, из которого уже предложено, второй раз не предлагается */
  proposals: RuleProposal[];
  /** предложение сохранено — список предложений на странице обновляется */
  onProposed: () => void;
  /** прогон поставлен или закончился — пометка прогонов в перечне обновляется */
  onRunChange?: () => void;
}

const NUMERIC_LABEL: Record<NumericKey, { title: string }> = {
  threshold: { title: "Порог" },
  trigger: { title: "Порог Матрицы" },
  tolerance: { title: "Допуск" },
  tolerance_pct: { title: "Допуск, %" },
};

/**
 * Как записывать число поля. Порог и допуск бывают долей (у сравнения «отклоняется от проектного»: порог 1 %
 * записан как 0,01) и значением в единицах правила (ширина проезда: порог 4,2 м записан как 4,2) — какой
 * случай, видно по порогу словами.
 */
function numericHint(key: NumericKey, logic: RuleLogic): string {
  if (key === "tolerance_pct") return "в процентах";
  if ((key === "threshold" || key === "tolerance") && /%/.test(logic.threshold ?? "")) {
    return "доля записывается дробью: 0,05 — это 5 %";
  }
  return logic.unit ? `в единицах правила, ${logic.unit}` : "в единицах правила";
}

/** Место записи словами: код вида места («SITE») — как в карточке записи инспектора. */
function place(location: string): string {
  const word = LOCATION_TYPE[location];
  return word ? word[0].toUpperCase() + word.slice(1) : location;
}
const STAGE_TITLE = { PD: "ПД", RD: "РД", ID: "ИД" } as const;
const CHANGE_WORD: Record<TestChange["change"], string> = {
  added: "появится",
  removed: "пропадёт",
  changed: "изменится",
};
const POLL_MS = 1500;
// свой прогон правила показывается снова, если вернуться к правилу в течение полусуток
const RESTORE_MS = 12 * 3600 * 1000;
const ESTIMATE_HINT = "Оценка — по числу страниц объекта и скорости последних прогонов на стенде. Ожидание в очереди в неё не входит.";

function times(n: number): string {
  const last = n % 10;
  return last >= 2 && last <= 4 && (n % 100 < 12 || n % 100 > 14) ? "раза" : "раз";
}

/** Подсказка к оценке: если прогоны сейчас идут дольше обычного, сказать во сколько раз. */
function estimateHint(speed: number | undefined): string {
  if (!speed || speed < 1.5) return ESTIMATE_HINT;
  const n = Math.round(speed);
  return `${ESTIMATE_HINT} Сейчас прогоны идут дольше обычного примерно в ${n} ${times(n)}.`;
}

/** «около 8 с», «около 4 мин», «около 1 ч 10 мин». */
function about(seconds: number | null | undefined): string | null {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return null;
  if (seconds < 60) return `около ${Math.max(1, Math.round(seconds))} с`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `около ${minutes} мин`;
  return `около ${Math.floor(minutes / 60)} ч${minutes % 60 ? ` ${minutes % 60} мин` : ""}`;
}

function took(run: RuleTest): string | null {
  if (!run.started_at || !run.finished_at) return null;
  const s = (Date.parse(run.finished_at) - Date.parse(run.started_at)) / 1000;
  if (!Number.isFinite(s) || s < 0) return null;
  return s < 60 ? `${Math.max(1, Math.round(s))} с` : `${Math.round(s / 60)} мин`;
}

export function when(iso: string): string {
  const d = new Date(iso);
  const time = d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  return d.toDateString() === new Date().toDateString()
    ? time
    : `${d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" })} ${time}`;
}

/** Что поменяно в варианте — словами: «порог 0,05; подписи: 2». */
export function describeVariant(variant: Record<string, unknown>): string {
  const out: string[] = [];
  const compare = (variant.compare ?? {}) as Partial<Record<NumericKey, number>>;
  for (const [key, value] of Object.entries(compare)) {
    const title = NUMERIC_LABEL[key as NumericKey]?.title ?? key;
    out.push(`${title.toLowerCase()} ${String(value).replace(".", ",")}`);
  }
  const listed = (key: string, word: string) => {
    if (Array.isArray(variant[key])) out.push(`${word}: ${(variant[key] as unknown[]).length}`);
  };
  listed("labels", "подписи");
  listed("exclude", "исключения");
  listed("features", "признаки");
  return out.join("; ");
}

interface Estimates {
  speed: number;
  byObject: Map<string, RuleEstimate>;
}

// Оценка времени одна на страницу правил: берётся раз в минуту и после каждого прогона — прогон её уточняет
let estimates: { at: number; data: Promise<Estimates> } | null = null;
function loadEstimates(fresh = false): Promise<Estimates> {
  if (fresh || !estimates || Date.now() - estimates.at > 60_000) {
    const data = api
      .ruleTestEstimate()
      .then((r) => ({ speed: r.speed, byObject: new Map(r.processes.map((p) => [p.object_id, p])) }));
    estimates = { at: Date.now(), data };
    data.catch(() => {
      estimates = null;
    });
  }
  return estimates.data;
}

function lines(text: string): string[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
}

function number(text: string): number | null {
  const n = Number(text.trim().replace(",", "."));
  return text.trim() && Number.isFinite(n) ? n : null;
}

function same(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((x, i) => x === b[i]);
}

/** Вариант правила из формы: только поля, которые отличаются от рабочего правила. */
function buildVariant(
  logic: RuleLogic,
  nums: Partial<Record<NumericKey, string>>,
  labels: string,
  exclude: string,
  features: string,
): { variant: Record<string, unknown> | null; problems: string[] } {
  const variant: Record<string, unknown> = {};
  const problems: string[] = [];
  const compare: Record<string, number> = {};
  for (const key of Object.keys(logic.values) as NumericKey[]) {
    const raw = nums[key] ?? "";
    const n = number(raw);
    if (n === null || n < 0) problems.push(`${NUMERIC_LABEL[key].title}: нужно неотрицательное число`);
    else if (n !== logic.values[key]) compare[key] = n;
  }
  if (Object.keys(compare).length) variant.compare = compare;
  if (logic.editable.includes("labels")) {
    const got = lines(labels);
    if (!got.length) problems.push("Подписи: нужна хотя бы одна");
    else if (!same(got, logic.labels)) variant.labels = got;
  }
  if (logic.editable.includes("exclude")) {
    const got = lines(exclude);
    if (!same(got, logic.exclude)) variant.exclude = got;
  }
  if (logic.editable.includes("features")) {
    const parsed = lines(features).map((l) => {
      const at = l.indexOf("=");
      return at > 0 ? { name: l.slice(0, at).trim(), pattern: l.slice(at + 1).trim() } : null;
    });
    if (parsed.some((f) => !f || !f.name || !f.pattern)) problems.push("Признаки: строка вида «название = выражение»");
    else {
      const got = parsed as { name: string; pattern: string }[];
      const before = logic.features.map((f) => `${f.name}=${f.pattern}`);
      if (!same(got.map((f) => `${f.name}=${f.pattern}`), before)) variant.features = got;
    }
  }
  return { variant: Object.keys(variant).length ? variant : null, problems };
}

function Finding({ f, quiet = false }: { f: TestFinding; quiet?: boolean }) {
  // в перемене решение инспектора сказано её заголовком — у «было» и «станет» его не повторяем
  const verdict = quiet ? null : f.decision;
  return (
    <div className="rules-finding">
      <b>{(f.violation_label && LABEL[f.violation_label]) ?? f.violation_label ?? "—"}</b>
      {f.locations.length > 0 && <span className="muted"> · {f.locations.map(place).join(", ")}</span>}
      <span>
        {" "}
        · ПД {f.pd_value ?? "—"} → РД {f.rd_value ?? "—"}
        {f.id_value ? ` · ИД ${f.id_value}` : ""}
      </span>
      {verdict && <span className="rules-decision"> · решение инспектора: {VERDICT[verdict]?.word ?? verdict}</span>}
      {f.detail && <div className="small muted">{f.detail}</div>}
    </div>
  );
}

function Candidate({ c }: { c: TestCandidate }) {
  return (
    <li className={c.chosen ? "chosen" : undefined}>
      <span className="mono small">
        {c.document ?? c.file_id} · стр. {c.page ?? "—"}
      </span>{" "}
      <b>{c.raw ?? c.value ?? "—"}</b>
      {c.chosen && <span className="rules-chosen"> выбрано</span>}
      {c.recognized && <span className="small muted"> · распознано</span>}
      {c.snippet && <div className="small muted">{c.snippet}</div>}
    </li>
  );
}

/** Что правило нашло по стадиям: выбранное значение, прочие значения стадии, что отбросили исключения. */
function Trace({ trace, title }: { trace: TestTrace; title: string }) {
  return (
    <div className="rules-trace" aria-label={title}>
      <div className="rules-trace-title">{title}</div>
      <div className="rules-stages">
        {(["PD", "RD", "ID"] as const).map((stage) => {
          const s = trace.stages[stage];
          return (
            <div key={stage} className="rules-stage">
              <div className="rules-stage-head">
                <b>{STAGE_TITLE[stage]}</b>{" "}
                {s.total ? (
                  <span className="small">
                    значений {s.total} в документах: {s.documents}; выбрано: {s.chosen.length ? s.chosen.join("; ") : "—"}
                  </span>
                ) : (
                  <span className="small muted">значение не найдено</span>
                )}
              </div>
              {s.candidates.length > 0 && (
                <ul className="rules-cands">
                  {s.candidates.map((c, i) => (
                    <Candidate key={`${c.file_id}-${c.page}-${i}`} c={c} />
                  ))}
                  {s.total > s.candidates.length && (
                    <li className="small muted">и ещё {s.total - s.candidates.length}</li>
                  )}
                </ul>
              )}
            </div>
          );
        })}
      </div>
      {trace.excluded_total > 0 && (
        <details className="rules-more">
          <summary>Отбросили исключения правила · {trace.excluded_total}</summary>
          <ul className="rules-cands">
            {trace.excluded.map((c, i) => (
              <Candidate key={`x-${c.file_id}-${c.page}-${i}`} c={{ ...c, chosen: false }} />
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export function Changes({ changes }: { changes: TestChange[] }) {
  return (
    <ul className="rules-changes">
      {changes.map((c) => (
        <li key={`${c.change}-${c.finding_id}`}>
          <b>{CHANGE_WORD[c.change]}</b>
          {c.decision && <span className="rules-decision"> · спорит с решением инспектора: {VERDICT[c.decision]?.word ?? c.decision}</span>}
          {c.before && (
            <div className="rules-was">
              <span className="small muted">было: </span>
              <Finding f={c.before} quiet />
            </div>
          )}
          {c.after && (
            <div>
              <span className="small muted">станет: </span>
              <Finding f={c.after} quiet />
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

function ObjectResult({ result }: { result: TestResult }) {
  return (
    <div className="rules-result">
      <div className="small muted">
        прочитано страниц {result.pages_read} · {String(result.elapsed_s).replace(".", ",")} с
      </div>
      <div className="rules-trace-title">Вывод рабочего правила</div>
      {result.base.findings.length ? (
        result.base.findings.map((f) => <Finding key={f.finding_id} f={f} />)
      ) : (
        <div className="small muted">записей нет: значение не найдено ни в одной стадии</div>
      )}
      {result.variant && (
        <>
          <div className="rules-trace-title">Что изменит вариант</div>
          {result.variant.changes.length ? (
            <Changes changes={result.variant.changes} />
          ) : (
            <div className="small muted">ничего: записи те же</div>
          )}
        </>
      )}
      {result.trace && <Trace trace={result.trace} title="Как решило рабочее правило" />}
      {result.variant?.trace && <Trace trace={result.variant.trace} title="Как решил вариант" />}
    </div>
  );
}

/** Итог прогона по многим объектам: где вариант что-то меняет и спорит ли с решениями инспекторов. */
function Summary({ run }: { run: RuleTest }) {
  const results = run.results ?? [];
  const done = results.filter((r) => r.status === "DONE" && r.result);
  const failed = results.filter((r) => r.status === "FAILED");
  const moved = done.filter((r) => r.result!.variant?.changes.length);
  const changes = moved.reduce((n, r) => n + r.result!.variant!.changes.length, 0);
  const disputed = moved.reduce((n, r) => n + r.result!.variant!.changes.filter((c) => c.decision).length, 0);
  return (
    <div className="rules-summary">
      <div className="rules-summary-head">
        {changes
          ? `Вариант меняет записей: ${changes} — на объектах: ${moved.length} из ${done.length}`
          : `На ${done.length} объектах вариант ничего не меняет`}
        {disputed > 0 && <span className="rules-decision"> · спорит с решениями инспекторов: {disputed}</span>}
      </div>
      {moved.map((r) => (
        <details key={r.process_id} className="rules-more" open={moved.length <= 3}>
          <summary>
            {r.object_name ?? r.object_id} · перемен {r.result!.variant!.changes.length}
          </summary>
          <Changes changes={r.result!.variant!.changes} />
        </details>
      ))}
      {failed.length > 0 && (
        <div className="small">
          Не прогнано на объектах: {failed.map((r) => `${r.object_name ?? r.object_id} — ${r.error ?? "сбой"}`).join("; ")}
        </div>
      )}
    </div>
  );
}

/**
 * Предложить вариант правкой правила (#224): вариант с разницей по объектам сохраняется на стенде,
 * разработчик переносит его в правила сервиса после проверки качества и отмечает, что сделано.
 */
function Propose({ run, proposed, onProposed }: { run: RuleTest; proposed: RuleProposal | null; onProposed: () => void }) {
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (proposed) {
    return (
      <div className="rules-propose small">
        Вариант предложен {when(proposed.created_at)} — {PROPOSAL_WORD[proposed.status]}. Предложение — ниже, в «Предложениях
        правки».
      </div>
    );
  }
  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.ruleProposalCreate({ test_id: run.id, ...(comment.trim() ? { comment: comment.trim() } : {}) });
      onProposed();
    } catch (e) {
      // вариант уже предложен из другой вкладки — показать его, а не ошибку
      if (e instanceof ApiFailure && e.code === "PROPOSAL_EXISTS") onProposed();
      else setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="rules-propose">
      <label className="rules-field">
        <span className="k">Зачем правка — для разработчика</span>
        <textarea
          rows={2}
          maxLength={2000}
          value={comment}
          placeholder="Например: подпись шире — находит «объём здания» в пояснительной записке"
          onChange={(e) => setComment(e.target.value)}
        />
      </label>
      <div className="rules-check-row">
        <button type="button" className="btn" disabled={busy} onClick={submit}>
          Предложить правку
        </button>
        <span className="small muted">
          {run.total === 1
            ? "Вариант проверен на одном объекте: перед переносом разработчик прогонит его на всех."
            : "Правила сервиса предложение не меняет: разработчик перенесёт правку после проверки качества."}
        </span>
      </div>
      {error && <div className="alert">{error}</div>}
    </div>
  );
}

/** Статус предложения словами — те же, что в «Предложениях правки»; короткие — для пометки в перечне. */
export const PROPOSAL_WORD: Record<RuleProposal["status"], string> = {
  NEW: "ждёт разработчика",
  APPLIED: "перенесено в правила",
  REJECTED: "отклонено",
};
export const PROPOSAL_MARK: Record<RuleProposal["status"], string> = {
  NEW: "предложено",
  APPLIED: "перенесено",
  REJECTED: "отклонено",
};

/**
 * Проверка правила на объектах стенда (#222, #223). «Как правило решило» — трасса рабочего правила на
 * выбранном объекте, у любого правила. Песочница — вариант правила: у паттерна подписи, исключения и порог,
 * у правила с моделью порог и допуск; по умолчанию на выбранном объекте, по желанию — на всех. У правила
 * с разбором в коде песочницы нет: код в ней не меняют. Рядом с кнопками — примерное время прогона.
 * Ничего на стенде не меняется: прогон считает в воркере, что дало бы правило, и показывает разницу
 * с рабочим на тех же данных. Прогон живёт в сервисе: вернувшись к правилу, эксперт видит свой прогон снова.
 */
export default function RuleCheck({ item, logic, objects, proposals, onProposed, onRunChange }: Props) {
  const ready = useMemo(
    () =>
      objects
        .filter((o) => o.last_process?.protocol_version != null)
        .sort((a, b) => a.name.localeCompare(b.name, "ru")),
    [objects],
  );
  const [objectId, setObjectId] = useState(() => ready[0]?.object_id ?? "");
  const [nums, setNums] = useState<Partial<Record<NumericKey, string>>>(() =>
    Object.fromEntries(Object.entries(logic.values).map(([k, v]) => [k, String(v).replace(".", ",")])),
  );
  const [labels, setLabels] = useState(logic.labels.join("\n"));
  const [exclude, setExclude] = useState(logic.exclude.join("\n"));
  const [features, setFeatures] = useState(logic.features.map((f) => `${f.name} = ${f.pattern}`).join("\n"));
  const [scope, setScope] = useState<"all" | "one">("one");
  const [run, setRun] = useState<RuleTest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [estimate, setEstimate] = useState<Estimates | null>(null);

  useEffect(() => {
    if (!objectId && ready[0]) setObjectId(ready[0].object_id);
  }, [ready, objectId]);

  useEffect(() => {
    let live = true;
    loadEstimates()
      .then((m) => live && setEstimate(m))
      .catch(() => live && setEstimate(null));
    return () => {
      live = false;
    };
  }, []);

  // Свой последний прогон правила — снова на экране: уход на другую страницу или к другому правилу
  // его не теряет, воркер считает его и без открытой страницы. У правила с кодом — только трасса:
  // прежний прогон песочницы для него показывать незачем
  useEffect(() => {
    let live = true;
    const me = currentLogin();
    const withVariant = logic.engine !== "code";
    api
      .ruleTests(item.code)
      .then(({ tests }) => {
        const mine = tests.find(
          (t) =>
            t.created_by === me && Date.now() - Date.parse(t.created_at) < RESTORE_MS && (withVariant || !t.variant),
        );
        return mine ? api.ruleTest(mine.id) : null;
      })
      .then((t) => {
        if (live && t) setRun((current) => current ?? t);
      })
      .catch(() => {
        // без прежнего прогона страница работает как обычно
      });
    return () => {
      live = false;
    };
  }, [item.code, logic.engine]);

  // ход прогона: воркер берёт его после обработки документов и считает по объекту за раз
  useEffect(() => {
    if (!run || run.status === "DONE" || run.status === "FAILED") return;
    const timer = window.setTimeout(() => {
      api
        .ruleTest(run.id)
        .then((next) => {
          setRun(next);
          if (next.status === "DONE" || next.status === "FAILED") {
            onRunChange?.();
            // замер этого прогона уточняет оценку следующих
            loadEstimates(true)
              .then(setEstimate)
              .catch(() => {});
          }
        })
        .catch((e) => setError((e as Error).message));
    }, POLL_MS);
    return () => window.clearTimeout(timer);
  }, [run]);

  const { variant, problems } = buildVariant(logic, nums, labels, exclude, features);
  const processId = ready.find((o) => o.object_id === objectId)?.last_process?.process_id;
  const running = !!run && (run.status === "QUEUED" || run.status === "RUNNING");
  // у правила с разбором в коде песочницы нет: код в ней не меняют (решение 28.09)
  const sandbox = logic.engine !== "code";
  // править есть что: числа сравнения или шаблоны; «compare» в editable бывает и без чисел
  const canEdit =
    Object.keys(logic.values).length +
      (["labels", "exclude", "features"] as const).filter((k) => logic.editable.includes(k)).length >
    0;
  const oneTrace = about(estimate?.byObject.get(objectId)?.trace_s);
  const oneVariant = about(estimate?.byObject.get(objectId)?.variant_s);
  // сумма — только по объектам с оценкой: без неё «около 1 с» на все объекты обманывало бы
  const known = estimate ? ready.filter((o) => estimate.byObject.has(o.object_id)) : [];
  const allVariant = known.length
    ? about(known.reduce((sum, o) => sum + (estimate!.byObject.get(o.object_id)?.variant_s ?? 0), 0))
    : null;
  const hint = estimateHint(estimate?.speed);
  const remaining = (() => {
    if (!run || !estimate || run.status !== "RUNNING" || !run.results) return null;
    const key = run.variant ? "variant_s" : "trace_s";
    const left = run.results
      .filter((r) => r.status === "QUEUED")
      .reduce((sum, r) => sum + (estimate.byObject.get(r.object_id ?? "")?.[key] ?? 0), 0);
    return left > 0 ? about(left) : null;
  })();

  async function start(withVariant: boolean) {
    if (!processId && (!withVariant || scope === "one")) return;
    setBusy(true);
    setError(null);
    try {
      const body = withVariant
        ? { code: item.code, variant, ...(scope === "one" ? { process_ids: [processId!], trace: true } : {}) }
        : { code: item.code, process_ids: [processId!], trace: true };
      setRun(await api.ruleTestStart(body));
      onRunChange?.();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const single = run?.results?.length === 1 ? run.results[0] : null;
  const runTitle = run
    ? [
        run.variant ? "Песочница" : "Трасса",
        single?.object_name ?? single?.object_id ?? null,
        run.variant ? describeVariant(run.variant) : null,
        when(run.created_at),
      ]
        .filter(Boolean)
        .join(" · ")
    : "";
  return (
    <section className="rules-check" aria-label="Проверка на объектах">
      <h3>Проверка на объектах</h3>
      <p className="small muted">
        Прогон ничего не меняет на стенде: ни правила, ни протоколы, ни решения инспекторов. Сервис берёт его, когда
        закончит обработку документов.
      </p>
      {ready.length === 0 ? (
        <div className="empty-state">На стенде нет проверенных объектов: прогонять правило не на чем.</div>
      ) : (
        <div className="rules-check-row">
          <label className="rules-field">
            <span className="k">Объект</span>
            <select value={objectId} onChange={(e) => setObjectId(e.target.value)} aria-label="Объект для проверки">
              {ready.map((o) => (
                <option key={o.object_id} value={o.object_id}>
                  {o.name}
                </option>
              ))}
            </select>
          </label>
          <button type="button" className="btn" disabled={busy || running || !processId} onClick={() => start(false)}>
            Как правило решило
          </button>
          {oneTrace && (
            <span className="small muted rules-eta" title={hint}>
              {oneTrace}
            </span>
          )}
        </div>
      )}

      {ready.length > 0 && !sandbox && (
        <p className="small muted">
          Разбор этого правила написан в коде: в песочнице такие правила не прогоняются — код в ней не меняют. Как правило
          решило на объекте, показывает трасса.
        </p>
      )}
      {ready.length > 0 && sandbox && (
        <details className="rules-sandbox">
          <summary>Песочница: вариант правила</summary>
          {!canEdit && (
            <p className="small muted">У этого правила в песочнице менять нечего: у него нет порога и шаблонов.</p>
          )}
          {canEdit && (
            <div className="rules-form">
              {(Object.keys(logic.values) as NumericKey[]).map((key) => (
                <label key={key} className="rules-field">
                  <span className="k">{NUMERIC_LABEL[key].title}</span>
                  <input
                    type="text"
                    inputMode="decimal"
                    value={nums[key] ?? ""}
                    onChange={(e) => setNums({ ...nums, [key]: e.target.value })}
                  />
                  <span className="small muted">
                    сейчас {String(logic.values[key]).replace(".", ",")} · {numericHint(key, logic)}
                  </span>
                </label>
              ))}
              {logic.editable.includes("labels") && (
                <label className="rules-field wide">
                  <span className="k">Подписи — по одной на строку</span>
                  <textarea rows={Math.min(8, Math.max(2, logic.labels.length + 1))} value={labels} onChange={(e) => setLabels(e.target.value)} />
                </label>
              )}
              {logic.editable.includes("exclude") && (
                <label className="rules-field wide">
                  <span className="k">Исключения — строка не берётся, если в подписи есть</span>
                  <textarea rows={Math.min(8, Math.max(2, logic.exclude.length + 1))} value={exclude} onChange={(e) => setExclude(e.target.value)} />
                </label>
              )}
              {logic.editable.includes("features") && (
                <label className="rules-field wide">
                  <span className="k">Признаки — «название = выражение», по одному на строку</span>
                  <textarea rows={Math.min(8, Math.max(2, logic.features.length + 1))} value={features} onChange={(e) => setFeatures(e.target.value)} />
                </label>
              )}
              {logic.engine === "llm" && (
                <p className="small muted wide">
                  Значение читает модель: в песочнице меняются порог и допуск, ответы модели берутся уже полученные.
                </p>
              )}
              <div className="rules-check-row wide" role="radiogroup" aria-label="На каких объектах прогнать">
                <label title={hint}>
                  <input type="radio" checked={scope === "one"} onChange={() => setScope("one")} /> выбранный объект — с трассой
                  {oneVariant && <span className="small muted"> · {oneVariant}</span>}
                </label>
                <label title={hint}>
                  <input type="radio" checked={scope === "all"} onChange={() => setScope("all")} /> все объекты стенда ({ready.length})
                  {allVariant && <span className="small muted"> · {allVariant}</span>}
                </label>
                <button
                  type="button"
                  className="btn btn-primary"
                  disabled={busy || running || !variant || problems.length > 0}
                  onClick={() => start(true)}
                >
                  Прогнать вариант
                </button>
              </div>
              {problems.length > 0 && <div className="alert wide">{problems.join("; ")}</div>}
              {!variant && problems.length === 0 && (
                <div className="small muted wide">Вариант совпадает с рабочим правилом: поменяйте порог или шаблоны.</div>
              )}
            </div>
          )}
        </details>
      )}

      {error && <div className="alert">{error}</div>}
      {run && (
        <div className="rules-run" aria-live="polite">
          <div className="rules-run-state">
            {runTitle}:{" "}
            {run.status === "QUEUED"
              ? run.ahead
                ? `в очереди — перед ним прогонов: ${run.ahead}`
                : "в очереди — ждёт, пока сервис закончит обработку документов"
              : run.status === "RUNNING"
                ? `идёт прогон — объектов ${run.done} из ${run.total}${remaining ? `, осталось ${remaining}` : ""}`
                : run.status === "FAILED"
                  ? `не выполнен — ${run.error ?? "сбой"}`
                  : `готово — объектов ${run.total}${took(run) ? ` за ${took(run)}` : ""}`}
          </div>
          {running && (
            <div className="small muted">
              Прогон идёт в сервисе: можно уйти на другую страницу или к другому правилу — вернитесь к этому, и итог будет
              здесь.
            </div>
          )}
          {single?.status === "DONE" && single.result && <ObjectResult result={single.result} />}
          {single?.status === "FAILED" && run.status !== "FAILED" && <div className="alert">{single.error}</div>}
          {!single && run.results && run.results.some((r) => r.status !== "QUEUED") && <Summary run={run} />}
          {run.variant && run.status === "DONE" && (
            <Propose run={run} proposed={proposals.find((p) => p.test_id === run.id) ?? null} onProposed={onProposed} />
          )}
        </div>
      )}
    </section>
  );
}
