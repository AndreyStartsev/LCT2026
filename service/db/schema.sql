-- Схема базы «Инспектора ИИ». Задача #32.
--
-- Подмножество таблиц из раздела 10 ТЗ, нужное, чтобы провести объект
-- от загрузки до протокола и решения инспектора. Имена полей — как в ТЗ,
-- где таблица там описана: Objects, Files, Protocols, Checks, Audit_Log.
-- Сервис API применяет файл при каждом старте, поэтому всё идемпотентно.

create table if not exists objects (
    id          text primary key,
    name        text not null,
    address     text,
    customer    text,
    contractor  text,
    permit_number text,
    created_at  timestamptz not null default now()
);

-- Процесс проверки: загрузка, разбор, протокол, верификация, финализация.
-- status — жизненный цикл по ТЗ (PENDING, PARSING, READY, VERIFYING, COMPLETED,
-- FINALIZED). processing — состояние задания в очереди: у ТЗ нет статуса
-- для сбоя обработки, и смешивать его с жизненным циклом нельзя.
create table if not exists processes (
    id            uuid primary key,
    object_id     text not null references objects(id),
    status        text not null default 'PENDING',
    scenario      text,
    upload_status jsonb not null default '[]',
    processing    jsonb not null default '{}',
    created_by    text,
    -- Способ чтения объекта (#54): layer, tesseract или model. Выбирается при загрузке,
    -- потому что зависит от документов: где-то хватает текстового слоя, а объект из сканов
    -- без распознавания и модели не даёт решений вовсе. Пусто — режим сервиса.
    reading_mode  text,
    -- Модель, выбранная при загрузке для режима «модель»: идентификатор у провайдера,
    -- например qwen/qwen3-vl-30b-a3b-instruct. Пусто — модель сервиса по умолчанию.
    model_name    text,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now(),
    finalized_at  timestamptz
);
alter table processes add column if not exists reading_mode text;
alter table processes add column if not exists model_name text;
-- Ключ загрузки из веба: пакет без process_id, повторённый после обрыва (ответ потерян, а процесс
-- уже заведён), попадает в тот же процесс, а не заводит второй — иначе в реестре дубль объекта.
alter table processes add column if not exists upload_key text;
create unique index if not exists processes_upload_key_idx on processes(upload_key) where upload_key is not null;
create index if not exists processes_object_idx on processes(object_id, created_at desc);

create table if not exists upload_batches (
    id             uuid primary key,
    process_id     uuid not null references processes(id),
    files_accepted integer not null default 0,
    files_rejected integer not null default 0,
    bytes_accepted bigint not null default 0,
    final_batch    boolean not null default true,
    created_by     text,
    created_at     timestamptz not null default now()
);

-- Ключ загрузки у пакета: повтор последнего пакета той же загрузки после потерянного ответа
-- узнаётся по нему и не ставит разбор второй раз; по нему же считается, приняла ли загрузка файлы.
alter table upload_batches add column if not exists upload_key text;
create index if not exists upload_batches_key_idx on upload_batches(process_id, upload_key) where upload_key is not null;

-- Файлы процесса. Содержимое лежит в хранилище по SHA-256 (blobs/<sha256>),
-- здесь — путь внутри загруженной папки и то, что о файле узнал разбор.
create table if not exists files (
    id              bigserial primary key,
    process_id      uuid not null references processes(id),
    object_id       text not null references objects(id),
    batch_id        uuid references upload_batches(id),
    relative_path   text not null,
    file_hash       text,
    size_bytes      bigint,
    extension       text,
    status          text not null,          -- ACCEPTED или REJECTED
    reject_code     text,
    reject_message  text,
    file_id         text,                   -- F0001 из реестра организатора или L0001
    doc_stage       text,
    discipline      text,
    -- Стадия и раздел, заданные инспектором руками (#39). Разбор их не перезаписывает:
    -- на чужом оформлении папок стадия угадывается неверно, и документ выпадает
    -- из сравнения. Кто и когда поправил — в журнале аудита, действие FILE_STAGE_SET.
    stage_manual    text,
    section_manual  text,
    manual_by       text,
    manual_at       timestamptz,
    document_code   text,
    revision        text,
    approval_status text,
    approval_date   date,
    predecessor_id  bigint,
    -- Цепочки редакций (#10): chain_id общий у редакций одного документа, revision_status —
    -- CURRENT, SUPERSEDED, DUPLICATE или CLARIFICATION_REQUIRED. Инспектор может назвать
    -- актуальную редакцию руками: revision_manual, кто и когда — рядом, действие аудита
    -- FILE_REVISION_SET. Разбор выбор не перезаписывает.
    chain_id            text,
    revision_status     text,
    revision_manual     boolean,
    revision_manual_by  text,
    revision_manual_at  timestamptz,
    pdf_pages       integer,
    uploaded_at     timestamptz not null default now(),
    unique (process_id, relative_path)
);
-- База стенда заведена раньше правки стадии руками (#39), а create table if not exists
-- новые колонки существующей таблице не добавляет: дописываем отдельно.
alter table files add column if not exists stage_manual   text;
alter table files add column if not exists section_manual text;
alter table files add column if not exists manual_by      text;
alter table files add column if not exists manual_at      timestamptz;
alter table files add column if not exists chain_id           text;
alter table files add column if not exists revision_status    text;
alter table files add column if not exists revision_manual    boolean;
alter table files add column if not exists revision_manual_by text;
alter table files add column if not exists revision_manual_at timestamptz;

create table if not exists protocols (
    id                  bigserial primary key,
    process_id          uuid not null references processes(id),
    object_id           text not null references objects(id),
    version             integer not null,
    matrix_version      text,
    dataset_version     text,
    model_version       text,
    input_manifest_hash text,
    status              text not null default 'READY',
    body                jsonb not null,     -- протокол в формате сдачи организатора
    report              jsonb not null default '{}',
    created_at          timestamptz not null default now(),
    finalized_at        timestamptz,
    unique (process_id, version)
);

-- Находки последней версии протокола (в ТЗ — Checks). Строка переживает
-- пересборку протокола при дозагрузке: ключ — идентификатор находки конвейера,
-- поэтому решение инспектора не теряется.
create table if not exists findings (
    id                  uuid primary key,
    process_id          uuid not null references processes(id),
    finding_id          text not null,
    protocol_version    integer not null,
    parameter_code      text,
    location            text,
    violation_label     text,
    protocol_status     text,
    criticality         text,
    pd_value            text,
    rd_value            text,
    verification_status text not null,      -- PENDING, CONFIRMED_VIOLATION, NEGATIVE_VERIFIED,
                                            -- CLARIFICATION_REQUIRED, NOT_REQUIRED,
                                            -- SPLIT (разделена инспектором на атомарные)
    reason_code         text,
    comment             text,
    decided_by          text,
    decided_at          timestamptz,
    body                jsonb not null,
    unique (process_id, finding_id)
);

-- Что изменилось между редакциями одного документа (#19, #81): пара «прежняя → следующая»
-- из цепочки редакций и её страницы — что изменилось, где на листе (рамки в долях страницы)
-- и отмечено ли изменение в штампе листа и в ведомости. Перезаписывается каждым разбором
-- процесса; экран файлов и карточка находки читают её, не заглядывая в рабочий каталог воркера.
create table if not exists revision_changes (
    process_id    uuid not null references processes(id) on delete cascade,
    pair_id       text not null,
    chain_id      text,
    stage_group   text,
    old_file_id   text not null,
    new_file_id   text not null,
    old_revision  text,
    new_revision  text,
    summary       jsonb not null default '{}',
    pages         jsonb not null default '[]',
    created_at    timestamptz not null default now(),
    primary key (process_id, pair_id)
);
create index if not exists revision_changes_new_file_idx on revision_changes (process_id, new_file_id);

create table if not exists audit_log (
    id          bigserial primary key,
    user_id     text,
    action      text not null,
    object_id   text,
    process_id  uuid,
    details     jsonb not null default '{}',
    timestamp   timestamptz not null default now(),
    ip_address  text,
    user_agent  text
);

create table if not exists notifications (
    id          bigserial primary key,
    role        text not null,              -- inspector или admin
    process_id  uuid,
    level       text not null,              -- INFO, WARNING, ERROR
    -- Чего требует запись: ACTION — действия человека (перезагрузить файл, пересмотреть
    -- решение), QUALITY — наблюдение о качестве разбора, ему место в журнале обработки,
    -- а не на рабочем экране инспектора (#83), INFO — событие без действия.
    category    text not null default 'INFO',
    message     text not null,
    created_at  timestamptz not null default now()
);
alter table notifications add column if not exists category text not null default 'INFO';
-- Уведомления, записанные до появления вида: наблюдения о качестве разбора узнаются
-- по началу строки и переезжают в журнал обработки, чтобы не висеть на рабочем экране.
update notifications set category = 'QUALITY'
 where category = 'INFO'
   and (message like 'Контроль качества чтения:%' or message like 'Готовность объекта:%');

-- Передача финализированного протокола во внешнюю систему ИАИС «РиН». Задача #34, ТЗ 9.6.
-- Передаётся только финализированный протокол; при ошибке 5xx или таймауте — до трёх
-- повторов с задержкой 1, 5 и 15 минут. Недоступность внешней системы не меняет решения
-- инспектора: протокол остаётся PROTOCOL_FINALIZED, передача — PENDING_SYNC.
create table if not exists inspection_sync (
    id                bigserial primary key,
    process_id        uuid not null references processes(id),
    protocol_version  integer not null,
    status            text not null,          -- PENDING_SYNC, SYNCED, REJECTED, CANCELLED
    attempts          integer not null default 0,
    next_attempt_at   timestamptz,
    last_error        text,
    last_status_code  integer,
    external_id       text,
    payload_sha256    text,
    requested_by      text,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now(),
    synced_at         timestamptz
);
create index if not exists inspection_sync_due_idx on inspection_sync(status, next_attempt_at);
create index if not exists inspection_sync_process_idx on inspection_sync(process_id, id desc);

-- Решения инспектора как набор примеров для дообучения. Задача #34, ТЗ 9.4.
-- Черновик набора не хранится: это решения финализированных протоколов, подтверждённые
-- нарушения (положительные примеры) и отклонённые кандидаты с кодом причины
-- (отрицательные). Запросы уточнения и записи без решения в набор не входят.
-- Куратор выпускает версию — снимок черновика целиком. Строки версии не меняются:
-- отмена финализации или новое решение меняют только следующий черновик.
create table if not exists dataset_versions (
    dataset_version  text primary key,              -- ds-<первые 12 знаков manifest_sha256>
    items            integer not null,
    positives        integer not null,
    negatives        integer not null,
    added            integer not null,              -- разница с предыдущей версией
    changed          integer not null,
    removed          integer not null,
    objects          jsonb not null default '[]',
    manifest_sha256  text not null,
    comment          text,
    released_by      text,
    released_at      timestamptz not null default now(),
    -- Версию не удаляют: на неё ссылаются протоколы. Ошибочную помечают отозванной —
    -- запись остаётся в истории, но в обучение такая версия не берётся (#74).
    withdrawn_at     timestamptz,
    withdrawn_by     text,
    withdrawn_reason text
);
alter table dataset_versions add column if not exists withdrawn_at     timestamptz;
alter table dataset_versions add column if not exists withdrawn_by     text;
alter table dataset_versions add column if not exists withdrawn_reason text;

create table if not exists dataset_items (
    id                 bigserial primary key,
    dataset_version    text not null references dataset_versions(dataset_version),
    finding_row_id     uuid not null,
    process_id         uuid not null,
    object_id          text not null,
    protocol_version   integer not null,
    finding_id         text not null,
    parameter_code     text,
    location           text,
    gold_label         text not null,          -- CONFIRMED_VIOLATION или NEGATIVE_VERIFIED
    reason_code        text,
    comment            text,
    expert_id          text,
    decided_at         timestamptz,
    evidence           jsonb not null default '[]',
    card               jsonb not null default '{}',
    unique (dataset_version, process_id, finding_id)
);

-- Правила, которыми разбирает воркер: очереди Матрицы, черновики, каталог 132 параметров
-- и решения специалиста по видам свободного поиска (Р-134). Файлы правил лежат в образе
-- воркера, API собирается без них, поэтому воркер при старте кладёт сюда их снимок,
-- а страница правил эксперта показывает последний. Ключ — отпечаток содержимого: тот же
-- образ после перезапуска строк не множит, только сдвигает время.
create table if not exists rule_snapshots (
    fingerprint   text primary key,
    body          jsonb not null,
    published_at  timestamptz not null default now()
);
create index if not exists rule_snapshots_published_idx on rule_snapshots(published_at desc);

-- Пробные прогоны правил со страницы правил эксперта (#222, #223): трасса — как рабочее правило
-- решило на объекте, песочница — что дал бы вариант правила. Прогон ничего не меняет: ни файлов
-- правил, ни протоколов, ни решений инспектора. Задание ставит API, воркер выполняет его по объекту
-- за раз, после шагов обработки документов; итог по каждому объекту — в rule_test_results.
create table if not exists rule_tests (
    id           uuid primary key,
    code         text not null,
    variant      jsonb,                          -- поля правила из песочницы; пусто — рабочее правило
    trace        boolean not null default true,  -- кандидаты по стадиям в итоге
    process_ids  jsonb not null default '[]',    -- проверки объектов, на которых прогоняется правило
    status       text not null default 'QUEUED', -- QUEUED, RUNNING, DONE, FAILED
    total        integer not null default 0,
    done         integer not null default 0,
    error        text,
    created_by   text,
    created_at   timestamptz not null default now(),
    started_at   timestamptz,
    finished_at  timestamptz
);
create index if not exists rule_tests_code_idx on rule_tests(code, created_at desc);

create table if not exists rule_test_results (
    test_id      uuid not null references rule_tests(id) on delete cascade,
    process_id   uuid not null,
    object_id    text,
    status       text not null,                  -- DONE, FAILED
    result       jsonb,
    error        text,
    elapsed_s    real,
    finished_at  timestamptz not null default now(),
    primary key (test_id, process_id)
);
-- Отпечаток правила на момент прогона (#224): предложение правки из прогона принимается, только пока
-- правило то же — иначе разница по объектам говорила бы о другом правиле
alter table rule_tests add column if not exists rule_digest text;

-- Предложения правки правила из песочницы (#224, Р-164). Вариант с разницей по объектам хранится
-- снимком: прогон песочницы убирается через две недели, а предложение остаётся со своей разницей.
-- Правила прода предложение не меняет: разработчик переносит его в файл правил через PR и гейт
-- качества (tools/rule_proposals.py) и отмечает статус — перенесено или отклонено с причиной.
create table if not exists rule_proposals (
    id             uuid primary key,
    code           text not null,
    queue          integer not null,
    draft          boolean not null default false,  -- черновик правила (rules/provisional) или рабочее
    file           text not null,                   -- файл правил, к которому прикладывается правка
    variant        jsonb not null,                  -- поля правила поверх рабочего
    rule           jsonb not null,                  -- правило на момент предложения
    fingerprint    text not null,                   -- снимок правил, на котором предложено
    test_id        uuid references rule_tests(id) on delete set null,
    diff           jsonb not null,                  -- разница по объектам: итоги и перемены
    comment        text,
    status         text not null default 'NEW',     -- NEW, APPLIED, REJECTED
    status_reason  text,
    status_by      text,
    status_at      timestamptz,
    created_by     text not null,
    created_at     timestamptz not null default now()
);
create index if not exists rule_proposals_code_idx on rule_proposals(code, created_at desc);
create unique index if not exists rule_proposals_test_idx on rule_proposals(test_id) where test_id is not null;

-- Удаление процесса уносит его записи: пакеты загрузки, файлы, протоколы, находки и
-- очередь передачи. Без этого убрать проверочный объект со стенда можно было только
-- вручную по таблицам в правильном порядке, и любая ошибка оставляла осиротевшие строки.
-- Журнал аудита и уведомления ссылаются на процесс без внешнего ключа и остаются:
-- запись о том, что делали с процессом, переживает сам процесс (ТЗ 9.5). Набор решений
-- для дообучения (`dataset_items`) тоже не привязан ключом и остаётся снимком.
-- Объект (`objects`) не каскадируется намеренно: удаление объекта не должно молча
-- уносить его проверки — процессы удаляются отдельной командой.
do $$
declare
    fk record;
begin
    for fk in
        select *
        from (values ('upload_batches', 'upload_batches_process_id_fkey'),
                     ('files', 'files_process_id_fkey'),
                     ('protocols', 'protocols_process_id_fkey'),
                     ('findings', 'findings_process_id_fkey'),
                     ('inspection_sync', 'inspection_sync_process_id_fkey'))
             as t(table_name, constraint_name)
    loop
        -- confdeltype = 'c' — каскад уже стоит; тогда ключ не трогаем, чтобы
        -- перезапуск сервиса не перепроверял внешние ключи на всех строках
        if not exists (select 1 from pg_constraint
                       where conname = fk.constraint_name and confdeltype = 'c') then
            execute format('alter table %I drop constraint if exists %I', fk.table_name, fk.constraint_name);
            execute format('alter table %I add constraint %I foreign key (process_id) '
                           || 'references processes(id) on delete cascade',
                           fk.table_name, fk.constraint_name);
        end if;
    end loop;
end $$;
