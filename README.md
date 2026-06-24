# Vordr 🐺

> _Na mitologia nórdica, **Vörðr** é o espírito-guardião que acompanha cada pessoa do
> nascimento à morte, vigiando-a sem descanso. Aqui, Vordr monta guarda diante dos
> seus servidores._

**Vordr** é uma CLI que vigia seus hosts Linux por SSH e responde, num só lugar, às
perguntas que importam no dia a dia:

- **Estão de pé?** — estado, uptime, carga, RAM, disco e containers de todos os hosts.
- **Vou ser cobrado?** — quantos dias faltam para cada servidor/serviço expirar e
  quanto você gasta por mês. _O recurso que evita a cobrança surpresa._
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
como saber quando o provedor vai cobrar de novo).

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

  [hosts.web.billing]
  provider = "Hetzner"
  expires = "2026-08-15"      # AAAA-MM-DD
  cost = 6.99
  currency = "USD"
  cycle = "monthly"           # monthly | yearly
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
vordr cost                # dias até expirar + gasto mensal estimado
vordr hosts               # lista o que está configurado
```

Todas as cores seguem limiares: verde (ok), amarelo (atenção), vermelho (crítico) —
para disco/RAM, load por CPU e dias até a cobrança.

## Como funciona

| Camada            | Arquivo            | Responsabilidade                                   |
|-------------------|--------------------|----------------------------------------------------|
| Transporte SSH    | `vordr/ssh.py`     | Executa comandos remotos (`BatchMode`, timeout).   |
| Coleta de métrica | `vordr/probe.py`   | Scripts `sh` → `CHAVE=valor` → dataclasses.        |
| Configuração      | `vordr/config.py`  | Lê o TOML; cálculo de dias/custo.                  |
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
