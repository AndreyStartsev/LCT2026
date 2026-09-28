import type { ReactElement } from "react";
import type { Session } from "../api";
import Tip from "./Tip";

export type Section = "objects" | "new" | "verification" | "dataset" | "rules";

interface Props {
  section: Section;
  canVerify: boolean;
  session: Session;
  onGo: (section: Section) => void;
  onLogout: () => void;
}

export function Mark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 34 34" aria-hidden="true">
      <rect x="1.5" y="1.5" width="31" height="31" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M6 24.5 L14 9.5 L22 24.5" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
      <path d="M9.6 18.5 H18.4" stroke="currentColor" strokeWidth="1.2" />
      <circle cx="23.5" cy="13" r="4.6" fill="none" stroke="currentColor" strokeWidth="1.4" />
      <path d="M26.8 16.3 L30.5 20" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

const ICONS: Record<Section, ReactElement> = {
  objects: (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <path d="M3 17V7l5-3 5 3v10" />
      <path d="M13 17V9h4v8" />
      <path d="M2 17h16" />
    </svg>
  ),
  new: (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <path d="M5 2.5h7l3 3v12H5z" />
      <path d="M10 8.5v6M7 11.5h6" />
    </svg>
  ),
  verification: (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <rect x="3" y="2.5" width="14" height="15" />
      <path d="M6 7h8M6 10h8M6 13h5" />
    </svg>
  ),
  dataset: (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <ellipse cx="10" cy="5" rx="6" ry="2.5" />
      <path d="M4 5v10c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5V5" />
      <path d="M4 10c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5" />
    </svg>
  ),
  // чертёжный угольник с делениями: правило — и инструмент выверки, и норма, по которой сверяют
  rules: (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <path d="M3 2.5v15h15z" />
      <path d="M6.5 10.5v3.5H10z" />
      <path d="M3 6h2M3 9h1.5M3 12h2M3 15h1.5" />
    </svg>
  ),
};

const TITLES: Record<Section, string> = {
  objects: "Объекты",
  new: "Новая проверка",
  verification: "Верификация",
  dataset: "Набор решений",
  rules: "Правила",
};

/** Значок без подписи сам себя не объясняет (#74): что за экраном — словами. */
const HINTS: Record<Section, string> = {
  objects: "Объекты: реестр проверок — состояние каждого объекта, стадии и сколько записей ждут решения",
  new: "Новая проверка: загрузка папки объекта, выбор способа чтения и модели",
  verification: "Верификация: карточки находок с доказательствами и решения инспектора по каждой",
  dataset: "Набор решений: решения инспекторов как примеры для дообучения, черновик и выпущенные версии",
  rules: "Правила: все правила сверки — что сравнивается, каким порогом и в каких документах, черновики и параметры вне проверки",
};

const ROLE: Record<Session["role"], { word: string; short: string }> = {
  inspector: { word: "инспектор", short: "инсп" },
  admin: { word: "администратор", short: "адм" },
  expert: { word: "эксперт", short: "эксп" },
};

export default function Rail({ section, canVerify, session, onGo, onLogout }: Props) {
  // Все экраны видны всем (#74): администраторский погашен, но человек знает, что он есть.
  // Правила — исключение (Р-134): страница эксперта, у остальных ролей её нет вовсе, у администратора тоже
  const expert = session.role === "expert";
  const order: Section[] = ["objects", "verification", "new", "dataset", ...(expert ? (["rules"] as const) : [])];
  const admin = session.role === "admin";
  const role = ROLE[session.role] ?? ROLE.inspector;
  return (
    <nav className="rail" aria-label="Разделы">
      <span className="rail-mark" title="Инспектор ИИ">
        <Mark />
      </span>
      {order.map((key) => (
        <Tip
          key={key}
          place="right"
          text={
            key === "dataset" && !admin
              ? `${HINTS[key]}. Доступен администратору`
              : key === "verification" && !canVerify
                ? `${HINTS[key]}. Станет доступна, когда протокол сформирован`
                : HINTS[key]
          }
        >
          <button
            type="button"
            className={`rail-btn${key === "dataset" && !admin ? " off" : ""}`}
            aria-current={section === key}
            aria-label={TITLES[key]}
            aria-disabled={key === "dataset" && !admin}
            disabled={key === "verification" && !canVerify}
            onClick={() => onGo(key)}
          >
            {ICONS[key]}
          </button>
        </Tip>
      ))}
      <div className="rail-user" title={`${session.login}: ${role.word}`}>
        <span className="rail-initial">{session.login.slice(0, 1).toUpperCase()}</span>
        <span className="rail-role">{role.short}</span>
      </div>
      <Tip place="right" text="Выйти: сеанс закроется, решения и протоколы останутся на месте">
      <button type="button" className="rail-btn rail-exit" aria-label="Выйти" onClick={onLogout}>
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
          <path d="M8 3H3v14h5" />
          <path d="M13 6l4 4-4 4M7 10h10" />
        </svg>
      </button>
      </Tip>
    </nav>
  );
}
