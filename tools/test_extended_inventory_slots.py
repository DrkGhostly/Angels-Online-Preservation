"""Regression del cierre al mover items desde Card/Furniture a la mochila."""

import ast
import logging
import pathlib
import struct
from types import SimpleNamespace


HERE = pathlib.Path(__file__).resolve().parent
INVENTARIO = (HERE / "inventario.py")
if not INVENTARIO.exists():
    INVENTARIO = HERE.parent / "server" / "inventario.py"
SOURCE = INVENTARIO.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
FUNC = next(n for n in TREE.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "vaciar_ranura")
NS = {
    "struct": struct,
    "log": logging.getLogger("test_extended_inventory_slots"),
    "CONT_MOCHILA": 1,
}
exec(compile(ast.Module(body=[FUNC], type_ignores=[]), "inventario.py", "exec"), NS)
inventario = SimpleNamespace(
    vaciar_ranura=NS["vaciar_ranura"],
    CONT_MOCHILA=NS["CONT_MOCHILA"],
)


def test_vaciar_ranuras_extendidas():
    entidad = 123456
    for ranura in (167, 175, 176, 275, 276, 280, 496, 497, 556):
        paquete = inventario.vaciar_ranura(entidad, ranura)
        assert paquete == struct.pack(
            "<HIBBIH", 0x001B, 1, 2,
            inventario.CONT_MOCHILA, entidad, ranura,
        )


def test_ranuras_desconocidas_siguen_bloqueadas():
    for ranura in (155, 166, 557, 9999):
        assert inventario.vaciar_ranura(123456, ranura) == b""


if __name__ == "__main__":
    test_vaciar_ranuras_extendidas()
    test_ranuras_desconocidas_siguen_bloqueadas()
    print("OK: ranura Card 280 y rango extendido 167..556")
