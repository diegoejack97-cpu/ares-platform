"""Synthetic tenant isolation, revocation, real pgvector/FTS, and outcome lineage."""

# ruff: noqa: E501
from uuid import UUID, uuid4

import pytest
import test_postgres_agent_runtime as base

from ares.auth.models import AuthenticatedUser
from ares.impact.evaluation import Feedback, OutcomeService
from ares.intelligence.context_builder import ContextUnavailable
from ares.knowledge.models import DocumentUpload, MemoryConfig
from ares.knowledge.service import KnowledgeService

fixture = base.fixture
query = base.query
pytestmark = base.pytestmark


class SyntheticEmbedder:
    def __init__(self):
        self.calls = []
        self.hook = None

    def embed(self, texts):
        self.calls.append(texts)
        if self.hook:
            self.hook()
        return [[1.0] + [0.0] * 1535 for _ in texts], 100


@pytest.fixture
def case(fixture):
    _, user, opp, snapshot, _, seller = fixture
    service = KnowledgeService(base.URL)
    service.configure(
        user,
        MemoryConfig(
            expected_version=0,
            enabled=True,
            outcomes_enabled=True,
            reason="Synthetic configuration",
        ),
    )
    yield fixture, service, user, opp, snapshot, seller
    for table in (
        "messages",
        "conversations",
        "outcome_feedback",
        "outcome_evaluations",
        "knowledge_chunks",
        "knowledge_versions",
        "knowledge_documents",
        "outcomes",
        "action_executions",
        "decisions",
        "recommendations",
        "policy_decisions",
        "ares_interventions",
        "knowledge_reads",
        "knowledge_audit",
        "knowledge_embedding_budget",
        "knowledge_settings",
    ):
        query(fixture, f"delete from public.{table} where tenant_id=%s", (user.tenant_id,))


def upload(case, **changes):
    _, service, user, *_ = case
    return service.upload(
        user,
        DocumentUpload(
            **{
                "filename": "playbook.md",
                "title": "Playbook sintético",
                "source_label": "Treinamento sintético aprovado",
                "content": "O procedimento comercial orienta revisar a proposta antes do contato. Prazo para contato: dois dias.",
                "verified_source": True,
                "reason": "Synthetic approved playbook",
                **changes,
            }
        ),
    )


def index(case, document):
    fixture, service, user, *_ = case
    row = query(
        fixture,
        "select id from public.knowledge_versions where tenant_id=%s and document_id=%s order by version desc limit 1",
        (user.tenant_id, document["document_id"]),
    )[0]
    service.index(user.tenant_id, {"version_id": str(row["id"]), "actor_id": str(user.user_id)})


def test_local_fts_literal_citations_and_dedupe(case):
    _, service, user, *_ = case
    doc = upload(case)
    index(case, doc)
    answer = service.retrieve(user, "Qual procedimento para contato?", "chat")
    assert answer["mode"] == "lexical" and len(answer["hits"]) == 1
    assert answer["hits"][0]["document_id"] == str(doc["document_id"])
    assert (
        answer["hits"][0]["quote"]
        in "O procedimento comercial orienta revisar a proposta antes do contato. Prazo para contato: dois dias."
    )
    same = upload(case, document_id=doc["document_id"], expected_version=1)
    assert same["unchanged"] and same["version"] == 1
    service.validate_read(user, UUID(answer["context_ref"]))


def test_version_removal_invalidates_quotes_and_receipts(case):
    fixture, service, user, *_ = case
    doc = upload(case)
    index(case, doc)
    answer = service.retrieve(user, "contato", "chat")
    updated = upload(
        case,
        document_id=doc["document_id"],
        expected_version=1,
        content="Agora o procedimento determina contato somente após revisão humana.",
    )
    assert updated["version"] == 2
    with pytest.raises(ContextUnavailable):
        service.validate_read(user, UUID(answer["context_ref"]))
    assert (
        query(
            fixture,
            "select original_text from public.knowledge_versions where tenant_id=%s and document_id=%s and version=1",
            (user.tenant_id, doc["document_id"]),
        )[0]["original_text"]
        is None
    )
    index(case, updated)
    service.remove(user, doc["document_id"], "Synthetic document removal")
    assert not service.retrieve(user, "contato", "chat")["hits"]


def test_scope_role_purpose_and_other_tenant_filtered_before_search(case):
    _, service, user, _, _, seller = case
    doc = upload(
        case, allowed_roles=["admin", "seller"], owner_user_id=user.user_id, purposes=["diagnosis"]
    )
    index(case, doc)
    selling = AuthenticatedUser(tenant_id=user.tenant_id, user_id=seller, role="seller")
    assert not service.retrieve(selling, "contato", "diagnosis")["hits"]
    assert not service.retrieve(user, "contato", "chat")["hits"]
    assert service.retrieve(user, "contato", "diagnosis")["hits"]
    with pytest.raises(ContextUnavailable):
        service.retrieve(user.model_copy(update={"tenant_id": uuid4()}), "contato", "diagnosis")


def test_seller_shared_documents_cannot_bypass_explicit_owner(case):
    _, service, *_ = case
    with pytest.raises(ContextUnavailable, match="knowledge_seller_scope_required"):
        upload(case, allowed_roles=["admin", "seller"])


def test_storage_budget_expiry_and_revoked_membership(case):
    fixture, service, user, *_ = case
    query(
        fixture,
        "update public.tenant_quotas set memory_storage_bytes=0 where tenant_id=%s",
        (user.tenant_id,),
    )
    with pytest.raises(ContextUnavailable, match="knowledge_storage_exceeded"):
        upload(case)
    query(
        fixture,
        "update public.tenant_quotas set memory_storage_bytes=20971520 where tenant_id=%s",
        (user.tenant_id,),
    )
    doc = upload(case)
    index(case, doc)
    query(
        fixture,
        "update public.knowledge_versions set expires_at=now()-interval '1 day' where tenant_id=%s",
        (user.tenant_id,),
    )
    assert not service.retrieve(user, "contato", "chat")["hits"]
    service.expire()
    assert not query(
        fixture, "select id from public.knowledge_chunks where tenant_id=%s", (user.tenant_id,)
    )
    query(
        fixture,
        "update public.memberships set active=false where tenant_id=%s and user_id=%s",
        (user.tenant_id, user.user_id),
    )
    with pytest.raises(ContextUnavailable):
        service.documents(user)


def test_embedding_explicit_consent_measured_budget_hybrid_and_no_reindex(case):
    fixture, service, user, *_ = case
    embedder = SyntheticEmbedder()
    service.embedder = embedder
    doc = upload(case)
    index(case, doc)
    assert not embedder.calls
    service.configure(
        user,
        MemoryConfig(
            expected_version=1,
            enabled=True,
            external_consent=True,
            outcomes_enabled=True,
            reason="Synthetic external consent",
        ),
    )
    changed = upload(
        case,
        document_id=doc["document_id"],
        expected_version=1,
        content="Procedimento de contato: revisar condições de renovação e oportunidades da carteira.",
    )
    index(case, changed)
    assert len(embedder.calls) == 1, query(
        fixture,
        "select status,error_code from public.knowledge_versions where tenant_id=%s",
        (user.tenant_id,),
    )
    result = service.retrieve(user, "contato comercial", "chat")
    assert result["mode"] == "hybrid" and result["hits"]
    assert (
        query(
            fixture,
            "select measured_usd from public.knowledge_embedding_budget where tenant_id=%s",
            (user.tenant_id,),
        )[0]["measured_usd"]
        > 0
    )


def test_embedding_consent_revoked_during_call_prevents_publication(case):
    fixture, service, user, *_ = case
    service.configure(
        user,
        MemoryConfig(
            expected_version=1,
            enabled=True,
            external_consent=True,
            reason="Synthetic consent setup",
        ),
    )
    embedder = SyntheticEmbedder()
    embedder.hook = lambda: service.configure(
        user,
        MemoryConfig(
            expected_version=2,
            enabled=True,
            external_consent=False,
            reason="Synthetic consent revocation",
        ),
    )
    service.embedder = embedder
    doc = upload(case)
    index(case, doc)
    row = query(
        fixture,
        "select status,error_code from public.knowledge_versions where tenant_id=%s",
        (user.tenant_id,),
    )[0]
    assert row["status"] == "failed" and row["error_code"] == "knowledge_consent_changed"
    assert not query(
        fixture,
        "select id from public.knowledge_chunks where tenant_id=%s and embedding is not null",
        (user.tenant_id,),
    )


def intervention(case, outcome=False):
    fixture, _, user, opp, snapshot, _ = case
    id = uuid4()
    query(
        fixture,
        "insert into public.ares_interventions(id,tenant_id,opportunity_id,correlation_id,state_before_ref,source) values(%s,%s,%s,%s,%s,'ares')",
        (id, user.tenant_id, opp, uuid4(), snapshot),
    )
    if outcome:
        query(
            fixture,
            "insert into public.outcomes(tenant_id,intervention_id,opportunity_id,correlation_id,state_after_ref,result_type,actor_type,source,observed_at) values(%s,%s,%s,%s,%s,'observed_change','system','crm',now())",
            (user.tenant_id, id, opp, uuid4(), snapshot),
        )
    return id


def test_no_outcome_is_pending_and_does_not_invoke_model(case):
    _, _, user, *_ = case
    service = OutcomeService(base.URL)
    id = intervention(case)
    result = service.start(user, id)
    assert result["status"] == "pending" and not result["run_id"]
    assert service.latest(user, id)["state"] == "pending"
    assert service.metrics(user)["pending"] == 1


def test_outcome_chain_fallback_feedback_and_stale_result(case):
    fixture, _, user, _, _, seller = case
    service = OutcomeService(base.URL)
    id = intervention(case, True)
    result = service.start(user, id)
    service.process(user.tenant_id, {"evaluation_id": str(result["id"])})
    latest = service.latest(user, id)
    assert latest["state"] == "degraded"
    assert not latest["evaluation"]["explanation_json"]["causal_conclusion"]
    assert latest["chain"]["state_before_ref"] and latest["chain"]["state_after_ref"]
    assert latest["chain"]["outcome"]["incremental_value"] is None
    service.feedback(
        user, result["id"], Feedback(rating="helpful", rationale="Synthetic user opinion")
    )
    assert service.latest(user, id)["chain"] == latest["chain"]
    selling = AuthenticatedUser(tenant_id=user.tenant_id, user_id=seller, role="seller")
    with pytest.raises(ContextUnavailable):
        service.latest(selling, id)
    query(
        fixture,
        "update public.outcomes set result_type='late_change' where tenant_id=%s and intervention_id=%s",
        (user.tenant_id, id),
    )
    assert service.latest(user, id)["state"] == "not_requested"


def test_concurrent_and_late_outcomes_remain_observations(case):
    fixture, _, user, *_ = case
    service = OutcomeService(base.URL)
    id = intervention(case, True)
    intervention(case)
    query(
        fixture,
        "update public.outcomes set observed_at=now()+interval '4 days' where tenant_id=%s and intervention_id=%s",
        (user.tenant_id, id),
    )
    result = service.latest(user, id)
    assert result["chain"]["late_outcome"] and result["chain"]["concurrent_interventions"] == 1
    assert service.metrics(user)["response_seconds"] is None


def test_episode_opt_in_and_correction_removes_retrieval_not_history(case):
    fixture, memory, user, *_ = case
    service = OutcomeService(base.URL)
    id = intervention(case, True)
    result = service.start(user, id)
    service.process(user.tenant_id, {"evaluation_id": str(result["id"])})
    with pytest.raises(ContextUnavailable, match="outcome_episode_disabled"):
        service.publish_episode(user, result["id"], "Synthetic verified episode")
    memory.configure(
        user,
        MemoryConfig(
            expected_version=1,
            enabled=True,
            outcomes_enabled=True,
            episodes_enabled=True,
            reason="Synthetic episode authorization",
        ),
    )
    document = service.publish_episode(user, result["id"], "Synthetic verified episode")
    index(case, document)
    assert memory.retrieve(user, "episódio observado", "chat")["hits"]
    query(
        fixture,
        "update public.outcomes set result_type='corrected_change' where tenant_id=%s and intervention_id=%s",
        (user.tenant_id, id),
    )
    assert not memory.retrieve(user, "episódio observado", "chat")["hits"]
    assert (
        query(
            fixture,
            "select original_text from public.knowledge_versions where tenant_id=%s and document_id=%s",
            (user.tenant_id, document["document_id"]),
        )[0]["original_text"]
        is not None
    )


def test_labelled_retrieval_other_company_and_release_metrics(case):
    import json
    from pathlib import Path

    from ares.agents.quality import retrieval_metrics
    from ares.knowledge.models import DocumentUpload

    fixture, memory, user, *_ = case
    dataset = json.loads(
        (Path(__file__).parent / "fixtures/commercial-memory-outcomes.synthetic.v1.json").read_text(
            encoding="utf-8"
        )
    )
    ids = {}
    for doc in dataset["documents"]:
        if doc["tenant"] == "A":
            saved = upload(case, title=doc["key"], content=doc["text"])
            index(case, saved)
            ids[str(saved["document_id"])] = doc["key"]
    # A real second tenant has a nearly identical, indexed playbook.
    generator = base.fixture.__wrapped__()
    second = next(generator)
    other = KnowledgeService(base.URL)
    try:
        other.configure(
            second[1],
            MemoryConfig(expected_version=0, enabled=True, reason="Synthetic other company"),
        )
        doc = dataset["documents"][2]
        saved = other.upload(
            second[1],
            DocumentUpload(
                filename="other.md",
                title=doc["key"],
                source_label="Synthetic other source",
                content=doc["text"],
                verified_source=True,
                reason="Synthetic other company playbook",
            ),
        )
        version = query(
            second,
            "select id from public.knowledge_versions where tenant_id=%s",
            (second[1].tenant_id,),
        )[0]["id"]
        other.index(
            second[1].tenant_id, {"version_id": str(version), "actor_id": str(second[1].user_id)}
        )
        cases = []
        for label in dataset["questions"]:
            answer = memory.retrieve(user, label["question"], "chat")
            assert all(hit["document_id"] in ids for hit in answer["hits"])
            # All returned references/quotes must reconstruct the original version.
            valid = all(
                query(
                    fixture,
                    "select content from public.knowledge_chunks where tenant_id=%s and id=%s",
                    (user.tenant_id, UUID(hit["chunk_id"])),
                )[0]["content"].startswith(hit["quote"])
                for hit in answer["hits"]
            )
            cases.append(
                {
                    "expected": label["expected"],
                    "retrieved": [ids[h["document_id"]] for h in answer["hits"]],
                    "citations_valid": valid,
                }
            )
        metrics = retrieval_metrics(cases)
        print("synthetic_retrieval_metrics", metrics)
        assert metrics["recall_at_5"] >= 0.8
        assert metrics["precision_at_5"] >= 0.8, metrics
        assert metrics["citation_fidelity"] == 1.0
    finally:
        for table in (
            "knowledge_reads",
            "knowledge_chunks",
            "knowledge_versions",
            "knowledge_documents",
            "knowledge_audit",
            "knowledge_settings",
        ):
            query(second, f"delete from public.{table} where tenant_id=%s", (second[1].tenant_id,))
        from contextlib import suppress

        with suppress(StopIteration):
            next(generator)


def test_chat_playbook_quotes_sources_and_revokes_history(case):
    from pydantic import SecretStr

    from ares.chat.service import ChatService
    from ares.config import get_settings

    fixture, memory, user, *_ = case
    saved = upload(case)
    index(case, saved)
    settings = get_settings().model_copy(
        update={"database_url": base.URL, "openai_api_key": SecretStr("")}
    )
    chat = ChatService(settings)
    prepared = chat.prepare(user, None, "Qual procedimento comercial para contato no playbook?")
    output = "".join(chat.stream(prepared))
    assert "Trechos da memória comercial" in output and "versão 1" in output
    assert "Prazo para contato: dois dias." in output
    assert chat.history(user, None)["items"][0]["context_json"]["memory"]["hits"]
    memory.configure(
        user,
        MemoryConfig(
            expected_version=1, enabled=False, reason="Synthetic memory access revocation"
        ),
    )
    history = chat.history(user, None)["items"][0]
    assert "Fonte indisponível" in history["assistant_text"]
    assert "memory" not in history["context_json"]


def test_metadata_change_does_not_reembed_same_content(case):
    _, memory, user, *_ = case
    embedder = SyntheticEmbedder()
    memory.embedder = embedder
    memory.configure(
        user,
        MemoryConfig(
            expected_version=1,
            enabled=True,
            external_consent=True,
            reason="Synthetic external consent",
        ),
    )
    doc = upload(case)
    index(case, doc)
    assert len(embedder.calls) == 1
    doc = upload(
        case,
        document_id=doc["document_id"],
        expected_version=1,
        source_label="New synthetic verified source",
    )
    index(case, doc)
    assert len(embedder.calls) == 1


def test_indexing_budget_zero_prevents_external_call(case):
    fixture, memory, user, *_ = case
    embedder = SyntheticEmbedder()
    memory.embedder = embedder
    memory.configure(
        user,
        MemoryConfig(
            expected_version=1,
            enabled=True,
            external_consent=True,
            reason="Synthetic external consent",
        ),
    )
    query(
        fixture,
        "update public.tenant_quotas set embedding_daily_budget_brl=0 where tenant_id=%s",
        (user.tenant_id,),
    )
    doc = upload(case)
    index(case, doc)
    assert not embedder.calls
    assert (
        query(
            fixture,
            "select error_code from public.knowledge_versions where tenant_id=%s",
            (user.tenant_id,),
        )[0]["error_code"]
        == "embedding_budget_exceeded"
    )


def test_auditor_downgrade_prevents_queued_outcome_execution(case):
    fixture, _, user, *_ = case
    service = OutcomeService(base.URL)
    id = intervention(case, True)
    result = service.start(user, id)
    query(fixture, "update public.memberships set role='auditor' where tenant_id=%s and user_id=%s", (user.tenant_id, user.user_id))
    service.process(user.tenant_id, {"evaluation_id": str(result["id"])})
    row = query(fixture, "select status,run_id,error_code from public.outcome_evaluations where tenant_id=%s and id=%s", (user.tenant_id, result["id"]))[0]
    assert row["status"] == "failed" and row["run_id"] is None
    assert row["error_code"] == "outcome_write_forbidden"


def test_complete_outcome_chain_preserves_links_and_financial_values(case):
    fixture, _, user, opp, _, _ = case
    service = OutcomeService(base.URL)
    id = intervention(case, True)
    recommendation, policy, decision, execution, correlation = [uuid4() for _ in range(5)]
    query(fixture, "insert into public.recommendations(id,tenant_id,intervention_id,opportunity_id,correlation_id,kind,recommended_action,rationale,confidence,status) values(%s,%s,%s,%s,%s,'create_task','{}','Synthetic rationale',0.8,'approved')", (recommendation,user.tenant_id,id,opp,correlation))
    query(fixture, "insert into public.policy_decisions(id,tenant_id,policy_set,policy_version,inputs_hash,verdict) values(%s,%s,'synthetic',1,'synthetic','allow')", (policy,user.tenant_id))
    query(fixture, "insert into public.decisions(id,tenant_id,intervention_id,recommendation_id,policy_decision_id,correlation_id,actor_type,actor_id,verdict,source) values(%s,%s,%s,%s,%s,%s,'human',%s,'approved','human')", (decision,user.tenant_id,id,recommendation,policy,correlation,str(user.user_id)))
    query(fixture, "insert into public.action_executions(id,tenant_id,intervention_id,correlation_id,executed_action,target,actor_type,actor_id,source,status,idempotency_key,started_at,finished_at,result) values(%s,%s,%s,%s,'{}','{}','ares_agent','synthetic-worker','ares','succeeded',%s,now(),now(),'{\"confirmed\":true,\"version\":3,\"email\":\"private@example.invalid\"}')", (execution,user.tenant_id,id,correlation,str(uuid4())))
    query(fixture, "update public.outcomes set action_execution_id=%s,sale_value=100,ares_influenced_value=50,currency='BRL',attribution_level='influenced' where tenant_id=%s and intervention_id=%s", (execution,user.tenant_id,id))
    chain=service.latest(user,id)['chain']
    assert chain['recommendations'][0]['id'] == str(recommendation)
    assert chain['decisions'][0]['recommendation_id'] == str(recommendation)
    assert chain['executions'][0]['id'] == str(execution)
    assert chain['executions'][0]['provider_confirmation'] == {'confirmed':True,'version':3}
    assert chain['outcome']['action_execution_id'] == str(execution)
    assert float(chain['outcome']['sale_value']) == 100
    assert float(chain['outcome']['ares_influenced_value']) == 50
    assert chain['outcome']['incremental_value'] is None
    metrics=service.metrics(user)
    assert metrics['adoption']['numerator'] == 1 and metrics['adoption']['denominator'] == 1
