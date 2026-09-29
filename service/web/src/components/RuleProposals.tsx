import { useState, type SyntheticEvent } from "react";
import { api, download, type ProposalTotals, type RuleProposal } from "../api";
import { Changes, describeVariant, PROPOSAL_WORD, when } from "./RuleCheck";

/** Разница варианта по объектам — одной строкой, как итог прогона в песочнице. */
export function totalsLine(t: ProposalTotals): string {
  const parts = [
    t.changes
      ? `меняет записей: ${t.changes} — на объектах: ${t.changed_objects} из ${t.done}`
      : `на ${t.done} ${t.done === 1 ? "объекте" : "объектах"} ничего не меняет`,
  ];
  if (t.disputed) parts.push(`спорит с решениями инспекторов: ${t.disputed}`);
  if (t.failed) parts.push(`не прогнано на объектах: ${t.failed}`);
  return parts.join(" · ");
}

function Proposal({ p }: { p: RuleProposal }) {
  const [full, setFull] = useState<RuleProposal | null>(null);
  const [error, setError] = useState<string | null>(null);

  function open(event: SyntheticEvent<HTMLDetailsElement>) {
    if (!event.currentTarget.open || full) return;
    api
      .ruleProposal(p.id)
      .then(setFull)
      .catch((e) => setError((e as Error).message));
  }

  function save() {
    setError(null);
    download(`/api/v1/rules/proposals/${p.id}/patch`, `rule-proposal-${p.code}.json`).catch((e) =>
      setError((e as Error).message),
    );
  }

  return (
    <li className="rules-proposal">
      <div className="rules-proposal-head">
        <span className={`rules-pstatus ps-${p.status}`}>{PROPOSAL_WORD[p.status]}</span>
        <b>{describeVariant(p.variant) || "вариант"}</b>
        <span className="small muted">
          {" "}
          · {p.created_by} · {when(p.created_at)}
          {p.draft ? " · черновик правила" : ""}
        </span>
      </div>
      <div className="small">{totalsLine(p.totals)}</div>
      {p.comment && <div className="rules-proposal-comment">{p.comment}</div>}
      {p.status !== "NEW" && (
        <div className="small">
          {p.status === "REJECTED" ? "Причина" : "Что сделано"}: {p.status_reason ?? "—"}
          {p.status_at && <span className="muted"> · {when(p.status_at)}</span>}
        </div>
      )}
      <div className="rules-check-row">
        <button type="button" className="btn" onClick={save}>
          Правка файла правил, JSON
        </button>
      </div>
      <details className="rules-more" onToggle={open}>
        <summary>Разница по объектам</summary>
        {!full && !error && <div className="small muted">Загрузка…</div>}
        {full &&
          (full.objects?.length ? (
            full.objects.map((o) => (
              <div key={o.process_id} className="rules-proposal-object">
                <b>{o.object_name ?? o.object_id}</b>
                {o.status === "FAILED" ? (
                  <span className="small"> · не прогнано — {o.error ?? "сбой"}</span>
                ) : (
                  <Changes changes={o.changes} />
                )}
              </div>
            ))
          ) : (
            <div className="small muted">Вариант не меняет ни одной записи.</div>
          ))}
      </details>
      {error && <div className="alert">{error}</div>}
    </li>
  );
}

/**
 * Предложения правки правила (#224): вариант из песочницы с разницей по объектам снимком — прогон
 * убирается через две недели, предложение остаётся. Правила сервиса предложение не меняет: разработчик
 * переносит правку после проверки качества на всех объектах и отмечает, что сделано.
 */
export default function RuleProposals({ proposals }: { proposals: RuleProposal[] }) {
  if (!proposals.length) return null;
  return (
    <section className="rules-proposals" aria-label="Предложения правки">
      <h3>Предложения правки</h3>
      <p className="small muted">
        Правила сервиса предложение не меняет: разработчик переносит правку после проверки качества на всех объектах и
        отмечает, что сделано. Файл правки — для разработчика: что и где поменять в правилах.
      </p>
      <ul>
        {proposals.map((p) => (
          <Proposal key={p.id} p={p} />
        ))}
      </ul>
    </section>
  );
}
