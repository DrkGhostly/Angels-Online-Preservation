"""Mapas del tesoro (treasuremap.xml).

101 mapas en el pak vigente (UPDATE8). Cada uno dice que cofre dibuja, de
que tabla de drop saca el premio, y en que escenas y puntos de disparo
puede aparecer.

    <藏寶圖 編號="1" 名稱="Dusty Wooden Box" 寶箱圖形="60153"
            掉寶資料="473" 場景01="41" 觸發點01="100" .../>

Lo que NO esta en el cliente es la REGLA DE SELECCION: cual de los puntos
sale cada vez. Eso lo decidia el servidor.
"""
import json
import pathlib
import random

_TABLA = None


def tabla() -> list:
    global _TABLA
    if _TABLA is None:
        f = pathlib.Path(__file__).parent / 'plantillas' / 'mapas_tesoro.json'
        try:
            _TABLA = json.loads(f.read_text(encoding='utf-8'))['filas']
        except Exception:
            _TABLA = []
    return _TABLA


def de_id(mid: int):
    for m in tabla():
        if m.get('id') == int(mid):
            return m
    return None


def en_escena(stage: int) -> list:
    """Los mapas que pueden aparecer en ese escenario."""
    return [m for m in tabla() if int(stage) in (m.get('escenas') or [])]


def punto_al_azar(mid: int):
    """Un punto de disparo del mapa. SUPOSICION: el cliente no dice cual."""
    m = de_id(mid)
    pts = (m or {}).get('puntos') or []
    return random.choice(pts) if pts else None
