import { useState, type FormEvent } from "react";
import {
  ArrowClockwiseIcon,
  ClockCountdownIcon,
  PlusIcon,
  ShieldWarningIcon,
  TimerIcon,
  UserMinusIcon,
} from "@phosphor-icons/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Freshness } from "@/components/live/freshness";
import { useAuth } from "@/features/auth/auth-context";
import type {
  SentinelRuleCommand,
  SentinelSchedule,
} from "@/features/agents/contract";
import { signalLabels } from "@/features/opportunities/format";
import { dateTime } from "@/features/opportunities/format";
import { account } from "@/features/provider/account-api";
import {
  archiveSentinelRule,
  createSentinelRule,
  getSentinelCatalog,
  saveSentinelRule,
  previewSentinelRule,
  getSentinelOptions,
} from "./api";
import "./sentinels.css";

type Kind = SentinelRuleCommand["kind"];
const intervals = [1, 5, 15, 30, 60, 120, 360, 720, 1440] as const;
const kinds: Record<Kind, { name: string; detail: string; threshold: string }> =
  {
    sla_overdue: {
      name: "SLA vencido",
      detail: "Oportunidades abertas cujo prazo venceu.",
      threshold: "Horas após o SLA",
    },
    unassigned: {
      name: "Sem responsável",
      detail: "Oportunidades abertas sem responsável definido.",
      threshold: "Horas desde a abertura",
    },
    stale: {
      name: "Sem atualização",
      detail: "Oportunidades abertas sem atualização recente.",
      threshold: "Horas sem atualização",
    },
  };

function frequency(minutes: number): string {
  if (minutes === 1) return "A cada minuto";
  if (minutes < 60) return `A cada ${minutes} minutos`;
  if (minutes === 60) return "A cada hora";
  if (minutes === 1440) return "Uma vez ao dia";
  return `A cada ${minutes / 60} horas`;
}

function localDate(value: string | null, timezone: string): string {
  if (!value) return "Ainda não executada";
  try {
    return new Intl.DateTimeFormat("pt-BR", {
      dateStyle: "short",
      timeStyle: "short",
      timeZone: timezone,
    }).format(new Date(value));
  } catch {
    return dateTime(value);
  }
}

function RuleIcon({ kind }: { kind: Kind }) {
  if (kind === "unassigned") return <UserMinusIcon size={19} aria-hidden />;
  if (kind === "stale") return <TimerIcon size={19} aria-hidden />;
  return <ShieldWarningIcon size={19} aria-hidden />;
}

function RuleEditor({
  rule,
  timezone,
  slots,
  activeCount,
  onClose,
  onSaved,
}: {
  rule: SentinelSchedule | null;
  timezone: string;
  slots: number;
  activeCount: number;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const client = useQueryClient();
  const options = useQuery({
    queryKey: ["sentinel-options"],
    queryFn: getSentinelOptions,
  });
  const [title, setTitle] = useState(rule?.title ?? "");
  const [kind, setKind] = useState<Kind>(rule?.kind ?? "sla_overdue");
  const [threshold, setThreshold] = useState(rule?.threshold_hours ?? 0);
  const [enabled, setEnabled] = useState(rule?.enabled ?? false);
  const [interval, setInterval] = useState<
    SentinelRuleCommand["interval_minutes"]
  >(rule?.interval_minutes ?? 1440);
  const [startTime, setStartTime] = useState(
    rule?.start_time_local.slice(0, 5) ?? "09:00",
  );
  const [reason, setReason] = useState("");
  const [days, setDays] = useState(
    rule?.calendar?.days_of_week ?? [0, 1, 2, 3, 4, 5, 6],
  );
  const [zone, setZone] = useState(rule?.calendar?.timezone || timezone);
  const [endTime, setEndTime] = useState(
    rule?.calendar?.end_time_local?.slice(0, 5) ?? "",
  );
  const [times, setTimes] = useState(
    rule?.calendar?.execution_times?.map((t) => t.slice(0, 5)).join(", ") ?? "",
  );
  const [mode, setMode] = useState(
    rule?.calendar?.execution_times?.length ? "times" : "interval",
  );
  const [stages, setStages] = useState<
    NonNullable<SentinelRuleCommand["criteria"]>["stages"]
  >(rule?.criteria?.stages ?? []);
  const [owner, setOwner] = useState(rule?.criteria?.owner_user_id ?? "");
  const [minValue, setMinValue] = useState(
    String(rule?.criteria?.min_value ?? ""),
  );
  const [maxValue, setMaxValue] = useState(
    String(rule?.criteria?.max_value ?? ""),
  );
  const [currency, setCurrency] = useState(rule?.criteria?.currency ?? "");
  const [risks, setRisks] = useState(
    rule?.criteria?.risk_types?.join(", ") ?? "",
  );
  const [interpret, setInterpret] = useState(rule?.interpret_with_ai ?? false);
  function command(preview = false): SentinelRuleCommand {
    return {
      expected_version: rule?.version ?? null,
      title: title.trim(),
      kind,
      threshold_hours: threshold,
      enabled,
      interval_minutes: mode === "times" ? 1440 : interval,
      start_time_local: startTime,
      reason: reason.trim() || (preview ? "Teste manual de regra" : ""),
      criteria: {
        stages,
        owner_user_id: kind === "unassigned" ? null : owner || null,
        min_value: minValue || null,
        max_value: maxValue || null,
        currency: currency || null,
        risk_types: risks
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      },
      calendar: {
        days_of_week: days,
        timezone: zone,
        end_time_local: endTime || null,
        execution_times:
          mode === "times"
            ? times
                .split(",")
                .map((t) => t.trim())
                .filter(Boolean)
            : [],
      },
      interpret_with_ai: interpret,
    };
  }
  const preview = useMutation({
    mutationFn: () => previewSentinelRule(command(true)),
  });

  const refresh = async () => {
    await Promise.all([
      client.invalidateQueries({ queryKey: ["sentinel-catalog"] }),
      client.invalidateQueries({ queryKey: ["sentinel-findings"] }),
      client.invalidateQueries({ queryKey: ["sentinel-notifications"] }),
    ]);
  };
  const mutation = useMutation({
    mutationFn: (command: SentinelRuleCommand) =>
      rule
        ? saveSentinelRule(rule.rule_id, command)
        : createSentinelRule(command),
    onSuccess: async () => {
      await refresh();
      onSaved(
        rule ? "Regra atualizada e auditada." : "Regra criada e auditada.",
      );
      onClose();
    },
  });
  const archive = useMutation({
    mutationFn: () =>
      archiveSentinelRule(rule!.rule_id, {
        expected_version: rule!.version,
        reason: reason.trim(),
      }),
    onSuccess: async () => {
      await refresh();
      onSaved("Regra arquivada; o histórico foi preservado.");
      onClose();
    },
  });
  const hasCapacity = !enabled || !!rule?.enabled || activeCount < slots;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!hasCapacity) return;
    mutation.mutate(command());
  }

  return (
    <section
      className="sentinel-editor-panel"
      aria-labelledby="sentinel-editor-title"
    >
      <div className="sentinel-editor-head">
        <div>
          <span className="eyebrow">CONTROLE DA EMPRESA</span>
          <h2 id="sentinel-editor-title">
            {rule ? "Editar regra" : "Nova regra"}
          </h2>
          <p>
            A regra consulta oportunidades ARES e registra achados sem escrever
            no CRM.
          </p>
        </div>
        <Button variant="outline" onClick={onClose}>
          Fechar
        </Button>
      </div>
      <form className="sentinel-editor" onSubmit={submit}>
        <div className="sentinel-form-grid">
          <label>
            Nome da regra
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              minLength={3}
              maxLength={80}
              required
            />
          </label>
          <label>
            Condição observada
            <select
              value={kind}
              disabled={!!rule}
              onChange={(event) => setKind(event.target.value as Kind)}
            >
              {Object.entries(kinds).map(([key, value]) => (
                <option key={key} value={key}>
                  {value.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="sentinel-form-note">
          {kinds[kind].detail} O tipo não pode ser trocado depois da criação.
        </p>
        <div className="sentinel-form-grid sentinel-form-grid-three">
          <label>
            {kinds[kind].threshold}
            <input
              type="number"
              min={0}
              max={720}
              value={threshold}
              onChange={(event) => setThreshold(Number(event.target.value))}
              required
            />
          </label>
          <label>
            Frequência
            <select
              value={interval}
              disabled={mode === "times"}
              onChange={(event) =>
                setInterval(
                  Number(
                    event.target.value,
                  ) as SentinelRuleCommand["interval_minutes"],
                )
              }
            >
              {intervals.map((minutes) => (
                <option value={minutes} key={minutes}>
                  {frequency(minutes)} · {1440 / minutes} por dia
                </option>
              ))}
            </select>
          </label>
          <label>
            Horário de referência
            <input
              type="time"
              step={60}
              value={startTime}
              onChange={(event) => setStartTime(event.target.value)}
              required
            />
          </label>
        </div>
        <fieldset className="sentinel-options">
          <legend>Dias e janela de execução</legend>
          <div className="sentinel-weekdays">
            {["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"].map(
              (day, index) => (
                <label key={day}>
                  <input
                    type="checkbox"
                    checked={days.includes(index)}
                    onChange={() =>
                      setDays((current) =>
                        current.includes(index)
                          ? current.filter((d) => d !== index)
                          : [...current, index],
                      )
                    }
                  />
                  {day}
                </label>
              ),
            )}
          </div>
          <div className="sentinel-form-grid">
            <label>
              Fuso da regra
              <input
                value={zone}
                onChange={(e) => setZone(e.target.value)}
                placeholder="America/Sao_Paulo"
                required
              />
            </label>
            <label>
              Fim da janela (opcional)
              <input
                type="time"
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
              />
            </label>
            <label>
              Modo da agenda
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="interval">Intervalo</option>
                <option value="times">Horários específicos</option>
              </select>
            </label>
            {mode === "times" ? (
              <label>
                Horários (separados por vírgula)
                <input
                  value={times}
                  onChange={(e) => setTimes(e.target.value)}
                  placeholder="09:00, 14:00, 17:00"
                  required
                />
              </label>
            ) : null}
          </div>
          <p className="sentinel-form-note">
            A janela começa no horário de referência e termina no mesmo dia. O
            worker executa após o horário previsto; dias sem agenda não
            executam.
          </p>
        </fieldset>
        <fieldset className="sentinel-options">
          <legend>Recorte observado (opcional)</legend>
          <div className="sentinel-form-grid">
            <label>
              Etapa do CRM
              <select
                multiple
                value={stages}
                onChange={(e) =>
                  setStages(
                    Array.from(
                      e.target.selectedOptions,
                      (option) => option.value,
                    ) as typeof stages,
                  )
                }
              >
                {[
                  "new",
                  "qualification",
                  "proposal",
                  "negotiation",
                  "won",
                  "lost",
                ].map((value) => (
                  <option key={value} value={value}>
                    {
                      (
                        {
                          new: "Entrada",
                          qualification: "Qualificação",
                          proposal: "Proposta",
                          negotiation: "Negociação",
                          won: "Ganho",
                          lost: "Perdido",
                        } as Record<string, string>
                      )[value]
                    }
                  </option>
                ))}
              </select>
            </label>
            <label>
              Responsável
              <select
                value={owner}
                onChange={(e) => setOwner(e.target.value)}
                disabled={
                  kind === "unassigned" || options.isPending || options.isError
                }
              >
                <option value="">Toda a carteira</option>
                {owner &&
                !options.data?.members.some(
                  (member) => member.user_id === owner,
                ) ? (
                  <option value={owner}>Responsável configurado</option>
                ) : null}
                {options.data?.members.map((member) => (
                  <option key={member.user_id} value={member.user_id}>
                    {member.email ?? `Membro sem e-mail (${member.role})`}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Moeda
              <input
                value={currency}
                maxLength={3}
                pattern="[A-Z]{3}"
                onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                placeholder="BRL"
              />
            </label>
            <label>
              Valor mínimo
              <input
                type="number"
                min={0}
                step="0.01"
                value={minValue}
                onChange={(e) => setMinValue(e.target.value)}
              />
            </label>
            <label>
              Valor máximo
              <input
                type="number"
                min={0}
                step="0.01"
                value={maxValue}
                onChange={(e) => setMaxValue(e.target.value)}
              />
            </label>
            <label>
              Tipos de risco
              <select
                multiple
                value={risks
                  .split(",")
                  .map((r) => r.trim())
                  .filter(Boolean)}
                onChange={(e) =>
                  setRisks(
                    Array.from(
                      e.target.selectedOptions,
                      (option) => option.value,
                    ).join(","),
                  )
                }
              >
                {Object.entries(signalLabels).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="sentinel-form-note">
            Valores exigem moeda. Sem seleção de etapa ou risco, todas as
            condições correspondentes são consideradas.
          </p>
        </fieldset>
        <label className="sentinel-switch">
          <input
            type="checkbox"
            checked={interpret}
            disabled={!interpret && (options.data?.agent_slots ?? 0) < 1}
            onChange={(e) => setInterpret(e.target.checked)}
          />{" "}
          Interpretar achados com agente de IA
        </label>
        {options.isError ? (
          <p role="alert" className="sentinel-form-warning">
            Não foi possível carregar responsáveis e capacidade. Atualize a
            tela.
          </p>
        ) : null}
        <p className="sentinel-form-note">
          A interpretação usa capacidade e orçamento do plano. Sem IA, o achado
          objetivo permanece no sino.
        </p>
        <label className="sentinel-switch">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
          />{" "}
          Ativar esta sentinela
        </label>
        {!hasCapacity ? (
          <p className="sentinel-form-warning" role="alert">
            Limite do plano: {slots} sentinela{slots === 1 ? "" : "s"} ativa
            {slots === 1 ? "" : "s"}. Pause outra regra antes de ativar esta.
          </p>
        ) : null}
        <label className="sentinel-reason">
          Motivo da alteração
          <input
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            minLength={3}
            maxLength={500}
            placeholder="Ex.: acompanhar oportunidades paradas"
            required
          />
        </label>
        {mutation.isError || archive.isError ? (
          <p className="sentinel-form-warning" role="alert">
            {mutation.error?.message ?? archive.error?.message}
          </p>
        ) : null}
        {preview.isError ? (
          <p role="alert" className="sentinel-form-warning">
            {preview.error.message}
          </p>
        ) : null}
        {preview.data ? (
          <section className="sentinel-preview" aria-label="Resultado do teste">
            <strong>
              {preview.data.matched_count} oportunidades correspondem aos
              critérios.
            </strong>
            <p>
              Teste auditado, sem salvar achados, chamar IA ou escrever no CRM.
              {preview.data.truncated ? " Amostra de até 10 registros." : ""}
            </p>
            <ul>
              {preview.data.items.map((item) => (
                <li key={item.opportunity_id}>
                  {item.title ?? "Oportunidade ARES"}
                </li>
              ))}
            </ul>
          </section>
        ) : null}
        <div className="sentinel-editor-actions">
          <Button
            type="submit"
            disabled={mutation.isPending || archive.isPending || !hasCapacity}
          >
            {mutation.isPending
              ? "Salvando…"
              : rule
                ? "Salvar regra"
                : "Criar regra"}
          </Button>
          <Button
            type="button"
            variant="outline"
            disabled={preview.isPending || title.trim().length < 3}
            onClick={() => preview.mutate()}
          >
            {preview.isPending ? "Testando…" : "Testar critérios sem salvar"}
          </Button>
          {rule ? (
            <Button
              type="button"
              variant="outline"
              disabled={
                archive.isPending ||
                mutation.isPending ||
                reason.trim().length < 3
              }
              onClick={() => archive.mutate()}
            >
              {archive.isPending ? "Arquivando…" : "Arquivar regra"}
            </Button>
          ) : null}
        </div>
      </form>
    </section>
  );
}

export function SentinelsPage() {
  const { session } = useAuth();
  const [editing, setEditing] = useState<string | null>(null);
  const [saved, setSaved] = useState("");
  const catalog = useQuery({
    queryKey: ["sentinel-catalog"],
    queryFn: getSentinelCatalog,
    refetchInterval: 60_000,
  });
  const role = useQuery({
    queryKey: [
      "account-role",
      session.user.id,
      session.user.app_metadata.active_tenant_id,
    ],
    queryFn: () => account<{ role: string }>("/me"),
    retry: false,
  });
  const items = catalog.data?.items ?? [];
  const selected = items.find((item) => item.rule_id === editing) ?? null;
  const canEdit = role.data?.role === "admin";

  return (
    <main className="workspace sentinels-page">
      <header className="page-header">
        <div>
          <span className="eyebrow">ARES CONNECT / MONITORAMENTO</span>
          <h1>Sentinelas</h1>
          <p>
            Defina o que observar nas oportunidades, quando verificar e quantas
            vezes ao dia.
          </p>
          <Freshness timestamp={catalog.dataUpdatedAt} />
        </div>
        <div className="sentinel-header-actions">
          <Button
            variant="outline"
            disabled={catalog.isFetching}
            onClick={() => void catalog.refetch()}
          >
            <ArrowClockwiseIcon size={16} aria-hidden /> Atualizar
          </Button>
          {canEdit ? (
            <Button
              onClick={() => {
                setSaved("");
                setEditing("new");
              }}
            >
              <PlusIcon size={16} aria-hidden /> Criar sentinela
            </Button>
          ) : null}
        </div>
      </header>
      {catalog.isPending ? (
        <p className="sentinel-state" role="status">
          Carregando regras…
        </p>
      ) : catalog.isError ? (
        <section className="sentinel-state" role="alert">
          <strong>Regras indisponíveis</strong>
          <p>{catalog.error.message}</p>
          <Button variant="outline" onClick={() => void catalog.refetch()}>
            Tentar novamente
          </Button>
        </section>
      ) : catalog.data ? (
        <>
          <div className="sentinel-catalog-meta">
            <span>
              {catalog.data.active_count} de {catalog.data.sentinel_slots}{" "}
              sentinelas ativas no plano
            </span>
            <span>Fuso da empresa: {catalog.data.timezone}</span>
          </div>
          {saved ? (
            <p className="sentinel-form-success" role="status">
              {saved}
            </p>
          ) : null}
          {editing !== null && canEdit ? (
            <RuleEditor
              key={`${editing}-${selected?.version ?? "new"}`}
              rule={selected}
              timezone={catalog.data.timezone}
              slots={catalog.data.sentinel_slots}
              activeCount={catalog.data.active_count}
              onClose={() => setEditing(null)}
              onSaved={setSaved}
            />
          ) : null}
          {items.length ? (
            <ul
              className="sentinel-rule-grid"
              aria-label="Regras das sentinelas"
            >
              {items.map((rule) => (
                <li key={rule.rule_id} className="sentinel-rule-card">
                  <div className="sentinel-card-top">
                    <span className="sentinel-rule-icon">
                      <RuleIcon kind={rule.kind} />
                    </span>
                    <div>
                      <span className="eyebrow">
                        {kinds[rule.kind].name.toUpperCase()}
                      </span>
                      <h2>{rule.title}</h2>
                    </div>
                    <strong
                      className="sentinel-status"
                      data-running={rule.can_run}
                    >
                      {rule.can_run
                        ? "Ativa"
                        : rule.enabled
                          ? "Limite do plano"
                          : "Pausada"}
                    </strong>
                  </div>
                  <p className="sentinel-card-definition">
                    {rule.definition}{" "}
                    {rule.threshold_hours
                      ? `Limite: ${rule.threshold_hours} h.`
                      : "Detecção imediata após o limite."}
                  </p>
                  <dl className="sentinel-card-facts">
                    <div>
                      <dt>Frequência</dt>
                      <dd>
                        {rule.calendar?.execution_times?.length
                          ? rule.calendar.execution_times
                              .map((t) => t.slice(0, 5))
                              .join(" · ")
                          : frequency(rule.interval_minutes)}
                      </dd>
                    </div>
                    <div>
                      <dt>Execuções previstas</dt>
                      <dd>
                        {rule.calendar?.execution_times?.length ||
                          (rule.calendar?.timezone ||
                          rule.calendar?.end_time_local
                            ? Math.floor(
                                ((
                                  rule.calendar?.end_time_local?.slice(0, 5) ??
                                  "23:59"
                                )
                                  .split(":")
                                  .reduce((h, m) => h * 60 + Number(m), 0) -
                                  rule.start_time_local
                                    .slice(0, 5)
                                    .split(":")
                                    .reduce((h, m) => h * 60 + Number(m), 0)) /
                                  rule.interval_minutes,
                              ) + 1
                            : 1440 / rule.interval_minutes)}{" "}
                        por dia
                      </dd>
                    </div>
                    <div>
                      <dt>Início no dia</dt>
                      <dd>{rule.start_time_local.slice(0, 5)}</dd>
                    </div>
                    <div>
                      <dt>Próxima</dt>
                      <dd>
                        {rule.can_run
                          ? localDate(rule.next_run_at, rule.timezone)
                          : "Não programada"}
                      </dd>
                    </div>
                    <div>
                      <dt>Última</dt>
                      <dd>{localDate(rule.last_run_at, rule.timezone)}</dd>
                    </div>
                    <div>
                      <dt>Novos achados</dt>
                      <dd>{rule.last_created_count ?? "—"}</dd>
                    </div>
                  </dl>
                  <p className="sentinel-form-note">
                    {(rule.calendar?.days_of_week ?? [0, 1, 2, 3, 4, 5, 6])
                      .map(
                        (d) =>
                          ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"][d],
                      )
                      .join(" · ")}{" "}
                    · {rule.timezone}
                    {rule.calendar?.end_time_local
                      ? ` · Até ${rule.calendar.end_time_local.slice(0, 5)}`
                      : ""}
                  </p>
                  <p className="sentinel-form-note">
                    {rule.criteria?.stages?.length
                      ? `Etapa: ${rule.criteria.stages.join(", ")} · `
                      : ""}
                    {rule.criteria?.currency
                      ? `Moeda: ${rule.criteria.currency} · Valor: ${rule.criteria.min_value ?? "sem mínimo"} a ${rule.criteria.max_value ?? "sem máximo"}`
                      : "Toda a carteira nos critérios da regra"}{" "}
                    ·{" "}
                    {rule.interpret_with_ai
                      ? "Interpretação por IA"
                      : "Detecção objetiva"}
                  </p>
                  {rule.last_error_code ? (
                    <p role="status" className="sentinel-form-warning">
                      Última falha: {rule.last_error_code}
                    </p>
                  ) : null}
                  <div className="sentinel-card-foot">
                    <span>
                      <ClockCountdownIcon size={15} aria-hidden /> Somente
                      leitura · ARES Core
                    </span>
                    {canEdit ? (
                      <Button
                        variant="outline"
                        onClick={() => {
                          setSaved("");
                          setEditing(rule.rule_id);
                        }}
                      >
                        Configurar
                      </Button>
                    ) : null}
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <section className="sentinel-state">
              <h2>Nenhuma sentinela configurada</h2>
              <p>Crie uma regra para iniciar o monitoramento.</p>
            </section>
          )}
          {!canEdit && !role.isPending ? (
            <p className="sentinel-readonly">
              Somente o administrador da empresa pode criar ou alterar regras.
            </p>
          ) : null}
        </>
      ) : null}
    </main>
  );
}
