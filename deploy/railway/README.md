# ARES no Railway

Variante do pacote `deploy/` para o Railway. O Railway termina o HTTPS na borda, então o Caddy
deste diretório serve HTTP na porta `$PORT` e faz proxy de `/api/*` para a API pela rede privada.

| Serviço Railway | Arquivo de configuração           | Observação                               |
|-----------------|-----------------------------------|------------------------------------------|
| `api`           | `/deploy/railway/api.json`        | privado, porta 8000                      |
| `worker`        | `/deploy/railway/worker.json`     | sem porta                                |
| `crm`           | `/deploy/railway/crm.json`        | privado, porta 8010, volume em `/data`   |
| `web`           | `/deploy/railway/web.json`        | único serviço com domínio público        |

Os nomes dos serviços precisam ser exatamente esses: a rede privada usa `api.railway.internal`
e `crm.railway.internal`.

As variáveis de cada serviço ficam em `deploy/railway/.env.railway` (ignorado pelo Git; nunca
versionar). O banco usa o **Session pooler** do Supabase, porque a conexão direta é só IPv6.
