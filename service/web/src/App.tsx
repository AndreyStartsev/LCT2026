import { useCallback, useEffect, useState } from "react";
import { api, loadSession, logout, setUnauthorizedHandler, type Limits, type ObjectItem, type Session } from "./api";
import Login from "./components/Login";
import DatasetScreen from "./components/DatasetScreen";
import ObjectsScreen from "./components/ObjectsScreen";
import Rail, { type Section } from "./components/Rail";
import RulesScreen from "./components/RulesScreen";
import UploadPanel from "./components/UploadPanel";
import VerificationScreen from "./components/VerificationScreen";

// finding — запись, на которой открыть проверку: переход со щелчка по клетке дашборда (#83)
type View =
  | { kind: "objects" }
  | { kind: "new" }
  | { kind: "dataset" }
  | { kind: "rules" }
  | { kind: "process"; id: string; finding?: string; table?: string };

const LAST_PROCESS_KEY = "inspector-last-process";

// Адрес страницы повторяет открытый экран: ссылку можно переслать, перезагрузка не теряет место.
function readHash(): View {
  // #/process/{id}, #/process/{id}/finding/{запись}, #/process/{id}/table/{таблица}: переходы с дашборда (#83)
  const process = window.location.hash.match(
    /^#\/process\/([0-9a-f-]{36})(?:\/finding\/([0-9a-f-]{36})|\/table\/([a-z]+))?$/i,
  );
  if (process) return { kind: "process", id: process[1], finding: process[2], table: process[3] };
  if (window.location.hash === "#/new") return { kind: "new" };
  if (window.location.hash === "#/dataset") return { kind: "dataset" };
  if (window.location.hash === "#/rules") return { kind: "rules" };
  return { kind: "objects" };
}

function remember(id: string) {
  try {
    localStorage.setItem(LAST_PROCESS_KEY, id);
  } catch {
    // без хранилища рельс просто не помнит последний процесс
  }
}

function recall(): string | null {
  try {
    return localStorage.getItem(LAST_PROCESS_KEY);
  } catch {
    return null;
  }
}

export default function App() {
  const [session, setSession] = useState<Session | null>(loadSession());
  const [expired, setExpired] = useState(false);
  const [view, setView] = useState<View>(readHash());
  const [objects, setObjects] = useState<ObjectItem[]>([]);
  const [limits, setLimits] = useState<Limits | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(
    () =>
      setUnauthorizedHandler(() => {
        setSession(null);
        setExpired(true);
      }),
    [],
  );

  useEffect(() => {
    const onHash = () => setView(readHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  useEffect(() => {
    if (view.kind === "process") remember(view.id);
  }, [view]);

  // Страница правил есть только у эксперта (Р-134): по ссылке #/rules остальные попадают в реестр,
  // как по любому незнакомому адресу, — о том, что страница существует, экран не говорит
  useEffect(() => {
    if (session && session.role !== "expert" && view.kind === "rules") {
      window.history.replaceState(null, "", "#/objects");
      setView({ kind: "objects" });
    }
  }, [session, view]);

  const go = useCallback((next: View) => {
    window.location.hash =
      next.kind === "process"
        ? `#/process/${next.id}${next.finding ? `/finding/${next.finding}` : next.table ? `/table/${next.table}` : ""}`
        : next.kind === "objects"
          ? "#/objects"
          : `#/${next.kind}`;
    setView(next);
  }, []);

  const refreshObjects = useCallback(async () => {
    try {
      setObjects((await api.objects()).objects);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    if (!session) return;
    api
      .health()
      .then((h) => setLimits(h.limits))
      .catch((e) => setError((e as Error).message));
    refreshObjects();
    const timer = window.setInterval(refreshObjects, 10000);
    return () => window.clearInterval(timer);
  }, [session, refreshObjects]);

  if (!session) {
    return (
      <Login
        notice={expired ? "Сессия закончилась, войдите снова" : null}
        onLogin={(s) => {
          setExpired(false);
          setSession(s);
        }}
      />
    );
  }

  const lastProcess = view.kind === "process" ? view.id : recall();
  const section: Section = view.kind === "process" ? "verification" : view.kind;

  return (
    <div className="app">
      <Rail
        section={section}
        session={session}
        canVerify={!!lastProcess}
        onGo={(target) => {
          if (target === "verification" && lastProcess) go({ kind: "process", id: lastProcess });
          else if (target === "new") go({ kind: "new" });
          else if (target === "dataset") go({ kind: "dataset" });
          else if (target === "rules") go({ kind: "rules" });
          else go({ kind: "objects" });
        }}
        onLogout={() => {
          logout();
          setSession(null);
        }}
      />
      <div className="sheet">
        {view.kind === "objects" && (
          <ObjectsScreen
            objects={objects}
            error={error}
            session={session}
            onOpen={(id, where) => go({ kind: "process", id, ...where })}
            onNew={() => go({ kind: "new" })}
            onChanged={refreshObjects}
          />
        )}
        {view.kind === "new" && (
          <div className="frame">
            <header className="sheet-head">
              <div>
                <h1>Новая проверка</h1>
                <div className="sub">Загрузка папки объекта</div>
              </div>
            </header>
            {error && <div className="alert">Сервис недоступен: {error}</div>}
            {limits ? (
              <UploadPanel
                limits={limits}
                objects={objects}
                onUploaded={(id) => {
                  refreshObjects();
                  // Загрузка могла закончиться, когда человек уже работает на другом экране:
                  // переносить его на новый объект посреди чужой проверки нельзя — объект и так
                  // виден в очереди обработки. Переходим, только если он всё ещё ждёт здесь.
                  if (readHash().kind === "new") go({ kind: "process", id });
                }}
              />
            ) : (
              !error && <div className="empty-state">Загрузка настроек сервиса…</div>
            )}
          </div>
        )}
        {view.kind === "dataset" && session.role === "admin" && <DatasetScreen />}
        {/* Экран виден всем, но работает у администратора (#74): вместо пустоты — объяснение */}
        {view.kind === "dataset" && session.role !== "admin" && (
          <div className="frame">
            <header className="sheet-head">
              <div>
                <h1>Набор решений</h1>
                <div className="sub">Примеры для дообучения из финализированных протоколов</div>
              </div>
            </header>
            <p className="lede">
              Экран доступен администратору: здесь собирают решения инспекторов в набор примеров и выпускают версии
              для дообучения. Ваши решения по находкам попадают в него сами, когда протокол финализирован.
            </p>
          </div>
        )}
        {view.kind === "rules" && session.role === "expert" && <RulesScreen objects={objects} />}
        {view.kind === "process" && (
          <VerificationScreen
            key={view.id}
            processId={view.id}
            initialFindingId={view.finding}
            initialTable={view.table}
            session={session}
            limits={limits}
            onChanged={refreshObjects}
            onObjects={() => go({ kind: "objects" })}
          />
        )}
      </div>
    </div>
  );
}
