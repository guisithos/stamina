"""Camada de IA: transforma as métricas já calculadas (analysis.py) numa narrativa
de treinador. Provider-agnostic via protocolo OpenAI-compatible — funciona com
DeepSeek, OpenRouter, OpenAI, ou qualquer gateway compatível, só trocando env vars.

A IA NÃO vê dado cru: recebe só o dataset de métricas e é instruída a não inventar
números. Determinismo mora no analysis.py; aqui é só redação.

Config (env / fly secrets):
  AI_ENABLED   = true|false      (default false — desligado até ter chave)
  AI_BASE_URL  = https://api.deepseek.com   (sem /chat/completions)
  AI_API_KEY   = <chave do provedor>
  AI_MODEL     = deepseek-chat
"""
import json
import os
from typing import Any, Optional

import httpx

SYSTEM_PROMPT = (
    "Você é um treinador de corrida que analisa dados de treino de forma direta, "
    "honesta e baseada em ciência do esporte. Responda em português do Brasil, em "
    "no máximo 4 frases curtas, sem markdown, sem listas e sem emojis. "
    "Use SOMENTE os números fornecidos — nunca invente dados nem cite o que não está lá. "
    "O que importa, em ordem: Efficiency Factor (EF = velocidade ÷ FC; maior = mais "
    "condicionamento, sobretudo se o pace se manteve com FC menor); desacoplamento "
    "aeróbico (<5% = boa resistência, alto = fadigou na 2ª metade); relação pace×FC; "
    "volume e consistência das corridas anteriores; e o RPE (esforço percebido 0-10). "
    "Compare a corrida 'atual' com a tendência das 'anteriores' e termine com um "
    "veredito prático (melhorando, estável, ou sinal de fadiga) e, quando fizer "
    "sentido, uma sugestão objetiva para a próxima corrida."
)


def _cfg() -> dict:
    return {
        "enabled": os.getenv("AI_ENABLED", "false").lower() == "true",
        "base_url": os.getenv("AI_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        "api_key": os.getenv("AI_API_KEY", ""),
        "model": os.getenv("AI_MODEL", "deepseek-chat"),
    }


def is_enabled() -> bool:
    c = _cfg()
    return c["enabled"] and bool(c["api_key"])


def generate_run_narrative(dataset: dict[str, Any]) -> Optional[str]:
    """Chama o provedor (OpenAI-compatible) e devolve a narrativa, ou None em erro."""
    c = _cfg()
    if not (c["enabled"] and c["api_key"]):
        return None
    try:
        resp = httpx.post(
            f"{c['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {c['api_key']}", "Content-Type": "application/json"},
            json={
                "model": c["model"],
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content":
                        "Analise a corrida 'atual' comparando com as 'anteriores' "
                        "(da mais recente pra mais antiga). Dados:\n"
                        + json.dumps(dataset, ensure_ascii=False)},
                ],
                "temperature": 0.4,
                "max_tokens": 400,
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:  # rede/timeout/resposta inesperada — degrada graciosamente
        print(f"[ai] falha ao gerar análise: {exc}")
        return None
