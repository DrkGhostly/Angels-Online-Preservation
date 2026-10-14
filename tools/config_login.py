"""Ver y cambiar los interruptores del login (tabla `configuracion` de cuentas.db).

Sustituyen a las variables de entorno AO_VALIDAR_PASSWORD,
AO_REGISTRAR_PRIMER_HASH y AO_GUARDAR_AUTH_CRUDO. Valen en el siguiente
login, sin reiniciar el servidor.

    python tools/config_login.py                               ver todo
    python tools/config_login.py validar_password 0            apagar uno
    python tools/config_login.py reemplazar_contrasena 1       encender uno

PONER LA MISMA CONTRASENA A TODAS LAS CUENTAS (p. ej. 123456):
    1. python tools/config_login.py reemplazar_contrasena 1
    2. entrar una vez en cada cuenta con 123456
    3. python tools/config_login.py reemplazar_contrasena 0
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'server'))

import cuentas


def main():
    cuentas._init_db()
    con = cuentas._get_conn()
    try:
        if len(sys.argv) == 3:
            clave, valor = sys.argv[1], sys.argv[2]
            if clave not in cuentas.CONFIGURACION_POR_DEFECTO:
                raise SystemExit('no existe: %s (hay: %s)'
                                 % (clave, ', '.join(cuentas.CONFIGURACION_POR_DEFECTO)))
            if valor not in ('0', '1'):
                raise SystemExit('el valor es 0 o 1')
            con.execute('UPDATE configuracion SET valor = ? WHERE clave = ?', (valor, clave))
            con.commit()
        elif len(sys.argv) != 1:
            raise SystemExit(__doc__)
        for clave, valor, nota in con.execute('SELECT clave, valor, nota FROM configuracion ORDER BY clave'):
            print('%-24s %s   %s' % (clave, valor, nota))
    finally:
        con.close()


if __name__ == '__main__':
    main()
