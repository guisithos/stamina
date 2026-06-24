# Stamina — diário de treinos (estilo Strava, uso pessoal)

Backend em FastAPI + frontend server-side com Jinja2/HTMX. Importa arquivos `.fit`, guarda histórico de atividades por usuário, mostra mapa (Leaflet) pra atividades com GPS e gráfico de frequência cardíaca (Chart.js).

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


fly launch --no-deploy  

# cria o volume persistente (precisa bater com source/region do fly.toml)
fly volumes create stamina_data --region gru --size 1


python -c "import secrets; print(secrets.token_hex(32))"
fly secrets set SECRET_KEY=<cole-aqui>

fly deploy
```

Depois disso, `fly deploy` a cada mudança já atualiza o app no ar. Como o
volume prende o app a uma única máquina, mantenha `min_machines_running = 0`
(escala a zero quando ocioso) — é o padrão do `fly.toml`.

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