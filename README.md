# Vordr 🐺

> _Na mitologia nórdica, **Vörðr** é o espírito-guardião que acompanha cada pessoa do
> nascimento à morte, vigiando-a sem descanso. Aqui, Vordr monta guarda diante dos
> seus servidores._

**Vordr** é uma CLI que vigia seus hosts Linux por SSH e responde, num só lugar, às
perguntas que importam no dia a dia:

- **Estão de pé?** — estado, uptime, carga, RAM, disco e containers de todos os hosts.
- **Vou ser cobrado?** — há quanto tempo você hospeda cada host, quando o
  **servidor** renova e quando o **domínio** expira, e quanto você gasta por mês.
  _O recurso que evita a cobrança surpresa._
- **Estão seguros?** — falhas de login, portas em escuta, fail2ban, atualizações
  pendentes e necessidade de reboot.

Sem agentes instalados nos servidores, sem banco de dados, sem segredos no código:
Vordr só precisa do seu `~/.ssh/config`.

```
┌──────────────────────────────────────────────────────────────────────┐
│ Vordr · status dos servidores                                          │
├───────────┬──────────┬─────────┬──────┬─────┬───────┬────────┬─────────┤
│ host      │ estado   │ uptime  │ load │ ram │ disco │ docker │ expira  │
├───────────┼──────────┼─────────┼──────┼─────┼───────┼────────┼─────────┤
│ web       │ ● online │ 2sem 5d │ 0.28 │ 32% │ 22%   │ 5/6    │ 53d     │
│ db        │ ● online │ 4sem 4d │ 0.04 │ 18% │ 62%   │ 6/6    │ 6d  ⚠   │
└───────────┴──────────┴─────────┴──────┴─────┴───────┴────────┴─────────┘
```

## Por que existe

Quem mantém alguns servidores acaba acumulando comandos soltos e logins repetidos
para responder perguntas simples. Vordr junta isso numa camada única que:

1. olha **todos os hosts de uma vez**, com métricas comparáveis e coloridas por
   limiar (load por CPU, % de disco/RAM);
2. avisa **antes** de uma renovação cobrar de novo;
3. dá uma **auditoria rápida de segurança** sem precisar logar em cada máquina.

Vordr coleta métricas via pequenos scripts `sh` que emitem `CHAVE=valor` (estável e
testável) em vez de parsear saída colorida e frágil — mas ainda oferece um modo
`--raw` que reproduz a saída nativa de um `status_command` seu, quando você define um.

## Instalação

Requer Python 3.11+ e o cliente `ssh` configurado com os hosts que você quer monitorar.

```bash
pipx install vordr          # recomendado (ferramenta isolada no PATH)
# ou, para desenvolvimento:
pip install -e ".[dev]"
```

## Configuração

Os hosts são **aliases do seu `~/.ssh/config`** — nenhum IP, usuário ou chave fica
guardado pelo Vordr. As datas de cobrança são informadas por você (o servidor não tem
como saber quando o provedor ou o registrar vão cobrar de novo).

Cada host tem dois blocos opcionais de ciclo de vida: `[hosts.X.server]` (a
hospedagem) e `[hosts.X.domain]` (o domínio). Ambos com `expires`/`cost`, somados no
custo mensal.

```bash
vordr init        # cria ~/.config/vordr/config.toml comentado
```

```toml
[thresholds]
warn_days = 14
critical_days = 7

[hosts.web]
ssh = "web"                   # alias no ~/.ssh/config
label = "Web"
# status_command = "meu-status"   # opcional: seu script para `vordr status --raw`

  [hosts.web.server]          # a hospedagem
  provider = "Hetzner"
  since   = "2024-03-01"      # desde quando você hospeda (tempo de hospedagem)
  expires = "2026-08-15"      # AAAA-MM-DD — próxima renovação do servidor
  cost = 6.99
  currency = "USD"
  cycle = "monthly"           # monthly | yearly

  [hosts.web.domain]          # o domínio (opcional)
  name = "web.exemplo.com"
  registrar = "Cloudflare"
  expires = "2027-03-01"
  cost = 12.00
  currency = "USD"
  cycle = "yearly"
```

Vordr não embute nenhum host: `vordr init` cria um `config.toml` comentado para você
preencher com seus aliases. Sem hosts configurados, os comandos apenas orientam a
rodar `vordr init`.

## Uso

```bash
vordr status              # painel de todos os hosts
vordr status web          # só um host
vordr status --watch 5    # atualiza a cada 5s (tela cheia)
vordr status --raw        # saída nativa do status_command do host

vordr resources           # CPU/load, memória e disco em detalhe
vordr security            # auditoria: logins, falhas, portas, fail2ban, updates
vordr cost                # tabela: hospedagem, renovação de servidor/domínio, custo/mês
vordr cost web            # painel detalhado do ciclo de vida de um host
vordr cost --offline      # sem rede: usa só o que está no config
vordr hosts               # lista o que está configurado

vordr secret set hetzner  # guarda o token da API (chmod 600, fora do repo)
vordr secret status       # mostra quais provedores têm token (mascarado)
```

Todas as cores seguem limiares: verde (ok), amarelo (atenção), vermelho (crítico) —
para disco/RAM, load por CPU e dias até a cobrança.

## Automação do `cost` (sem digitar datas)

O `cost` preenche sozinho o que você não informou — **e o valor do config sempre
vence** (útil para preços promocionais/legados):

- **Domínio:** informe só `name` no `[hosts.X.domain]` e a expiração vem do **RDAP**
  (público, sem credencial), cacheada em `~/.cache/vordr/rdap.json`.
- **Servidor:** com `provider = "Hetzner"` e um token (`vordr secret set hetzner`),
  o `since` (data de criação) e o **custo mensal** vêm da **API do provedor**.

Tokens nunca ficam no repositório: são lidos de variável de ambiente (`HCLOUD_TOKEN`)
ou de `~/.config/vordr/secrets.toml` (chmod 600, no `.gitignore`). O env tem
prioridade. Valores vindos da rede aparecem marcados com `(API)` / `(RDAP)`.

> ⚠️ O preço da API da Hetzner é o **preço de lista atual** do tipo de servidor — se
> a sua conta tem um valor promocional/travado, informe `cost` no config (ele vence).

## Como funciona

| Camada            | Arquivo            | Responsabilidade                                   |
|-------------------|--------------------|----------------------------------------------------|
| Transporte SSH    | `vordr/ssh.py`     | Executa comandos remotos (`BatchMode`, timeout).   |
| Coleta de métrica | `vordr/probe.py`   | Scripts `sh` → `CHAVE=valor` → dataclasses.        |
| Configuração      | `vordr/config.py`  | Lê o TOML; cálculo de dias/custo.                  |
| Expiração domínio | `vordr/rdap.py`    | RDAP público + cache em disco (sem credencial).    |
| API de provedor   | `vordr/hetzner.py` | Cliente read-only da Hetzner (since + preço).      |
| Segredos          | `vordr/secrets.py` | Tokens fora do repo (env > arquivo chmod 600).     |
| Formatação        | `vordr/format.py`  | Funções puras (uptime, bytes, limiares de cor).    |
| CLI               | `vordr/cli.py`     | Typer + Rich; orquestra tudo em paralelo.          |

Os hosts são consultados **em paralelo** (`ThreadPoolExecutor`), então monitorar 2 ou
10 servidores leva praticamente o mesmo tempo.

### Segurança por design

- **Read-only:** Vordr só roda comandos de leitura (`/proc`, `df`, `ss`, `last`, …).
- **Sem segredos no repositório:** hosts são aliases SSH; o `config.toml` real fica
  fora do versionamento (veja `.gitignore`).
- **Sem `sudo` interativo:** checagens privilegiadas usam `sudo -n` (não-interativo) e
  degradam graciosamente quando não há permissão — nunca travam o terminal.
- **`BatchMode`:** se a chave não estiver disponível, falha rápido em vez de pedir senha.

## Desenvolvimento

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

Os testes não tocam a rede: a camada SSH é injetada (`monkeypatch`) e a lógica de
parsing/formatação é testada com amostras reais de saída dos servidores.

## Licença

MIT — veja [LICENSE](LICENSE).
