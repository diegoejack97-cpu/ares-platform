-- Distinguish embedding generation from chat/model generation in measured usage.
alter table public.agent_runs drop constraint agent_runs_generation_mode_check;
alter table public.agent_runs add constraint agent_runs_generation_mode_check
 check(generation_mode in ('agno_openai','deterministic_fallback','openai_embeddings'));
