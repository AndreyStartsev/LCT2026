// Правила сверки для эксперта (Р-134): последний снимок правил воркера в виде для чтения человеком.
// Страница правил открыта только роли expert — ни инспектору, ни администратору: закрыт и сам маршрут,
// а не только кнопка в интерфейсе.
import { randomUUID } from "node:crypto";
import type { FastifyInstance } from "fastify";
import { authenticate, bearer, requireRole } from "../auth.js";
import { pool } from "../db.js";
import { ApiError } from "../errors.js";
import { iso } from "../process.js";
import { publishRuleTest } from "../queue.js";
import { buildRulesView, ENGINES, NUMERIC, RULE_STATES, variantProblems, type RulesView } from "../rules.js";
import { errorResponses } from "../schemas.js";

const text = { type: "string", nullable: true };
const strings = { type: "array", items: { type: "string" } };
const count = { type: "integer" };

const LOGIC = {
  type: "object",
  nullable: true,
  required: [
    "engine", "editable", "values", "compare", "threshold", "unit", "labels", "exclude", "features", "documents",
    "model", "hypothesis_only", "note",
  ],
  properties: {
    engine: { type: "string", enum: [...ENGINES], nullable: true, description: "как правило находит значение: шаблоны, код или модель" },
    editable: { ...strings, description: "поля, которые песочница может поменять" },
    values: {
      type: "object",
      description: "текущие числа сравнения",
      properties: Object.fromEntries(NUMERIC.map((k) => [k, { type: "number" }])),
    },
    features: {
      type: "array",
      items: { type: "object", required: ["name", "pattern"], properties: { name: { type: "string" }, pattern: { type: "string" } } },
    },
    compare: { ...text, description: "что считается нарушением при этом виде сравнения" },
    threshold: { ...text, description: "порог и допуск словами: «порог Матрицы 1200 мм», «порог 1 %»" },
    unit: text,
    labels: { ...strings, description: "подписи, по которым ищется значение (регулярные выражения)" },
    exclude: { ...strings, description: "слова, при которых строка не берётся" },
    documents: {
      type: "array",
      description: "в каких документах стадии ищется значение: названия или выражение, если названий из него не выделить",
      items: {
        type: "object",
        required: ["stage", "names", "pattern"],
        properties: { stage: { type: "string", enum: ["PD", "RD", "ID"] }, names: strings, pattern: text },
      },
    },
    model: {
      type: "object",
      nullable: true,
      description: "значение с чертежей читает модель: что спрашивается, в каких стадиях и разделах, вопрос целиком",
      required: ["what", "stages", "sections", "prompt"],
      properties: { what: text, stages: strings, sections: strings, prompt: text },
    },
    hypothesis_only: { type: "boolean", description: "расхождение по чертежу — только гипотеза" },
    note: { ...text, description: "пояснение правила без служебных ссылок" },
  },
};

export const RULES_RESPONSE = {
  type: "object",
  required: ["fingerprint", "published_at", "counts", "parameters", "guidance"],
  properties: {
    fingerprint: { type: "string", description: "отпечаток снимка правил воркера" },
    published_at: { type: "string", format: "date-time", description: "когда воркер передал снимок" },
    counts: {
      type: "object",
      required: ["parameters", "active", "draft", "not_checked", "out_of_scope"],
      properties: { parameters: count, active: count, draft: count, not_checked: count, out_of_scope: count },
    },
    parameters: {
      type: "array",
      items: {
        type: "object",
        required: ["code", "state", "sources", "rule", "draft"],
        properties: {
          code: { type: "string" },
          id: { type: "integer", nullable: true },
          name: text,
          section: text,
          queue: { type: "integer", nullable: true },
          criticality: text,
          unit: text,
          sources: {
            type: "object",
            required: ["pd", "rd", "id"],
            properties: { pd: text, rd: text, id: text },
          },
          trigger: { ...text, description: "триггер ошибки из Матрицы 132 параметров" },
          state: { type: "string", enum: [...RULE_STATES] },
          state_note: text,
          rule: LOGIC,
          draft: { ...LOGIC, description: "черновик правила: его расхождения — гипотезы" },
        },
      },
    },
    guidance: {
      type: "array",
      description: "решения специалиста по видам свободного поиска: как показываются записи вида",
      items: {
        type: "object",
        required: ["code", "aspect", "verdict", "submit", "note"],
        properties: {
          code: { type: "string" },
          aspect: text,
          verdict: text,
          submit: { type: "boolean", description: "вид признан нарушением и идёт в сдачу без перевода инспектором" },
          note: text,
        },
      },
    },
  },
};

const TEST_STATUS = ["QUEUED", "RUNNING", "DONE", "FAILED"] as const;
// сколько объектов берёт один прогон: на стенде их два с половиной десятка
const MAX_PROCESSES = 60;

const TEST_SUMMARY = {
  type: "object",
  required: ["id", "code", "variant", "trace", "status", "total", "done", "created_at"],
  properties: {
    id: { type: "string" },
    code: { type: "string" },
    variant: { type: "object", nullable: true, additionalProperties: true, description: "поля правила из песочницы" },
    trace: { type: "boolean" },
    status: { type: "string", enum: [...TEST_STATUS] },
    total: count,
    done: count,
    error: text,
    created_by: text,
    created_at: { type: "string", format: "date-time" },
    started_at: { type: "string", format: "date-time", nullable: true },
    finished_at: { type: "string", format: "date-time", nullable: true },
  },
};

const TEST_FULL = {
  ...TEST_SUMMARY,
  required: [...TEST_SUMMARY.required, "results", "ahead"],
  properties: {
    ...TEST_SUMMARY.properties,
    ahead: { ...count, description: "сколько прогонов в очереди перед этим: воркер берёт их по одному" },
    results: {
      type: "array",
      description: "по объекту: QUEUED — ждёт очереди, DONE — итог прогона, FAILED — прогон на объекте не удался",
      items: {
        type: "object",
        required: ["process_id", "status"],
        properties: {
          process_id: { type: "string" },
          object_id: text,
          object_name: text,
          status: { type: "string", enum: ["QUEUED", "DONE", "FAILED"] },
          error: text,
          elapsed_s: { type: "number", nullable: true },
          result: {
            type: "object",
            nullable: true,
            additionalProperties: true,
            description: "base — записи рабочего правила, variant — варианта и разница, trace — кандидаты по стадиям",
          },
        },
      },
    },
  },
};

// Примерное время прогона на проверке. Почти всё уходит на кандидатов всей очереди — их читает любой
// прогон, — поэтому время растёт с числом страниц проверки, а от правила зависит мало. Замер стенда 28.09
// при прогретом кеше и спокойной машине: запуск около 1,5 с, трасса 1,5 мс на страницу, вариант 2,5 мс.
// Та же проверка идёт и в 5–10 раз дольше: первый прогон после выкладки пересобирает кеш (Полярная 16 —
// 794 с), а под нагрузкой на машину медленно отвечает смонтированный кеш (Новослободская 28.09 вечером —
// 40–100 с вместо 7). Поэтому расчёт по страницам умножается на скорость последних прогонов стенда: во
// сколько раз они шли дольше расчёта — за последний час, по проверкам не меньше MIN_PAGES страниц.
const START_S = 1.5;
const PAGE_S = { trace: 0.0015, variant: 0.0025 };
const MIN_PAGES = 300;
const RECENT = 10;

const ESTIMATE = {
  type: "object",
  required: ["speed", "recent", "processes"],
  properties: {
    speed: { type: "number", description: "во сколько раз последние прогоны шли дольше расчёта по страницам; 1 — без замеров" },
    recent: { ...count, description: "по скольким прогонам за последний час посчитана скорость" },
    processes: {
      type: "array",
      description: "последняя проверка каждого объекта с протоколом — на них идёт прогон по всем объектам",
      items: {
        type: "object",
        required: ["process_id", "object_id", "pages", "trace_s", "variant_s"],
        properties: {
          process_id: { type: "string" },
          object_id: { type: "string" },
          pages: { ...count, description: "страниц в принятых файлах проверки" },
          trace_s: { type: "number", description: "примерное время трассы, секунд" },
          variant_s: { type: "number", description: "примерное время варианта, секунд" },
        },
      },
    },
  },
};

/** Во сколько раз прогоны шли дольше расчёта: по страницам, без времени запуска; 0,5…20. */
export function runSpeed(runs: { elapsed_s: unknown; pages: unknown; variant: unknown }[]): { speed: number; recent: number } {
  const used = runs
    .map((r) => ({ s: Number(r.elapsed_s), pages: Number(r.pages), kind: r.variant ? ("variant" as const) : ("trace" as const) }))
    .filter((r) => Number.isFinite(r.s) && r.s > 0 && r.pages >= MIN_PAGES)
    .slice(0, RECENT);
  if (!used.length) return { speed: 1, recent: 0 };
  const took = used.reduce((sum, r) => sum + Math.max(0, r.s - START_S), 0);
  const model = used.reduce((sum, r) => sum + r.pages * PAGE_S[r.kind], 0);
  return { speed: Math.round(Math.min(20, Math.max(0.5, took / model)) * 10) / 10, recent: used.length };
}

async function latestView(): Promise<RulesView> {
  const { rows } = await pool.query(
    "select fingerprint, body, published_at from rule_snapshots order by published_at desc limit 1",
  );
  const row = rows[0];
  if (!row) {
    throw new ApiError(404, "RULES_NOT_PUBLISHED", "Правила ещё не получены: сервис обработки передаёт их при запуске");
  }
  return buildRulesView(row.body, { fingerprint: row.fingerprint, published_at: iso(row.published_at)! });
}

function summary(row: Record<string, any>) {
  return {
    id: row.id,
    code: row.code,
    variant: row.variant ?? null,
    trace: row.trace,
    status: row.status,
    total: row.total,
    done: row.done,
    error: row.error ?? null,
    created_by: row.created_by ?? null,
    created_at: iso(row.created_at)!,
    started_at: iso(row.started_at),
    finished_at: iso(row.finished_at),
  };
}

export async function rulesRoutes(app: FastifyInstance): Promise<void> {
  app.get(
    "/api/v1/rules",
    {
      preHandler: [authenticate, requireRole("expert")],
      schema: {
        tags: ["rules"],
        summary: "Все правила сверки (эксперт)",
        description:
          "132 параметра Матрицы: что правило сравнивает, каким порогом, в каких документах ищет значение, " +
          "черновики правил и параметры, которые не проверяются, с причиной; решения специалиста по видам " +
          "свободного поиска. Правила — те, которыми разбирает воркер: он передаёт их снимок при запуске. " +
          "Доступно только роли expert.",
        security: bearer,
        response: { 200: RULES_RESPONSE, ...errorResponses },
      },
    },
    async () => latestView(),
  );

  app.post(
    "/api/v1/rules/tests",
    {
      preHandler: [authenticate, requireRole("expert")],
      schema: {
        tags: ["rules"],
        summary: "Пробный прогон правила: трасса или песочница (эксперт)",
        description:
          "Воркер прогоняет правило на проверках объектов и показывает, что оно решило. Без variant — рабочее " +
          "правило: трасса, как оно решило на объекте. С variant — ещё вариант правила и разница с рабочим на тех же " +
          "данных. Ничего не меняется: ни файлы правил, ни протоколы, ни решения инспектора. Без process_ids — " +
          "последняя проверка каждого объекта. Прогон ждёт в очереди, пока воркер обрабатывает документы.",
        security: bearer,
        body: {
          type: "object",
          required: ["code"],
          additionalProperties: false,
          properties: {
            code: { type: "string", maxLength: 32 },
            variant: {
              type: "object",
              nullable: true,
              additionalProperties: true,
              description: "поля правила поверх рабочего: compare {threshold, trigger, tolerance, tolerance_pct}, labels, exclude, features",
            },
            process_ids: { type: "array", maxItems: MAX_PROCESSES, items: { type: "string", format: "uuid" } },
            trace: { type: "boolean", description: "кандидаты по стадиям в итоге; по умолчанию — если объект один" },
          },
        },
        response: { 202: TEST_SUMMARY, 422: { $ref: "Error#" }, 503: { $ref: "Error#" }, ...errorResponses },
      },
    },
    async (request, reply) => {
      const body = request.body as { code: string; variant?: Record<string, unknown> | null; process_ids?: string[]; trace?: boolean };
      const view = await latestView();
      const param = view.parameters.find((p) => p.code === body.code);
      const logic = param?.rule ?? param?.draft ?? null;
      if (!param || !logic) {
        throw new ApiError(422, "NO_MACHINE_RULE", `У параметра ${body.code} нет машинного правила: прогонять нечего`);
      }
      const problems = variantProblems(body.variant, logic);
      if (problems.length) {
        throw new ApiError(422, "BAD_VARIANT", `Вариант правила не принят: ${problems.join("; ")}`, { problems });
      }
      const { rows } = body.process_ids?.length
        ? await pool.query(
            `select p.id from processes p where p.id = any($1::uuid[])
               and exists (select 1 from protocols pr where pr.process_id = p.id)`,
            [body.process_ids],
          )
        : await pool.query(
            `select distinct on (p.object_id) p.id from processes p
              where exists (select 1 from protocols pr where pr.process_id = p.id)
              order by p.object_id, p.created_at desc`,
          );
      const found = new Set(rows.map((r) => String(r.id)));
      const processIds = body.process_ids?.length ? body.process_ids.filter((id) => found.has(id)) : [...found];
      if (body.process_ids?.length && processIds.length !== body.process_ids.length) {
        throw new ApiError(422, "PROCESS_NOT_READY", "У части выбранных проверок нет протокола: прогонять правило не на чем");
      }
      if (!processIds.length) throw new ApiError(422, "PROCESS_NOT_READY", "На стенде нет проверок с протоколом");
      if (processIds.length > MAX_PROCESSES) processIds.length = MAX_PROCESSES;
      const variant = body.variant && Object.keys(body.variant).length ? body.variant : null;
      const trace = body.trace ?? processIds.length === 1;
      const id = randomUUID();
      const inserted = await pool.query(
        `insert into rule_tests (id, code, variant, trace, process_ids, total, created_by)
         values ($1, $2, $3, $4, $5, $6, $7) returning *`,
        [id, body.code, variant, trace, JSON.stringify(processIds), processIds.length, request.user.sub],
      );
      try {
        await publishRuleTest(id, request.user.sub, request.id);
      } catch (error) {
        request.log.error({ err: error }, "пробный прогон не поставлен в очередь");
        await pool.query("update rule_tests set status = 'FAILED', error = $2, finished_at = now() where id = $1", [
          id,
          "очередь недоступна",
        ]);
        throw new ApiError(503, "QUEUE_UNAVAILABLE", "Очередь обработки недоступна: пробный прогон не поставлен");
      }
      reply.status(202);
      return summary(inserted.rows[0]);
    },
  );

  app.get(
    "/api/v1/rules/tests",
    {
      preHandler: [authenticate, requireRole("expert")],
      schema: {
        tags: ["rules"],
        summary: "Последние пробные прогоны правила (эксперт)",
        security: bearer,
        querystring: {
          type: "object",
          required: ["code"],
          additionalProperties: false,
          properties: { code: { type: "string", maxLength: 32 } },
        },
        response: {
          200: { type: "object", required: ["tests"], properties: { tests: { type: "array", items: TEST_SUMMARY } } },
          ...errorResponses,
        },
      },
    },
    async (request) => {
      const { code } = request.query as { code: string };
      const { rows } = await pool.query(
        "select * from rule_tests where code = $1 order by created_at desc limit 20",
        [code],
      );
      return { tests: rows.map(summary) };
    },
  );

  app.get(
    "/api/v1/rules/tests/estimate",
    {
      preHandler: [authenticate, requireRole("expert")],
      schema: {
        tags: ["rules"],
        summary: "Примерное время пробного прогона по объектам (эксперт)",
        description:
          "По последней проверке каждого объекта с протоколом: сколько примерно займёт трасса и вариант правила. " +
          "Оценка — по числу страниц проверки и скорости прогонов стенда за последний час. Ожидание очереди в неё не входит.",
        security: bearer,
        response: { 200: ESTIMATE, ...errorResponses },
      },
    },
    async () => {
      const pagesOf = (alias: string) =>
        `(select coalesce(sum(f.pdf_pages), 0) from files f where f.process_id = ${alias} and f.status = 'ACCEPTED')`;
      const [latest, recent] = await Promise.all([
        pool.query(
          `with l as (
             select distinct on (p.object_id) p.id, p.object_id from processes p
              where exists (select 1 from protocols pr where pr.process_id = p.id)
              order by p.object_id, p.created_at desc)
           select l.id, l.object_id, ${pagesOf("l.id")} as pages from l order by l.object_id`,
        ),
        pool.query(
          `select r.elapsed_s, t.variant is not null as variant, ${pagesOf("r.process_id")} as pages
             from rule_test_results r join rule_tests t on t.id = r.test_id
            where r.status = 'DONE' and r.finished_at > now() - interval '1 hour'
            order by r.finished_at desc limit 50`,
        ),
      ]);
      const { speed, recent: used } = runSpeed(recent.rows);
      const secs = (pages: number, kind: keyof typeof PAGE_S) => Math.round((START_S + pages * PAGE_S[kind] * speed) * 10) / 10;
      return {
        speed,
        recent: used,
        processes: latest.rows.map((r) => {
          const pages = Number(r.pages) || 0;
          return { process_id: String(r.id), object_id: String(r.object_id), pages, trace_s: secs(pages, "trace"), variant_s: secs(pages, "variant") };
        }),
      };
    },
  );

  app.get(
    "/api/v1/rules/tests/:id",
    {
      preHandler: [authenticate, requireRole("expert")],
      schema: {
        tags: ["rules"],
        summary: "Ход и итог пробного прогона правила (эксперт)",
        security: bearer,
        params: { type: "object", required: ["id"], properties: { id: { type: "string", format: "uuid" } } },
        response: { 200: TEST_FULL, ...errorResponses },
      },
    },
    async (request) => {
      const { id } = request.params as { id: string };
      const { rows } = await pool.query("select * from rule_tests where id = $1", [id]);
      const test = rows[0];
      if (!test) throw new ApiError(404, "NOT_FOUND", "Пробный прогон не найден: прогоны старше двух недель убираются");
      const processIds: string[] = (test.process_ids ?? []).map(String);
      const [results, names, queued] = await Promise.all([
        pool.query(
          "select process_id, object_id, status, result, error, elapsed_s from rule_test_results where test_id = $1",
          [id],
        ),
        pool.query(
          "select p.id, p.object_id, o.name from processes p join objects o on o.id = p.object_id where p.id = any($1::uuid[])",
          [processIds],
        ),
        // воркер берёт прогоны по одному: ждущему прогону важно, сколько их впереди
        test.status === "QUEUED"
          ? pool.query(
              "select count(*)::int as ahead from rule_tests where status in ('QUEUED', 'RUNNING') and created_at < $1",
              [test.created_at],
            )
          : Promise.resolve({ rows: [{ ahead: 0 }] }),
      ]);
      const byProcess = new Map(results.rows.map((r) => [String(r.process_id), r]));
      const nameOf = new Map(names.rows.map((r) => [String(r.id), r]));
      return {
        ...summary(test),
        ahead: Number(queued.rows[0]?.ahead ?? 0),
        results: processIds.map((pid) => {
          const r = byProcess.get(pid);
          const named = nameOf.get(pid);
          return {
            process_id: pid,
            object_id: r?.object_id ?? named?.object_id ?? null,
            object_name: named?.name ?? null,
            status: r ? r.status : "QUEUED",
            error: r?.error ?? null,
            elapsed_s: r?.elapsed_s ?? null,
            result: r?.result ?? null,
          };
        }),
      };
    },
  );
}
