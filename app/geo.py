"""Serialização dos pontos do percurso para GeoJSON (RFC 7946).

GeoJSON é o formato padrão para geometria em mapas web — o Leaflet consome
direto via L.geoJSON. Isolar essa conversão aqui mantém o parser de FIT focado
em ler o arquivo e as rotas focadas em HTTP (responsabilidade única).
"""
from typing import Any


def track_to_geojson(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Converte os pontos do percurso num FeatureCollection.

    - Pontos com lat/lon viram a geometria (LineString) da rota.
    - As séries temporais (tempo, FC, velocidade, cadência, altitude) vão em
      `properties`, para o gráfico de FC e futura sincronização gráfico↔mapa.
    - Atividades indoor (sem GPS) retornam uma Feature com geometry=null, que é
      GeoJSON válido — assim um único endpoint serve mapa e gráfico nos dois casos.
    """
    coords = [
        [p["lon"], p["lat"]]  # GeoJSON usa a ordem [longitude, latitude]
        for p in points
        if p.get("lat") is not None and p.get("lon") is not None
    ]

    properties = {
        "t": [p.get("t") for p in points],
        "hr": [p.get("hr") for p in points],
        "speed": [p.get("speed") for p in points],
        "cadence": [p.get("cadence") for p in points],
        "alt": [p.get("alt") for p in points],
    }

    geometry = {"type": "LineString", "coordinates": coords} if coords else None

    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": geometry, "properties": properties}
        ],
    }
