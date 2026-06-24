"""Catálogo de exercícios de musculação e seu mapeamento para grupos musculares.

Fonte única de verdade do "exercício -> músculos treinados". Os slugs de músculo
são exatamente os que a lib `body-highlighter` (CDN, MIT) entende, então o mapa
muscular do front consome direto.

Slugs válidos (body-highlighter):
  trapezius, upper-back, lower-back, chest, biceps, triceps, forearm,
  back-deltoids, front-deltoids, abs, obliques, adductor, hamstring,
  quadriceps, abductors, calves, gluteal, head, neck

Para adicionar um exercício: acrescente em EXERCISES e referencie a chave no
grupo certo de EXERCISE_GROUPS (ordem do <select> na tela).
"""

EXERCISES: dict[str, dict] = {
    # Peito
    "supino_reto": {"label": "Supino reto", "muscles": ["chest", "triceps", "front-deltoids"]},
    "supino_inclinado": {"label": "Supino inclinado", "muscles": ["chest", "front-deltoids", "triceps"]},
    "crucifixo": {"label": "Crucifixo", "muscles": ["chest"]},
    "flexao": {"label": "Flexão de braço", "muscles": ["chest", "triceps", "front-deltoids"]},
    # Costas
    "puxada_frontal": {"label": "Puxada frontal", "muscles": ["upper-back", "biceps", "back-deltoids"]},
    "remada_curvada": {"label": "Remada curvada", "muscles": ["upper-back", "lower-back", "biceps"]},
    "barra_fixa": {"label": "Barra fixa", "muscles": ["upper-back", "biceps", "forearm"]},
    "remada_unilateral": {"label": "Remada unilateral", "muscles": ["upper-back", "biceps"]},
    "levantamento_terra": {"label": "Levantamento terra", "muscles": ["lower-back", "gluteal", "hamstring", "trapezius"]},
    # Ombros
    "desenvolvimento": {"label": "Desenvolvimento", "muscles": ["front-deltoids", "back-deltoids", "triceps"]},
    "elevacao_lateral": {"label": "Elevação lateral", "muscles": ["back-deltoids", "front-deltoids"]},
    "encolhimento": {"label": "Encolhimento", "muscles": ["trapezius"]},
    # Braços
    "rosca_direta": {"label": "Rosca direta", "muscles": ["biceps", "forearm"]},
    "rosca_martelo": {"label": "Rosca martelo", "muscles": ["biceps", "forearm"]},
    "triceps_testa": {"label": "Tríceps testa", "muscles": ["triceps"]},
    "triceps_corda": {"label": "Tríceps na corda", "muscles": ["triceps"]},
    # Pernas
    "agachamento": {"label": "Agachamento", "muscles": ["quadriceps", "gluteal", "hamstring", "adductor"]},
    "leg_press": {"label": "Leg press", "muscles": ["quadriceps", "gluteal"]},
    "cadeira_extensora": {"label": "Cadeira extensora", "muscles": ["quadriceps"]},
    "cadeira_flexora": {"label": "Cadeira flexora", "muscles": ["hamstring"]},
    "afundo": {"label": "Afundo", "muscles": ["quadriceps", "gluteal", "hamstring"]},
    "panturrilha": {"label": "Panturrilha", "muscles": ["calves"]},
    "cadeira_abdutora": {"label": "Cadeira abdutora", "muscles": ["abductors", "gluteal"]},
    "cadeira_adutora": {"label": "Cadeira adutora", "muscles": ["adductor"]},
    # Core
    "abdominal": {"label": "Abdominal", "muscles": ["abs"]},
    "prancha": {"label": "Prancha", "muscles": ["abs", "obliques"]},
    "abdominal_obliquo": {"label": "Abdominal oblíquo", "muscles": ["obliques", "abs"]},
}

# Agrupamento para o <select> na tela (rótulo do grupo -> chaves, na ordem desejada).
EXERCISE_GROUPS: dict[str, list[str]] = {
    "Peito": ["supino_reto", "supino_inclinado", "crucifixo", "flexao"],
    "Costas": ["puxada_frontal", "remada_curvada", "barra_fixa", "remada_unilateral", "levantamento_terra"],
    "Ombros": ["desenvolvimento", "elevacao_lateral", "encolhimento"],
    "Braços": ["rosca_direta", "rosca_martelo", "triceps_testa", "triceps_corda"],
    "Pernas": ["agachamento", "leg_press", "cadeira_extensora", "cadeira_flexora", "afundo", "panturrilha", "cadeira_abdutora", "cadeira_adutora"],
    "Core": ["abdominal", "prancha", "abdominal_obliquo"],
}


def exercise_label(key: str) -> str:
    return EXERCISES.get(key, {}).get("label", key)


def muscles_for(exercise_keys) -> set[str]:
    """União dos músculos treinados por uma coleção de exercícios."""
    out: set[str] = set()
    for key in exercise_keys:
        out.update(EXERCISES.get(key, {}).get("muscles", []))
    return out
