# DALDEGAN

**Laboratório doméstico de investigação de intenção consciente sobre eventos aleatórios quânticos.**

O Daldegan é um instrumento experimental local, transparente e auditável para testar uma hipótese:

> Uma intenção consciente direcionada a um resultado binário pode produzir alguma alteração estatisticamente mensurável na distribuição de resultados produzidos por uma fonte de aleatoriedade quântica?

O software **não assume que a hipótese é verdadeira**. Ele foi construído para que você consiga executar o experimento e descobrir que a sua hipótese estava errada. Isso é uma característica do projeto, não uma falha.

> **Um resultado negativo também é um resultado válido.**

Especificação técnica completa: [SPEC.md](SPEC.md). Plano de desenvolvimento: [TASKS.md](TASKS.md). Detalhes da fonte quântica: [docs/qrng-anu.md](docs/qrng-anu.md).

---

## Instalação e uso

Requisitos: Python 3.12 ou superior.

```bash
python -m venv .venv
```

Ativar o ambiente virtual:

| Sistema | Comando |
|---|---|
| Windows (PowerShell) | `.venv\Scripts\Activate.ps1` |
| Windows (cmd) | `.venv\Scripts\activate.bat` |
| Linux / macOS | `source .venv/bin/activate` |

```bash
pip install -r requirements.txt          # ou requirements-dev.txt para rodar os testes
```

### Configurar a fonte quântica

1. Crie uma chave gratuita em <https://quantumnumbers.anu.edu.au> (plano gratuito: 100 requisições por mês, 1 por segundo).
2. Copie `.env.example` para `.env` e preencha `DALDEGAN_QRNG_API_KEY`.

Cada requisição traz até 8.192 bits. Uma sessão de 10.000 eventos consome 2 requisições; uma de 100.000 consome 13. A tela de novo experimento mostra quantas requisições a sessão vai usar.

Sem chave, a aplicação funciona apenas em **modo teste** (dados pseudoaleatórios, sem valor experimental). Ela nunca troca a fonte quântica por pseudoaleatoriedade sem avisar.

### Iniciar

```bash
uvicorn backend.app.main:app --reload
```

Abra <http://127.0.0.1:8000>.

O servidor escuta apenas em `127.0.0.1`. Não exponha a aplicação na rede: ela não tem autenticação.

### Testes

```bash
pip install -r requirements-dev.txt
pytest
```

O teste que chama a API real da ANU é pulado por padrão, porque consome cota. Para rodá-lo: `pytest -m qrng_live`.

### Verificação independente de uma sessão

```bash
python scripts/verify_session.py <SESSION_PATH>
python scripts/verify_session.py data/sessions/DAL-2026-3f9a1c07 --anchor <CÓDIGO_DE_AUDITORIA>
```

O verificador não importa nada da aplicação web. Ele recalcula todos os hashes, confere a cadeia do audit log, a sequência de eventos, a derivação dos bits a partir das respostas brutas da fonte e as estatísticas, e termina com `INTEGRIDADE: OK` ou `INTEGRIDADE: FALHOU`. Use `--json` para obter a saída em formato legível por máquina.

---

## O experimento

Cada evento é um bit: `0` (alvo A, mostrado como AZUL) ou `1` (alvo B, mostrado como VERMELHO). A medida principal é o número de **acertos**, isto é, de bits iguais ao alvo.

### Módulo 1 — Intenção antes da geração

O alvo é escolhido (pelo participante ou sorteado pela fonte quântica) e entra no pré-registro. Depois vem o período de intenção, e só então os bits são gerados.

Pergunta: *uma intenção previamente definida está associada a uma alteração na distribuição dos eventos quânticos subsequentes?*

### Módulo 2 — Intenção depois da geração

> Dados gerados antes da intenção e mantidos cegos até a conclusão da intenção.

Os bits são gerados, gravados e selados com SHA-256 antes de qualquer coisa. Só então o alvo é escolhido e começa a intenção. Ninguém vê os dados até a revelação, e a revelação só acontece depois de verificada a integridade.

**Por que é conceitualmente interessante:** nesse caso o resultado já está fisicamente determinado e registrado, mas ainda não foi observado por ninguém. Se a intenção estivesse associada a um desvio aqui, isso não poderia ser explicado como influência sobre o processo de geração, que já terminou. Por isso o Módulo 2 é o teste mais exigente da hipótese de "influência sobre um resultado já determinado, mas ainda não observado". Ele também é o que exige mais cuidado com o cegamento.

### Controle — período neutro

Tem o mesmo fluxo do Módulo 2, mas sem intenção: os participantes ficam em atividade neutra. Um alvo-placebo é sorteado pela fonte quântica depois do selamento e fica oculto até a revelação. Assim o Controle produz exatamente a mesma medida (acertos) que o Módulo 2 e pode servir de comparação. A aplicação não faz essa comparação automaticamente. Qualquer comparação entre sessões é uma análise exploratória.

### Participantes

O número de participantes é apenas registrado, exatamente como declarado. Ele não entra em nenhum cálculo e não "multiplica" nenhum efeito. Nomes reais não são necessários.

---

## O que o experimento testa e o que ele NÃO testa

**Testa:** se, sob um protocolo pré-registrado, a proporção de acertos em uma sequência de bits quânticos difere do esperado pelo acaso (50%) além do que a variação aleatória explicaria.

**Não testa e não demonstra:**

- que a oração funciona, que Deus existe ou qualquer interpretação religiosa ou filosófica;
- que a consciência "altera a matéria";
- que exista um mecanismo causal. Um desvio estatístico, mesmo que real, pode ter outras explicações: defeito ou viés na fonte, erro no software, falha de protocolo, acaso (com α = 0,05, cerca de 1 sessão em 20 dá resultado "significativo" sem nenhum efeito real) ou seleção dos resultados.

Qualquer interpretação deve ficar separada dos dados experimentais.

### Conceitos que não devem ser confundidos

| Conceito | Significado neste contexto |
|---|---|
| **Observação** | Uma pessoa tomar conhecimento de um resultado (aqui: ver os bits). No Daldegan, a observação humana é adiada até a revelação. |
| **Medição** | Na física quântica, a interação de um sistema com um aparelho que registra um resultado definido. Na fonte da ANU, a medição acontece no laboratório, por detectores, muito antes de qualquer pessoa ver o número. |
| **Interação física** | Troca de energia ou informação por meios físicos conhecidos. O experimento não propõe nenhuma. |
| **Consciência** | A experiência subjetiva de uma pessoa. O experimento não a mede; apenas registra que pessoas declararam estar concentradas. |
| **Intenção** | O propósito declarado de favorecer um alvo durante um período. É a variável manipulada pelo protocolo. |
| **Aleatoriedade** | Ausência de padrão previsível. A fonte quântica fornece bits que, sob H0, são independentes e têm P(1) = 0,5. |
| **Correlação** | Associação estatística entre duas coisas (por exemplo, alvo e proporção de bits). |
| **Causalidade** | Uma coisa produzir a outra. A correlação não basta para estabelecer causalidade, e um único experimento está longe de bastar. |

### Mecânica quântica e consciência

É comum ouvir que "a observação consciente colapsa a função de onda". A mecânica quântica **não estabelece** que a consciência humana seja necessária para o colapso nem para a obtenção de resultados definidos. Em todas as interpretações usadas na prática, a "medição" é uma interação física com um aparelho, e os bits da ANU são produzidos por detectores, sem nenhuma pessoa envolvida. A ideia de que a consciência teria um papel especial é uma posição filosófica minoritária, não um resultado experimental. O Daldegan não pressupõe nenhuma das duas posições.

---

## Estatística

- **Hipótese nula (H0):** P(acerto) = 0,5.
- **Hipótese alternativa:** bilateral, P(acerto) ≠ 0,5 (padrão), ou direcional, P(acerto) > 0,5. A escolha é feita **no pré-registro**.
- **Teste:** binomial exato (`scipy.stats.binomtest`). **α = 0,05**, fixo nesta versão.
- **Também são calculados:** proporção observada, proporção esperada, desvio absoluto, z-score, intervalo de confiança de 95% (Clopper-Pearson exato) e proporção de uns.

Linguagem do resultado (lista fechada):

- "Não foi detectado desvio estatisticamente significativo."
- "Foi detectado um desvio estatisticamente significativo."

**O p-value não é a probabilidade de a hipótese ser verdadeira.** Ele indica quão incomum seria um resultado pelo menos tão extremo quanto o observado *se apenas o acaso estivesse atuando*.

### Por que um resultado significativo isolado não demonstra causalidade

Com α = 0,05, 5% das sessões sem nenhum efeito real darão "significativo". Quem roda 20 sessões deve esperar, em média, uma delas significativa por puro acaso. Um resultado isolado é compatível com o acaso, com um defeito na fonte, com um erro de procedimento ou com um efeito real, e não permite distinguir entre essas possibilidades.

### Múltiplas comparações e p-hacking

Cada teste adicional (outro módulo, outro subconjunto, outra direção, outro limite de α, "só as sessões da manhã") é mais uma chance de obter um falso positivo. Escolher o teste, a direção ou as sessões **depois** de ver os dados faz o p-value perder o significado. Isso é p-hacking. Por isso o Daldegan:

- fixa teste, direção e α antes da geração e não permite alterá-los depois;
- não tem nenhuma opção para refazer, descartar ou regerar eventos;
- marca como **exploratória** qualquer análise que não tenha sido pré-especificada.

### Viés de seleção

Combinar só as sessões "que deram certo" cria um efeito artificial a partir de dados puramente aleatórios. A análise de múltiplas sessões tem dois modos:

- **Por protocolo (confirmatória):** inclui *todas* as sessões concluídas com exatamente os mesmos parâmetros pré-registrados (identificados por um *fingerprint* do protocolo). As sessões invalidadas, com erro ou canceladas são listadas, não escondidas.
- **Seleção manual:** sempre marcada como "Esta análise é exploratória e está sujeita a viés de seleção."

Sessões em modo teste nunca entram em nenhuma das duas.

### Por que o pré-registro importa

O pré-registro (`preregistration.json`) é gravado e recebe um hash SHA-256 antes de existir qualquer dado. Ele fixa o que será medido e como. Sem pré-registro, sempre é possível encontrar, depois, alguma forma de olhar os dados que pareça interessante. Você pode baixar o arquivo e guardar o hash fora da máquina antes de começar.

---

## Integridade e auditoria

Cada sessão fica em `data/sessions/<ID>/` (ou `data/sessions_test/` no modo teste):

| Arquivo | Conteúdo |
|---|---|
| `preregistration.json` | protocolo fixado antes dos dados |
| `qrng_raw.jsonl` | respostas brutas da fonte, exatamente como chegaram, na ordem |
| `events.csv` | `event_id, sequence_number, bit, timestamp_utc` |
| `manifest.json` | fonte, timestamps, quantidade de bits, transformação usada e hashes |
| `audit.log` | registro append-only com cadeia de hashes (cada entrada inclui o hash da anterior) |
| `analysis.json` | estatísticas, geradas somente na revelação |
| `report.html` | relatório final |

**Transformação de bytes em bits (protocolo 1.0):** cada byte (`uint8`) gera 8 bits, do mais significativo para o menos significativo, na ordem exata de chegada. São usados os primeiros N bits. Não há nenhum outro pós-processamento.

**Na revelação**, antes de mostrar qualquer número, a aplicação recalcula os hashes, confere manifesto, pré-registro, índice e audit log, valida a sequência de eventos, refaz a derivação dos bits a partir das respostas brutas e confere a ordem e a duração das etapas. Qualquer divergência resulta em:

> SESSÃO INVALIDADA — a integridade dos dados não pôde ser confirmada.

### Limitações conhecidas

- **O cegamento é procedimental.** Os arquivos ficam no seu disco, e quem tem acesso ao computador pode abrir `events.csv` antes da revelação. Isso compromete a sessão. Não abra os arquivos de uma sessão em andamento.
- **A cadeia de hashes pode ser reescrita por inteiro** por quem controla o disco. Ela detecta alterações parciais, mas uma cadeia refeita de forma coerente só é detectada com uma âncora externa. Por isso a interface mostra um **código de auditoria** (por exemplo, logo após a escolha do alvo no Módulo 2). Anote-o fora da máquina (papel, mensagem para alguém) e use-o depois com `--anchor` no verificador.
- **O resultado depende da fonte externa** declarada no manifesto. Se a fonte tiver um viés, ele aparece nos dados.
- **O plano gratuito da ANU limita a 100 requisições por mês**, o que limita o tamanho e o número de sessões.

---

## Estrutura

```
backend/app/        FastAPI, serviços, máquina de estados, estatística, QRNG, auditoria
backend/tests/      pytest: integridade, adulteração, estatística, fluxos, API, linguagem
frontend/           HTML + CSS + JavaScript puro
scripts/            verify_session.py (verificador independente)
data/               sessões (não versionado)
docs/               verificação da API da ANU
```

Versões: `SOFTWARE_VERSION = 0.1.0`, `PROTOCOL_VERSION = 1.0`. Qualquer alteração relevante no protocolo (formato de arquivo, regra de hash, conversão de bits, teste estatístico ou fluxo) incrementa `PROTOCOL_VERSION`. Como o fingerprint do protocolo inclui a versão, sessões de versões diferentes nunca são somadas na análise por protocolo.
