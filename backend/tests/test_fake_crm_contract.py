from ares.connectors.fake_crm import FakeCRMProvider


def test_fake_crm_supports_cursor_reads_and_idempotent_writes() -> None:
    provider = FakeCRMProvider("test-secret")

    first_page = provider.list_deals(limit=1)
    second_page = provider.list_deals(cursor=first_page.next_cursor, limit=1)
    first_write = provider.create_task("deal-001", "Retomar proposta", "intent-001")
    duplicate_write = provider.create_task("deal-001", "Retomar proposta", "intent-001")
    stage_write = provider.update_deal_stage("deal-002", "proposal", "intent-002")

    assert provider.capabilities().read_deals is True
    assert len(first_page.items) == 1
    assert len(second_page.items) == 1
    assert first_page.items[0].id != second_page.items[0].id
    assert first_write.duplicate is False
    assert duplicate_write.external_id == first_write.external_id
    assert duplicate_write.duplicate is True
    assert stage_write.duplicate is False
    assert provider.list_deals().items[1].stage == "proposal"
