import { useEffect, useId, useRef, type ReactNode } from "react";

interface Props {
  title: string;
  children: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  busy?: boolean;
  /** Куда вернуть фокус после закрытия, если окно открыли не сразу по нажатию (кнопку успели погасить). */
  returnTo?: HTMLElement | null;
  onConfirm: () => void;
  onCancel: () => void;
}

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';
/** Двойной щелчок по кнопке, открывшей окно, не должен сразу закрыть его щелчком по подложке. */
const BACKDROP_GRACE_MS = 500;

/** Можно ли вернуть фокус на элемент: он ещё на странице и не погашен. */
function focusable(el: HTMLElement | null): boolean {
  return !!el && el.isConnected && !(el as HTMLButtonElement).disabled;
}

/**
 * Вернуть фокус туда, откуда окно открыли. Кнопка-открыватель бывает погашена, пока идёт
 * запрос (busy), — тогда ждём, пока её включат; исчезла совсем (финализация убрала значок) —
 * фокус на первое доступное действие шапки, а не в начало документа.
 */
function restoreFocus(before: HTMLElement | null) {
  if (focusable(before)) {
    before!.focus();
    return;
  }
  // кнопка могла стать доступной позже: запрос кончится — её включат
  let tries = 0;
  const timer = window.setInterval(() => {
    tries += 1;
    if (focusable(before)) {
      before!.focus();
    } else if (tries < 30 && before?.isConnected) {
      return;
    } else if (document.activeElement === document.body || !document.activeElement) {
      document.querySelector<HTMLElement>(".head-actions button:not([disabled]), .head-actions summary")?.focus();
    }
    window.clearInterval(timer);
  }, 100);
}

/**
 * Окно подтверждения поверх экрана. Фокус сразу на «Отмена»: подтверждают им то, что отменить
 * трудно или нельзя, и случайный Enter не должен его совершить. Esc и щелчок по подложке
 * закрывают окно, Tab не уходит под него — и тогда, когда фокус потерян щелчком по тексту
 * или погашенной на время запроса кнопкой. После закрытия фокус возвращается туда, откуда
 * окно открыли. Клавиши экрана под окном не работают — это решает экран (keys.ts, overlay).
 */
export default function ConfirmDialog({ title, children, confirmLabel, cancelLabel = "Отмена", busy, returnTo, onConfirm, onCancel }: Props) {
  const titleId = useId();
  const box = useRef<HTMLDivElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const openedAt = useRef(0);
  const pressedOnBackdrop = useRef(false);
  // слушатель на документе живёт всё время окна: свежие busy и onCancel — через ref
  const latest = useRef({ busy, onCancel });
  latest.current = { busy, onCancel };

  useEffect(() => {
    const before = returnTo ?? (document.activeElement as HTMLElement | null);
    openedAt.current = performance.now();
    cancel.current?.focus();

    function onKey(e: KeyboardEvent) {
      if (!box.current) return;
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        if (!latest.current.busy) latest.current.onCancel();
        return;
      }
      if (e.key !== "Tab") return;
      const items = [...box.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      const inside = box.current.contains(document.activeElement);
      if (items.length === 0) {
        e.preventDefault();
        box.current.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      if (!inside || document.activeElement === box.current) {
        e.preventDefault();
        (e.shiftKey ? last : first).focus();
      } else if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    // в фазе перехвата: клавиша не доходит ни до экрана под окном, ни до его полей
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      restoreFocus(before);
    };
  }, []);

  // Пока идёт запрос, кнопки погашены и браузер снимает с них фокус: держим его на окне,
  // а когда запрос кончился (например, ошибкой) — возвращаем на «Отмена»
  useEffect(() => {
    if (!box.current) return;
    if (busy) {
      if (!box.current.contains(document.activeElement)) box.current.focus();
    } else if (!box.current.contains(document.activeElement) || document.activeElement === box.current) {
      cancel.current?.focus();
    }
  }, [busy]);

  return (
    <>
      <div
        className="dialog-backdrop"
        aria-hidden="true"
        onMouseDown={(e) => {
          pressedOnBackdrop.current = e.target === e.currentTarget;
        }}
        onClick={(e) => {
          const fresh = performance.now() - openedAt.current < BACKDROP_GRACE_MS;
          if (e.target === e.currentTarget && pressedOnBackdrop.current && !fresh && !busy) onCancel();
          pressedOnBackdrop.current = false;
        }}
      />
      <div ref={box} className="viewer confirm" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
        <div className="viewer-head">
          <span id={titleId} className="viewer-title">
            {title}
          </span>
        </div>
        <div className="card-body">
          {children}
          <div className="actions-row">
            <button ref={cancel} type="button" className="btn" disabled={busy} onClick={onCancel}>
              {cancelLabel}
            </button>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={onConfirm}>
              {confirmLabel}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
