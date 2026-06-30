# Stamina — diário de treinos (estilo Strava, uso pessoal)

Backend em FastAPI + frontend server-side com Jinja2/HTMX. Importa arquivos `.fit`, guarda histórico de atividades por usuário, mostra mapa (Leaflet) pra atividades com GPS, gráfico de frequência cardíaca (Chart.js), e permite anexar foto a cada treino (upload com compressão automática, inclusive HEIF do iPhone).

## Rodando localmente (do zero)

Precisa só de **Python 3.10+** instalado (testado no 3.14). Os comandos abaixo são
para **Windows / PowerShell**, que é o ambiente de desenvolvimento atual.

```powershell
# 1. criar e ativar o ambiente virtual
python -m venv venv
.\venv\Scripts\Activate.ps1
#   ^ se o PowerShell bloquear o script, rode uma vez:
#     Set-ExecutionPolicy -Scope CurrentUser RemoteSigned

# 2. instalar as dependências
pip install -r requirements.txt

# 3. subir o servidor
uvicorn app.main:app --reload
```

Acesse **http://127.0.0.1:8000**, crie uma conta (e-mail + senha) e suba um ou mais
arquivos `.fit`.

> **Linux/macOS:** os passos são iguais, trocando a ativação por
> `python3 -m venv venv && source venv/bin/activate`.

### Banco de dados

SQLite local em `app.db`, criado automaticamente no primeiro start — não precisa
configurar nada. Para começar do zero (apagar conta e atividades), feche o servidor
e delete o arquivo:

```powershell
Remove-Item app.db
```

### Smoke test automatizado

`smoke_test.py` simula o fluxo inteiro (registro → upload → dashboard → detalhe →
GeoJSON do percurso → exclusão → logout) usando o `TestClient` do FastAPI, sem
precisar de servidor rodando. Ele lê os 3 `.fit` de teste da pasta `~/Documents`
por padrão (ajustável pela variável de ambiente `FIT_DIR`):

```powershell
# o servidor NÃO pode estar rodando (ambos disputam o app.db)
Remove-Item app.db -ErrorAction SilentlyContinue
python smoke_test.py

# apontando para outra pasta com os .fit:
$env:FIT_DIR = "C:\caminho\para\os\fit"; python smoke_test.py
```

## Deploy no Fly.io

O `fly.toml` já vem configurado: app `stamina`, região `gru` (São Paulo),
volume persistente `stamina_data` montado em `/data` (onde o SQLite vive) e
`DATABASE_URL` apontando pra lá. O `.dockerignore` mantém o upload do build
enxuto (não envia `venv/`, `.git`, `lovable/` etc.).

```bash
# instalar a CLI (uma vez): https://fly.io/docs/flyctl/install/
fly auth login

# IMPORTANTE: passe --region explicitamente. Ao reaproveitar um fly.toml existente,
# o flyctl às vezes ignora o primary_region e falha com "region  not found".
fly launch --no-deploy --region gru

# cria o volume persistente (precisa bater com source/region do fly.toml)
fly volumes create stamina_data --region gru --size 1


python -c "import secrets; print(secrets.token_hex(32))"
fly secrets set SECRET_KEY=<cole-aqui>

fly deploy
```

Depois disso, `fly deploy` a cada mudança já atualiza o app no ar. Como o
volume prende o app a uma única máquina, mantenha `min_machines_running = 0`
(escala a zero quando ocioso) — é o padrão do `fly.toml`.

> No primeiro boot após o deploy, o app roda uma micro-migração que adiciona as
> colunas novas (`source`, `external_id`, `ingest_token`) ao `app.db` existente.
> É idempotente — não precisa fazer nada manualmente.

## Sincronização automática (Health Auto Export)

Em vez de exportar `.fit` manualmente, dá pra receber os treinos automaticamente:

1. **Zepp** (iPhone): Profile → Add accounts → **Apple Health** (envia os treinos do
   relógio pro Apple Health).
2. **Health Auto Export** (licença Basic, compra única): crie uma automação **REST API**,
   método `POST`, formato `JSON`, dados **Workouts** (com Route + Heart Rate).
3. No Stamina, abra **Integração** (no menu) e copie a sua URL de ingestão
   (`/ingest/hae?token=...`) pra dentro do Health Auto Export.

Os treinos passam a chegar sozinhos em `POST /ingest/hae` — autenticado pelo seu token,
idempotente (não duplica em reenvios). Detalhes em `doc-interna.md` §6.9.

## Análise por IA (opcional, desligada por padrão)

Na página de uma corrida, um botão "Analisar com IA" gera uma leitura comparativa
(últimas 8 corridas + a atual: EF, desacoplamento, pace×FC, volume, RPE). A IA só
**fraseia** os números que o `analysis.py` calcula — não vê dado cru nem inventa.

É **provider-agnostic** (protocolo OpenAI-compatible) — funciona com DeepSeek,
OpenRouter, OpenAI, etc. Fica desligada até você configurar:

```
fly secrets set AI_ENABLED=true \
  AI_BASE_URL=https://api.deepseek.com \
  AI_API_KEY=<sua-chave> \
  AI_MODEL=deepseek-chat
```

Para um gateway (ex.: OpenRouter alcançando Claude Haiku), troque `AI_BASE_URL` e
`AI_MODEL`. Sem essas vars, o botão não aparece. A narrativa é gerada sob demanda e
cacheada por treino (não chama o provedor a cada acesso).

## Foto do treino

Na página de cada atividade, há um ícone de câmera ao lado do título. Ao selecionar
uma foto, ela é enviada automaticamente:

- **Formatos suportados:** JPEG, PNG e **HEIF/HEIC** (fotos de iPhone).
- **Processamento automático:** redimensiona (max 1920px), comprime (JPEG quality 75).
  Uma foto de ~10 MB do iPhone vira ~200-400 KB.
- **Exibição:** entre o grid de estatísticas e o registro de RPE/nota.
- **Remoção:** botão de lixeira sobre a foto (com confirmação).
- **Armazenamento:** as fotos ficam em `photos/` (local) ou `/data/photos/` (volume
  persistente no Fly), mesmo diretório do banco.

## Decisões da v0 (e o que evolui depois)

- **Formato de entrada: FIT.** É o que Garmin usa nativamente e o que o Zepp também
  grava, já vem com os agregados calculados   pelo relógio (FC média/mín/máx, calorias), sem precisar recalcular nada.
- **Altitude:** os arquivos do Amazfit Active Edge testados não trazem altitude em
  nenhum campo, nem na atividade com GPS. O código já tenta `enhanced_altitude` e
  `altitude` (campos padrão do FIT), então qualquer Garmin ou relógio com barômetro
  vai preencher isso automaticamente.
- **Pontos do percurso guardados como JSON** num campo de texto da própria
  atividade, não numa tabela separada. Simples o suficiente pro volume pessoal;
  se a quantidade de atividades crescer muito, vale normalizar pra uma tabela
  `activity_point` com índice por `activity_id`.