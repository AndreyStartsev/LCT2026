import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import {
  api,
  type Engine,
  type ObjectItem,
  type RuleActivity,
  type RuleItem,
  type RuleLogic,
  type RuleProposal,
  type RuleState,
  type RulesView,
} from "../api";
import { ENGINE, FREE_SEARCH_KINDS, MATRIX_SECTION, SPECIALIST, when } from "../labels";
import { SpecialistMark } from "./Marks";
import RuleCheck, { PROPOSAL_MARK, when as shortWhen } from "./RuleCheck";
import RuleProposals from "./RuleProposals";
import Tip from "./Tip";

/**
 * Состояние параметра в правилах — те же группы, что в покрытии протокола и на дашборде: работает,
 * черновик (нарушения — гипотезами), не проверяется (правило на проверке), вне проверки документов.
 * Без цвета: цвет на листе — только у решений.
 */
const STATES: { key: RuleState; word: string; label: string; hint: string }[] = [
  { key: "ACTIVE", word: "работает", label: "Работают", hint: "правило сравнивает параметр в каждой проверке" },
  {
    key: "DRAFT",
    word: "черновик",
    label: "Черновики",
    hint: "черновик правила: расхождения показываются гипотезами, в сдачу — только решением инспектора",
  },
  { key: "NOT_CHECKED", word: "не проверяется", label: "Не проверяются", hint: "правило на проверке: параметр пока не сравнивается" },
  {
    key: "OUT_OF_SCOPE",
    word: "вне документов",
    label: "Вне проверки документов",
    hint: "по документам не проверяется: событие стадии строительства во внешней системе или сравнивать не с чем",
  },
];
const STATE = Object.fromEntries(STATES.map((s) => [s.key, s])) as Record<RuleState, (typeof STATES)[number]>;

type Filter = RuleState | "all" | "free";

const STAGE: Record<string, string> = { PD: "ПД", RD: "РД", ID: "ИД" };
// разделы вопроса модели по чертежам — коды реестра файлов
const SECTION_SHORT: Record<string, string> = {
  PZ: "ПЗ", GP: "ГП", AR: "АР", KR: "КР", OV: "ОВ", VK: "ВК", EOM: "ЭОМ", SS: "СС", PB: "ПБ", POS: "ПОС", OTHER: "прочие",
};

/** Раздел Матрицы по коду параметра: «AR-040» — «раздел 3, АР». */
function sectionTitle(code: string): string {
  return MATRIX_SECTION[code.split("-")[0]] ?? "прочие параметры";
}

function matches(text: string, query: string): boolean {
  return text.toLocaleLowerCase("ru").includes(query);
}

type Entry = { kind: "param"; key: string; group: string; item: RuleItem } | { kind: "free"; key: string; group: string; code: string; title: string };

/** Правило, которое работает по параметру: рабочее, а без него — черновик. */
function tested(item: RuleItem): RuleLogic | null {
  return item.rule ?? item.draft ?? null;
}

/** Тип правила бейджем (#222): паттерн, код или LLM — где живёт разбор значения. */
function EngineMark({ engine }: { engine: Engine | null | undefined }) {
  if (!engine || !ENGINE[engine]) return null;
  return (
    <Tip text={`Тип правила — ${ENGINE[engine].word}. ${ENGINE[engine].hint}`}>
      <span className={`rules-engine e-${engine}`}>{ENGINE[engine].word}</span>
    </Tip>
  );
}

function StateMark({ state }: { state: RuleState }) {
  return (
    <Tip text={`${STATE[state].label}: ${STATE[state].hint}`}>
      <span className={`rules-state s-${state}`}>{STATE[state].word}</span>
    </Tip>
  );
}

function Logic({ logic, title }: { logic: RuleLogic; title: string }) {
  return (
    <section className="rules-logic" aria-label={title}>
      <h3>{title}</h3>
      <dl className="kv">
        {logic.compare && (
          <>
            <dt>Сравнение</dt>
            <dd>{logic.compare}</dd>
          </>
        )}
        {logic.threshold && (
          <>
            <dt>Порог</dt>
            <dd>{logic.threshold}</dd>
          </>
        )}
        {logic.documents.length > 0 && (
          <>
            <dt>Документы</dt>
            <dd>
              {logic.documents.map((d) => (
                <div key={d.stage}>
                  {STAGE[d.stage] ?? d.stage}:{" "}
                  {d.names.length ? d.names.join(", ") : <span className="mono small">{d.pattern}</span>}
                </div>
              ))}
            </dd>
          </>
        )}
        {logic.model && (
          <>
            <dt>С чертежей</dt>
            <dd>
              значение читает модель{logic.model.what ? `: ${logic.model.what}` : ""}
              {logic.model.stages.length > 0 && ` · ${logic.model.stages.map((s) => STAGE[s] ?? s).join(", ")}`}
              {logic.model.sections.length > 0 && ` · ${logic.model.sections.map((s) => SECTION_SHORT[s] ?? s).join(", ")}`}
            </dd>
          </>
        )}
        {logic.hypothesis_only && (
          <>
            <dt>Итог</dt>
            <dd>расхождение по чертежу — гипотеза для инспектора, нарушение — только его решением</dd>
          </>
        )}
      </dl>
      {logic.note && <p className="rules-note">{logic.note}</p>}
      {logic.labels.length > 0 && (
        <details className="rules-more">
          <summary>Подписи, по которым ищется значение · {logic.labels.length}</summary>
          <ul className="rules-codes">
            {logic.labels.map((l) => (
              <li key={l}>{l}</li>
            ))}
          </ul>
          {logic.exclude.length > 0 && (
            <>
              <div className="small muted">строка не берётся, если в подписи есть:</div>
              <ul className="rules-codes">
                {logic.exclude.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </>
          )}
        </details>
      )}
      {logic.model?.prompt && (
        <details className="rules-more">
          <summary>Вопрос модели по листу</summary>
          <p className="rules-prompt">{logic.model.prompt}</p>
        </details>
      )}
    </section>
  );
}

/**
 * Прогоны правила в перечне (Р-165): идёт или был за последний час — зелёный кружок, прогоны раньше —
 * коричневый. Оттенки свои, не карандаши решения: кружок — о прогонах эксперта, а не о решении инспектора.
 */
const FRESH_MS = 3600 * 1000;
type RunState = "running" | "fresh" | "old";
const RUN_END: Record<RuleActivity["last_status"], string> = {
  DONE: "готово",
  FAILED: "не выполнен",
  QUEUED: "в очереди",
  RUNNING: "идёт",
};

function runState(a: RuleActivity, now: number): RunState {
  if (a.active > 0) return "running";
  return now - Date.parse(a.last_at) <= FRESH_MS ? "fresh" : "old";
}

function runLabel(a: RuleActivity, state: RunState): string {
  const what = a.last_variant ? "вариант" : "трасса";
  const who = a.last_by ? ` · ${a.last_by}` : "";
  if (state === "running") {
    const head = a.active > 1 ? `Идут прогоны: ${a.active}` : a.last_status === "QUEUED" ? "Прогон в очереди" : "Идёт прогон";
    return `${head} · ${what}${who}`;
  }
  const head = state === "fresh" ? "Прогон за последний час" : "Последний прогон";
  const more = a.runs > 1 ? ` · прогонов за две недели: ${a.runs}` : "";
  return `${head}: ${shortWhen(a.last_at)} · ${what} · ${RUN_END[a.last_status]}${who}${more}`;
}

function RunDot({ a, now }: { a: RuleActivity | undefined; now: number }) {
  if (!a) return null;
  const state = runState(a, now);
  const label = runLabel(a, state);
  return <span className={`rules-run-dot r-${state}`} role="img" aria-label={label} title={label} />;
}

function ParamCard({
  item,
  objects,
  proposals,
  onProposed,
  onRunChange,
}: {
  item: RuleItem;
  objects: ObjectItem[];
  proposals: RuleProposal[];
  onProposed: () => void;
  onRunChange: () => void;
}) {
  const logic = tested(item);
  return (
    <>
      <div className="rules-card-head">
        <span className="mono">{item.code}</span>
        <h2>{item.name}</h2>
        <EngineMark engine={logic?.engine} />
        <StateMark state={item.state} />
      </div>
      <div className="small muted">
        {sectionTitle(item.code)}
        {item.queue ? ` · очередь ${item.queue}` : ""}
        {item.criticality ? ` · ${item.criticality}` : ""}
      </div>
      <dl className="kv rules-matrix">
        <dt>Триггер Матрицы</dt>
        <dd>{item.trigger ?? "—"}</dd>
        <dt>Источник в ПД</dt>
        <dd>{item.sources.pd ?? "—"}</dd>
        <dt>Источник в РД</dt>
        <dd>{item.sources.rd ?? "—"}</dd>
        <dt>Источник в ИД</dt>
        <dd>{item.sources.id ?? "—"}</dd>
        {item.unit && (
          <>
            <dt>Единица</dt>
            <dd>{item.unit}</dd>
          </>
        )}
      </dl>
      {item.state_note && <div className="note-line">{item.state_note}</div>}
      {item.rule && <Logic logic={item.rule} title="Как проверяется" />}
      {item.draft && <Logic logic={item.draft} title={item.rule ? "Черновик новой редакции правила" : "Черновик правила"} />}
      {logic && (
        <RuleCheck
          key={item.code}
          item={item}
          logic={logic}
          objects={objects}
          proposals={proposals}
          onProposed={onProposed}
          onRunChange={onRunChange}
        />
      )}
      <RuleProposals proposals={proposals} />
    </>
  );
}

/** Что решение специалиста о виде значит для его записей — как их показывает протокол (pipeline/specialist.py). */
function consequence(g: RulesView["guidance"][number]): string {
  if (g.verdict === "violation" && g.submit) return "записи вида идут в кандидаты и в сдачу без перевода инспектором";
  if (g.verdict === "drop") return "записи вида — в конце таблицы гипотез, с низкой уверенностью";
  if (g.verdict === "need_info") return "записи вида — гипотезы с пометкой: для вывода не хватает данных";
  return "записи вида — гипотезы с пометкой";
}

function FreeCard({ code, title, guidance }: { code: string; title: string; guidance: RulesView["guidance"] }) {
  const mine = guidance.filter((g) => g.code === code);
  return (
    <>
      <div className="rules-card-head">
        <span className="mono">{code}</span>
        <h2>{title}</h2>
      </div>
      <div className="small muted">свободный поиск · вне Матрицы 132 параметров</div>
      <p className="rules-note">
        Правило ищет расхождение по логике самого проекта, а не по параметру Матрицы. Записи выходят гипотезами: в итоги
        нарушений запись попадает после перевода в кандидаты и решения инспектора, если специалист не признал вид
        нарушением.
      </p>
      <h3>Решение специалиста о таких записях</h3>
      {mine.length === 0 ? (
        <p className="empty-state">Решения по этому виду нет: записи показываются гипотезами.</p>
      ) : (
        <ul className="rules-guidance">
          {mine.map((g, i) => (
            <li key={`${g.aspect ?? ""}-${i}`}>
              {g.verdict && <SpecialistMark specialist={{ verdict: g.verdict, reviewed: null, note: g.note, cases: [] }} />}
              <b>{g.verdict ? SPECIALIST[g.verdict]?.word ?? g.verdict : "—"}</b>
              {g.aspect && <span className="muted"> · {g.aspect}</span>}
              <span className="muted"> — {consequence(g)}</span>
              {g.note && <div>{g.note}</div>}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

/**
 * Все правила сверки — страница эксперта (Р-134). Правила — те, которыми разбирает воркер: он передаёт
 * их снимок при запуске. Слева — параметры Матрицы по разделам и виды свободного поиска, справа —
 * правило выбранного: триггер и источники Матрицы, что сравнивается и каким порогом, где ищется
 * значение, вопрос модели по чертежам, черновик и почему параметр не проверяется.
 */
export default function RulesScreen({ objects }: { objects: ObjectItem[] }) {
  const [data, setData] = useState<RulesView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [engine, setEngine] = useState<Engine | "all">("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [proposals, setProposals] = useState<RuleProposal[]>([]);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .rules()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  // предложения правки (#224) — все сразу: пометка в перечне и раздел в карточке правила
  function loadProposals() {
    api
      .ruleProposals()
      .then((r) => setProposals(r.proposals))
      .catch(() => {
        // без предложений страница правил работает как обычно
      });
  }
  useEffect(loadProposals, []);
  const proposalsOf = useMemo(() => {
    const out = new Map<string, RuleProposal[]>();
    for (const p of proposals) out.set(p.code, [...(out.get(p.code) ?? []), p]);
    return out;
  }, [proposals]);
  const waiting = proposals.filter((p) => p.status === "NEW").length;

  // прогоны по правилам (Р-165): пока что-то идёт — раз в 15 с, иначе раз в минуту — так и свежий прогон
  // через час становится давним без перезагрузки страницы
  const [activity, setActivity] = useState<Map<string, RuleActivity>>(new Map());
  const [now, setNow] = useState(() => Date.now());
  function loadActivity() {
    api
      .ruleActivity()
      .then((r) => {
        setActivity(new Map(r.rules.map((a) => [a.code, a])));
        setNow(Date.now());
      })
      .catch(() => {
        // без пометки прогонов перечень работает как обычно
      });
  }
  useEffect(loadActivity, []);
  const anyActive = [...activity.values()].some((a) => a.active > 0);
  useEffect(() => {
    const timer = window.setInterval(loadActivity, anyActive ? 15_000 : 60_000);
    return () => window.clearInterval(timer);
  }, [anyActive]);

  const entries = useMemo<Entry[]>(() => {
    if (!data) return [];
    const params: Entry[] = data.parameters.map((item) => ({ kind: "param", key: item.code, group: sectionTitle(item.code), item }));
    // виды, о которых специалист решал, а в перечне страницы их нет, — тоже показываются
    const known = new Set(FREE_SEARCH_KINDS.map((k) => k.code));
    const extra = [...new Set(data.guidance.map((g) => g.code))].filter((c) => !known.has(c)).map((code) => ({ code, title: code }));
    const free: Entry[] = [...FREE_SEARCH_KINDS, ...extra].map((k) => ({
      kind: "free",
      key: k.code,
      group: "свободный поиск",
      code: k.code,
      title: k.title,
    }));
    return [...params, ...free];
  }, [data]);

  const shown = useMemo(() => {
    const q = query.trim().toLocaleLowerCase("ru");
    return entries.filter((e) => {
      if (filter === "free" ? e.kind !== "free" : filter !== "all" && (e.kind !== "param" || e.item.state !== filter)) return false;
      if (engine !== "all" && (e.kind !== "param" || tested(e.item)?.engine !== engine)) return false;
      if (!q) return true;
      if (e.kind === "free") return matches(`${e.code} ${e.title}`, q);
      const r = e.item;
      return matches(
        [r.code, r.name, r.trigger, r.state_note, r.rule?.note, r.draft?.note, r.sources.pd, r.sources.rd, r.sources.id]
          .filter(Boolean)
          .join(" "),
        q,
      );
    });
  }, [entries, filter, query, engine]);

  // типы — по работающим правилам и черновикам: у параметра без машинного правила типа нет
  const engineCounts = useMemo(() => {
    const out: Record<string, number> = {};
    for (const p of data?.parameters ?? []) {
      const e = tested(p)?.engine;
      if (e) out[e] = (out[e] ?? 0) + 1;
    }
    return out;
  }, [data]);

  // выбранное правило ушло из отбора — открыть первое из оставшихся
  const current = shown.find((e) => e.key === selected) ?? shown[0] ?? null;

  const counts = data?.counts;
  const freeCount = entries.filter((e) => e.kind === "free").length;
  const FILTERS: { key: Filter; label: string; count: number; hint: string }[] = counts
    ? [
        { key: "all", label: "Все", count: counts.parameters + freeCount, hint: "параметры Матрицы и виды свободного поиска" },
        ...STATES.map((s) => ({
          key: s.key as Filter,
          label: s.label,
          count: { ACTIVE: counts.active, DRAFT: counts.draft, NOT_CHECKED: counts.not_checked, OUT_OF_SCOPE: counts.out_of_scope }[s.key],
          hint: s.hint,
        })),
        { key: "free", label: "Свободный поиск", count: freeCount, hint: "правила вне Матрицы: расхождения по логике самого проекта" },
      ]
    : [];

  function onListKey(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    event.preventDefault();
    const at = current ? shown.indexOf(current) : -1;
    const next = shown[Math.min(shown.length - 1, Math.max(0, at + (event.key === "ArrowDown" ? 1 : -1)))];
    if (!next) return;
    setSelected(next.key);
    listRef.current?.querySelector<HTMLElement>(`[data-key="${CSS.escape(next.key)}"]`)?.focus();
  }

  let lastGroup = "";
  return (
    <div className="frame">
      <header className="sheet-head">
        <div>
          <h1>Правила</h1>
          <div className="sub">Все правила сверки: параметры Матрицы и свободный поиск</div>
        </div>
        {counts && data && (
          <div className="head-meta">
            <div className="head-cell">
              <span className="k">Работают</span>
              <span className="v">
                {counts.active} из {counts.parameters}
              </span>
            </div>
            <div className="head-cell">
              <span className="k">Черновики</span>
              <span className="v">{counts.draft}</span>
            </div>
            {proposals.length > 0 && (
              <Tip text="Предложения правки из песочницы: сколько ждут разработчика, из всех предложенных">
                <div className="head-cell">
                  <span className="k">Предложения</span>
                  <span className="v">
                    {waiting} из {proposals.length}
                  </span>
                </div>
              </Tip>
            )}
            <Tip
              text={
                "Правила, которыми сервис сейчас разбирает документы: обработка передаёт их при каждом запуске. " +
                `Версия ${data.fingerprint.slice(0, 12)}`
              }
            >
              <div className="head-cell">
                <span className="k">Правила получены</span>
                <span className="v">{when(data.published_at)}</span>
              </div>
            </Tip>
          </div>
        )}
      </header>
      {error && <div className="alert">{error}</div>}
      {!data && !error && <div className="empty-state">Загрузка правил…</div>}

      {data && (
        <>
          <div className="toolbar">
            <div className="filters" role="group" aria-label="Отбор по состоянию правила">
              {FILTERS.map((f) => (
                <Tip key={f.key} place="above" text={`${f.label}: ${f.hint}`}>
                  <button type="button" className="filter" aria-pressed={filter === f.key} onClick={() => setFilter(f.key)}>
                    {f.label} <span className="count">{f.count}</span>
                  </button>
                </Tip>
              ))}
            </div>
            <input
              id="rules-search"
              type="search"
              className="search"
              placeholder="Код, параметр, триггер или пояснение"
              aria-label="Поиск по правилам"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>

          {Object.keys(engineCounts).length > 0 && (
            <div className="toolbar toolbar-2">
              <div className="filters" role="group" aria-label="Отбор по типу правила">
                <Tip place="above" text="Тип правила: где живёт разбор значения. Считаются работающие правила и черновики">
                  <span className="filters-label">Тип</span>
                </Tip>
                <button type="button" className="filter" aria-pressed={engine === "all"} onClick={() => setEngine("all")}>
                  все
                </button>
                {(["pattern", "code", "llm"] as const)
                  .filter((k) => engineCounts[k])
                  .map((k) => (
                    <Tip key={k} place="above" text={`${ENGINE[k].word}: ${ENGINE[k].hint}`}>
                      <button
                        type="button"
                        className="filter"
                        aria-pressed={engine === k}
                        onClick={() => setEngine(engine === k ? "all" : k)}
                      >
                        {ENGINE[k].word} <span className="count">{engineCounts[k]}</span>
                      </button>
                    </Tip>
                  ))}
              </div>
              {activity.size > 0 && (
                <div className="rules-run-legend small muted">
                  <span className="rules-run-dot r-fresh" aria-hidden="true" /> прогон идёт или был за последний час
                  <span className="rules-run-dot r-old" aria-hidden="true" /> прогоны раньше
                </div>
              )}
            </div>
          )}

          <div className="rules-work">
            <section className="pane">
              <div className="pane-head">
                <h2>Перечень</h2>
                <span className="count">{shown.length}</span>
              </div>
              {shown.length === 0 ? (
                <div className="empty-state">Под отбор ничего не попало.</div>
              ) : (
                <div className="list" role="listbox" aria-label="Правила" ref={listRef} onKeyDown={onListKey}>
                  {shown.map((e) => {
                    const head = e.group !== lastGroup ? e.group : null;
                    lastGroup = e.group;
                    const active = current?.key === e.key;
                    return (
                      <div key={e.key} role="presentation">
                        {head && <div className="list-sub">{head}</div>}
                        <button
                          type="button"
                          role="option"
                          className="row rules-row"
                          data-key={e.key}
                          aria-selected={active}
                          aria-current={active}
                          tabIndex={active ? 0 : -1}
                          onClick={() => setSelected(e.key)}
                        >
                          <span className="row-top">
                            <span>{e.kind === "param" ? e.item.code : e.code}</span>
                            {e.kind === "param" && <RunDot a={activity.get(e.item.code)} now={now} />}
                            {e.kind === "param" && tested(e.item)?.engine && (
                              <span className={`rules-engine e-${tested(e.item)!.engine}`}>{ENGINE[tested(e.item)!.engine!].word}</span>
                            )}
                            {/* в строке — только исключения, как у пометки уверенности: «работает» у ста строк ничего не
                                говорит; в карточке состояние видно всегда */}
                            {e.kind === "param" && e.item.state !== "ACTIVE" && (
                              <span className={`rules-state s-${e.item.state}`}>{STATE[e.item.state].word}</span>
                            )}
                            {/* последнее предложение правки правила — его статус */}
                            {e.kind === "param" && proposalsOf.get(e.item.code)?.[0] && (
                              <span className={`rules-pmark ps-${proposalsOf.get(e.item.code)![0].status}`}>
                                {PROPOSAL_MARK[proposalsOf.get(e.item.code)![0].status]}
                              </span>
                            )}
                          </span>
                          <span className="row-title">{e.kind === "param" ? e.item.name : e.title}</span>
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </section>

            <section className="pane rules-card" aria-live="polite">
              {current ? (
                <div className="rules-card-body">
                  {current.kind === "param" ? (
                    <ParamCard
                      item={current.item}
                      objects={objects}
                      proposals={proposalsOf.get(current.item.code) ?? []}
                      onProposed={loadProposals}
                      onRunChange={loadActivity}
                    />
                  ) : (
                    <FreeCard code={current.code} title={current.title} guidance={data.guidance} />
                  )}
                </div>
              ) : (
                <div className="empty-state">Выберите правило в списке слева.</div>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}
