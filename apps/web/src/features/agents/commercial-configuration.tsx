import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/features/auth/auth-context";
import type { CommercialConfig } from "./contract";
import {
  getCommercialConfiguration,
  saveCommercialConfiguration,
  type CommercialConfiguration,
} from "./commercial-api";
import "./commercial.css";

export function CommercialConfigurationPanel() {
  const { session } = useAuth();
  const [saved, setSaved] = useState(false);
  const query = useQuery({
    queryKey: [
      "commercial-config",
      session.user.id,
      session.user.app_metadata.active_tenant_id,
    ],
    queryFn: getCommercialConfiguration,
  });
  return (
    <section
      className="panel commercial-panel"
      aria-label="Configurar agentes comerciais"
    >
      <header>
        <div>
          <span className="eyebrow">ROTINAS E LIMITES</span>
          <h2>Agentes comerciais</h2>
          <p>
            Priorização e Analista comercial ocupam uma rotina adicional.
            Recomendação e Follow-up usam a rotina de intervenção.
          </p>
        </div>
      </header>
      {query.isPending ? (
        <p role="status">Carregando configuração…</p>
      ) : query.isError ? (
        <p role="alert">
          Não foi possível ler a configuração.{" "}
          <Button onClick={() => void query.refetch()}>Tentar novamente</Button>
        </p>
      ) : query.data ? (
        <CommercialConfigurationForm
          key={query.data.version}
          data={query.data}
          onSaved={() => setSaved(true)}
        />
      ) : null}
      {saved ? <p role="status">Configuração salva.</p> : null}
    </section>
  );
}

function CommercialConfigurationForm({
  data,
  onSaved,
}: {
  data: CommercialConfiguration;
  onSaved: () => void;
}) {
  const client = useQueryClient();
  const [enabled, setEnabled] = useState(data.config?.enabled ?? false);
  const [recommendations, setRecommendations] = useState(
    data.config?.recommendations_enabled ?? false,
  );
  const [proactive, setProactive] = useState(
    data.config?.proactive_enabled ?? false,
  );
  const [criterion, setCriterion] = useState<
    NonNullable<CommercialConfig["criterion"]>
  >(data.config?.criterion ?? "urgency");
  const [currency, setCurrency] = useState(data.config?.currency ?? "BRL");
  const [times, setTimes] = useState(
    data.config?.calendar_json?.execution_times?.join(", ") ?? "09:00",
  );
  const [timezone, setTimezone] = useState(
    data.config?.calendar_json?.timezone ?? "America/Sao_Paulo",
  );
  const [days, setDays] = useState<number[]>(
    data.config?.calendar_json?.days_of_week ?? [0, 1, 2, 3, 4],
  );
  const [cooldown, setCooldown] = useState(data.config?.cooldown_hours ?? 24);
  const [limit, setLimit] = useState(data.config?.daily_proposal_limit ?? 3);
  const [reason, setReason] = useState("");
  const mutation = useMutation({
    mutationFn: saveCommercialConfiguration,
    onSuccess: () => {
      onSaved();
      void client.invalidateQueries({ queryKey: ["commercial-config"] });
      void client.invalidateQueries({ queryKey: ["portfolio-analysis"] });
    },
  });
  return (
    <form
      className="commercial-form"
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate({
          expected_version: data.version,
          enabled,
          recommendations_enabled: recommendations,
          proactive_enabled: proactive,
          criterion,
          currency: criterion === "value" ? currency : null,
          calendar: {
            days_of_week: days,
            timezone,
            execution_times: times
              .split(",")
              .map((value) => value.trim())
              .filter(Boolean),
          },
          cooldown_hours: cooldown,
          daily_proposal_limit: limit,
          reason,
        });
      }}
    >
      <fieldset disabled={!data.can_configure || mutation.isPending}>
        <legend>Execução por empresa</legend>
        <label>
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            disabled={!data.available}
          />{" "}
          Ativar análise da carteira
        </label>
        <label>
          <input
            type="checkbox"
            checked={recommendations}
            onChange={(e) => {
              setRecommendations(e.target.checked);
              if (!e.target.checked) setProactive(false);
            }}
          />{" "}
          Separar Recomendação e Follow-up
        </label>
        <label>
          <input
            type="checkbox"
            checked={proactive}
            disabled={!recommendations || !enabled}
            onChange={(e) => setProactive(e.target.checked)}
          />{" "}
          Preparar propostas automaticamente, sem aprovar
        </label>
        <label>
          Critério do briefing
          <select
            value={criterion}
            onChange={(e) => setCriterion(e.target.value as typeof criterion)}
          >
            <option value="urgency">Urgência</option>
            <option value="value">Maior valor</option>
            <option value="deadline">Prazo próximo</option>
            <option value="attractiveness">Atratividade com evidências</option>
          </select>
        </label>
        {criterion === "value" ? (
          <label>
            Moeda
            <input
              value={currency}
              onChange={(e) => setCurrency(e.target.value.toUpperCase())}
              pattern="[A-Z]{3}"
              required
            />
          </label>
        ) : null}
        <label>
          Horários do briefing
          <input
            value={times}
            onChange={(e) => setTimes(e.target.value)}
            placeholder="09:00, 15:00"
            required
          />
        </label>
        <label>
          Fuso horário
          <input
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            required
          />
        </label>
        <div className="commercial-days">
          {["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"].map(
            (day, index) => (
              <label key={day}>
                <input
                  type="checkbox"
                  checked={days.includes(index)}
                  onChange={(e) =>
                    setDays(
                      e.target.checked
                        ? [...days, index]
                        : days.filter((value) => value !== index),
                    )
                  }
                />
                {day}
              </label>
            ),
          )}
        </div>
        <label>
          Intervalo mínimo por oportunidade (horas)
          <input
            type="number"
            min="1"
            max="168"
            value={cooldown}
            onChange={(e) => setCooldown(Number(e.target.value))}
            required
          />
        </label>
        <label>
          Máximo de propostas por dia
          <input
            type="number"
            min="1"
            max="20"
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            required
          />
        </label>
        <label>
          Motivo da alteração
          <input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            minLength={3}
            maxLength={500}
            required
          />
        </label>
        <Button type="submit">
          {mutation.isPending ? "Salvando…" : "Salvar rotina"}
        </Button>
      </fieldset>
      {!data.available ? (
        <p>
          O plano exige pelo menos três capacidades de rotina para análise de
          carteira.
        </p>
      ) : null}
      {!data.can_configure ? (
        <p>Somente o administrador da empresa configura as rotinas.</p>
      ) : null}
      {mutation.isError ? <p role="alert">{mutation.error.message}</p> : null}
    </form>
  );
}
