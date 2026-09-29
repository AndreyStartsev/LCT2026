// Схемы запросов и ответов. Из них же собирается описание OpenAPI 3.0,
// поэтому типы записаны в его диалекте: nullable вместо массива типов.
import type { FastifyInstance } from "fastify";

export const PROCESS_STATUSES = ["PENDING", "PARSING", "READY", "VERIFYING", "COMPLETED", "FINALIZED"];
export const VERIFICATION_STATUSES = [
  "PENDING",
  "CONFIRMED_VIOLATION",
  "NEGATIVE_VERIFIED",
  "CLARIFICATION_REQUIRED",
  "NOT_REQUIRED",
  "SPLIT",
];
// Стадии и разделы документов конвейера (pipeline/config.py): ими инспектор поправляет
// стадию файла, когда её не удалось определить по пути (#39). RD_ID_MIXED — папка,
// в которой лежат и рабочая, и исполнительная документация.
export const DOC_STAGES = ["PD", "RD", "ID", "RD_ID_MIXED"];
export const DOC_SECTIONS = ["PZ", "GP", "AR", "KR", "OV", "VK", "EOM", "SS", "PB", "POS", "OTHER"];

export const REASON_CODES = ["WRONG_REVISION", "APPROVED_CHANGE", "OCR_ERROR", "LINKING_ERROR", "NOT_APPLICABLE"];

/**
 * Способ чтения объекта (#54). layer — только текстовый слой; tesseract — слой и распознавание
 * сканов; model — слой, распознавание и мультимодальная модель на сканах и чертежах. Выбор
 * делается при загрузке: где-то хватает слоя, а где-то без модели система молчит.
 */
export const READING_MODES = ["layer", "tesseract", "model"];

const nullableString = { type: "string", nullable: true };
const nullableInt = { type: "integer", nullable: true };
const dateTime = { type: "string", format: "date-time" };
const nullableDateTime = { type: "string", format: "date-time", nullable: true };
const sideSourceSchema = {
  type: "object",
  nullable: true,
  properties: { text_source: nullableString, binding: nullableString },
};

export const sharedSchemas: Record<string, unknown>[] = [
  {
    $id: "Error",
    type: "object",
    required: ["error"],
    properties: {
      error: {
        type: "object",
        required: ["code", "message"],
        properties: {
          code: { type: "string" },
          message: { type: "string" },
          details: { type: "object", nullable: true, additionalProperties: true },
        },
      },
    },
  },
  {
    $id: "Rejected",
    type: "object",
    required: ["relative_path", "code", "message"],
    properties: {
      relative_path: { type: "string" },
      code: { type: "string" },
      message: { type: "string" },
    },
  },
  {
    $id: "Limits",
    type: "object",
    required: ["max_file_mb", "max_package_mb", "formats"],
    properties: {
      max_file_mb: { type: "number", description: "Лимит файла при загрузке в браузере, МБ" },
      max_package_mb: { type: "number", description: "Лимит пакета при загрузке в браузере, МБ" },
      formats: { type: "array", items: { type: "string" } },
      loader_path: {
        type: "string",
        description: "Маршрут загрузчика папки объекта (роль admin): лимитов размера файла и пакета у него нет",
      },
      reading_models: {
        type: "array",
        description:
          "Модели для способа чтения «модель» (#54): инспектор выбирает одну при загрузке. " +
          "Пустой список — выбор не предлагается, работает модель сервиса",
        items: {
          type: "object",
          required: ["id", "label"],
          properties: { id: { type: "string" }, label: { type: "string" } },
        },
      },
      model_default: { ...nullableString, description: "Модель сервиса по умолчанию" },
      external_model: {
        type: "boolean",
        description:
          "Чтение моделью уходит во внешний сервис: страницы нового комплекта прочитает внешняя модель. " +
          "Отдаётся только в /api/v1/health и только когда хоть один воркер жив и сообщил признак",
      },
    },
  },
  {
    $id: "Processing",
    type: "object",
    description:
      "Состояние задания в очереди. У ТЗ нет статуса процесса для сбоя обработки, " +
      "поэтому сбой виден здесь, а статус процесса остаётся в жизненном цикле ТЗ.",
    properties: {
      state: { type: "string", enum: ["IDLE", "QUEUED", "RUNNING", "DONE", "FAILED"] },
      step: nullableString,
      attempt: nullableInt,
      message: nullableString,
      error: nullableString,
      queued_at: nullableString,
      started_at: nullableString,
      finished_at: nullableString,
    },
    additionalProperties: true,
  },
  {
    $id: "FindingCounts",
    type: "object",
    description:
      "Счётчики для пяти таблиц протокола ТЗ: кандидаты и решения по ним; no_violation — проверено, " +
      "расхождения нет; not_comparable — сравнение невозможно; split — составные записи, разделённые инспектором; " +
      "hypotheses — записи свободного поиска, не переведённые в кандидаты: они не входят в candidates и pending.",
    required: ["total", "candidates", "pending", "hypotheses", "confirmed", "rejected", "clarification", "split", "no_violation", "not_comparable"],
    properties: {
      total: { type: "integer" },
      candidates: { type: "integer" },
      pending: { type: "integer" },
      hypotheses: { type: "integer" },
      confirmed: { type: "integer" },
      rejected: { type: "integer" },
      clarification: { type: "integer" },
      split: { type: "integer" },
      no_violation: { type: "integer" },
      not_comparable: { type: "integer" },
      revisit: {
        type: "integer",
        description:
          "Записи с решением инспектора, у которых после дозагрузки изменились значения: решение " +
          "принято по прежним значениям и его надо пересмотреть. Новое решение отметку снимает.",
      },
      by_section: {
        type: "object",
        description:
          "По разделам Матрицы (ключ — начало кода параметра: PZ, SPZU, AR, KR, IOS1…IOS5, POS, POD, OOS, PPM, ODI, ZU, SM): " +
          "сколько записей ждут решения и сколько подтверждено. Разделы без таких записей не перечисляются.",
        additionalProperties: {
          type: "object",
          properties: { candidates: { type: "integer" }, confirmed: { type: "integer" } },
        },
      },
    },
  },
  {
    $id: "ProcessStatus",
    type: "object",
    required: ["process_id", "object_id", "status", "upload_status", "processing", "files", "created_at", "updated_at"],
    properties: {
      process_id: { type: "string", format: "uuid" },
      object_id: { type: "string" },
      object_name: { type: "string" },
      status: { type: "string", enum: PROCESS_STATUSES },
      scenario: nullableString,
      upload_status: { type: "array", items: { type: "string" } },
      reading_mode: {
        ...nullableString,
        description:
          `Способ чтения объекта, выбранный при загрузке (#54), одно из ${READING_MODES.join(", ")}: ` +
          "layer — только текстовый слой, " +
          "tesseract — слой и распознавание сканов, model — слой, распознавание и модель. " +
          "null — читается способом сервиса",
      },
      model_name: {
        ...nullableString,
        description:
          "Модель, выбранная при загрузке для режима «модель» (#54); null — модель сервиса. " +
          "Чем объект прочитан на самом деле, видно в readiness.model_name после разбора",
      },
      processing: { $ref: "Processing#" },
      progress: {
        type: "object",
        nullable: true,
        additionalProperties: true,
        properties: {
          step: { type: "string" },
          message: { type: "string" },
          done: { type: "integer" },
          total: { type: "integer" },
          updated_at: { type: "string" },
        },
      },
      files: {
        type: "object",
        required: ["accepted", "rejected", "bytes"],
        properties: {
          accepted: { type: "integer" },
          rejected: { type: "integer" },
          bytes: { type: "integer" },
        },
      },
      protocol_version: nullableInt,
      protocol: {
        type: "object",
        description: "Последняя версия протокола и версии Матрицы, набора данных и конвейера, по которым она собрана",
        properties: {
          version: { type: "integer" },
          status: { type: "string" },
          matrix_version: nullableString,
          dataset_version: nullableString,
          model_version: nullableString,
          created_at: dateTime,
        },
      },
      findings: { $ref: "FindingCounts#" },
      coverage: {
        type: "object",
        nullable: true,
        description:
          "Охват Матрицы последней версией протокола: compared — параметров, по которым значения " +
          "сопоставлены (правило есть и хотя бы одна запись сравнена), total — параметров в Матрице. " +
          "Считается так же, как группа COMPARED дашборда и раздела 2 протокола. Без сравнения — " +
          "параметры с правилом прода, по которым значения не сопоставлены: missing_evidence — нет " +
          "доказательств (значения или документа нет в одной из стадий), not_comparable — значения " +
          "несопоставимы; как одноимённые группы дашборда.",
        properties: {
          compared: { type: "integer" },
          total: { type: "integer" },
          missing_evidence: { type: "integer" },
          not_comparable: { type: "integer" },
        },
      },
      readiness: {
        type: "object",
        nullable: true,
        additionalProperties: true,
        description:
          "Готовность объекта (#39): pages, pages_without_text, share_without_text, stage_unknown, " +
          "section_other, unsupported, pages_low_quality, ocr_enabled, model_enabled, by_text_source, " +
          "reading_mode и model_name — чем объект прочитан на самом деле (#54). " +
          "Считается при разборе, лежит в отчёте протокола",
      },
      recompute: {
        type: "object",
        nullable: true,
        additionalProperties: true,
        description:
          "Что пересчитано при последней обработке, а что перенесено из прошлой версии (#60): " +
          "full, reason, documents_read, documents_total, recomputed, carried_over. " +
          "Дозагрузка пересчитывает только параметры, которых коснулись новые документы",
      },
      sync: {
        type: "object",
        nullable: true,
        description: "Передача финализированного протокола в ИАИС «РиН» (ТЗ 9.6): PENDING_SYNC, SYNCED, REJECTED, CANCELLED",
        properties: {
          status: { type: "string" },
          protocol_version: { type: "integer" },
          attempts: { type: "integer" },
          max_retries: { type: "integer" },
          next_attempt_at: nullableDateTime,
          last_error: nullableString,
          last_status_code: nullableInt,
          external_id: nullableString,
          created_at: nullableDateTime,
          updated_at: nullableDateTime,
          synced_at: nullableDateTime,
        },
      },
      created_at: dateTime,
      updated_at: dateTime,
      finalized_at: nullableDateTime,
    },
  },
  {
    $id: "Protocol",
    type: "object",
    description:
      "Протокол в формате сдачи организатора (contracts/submission.schema.json). " +
      "Записи несут и дополнительные поля проекции: matrix_scope, comparison_result, " +
      "parameter_id, location_type, document_status.",
    required: ["object_id", "checks"],
    properties: {
      object_id: { type: "string" },
      checks: {
        type: "array",
        items: {
          type: "object",
          required: ["parameter_code", "location", "violation_label", "evidence"],
          additionalProperties: true,
          properties: {
            parameter_code: { type: "string" },
            location: { type: "string" },
            pd_value: {},
            rd_value: {},
            id_value: {},
            violation_label: {
              type: "string",
              enum: ["VIOLATION_PRESENT", "NO_VIOLATION", "MISSING_DOCUMENT", "COMPARISON_IMPOSSIBLE"],
            },
            protocol_status: {
              type: "string",
              enum: ["OK", "WARNING", "CRITICAL", "ID_MISSING", "RD_MISSING", "PD_MISSING", "COMPARISON_IMPOSSIBLE"],
            },
            criticality: nullableString,
            evidence: {
              type: "array",
              items: {
                type: "object",
                required: ["stage", "file_id", "pdf_page_number"],
                additionalProperties: true,
                properties: {
                  stage: { type: "string", enum: ["PD", "RD", "ID"] },
                  file_id: { type: "string" },
                  pdf_page_number: { type: "integer", minimum: 1 },
                },
              },
            },
          },
        },
      },
    },
    additionalProperties: true,
  },
  {
    $id: "Finding",
    type: "object",
    required: ["id", "finding_id", "verification_status"],
    properties: {
      id: { type: "string", format: "uuid" },
      finding_id: { type: "string" },
      protocol_version: { type: "integer" },
      parameter_code: nullableString,
      parameter_id: nullableInt,
      location: nullableString,
      violation_label: nullableString,
      protocol_status: nullableString,
      criticality: nullableString,
      pd_value: nullableString,
      rd_value: nullableString,
      id_value: { ...nullableString, description: "Значение исполнительной документации (#42)" },
      id_check: { ...nullableString, description: "Итог сверки с исполнительной документацией (#42)" },
      sources: {
        type: "object",
        description:
          "Чем прочитано значение стороны и к чему привязано (#41): text_source RECOGNIZED — распознано машиной " +
          "(Tesseract или модель); binding CLAUSE — из указаний, SHEET — с листа чертежа, PAGE — со страницы, PATH — по пути файла",
        properties: {
          pd: sideSourceSchema,
          rd: sideSourceSchema,
          id: sideSourceSchema,
        },
      },
      needs_expert: {
        type: "boolean",
        description: "Система не решает сама (#41): распознанное значение, расхождение со слоем, замена марки — решает инспектор",
      },
      value_read_by: {
        type: "object",
        description: "RECOGNIZED у стороны, значение которой прочитано машиной, а не текстовым слоем (#52)",
        properties: { pd: nullableString, rd: nullableString, id: nullableString },
      },
      finding_status: {
        ...nullableString,
        description:
          "Статус по легенде организатора к Матрице с учётом решения инспектора (#80): CANDIDATE, CONFIRMED_VIOLATION, " +
          "NEGATIVE_VERIFIED, CLARIFICATION_REQUIRED, MISSING_EVIDENCE, NOT_COMPARABLE, SUSPICION",
      },
      specialist: {
        type: "object",
        nullable: true,
        description:
          "Решение специалиста (#129, Р-86, Р-108): violation — подтверждено нарушением, need_info — специалисту не " +
          "хватило данных, no_violation — не нарушение, hypothesis — вид показывать гипотезой, drop — специалист решил вид " +
          "не показывать (по решению пользователя такие записи видны в конце таблицы гипотез; как исполнено — в note). scope — к чему " +
          "решение: kind — к виду гипотезы, record — к этой записи с теми значениями, которые видел специалист",
        required: ["verdict"],
        properties: {
          verdict: { type: "string", enum: ["violation", "need_info", "no_violation", "hypothesis", "drop"] },
          scope: { type: "string", enum: ["kind", "record"] },
          reviewed: nullableString,
          note: nullableString,
          cases: { type: "array", items: { type: "string" } },
        },
      },
      confidence: {
        type: "object",
        nullable: true,
        description:
          "Уверенность в выводе (#80): уровень — для отбора, и признаки, из которых он сложен. Процента нет: " +
          "уровень выводится из признаков записи и показывается вместе с ними. HIGH — признаков сомнения нет, " +
          "MEDIUM — вывод опирается на то, что стоит проверить глазами (прочитано машиной, взято с листа, " +
          "соперничающее значение), LOW — система не решает сама. null — сравнения не было",
        required: ["level", "down", "up"],
        properties: {
          level: { type: "string", enum: ["HIGH", "MEDIUM", "LOW"] },
          down: { type: "array", items: { type: "string" }, description: "что снижает уверенность" },
          up: { type: "array", items: { type: "string" }, description: "на что вывод опирается" },
        },
      },
      verification_status: { type: "string", enum: VERIFICATION_STATUSES },
      reason_code: nullableString,
      comment: nullableString,
      decided_by: nullableString,
      decided_at: nullableDateTime,
      title: nullableString,
      locations: { type: "array", items: { type: "string" } },
      location_type: nullableString,
      comparison_result: nullableString,
      matrix_scope: nullableString,
      provisional: {
        type: "boolean",
        description:
          "Находка черновика правила (#95): параметр без правила прода проверен черновиком, который ждёт решения " +
          "специалиста. Как гипотеза свободного поиска — вне итогов, пока инспектор не взял её в кандидаты",
      },
      detail: nullableString,
      rule_basis: nullableString,
      origin: nullableString,
      carried_from_version: {
        ...nullableInt,
        description:
          "Запись перенесена из этой версии протокола (#60): дозагруженные документы её не касались, " +
          "значения и решение инспектора относятся к тому разбору. null — запись пересчитана сейчас",
      },
      parent_finding_id: nullableString,
      completeness_status: {
        ...nullableString,
        description: "Комплектность записи по ТЗ 9.2: COMPLETE, MISSING_EVIDENCE, NOT_COMPARABLE",
      },
      completeness_reason: nullableString,
      revisions: {
        type: "object",
        description:
          "Прежние редакции документов, в которых значение другое: сравнение идёт по последней редакции, " +
          "устаревшие показываются для проверки (ТЗ 9.1)",
        properties: {
          pd: { type: "array", items: { type: "object", additionalProperties: true } },
          rd: { type: "array", items: { type: "object", additionalProperties: true } },
        },
      },
      changed_after_decision: {
        type: "object",
        nullable: true,
        additionalProperties: true,
        description: "Значения до дозагрузки, если они изменились после решения инспектора: решение надо пересмотреть",
      },
      reopened: {
        type: "object",
        nullable: true,
        additionalProperties: true,
        description:
          "Прежнее решение инспектора, которое пересборка вернула ему в кандидаты: после дозагрузки автоматика " +
          "расхождения больше не видит. decision, by, at, reason_code, comment, version — в какой версии протокола " +
          "вернула, before — значения ПД и РД на момент решения. Новое решение отметку снимает.",
      },
      promoted_at: {
        ...nullableDateTime,
        description: "Когда инспектор взял гипотезу свободного поиска в кандидаты (ТЗ 9.2); до этого решения по ней не принимаются",
      },
      promoted_by: nullableString,
      disputed_at: {
        ...nullableDateTime,
        description:
          "Когда инспектор вернул в кандидаты запись, проверенную автоматически без нарушения (#74): " +
          "она снова ждёт решения и переживает пересборку протокола",
      },
      disputed_by: nullableString,
      evidence: {
        type: "array",
        description:
          "Доказательства. Кроме полей сдачи: document_code и document_sheet_number, если лист определён; " +
          "page_count; preview.aspect — пропорции страницы; highlights — прямоугольники места во внутренней " +
          "системе координат (доли видимой страницы, Y сверху) и highlight_source — чем место найдено " +
          "(VALUE, ROWS, LOCATION, FINDING — место указано самой находкой, REVISION — места, где лист изменился " +
          "между редакциями, #81). Пустой highlights при localization " +
          "PAGE_LEVEL или DOCUMENT_LEVEL означает, что доказательство относится к странице или документу целиком " +
          "и обводить нечего; при BBOX — что место на странице не найдено.",
        items: { type: "object", additionalProperties: true },
      },
    },
  },
];

export function addSharedSchemas(app: FastifyInstance): void {
  for (const schema of sharedSchemas) {
    app.addSchema(schema);
  }
}

export const errorResponses = {
  400: { $ref: "Error#" },
  401: { $ref: "Error#" },
  403: { $ref: "Error#" },
  404: { $ref: "Error#" },
  409: { $ref: "Error#" },
};

export const bearer = [{ bearerAuth: [] }];
