"""Create a dedicated synthetic local operator and labeled M6 outcome scenarios."""
import json
import base64
import secrets
from pathlib import Path
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx
import psycopg

from ares.config import get_settings
from ares.provider.models import ProviderPrincipal
from ares.provider.service import ProviderService
from ares.provider.quotas import QuotaCommand, set_quota

settings=get_settings()
assert settings.environment=="development"
assert urlparse(settings.supabase_url).hostname in {"localhost","127.0.0.1"}
assert urlparse(settings.database_url).hostname in {"localhost","127.0.0.1"}
credentials=Path("output/runtime/m6-provider-credentials.json")
credentials.parent.mkdir(parents=True,exist_ok=True)
with psycopg.connect(settings.database_url) as db:
    existing=db.execute("select user_id from private.provider_operators where active").fetchone()
    if not existing:
        password=secrets.token_urlsafe(30)
        email="provider-m6@ares.local"
        headers={"apikey":settings.supabase_secret_key.get_secret_value(),"Authorization":f"Bearer {settings.supabase_secret_key.get_secret_value()}"}
        result=httpx.post(f"{settings.supabase_url}/auth/v1/admin/users",headers=headers,json={"email":email,"password":password,"email_confirm":True},timeout=10)
        if result.status_code not in {200,201}:raise RuntimeError(f"local_operator_creation_failed_{result.status_code}")
        actor=UUID(result.json()["id"])
        db.execute("insert into private.provider_operators(user_id,reason) values(%s,'M6 synthetic local pilot operator')",(actor,))
        credentials.write_text(json.dumps({"email":email,"password":password}),encoding="utf-8")
    # Three separately labeled synthetic opportunities; no modification of customer records.
    tenant=settings.tenant_id
    for label,sale,influenced,result_type,level in [("observed",1000,None,"sale_observed","observed"),("influenced",2000,1200,"recovered","influenced"),("unproven",3000,None,"sale_observed","associated")]:
        ids={kind:uuid5(NAMESPACE_URL,f"ares-m6-pilot:{tenant}:{label}:{kind}") for kind in ["deal","opportunity","context","intervention","correlation","outcome"]}
        db.execute("insert into public.deals(id,tenant_id,title,value,currency,external_ref) values(%s,%s,%s,%s,'BRL','{\"provider\":\"synthetic-pilot\",\"synthetic\":true}'::jsonb) on conflict(id) do nothing",(ids["deal"],tenant,f"[SINTETICO M6] {label}",sale))
        db.execute("insert into public.ares_opportunities(id,tenant_id,opportunity_type,state) values(%s,%s,'m6_synthetic_pilot','observing') on conflict(id) do nothing",(ids["opportunity"],tenant))
        db.execute("update public.ares_opportunities set deal_id=%s where tenant_id=%s and id=%s and opportunity_type='m6_synthetic_pilot' and deal_id is null",(ids["deal"],tenant,ids["opportunity"]))
        db.execute("insert into public.context_snapshots(id,tenant_id,opportunity_id,snapshot_version,opportunity_state,content_hash,source,source_ref,facts_json) values(%s,%s,%s,1,'observing',%s,'ares','m6-synthetic-pilot','{\"synthetic\":true}'::jsonb) on conflict(id) do nothing",(ids["context"],tenant,ids["opportunity"],f"m6-synthetic-{label}"))
        db.execute("insert into public.ares_interventions(id,tenant_id,opportunity_id,correlation_id,state_before_ref,state_after_ref,status,source,source_ref) values(%s,%s,%s,%s,%s,%s,'observing','ares','m6-synthetic-pilot') on conflict(id) do nothing",(ids["intervention"],tenant,ids["opportunity"],ids["correlation"],ids["context"],ids["context"]))
        db.execute("insert into public.outcomes(id,tenant_id,intervention_id,opportunity_id,correlation_id,state_after_ref,result_type,sale_value,ares_influenced_value,incremental_value,currency,attribution_level,actor_type,actor_id,source,source_ref,observed_at) values(%s,%s,%s,%s,%s,%s,%s,%s,%s,null,'BRL',%s,'system','m6-synthetic-pilot','ares','m6-synthetic-pilot',now()) on conflict(id) do nothing",(ids["outcome"],tenant,ids["intervention"],ids["opportunity"],ids["correlation"],ids["context"],result_type,sale,influenced,level))
with psycopg.connect(settings.database_url) as db:
    configured=db.execute("select 1 from public.tenant_quotas where tenant_id=%s",(tenant,)).fetchone()
    version=db.execute("select version from public.tenants where id=%s",(tenant,)).fetchone()[0]
if not configured:
    login=httpx.post(f"{settings.supabase_url}/auth/v1/token?grant_type=password",headers={"apikey":settings.supabase_secret_key.get_secret_value()},json=json.loads(credentials.read_text()),timeout=10)
    if login.status_code!=200:raise RuntimeError("local_provider_login_failed")
    payload=login.json()
    token=payload['access_token'].split('.')[1]
    claims=json.loads(base64.urlsafe_b64decode(token+'='*(-len(token)%4)))
    principal=ProviderPrincipal(UUID(payload['user']['id']),UUID(claims['session_id']))
    set_quota(ProviderService(settings.database_url),principal,tenant,QuotaCommand(expected_version=version,seats_limit=10,ai_daily_budget_brl=0,ai_monthly_budget_brl=0,usd_brl_rate=5,rate_source="SYNTHETIC local test rate; not a market quotation",reason="Synthetic M6 pilot: ten seats, zero paid AI budget; no commercial contract inferred"))
print("Local synthetic pilot ready; credentials remain in ignored output/runtime. Paid AI budget defaults to zero only for this local pilot.")
