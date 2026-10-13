# Homologar el launcher de Global con el cliente de IGG

El launcher de Global es mas estable y mas moderno que el de IGG, y la
pregunta era si se puede usar con nuestro cliente sin romperlo. Se puede, y
no por casualidad: **son el mismo programa, rehecho**.

De la carpeta de Global no se toca nada. Solo se copia lo necesario a
`C:\AO\Angels Online`.

## Lo que son cada uno

|                  | linker      | compilado  | empaquetado | notas |
|------------------|-------------|------------|-------------|-------|
| IGG START.EXE    | 9.0 VS2008  | 2021-08-23 | no          | .text 413 KB |
| IGG angel.dat    | 9.0 VS2008  | 2025-09-11 | UPX         | el juego |
| Global START.EXE | 14.44 VS2022| 2026-06-09 | no          | .text 2.8 MB, WebView2 |
| Global angel.dat | 14.44 VS2022| 2026-10-02 | no          | D3D11 + steam_api |

## Por que el cambio es seguro para el juego

**Ninguno de los dos launchers lee `server.xml`.** Eso lo lee el juego. El
launcher solo parchea y lanza `angel.dat` con `CreateProcess` -- lo registra
el mismo: `[RESULT] angel.dat: Exists`. Asi que cambiarlo no toca el
protocolo ni a que servidor se conecta nadie.

Los dos son MFC, los dos parchean por FTP con las mismas clases
(`CFtpConnection`, `FtpGetFileA`), los dos leen `reg.ini` en `[PROFILE]`, y
los dos usan `update3.ini`, que es justo lo que ya sirve el FTP local de
server/cliente_local.py en el 2121.

## EL JUEGO DE GLOBAL NO SE TOCA

Su `angel.dat` es otro binario: recompilado con VS2022, D3D11, y pide
`steam_api.dll`. Toda la ingenieria inversa del proyecto -- el transporte,
los 203 manejadores de docs/tabla_s2c.md, las direcciones -- sale del binario
de IGG y NO vale para ese. Mezclar los clientes rompe el servidor. Se
homologa el launcher; el juego se queda como esta.

## El mapa de claves, que es todo el trabajo

Las dos versiones leen `reg.ini`, seccion `[PROFILE]`. Las claves son las
mismas menos una, y esa una es la que importa:

| IGG          | Global        | para que |
|--------------|---------------|----------|
| `UpdateIP`   | **`LoaderURL`** | el host de parches |
| `UpdatePort` | `UpdatePort`  | el puerto |
| `PassiveMode`| `PassiveMode` | FTP pasivo |
| `GameDir`    | `GameDir`     | donde esta el juego |
| `Version`    | `Version`     | se compara con la del servidor |
| `GameName`   | `GameName`    | |
| `LoaderVer`  | `LoaderVer`   | |
| --           | `IniURL`      | por defecto `update3.ini` |
| --           | `UpdateDir`   | el trozo de ruta de la URL |

## Como parchea Global, medido y no supuesto

Esto costo dos vueltas y conviene dejarlo escrito, porque las dos primeras
suposiciones eran razonables y las dos estaban mal.

**`LoaderURL` NO se lee del reg.ini.** Se lee del ini que el launcher acaba
de DESCARGARSE. El binario pide `INFO\LoaderURL` junto a `INFO\GameVerFrom`,
`INFO\GameVerTrans`, `INFO\LoaderVer`, `VERSION\GameVer`, `VERSION\GameURL` y
`COMPLEXFILE`, todos del fichero remoto. En el reg.ini se puede poner y no
pasa nada: lo ignora. Por eso la primera prueba se quedo en "Connecting to
the update server..": seguia yendo a `alog-patch.uj.com.tw`, que resuelve a
172.237.7.106 y no contesta.

Asi que el host SI hay que parchearlo en el binario. Son dos cadenas ASCII
sueltas, en `.rdata` (el valor por defecto, justo detras del nombre de la
clave) y en `.data`, las dos seguidas de ceros: se sobrescriben con
`127.0.0.1` y los ceros de relleno, sin mover nada de sitio.

**Y no habla FTP: habla HTTP.** El de IGG parchea por FTP, el de Global por
HTTP. Medido con una sonda escuchando en el 2121, lo primero que manda es:

    GET /alog-patch/version.ini HTTP/1.1
    User-Agent: test app
    Host: 127.0.0.1:2121

o sea que respeta `UpdatePort` -- el 2121 salio de nuestro ini -- pero arma
`http://%s:%d/%s%s` con host, puerto, `UpdateDir` (por defecto `alog-patch/`)
e `IniURL`. Sin contestarle eso sale "Failed to obtain the version".

Lo bueno: el CONTENIDO de ese ini es el mismo formato que el `update3.ini`
del launcher viejo, asi que vale el generador que ya habia.

Para no necesitar dos reg.ini distintos, el puerto 2121 ahora atiende a los
dos: huele el protocolo. En FTP habla primero el SERVIDOR (el 220 de
saludo) y en HTTP habla primero el CLIENTE, asi que se espera medio segundo a
ver si alguien dice algo. Esta en `_manejar_actualizacion` de
server/cliente_local.py.

## Lo que se ha hecho

En `C:\AO\Angels Online`, sin pisar nada:

    START_GLOBAL.EXE      copiado de Global, con otro nombre
    WebView2Loader.dll    copiado de Global, lo pide el launcher
    language.ini          copiado de Global (Language=4), IGG no tenia
    reg.ini               con las claves de LOS DOS, para que el viejo siga valiendo

Respaldos: `C:\AO\_backup_launcher_<fecha>\` con los dos START.EXE,
LOADER12.EXE, angel.dat, ANGLE.DAT, todos los .ini, server.xml y `setting/`.
Ademas `reg.ini.antes_global.bak` al lado del original.

El `reg.ini` que queda:

    [PROFILE]
    GameName = Angels Online
    Version = 8.5.1.0
    GameDir = ./
    LoaderVer = 1.7
    PassiveMode = 1
    UpdateIP = 127.0.0.1      <- lo lee el START.EXE de IGG
    UpdatePort = 2121
    LoaderURL = 127.0.0.1     <- lo lee el START_GLOBAL.EXE
    IniURL = update3.ini
    UpdateDir =

## Lo que falta probar

Se prueba arrancando `START_GLOBAL.EXE` con el servidor levantado. Deja
`start.log` en la carpeta con informacion del sistema y de cada paso, que es
parte de por que es mas estable, asi que ese fichero es la respuesta:

  * `[CONNECT] update started ... host=127.0.0.1 port=2121` dice que el
    redirigido funciono;
  * `[RESULT] angel.dat: Exists` y luego `ExecuteGame` dicen que lanza;
  * `[ERROR] ExecuteGame: CreateProcess failed` diria que no encuentra el
    juego;
  * `[ERROR] game too old cur=... required>=...` seria el unico corte por
    version, y la nuestra (8.5.1.0) es mas alta que la suya (0.1.0.4).

## Lo que se ha dejado a proposito

El panel de noticias apunta a `https://aog.userjoy.com/loader/<idioma>/` y se
dibuja en WebView2. Es cosmetico y NO se ha tocado, porque esas cadenas van
en los recursos con un prefijo de longitud y en bloques donde cada cadena
depende de donde acaba la anterior: cambiar una de largo descoloca las que
vienen detras. Si se quiere local -- el de IGG apunta a
`http://127.0.0.1:8080/p.htm`, que ya sirve cliente_local.py --, hay que
escribir una de EXACTAMENTE la misma longitud (34 caracteres), por ejemplo
`http://127.0.0.1:8080/p.htm?a=aaaa`.
