# La tabla de manejadores del servidor al cliente

Sacada del binario con Ghidra, no de capturas. Es la lista completa de
opcodes que el cliente sabe recibir, cada uno con la funcion que lo lee.

## Como se llego aqui

El camino importa porque hubo cuatro falsos positivos antes, todos por buscar
"la funcion con un switch cuyos casos parezcan opcodes": salieron la maquina
virtual de SQLite, un manejador de controles de interfaz, el switch de
estados del bucle principal y otro interprete de bytecode. Con opcodes del 1
al 0x24 ese criterio no distingue nada.

El reparto no es un switch. La cadena real es:

    0081e900   lee del socket y parte la trama en sub-mensajes
    0081dde0   encola cada uno  (la cola es el objeto en conexion + 0xC)
    0081de90   lo saca de la cola
    0081f520   el bucle que la vacia; por cada mensaje llama al metodo
               virtual en +0x10 del oyente (conexion + 0x2fbf8)
    005b1f50   el enlace del mundo pasa como oyente objeto_del_juego + 0x10,
               cuya vtable es 0x8C0114 (la escribe el constructor 005ad9b0)
    005e5260   la ranura +0x10 de esa vtable: EL DESPACHADOR

y el despachador es de una linea:

    (**(code **)(oyente + 0x7a0 + opcode * 0x10))(mensaje)

o sea una tabla de entradas de 16 bytes indexada por el opcode, que es el
primer u16 del sub-mensaje. La rellena 005e5350, de una vez, con 203
entradas: el opcode de cada una es (offset - 0x7a0) / 0x10.

## Lo que esto confirma de lo que ya estaba medido

Los nueve opcodes que el servidor ya usa tienen manejador, y uno que faltaba
tambien: el 0x001D, que no aparecia en la tabla del interprete de scripts con
la que se confundio antes.

## Como se dibuja y se cambia un objeto de mapa

El 0x000E, el 0x000F y el 0x0010 van todos a 005ef410, que llama a
005b85d0(id_entidad, sprite). Esa funcion es BUSCA-O-CREA, y busca por
`id & 0xFFFF` comprobando que el objeto guarde el id entero en su +0xBC. Dos
consecuencias:

  * los objetos se direccionan por id de entidad, no por casilla;
  * el sprite SOLO se usa al crear. Reenviar un 0x000E con el mismo id no
    cambia el dibujo: devuelve el objeto que ya estaba.

Lo que si se actualiza en un objeto que ya existe son los dos u16 de los
offsets 38 y 40 del cuerpo, que van a su +0x1FA y +0x1FC. En el armador de
login.py esos dos bytes caen dentro de 'cola', que se copiaba tal cual de la
captura sin saber que eran.

Queda por averiguar como se le dice al cliente que un objeto pasa a ser OTRO,
que es lo que pide la accion 52 CHANGE_STATICOBJ de los eventos (los mapas la
usan 363 veces con 23 objetos distintos). No es reenviar el 0x000E.

## OJO: el opcode es el indice MENOS UNO (corregido el 13/10/2026)

La primera version de esta tabla ponia como opcode el indice de la ranura,
(offset - 0x7a0) / 0x10. Pero el mensaje que viaja tiene un opcode una unidad
MENOR: el despachador recibe el sub-mensaje con el puntero un u16 antes, o el
oyente suma uno. Comprobado con REA sobre tres opcodes que el servidor ya usa
y funcionan:

  * 0x0005 (movimiento) cae en 005ec7b0, que lee origen y destino y mueve;
  * 0x0007 (quitar entidad) cae en 005eca40, que busca la entidad y la borra
    (con el byte +6 a 1 la anima antes);
  * 0x000D (aviso con id de msg.xml) cae en 005ef280, que lee el id en +2.

La tabla de abajo ya esta corregida. Lo dicho en "Como se dibuja y se cambia
un objeto de mapa" usaba los opcodes de red y sigue valiendo: el 0x000E, el
0x000F y el 0x0010 acaban en 005ef410.

## La tabla

| opcode | manejador |
|---|---|
| 0x0000 | `FUN_005e97c0` |
| 0x0001 | `FUN_005e97f0` |
| 0x0002 | `FUN_005e9c90` |
| 0x0003 | `FUN_005ec500` |
| 0x0004 | `FUN_005ec6d0` |
| 0x0005 | `FUN_005ec7b0` |
| 0x0007 | `FUN_005eca40` |
| 0x0008 | `FUN_005ebbf0` |
| 0x000a | `FUN_005ecbd0` |
| 0x000b | `FUN_005edd90` |
| 0x000c | `FUN_005ee7d0` |
| 0x000d | `FUN_005ef280` |
| 0x000e | `FUN_005ef5c0` |
| 0x000f | `FUN_005f0350` |
| 0x0010 | `FUN_005f03c0` |
| 0x0011 | `FUN_005f0420` |
| 0x0012 | `FUN_005ed670` |
| 0x0013 | `FUN_005f0cd0` |
| 0x0014 | `FUN_005f1230` |
| 0x0015 | `FUN_005f12e0` |
| 0x0016 | `FUN_005f1410` |
| 0x0017 | `FUN_005f1590` |
| 0x0018 | `FUN_005f14d0` |
| 0x0019 | `FUN_005f2200` |
| 0x001a | `FUN_005eb980` |
| 0x001b | `FUN_005f9650` |
| 0x001c | `FUN_005f23b0` |
| 0x001d | `FUN_005f0ef0` |
| 0x001e | `FUN_005f17d0` |
| 0x001f | `FUN_005f1840` |
| 0x0020 | `FUN_005f1e80` |
| 0x0021 | `FUN_005fbd30` |
| 0x0022 | `FUN_00602bd0` |
| 0x0023 | `FUN_00602d80` |
| 0x0024 | `FUN_00602f00` |
| 0x0025 | `FUN_006032d0` |
| 0x0026 | `FUN_00603ba0` |
| 0x0027 | `FUN_0056fc40` |
| 0x0028 | `FUN_00570000` |
| 0x0029 | `FUN_00570890` |
| 0x002a | `FUN_00570f20` |
| 0x002b | `FUN_005712c0` |
| 0x002c | `FUN_005719c0` |
| 0x002d | `FUN_00571330` |
| 0x002e | `FUN_00571ad0` |
| 0x002f | `FUN_00572260` |
| 0x0030 | `FUN_00603f60` |
| 0x0031 | `FUN_006043c0` |
| 0x0032 | `FUN_00604710` |
| 0x0033 | `FUN_00604d50` |
| 0x0034 | `FUN_00605190` |
| 0x0035 | `FUN_006052b0` |
| 0x0039 | `FUN_00605420` |
| 0x003a | `FUN_00605820` |
| 0x003b | `FUN_005a2350` |
| 0x003c | `FUN_005a24c0` |
| 0x003d | `FUN_005a25a0` |
| 0x003e | `FUN_005a3120` |
| 0x003f | `FUN_005a3220` |
| 0x0040 | `FUN_005a3250` |
| 0x0041 | `FUN_005a2120` |
| 0x0042 | `FUN_005eb130` |
| 0x0043 | `FUN_005f1110` |
| 0x0044 | `FUN_00605cd0` |
| 0x0045 | `FUN_00605fc0` |
| 0x0046 | `FUN_006060f0` |
| 0x0047 | `FUN_00606450` |
| 0x0048 | `FUN_00606670` |
| 0x0049 | `FUN_006068c0` |
| 0x004a | `FUN_00604f70` |
| 0x004b | `FUN_00606950` |
| 0x004c | `FUN_00606ea0` |
| 0x004d | `FUN_00607290` |
| 0x004e | `FUN_00607480` |
| 0x004f | `FUN_006078e0` |
| 0x0050 | `FUN_00607c90` |
| 0x0051 | `FUN_00607ff0` |
| 0x0052 | `FUN_00608630` |
| 0x0053 | `FUN_006086e0` |
| 0x0054 | `FUN_00608f70` |
| 0x0055 | `FUN_00608fb0` |
| 0x0056 | `FUN_00609050` |
| 0x0057 | `FUN_006090f0` |
| 0x0059 | `FUN_00607670` |
| 0x005a | `FUN_00609400` |
| 0x005b | `FUN_006095c0` |
| 0x005c | `FUN_006094a0` |
| 0x005d | `FUN_0060a160` |
| 0x005e | `FUN_0060a1a0` |
| 0x005f | `FUN_00620e80` |
| 0x0060 | `FUN_00621070` |
| 0x0061 | `FUN_006210e0` |
| 0x0062 | `FUN_00621260` |
| 0x0063 | `FUN_0060aa60` |
| 0x0064 | `FUN_0060a1e0` |
| 0x0065 | `FUN_0060adc0` |
| 0x0066 | `FUN_0060b3d0` |
| 0x0067 | `FUN_0060b530` |
| 0x0068 | `FUN_0060ccd0` |
| 0x0069 | `FUN_0060cd00` |
| 0x006a | `FUN_0060cef0` |
| 0x006b | `FUN_0060cf20` |
| 0x006c | `FUN_0060d3d0` |
| 0x006d | `FUN_00607c00` |
| 0x006f | `FUN_0060f5e0` |
| 0x0120 | `FUN_005f24e0` |
| 0x0121 | `FUN_005f2970` |
| 0x0122 | `FUN_005f2bf0` |
| 0x0123 | `FUN_005f2a70` |
| 0x0124 | `FUN_005f2650` |
| 0x0125 | `FUN_005f2850` |
| 0x0126 | `FUN_005f3c40` |
| 0x0127 | `FUN_005f33b0` |
| 0x0128 | `FUN_005f3b40` |
| 0x0129 | `FUN_005f2c30` |
| 0x012a | `FUN_00609600` |
| 0x012d | `FUN_005f2f40` |
| 0x012e | `FUN_0060b8b0` |
| 0x012f | `FUN_0060c6c0` |
| 0x0130 | `FUN_0060cb70` |
| 0x0131 | `FUN_0060b690` |
| 0x0132 | `FUN_0060c4a0` |
| 0x0133 | `FUN_0060c2b0` |
| 0x0134 | `FUN_0060cf40` |
| 0x0135 | `FUN_005f2080` |
| 0x0136 | `FUN_0060d2c0` |
| 0x0137 | `FUN_0060d2e0` |
| 0x0139 | `FUN_005f3ce0` |
| 0x013a | `FUN_005f3d20` |
| 0x013b | `FUN_005f3d70` |
| 0x013c | `FUN_005f3de0` |
| 0x013e | `FUN_005f9150` |
| 0x013f | `FUN_005f9450` |
| 0x0140 | `FUN_005ef5f0` |
| 0x0141 | `FUN_005ef8c0` |
| 0x0142 | `FUN_005ef920` |
| 0x0143 | `FUN_005ef8d0` |
| 0x0144 | `FUN_005ef9a0` |
| 0x0145 | `FUN_005efab0` |
| 0x0146 | `FUN_005efb90` |
| 0x0147 | `FUN_005efc00` |
| 0x0148 | `FUN_005efca0` |
| 0x0149 | `FUN_005efd40` |
| 0x014a | `FUN_005efe80` |
| 0x014b | `FUN_005efec0` |
| 0x014c | `FUN_005f0050` |
| 0x014d | `FUN_005f0190` |
| 0x0151 | `FUN_005f4890` |
| 0x0152 | `FUN_005f49e0` |
| 0x0155 | `FUN_005f4b10` |
| 0x0156 | `FUN_005f5120` |
| 0x0157 | `FUN_005f5dc0` |
| 0x0158 | `FUN_005f5e50` |
| 0x0159 | `FUN_005f5e90` |
| 0x015a | `FUN_005f6070` |
| 0x015b | `FUN_005f6480` |
| 0x015c | `FUN_005f6510` |
| 0x015d | `FUN_005f68f0` |
| 0x015e | `FUN_005f6980` |
| 0x015f | `FUN_005f6a20` |
| 0x0160 | `FUN_005f6bc0` |
| 0x0161 | `FUN_005f6ea0` |
| 0x0162 | `FUN_005f6eb0` |
| 0x0163 | `FUN_005f7110` |
| 0x0164 | `FUN_005f73f0` |
| 0x0165 | `FUN_005f7b80` |
| 0x0166 | `FUN_005f7ca0` |
| 0x0167 | `FUN_005f7d20` |
| 0x0168 | `FUN_005f8020` |
| 0x0169 | `FUN_005f8390` |
| 0x016a | `FUN_005f8590` |
| 0x016b | `FUN_005f8630` |
| 0x016c | `FUN_005f8670` |
| 0x016d | `FUN_005f84c0` |
| 0x016e | `FUN_005f86e0` |
| 0x016f | `FUN_005f86f0` |
| 0x0173 | `FUN_005f9000` |
| 0x0174 | `FUN_005f9040` |
| 0x0175 | `FUN_005f9090` |
| 0x0176 | `FUN_005f90d0` |
| 0x0177 | `FUN_005f9110` |
| 0x0179 | `FUN_005f8770` |
| 0x017a | `FUN_005f8eb0` |
| 0x017c | `FUN_005f8ef0` |
| 0x017d | `FUN_005f8fb0` |
| 0x017f | `FUN_006248a0` |
| 0x0181 | `FUN_0060f980` |
| 0x0185 | `FUN_0060fc60` |
| 0x0186 | `FUN_005f4110` |
| 0x0187 | `FUN_005f41e0` |
| 0x0188 | `FUN_005f4330` |
| 0x0189 | `FUN_005f4380` |
| 0x018a | `FUN_005f8730` |
| 0x018b | `FUN_005f4ac0` |
| 0x018c | `FUN_005f43f0` |
| 0x018d | `FUN_005f4420` |
| 0x018e | `FUN_005f45a0` |
| 0x018f | `FUN_005f46e0` |
| 0x0190 | `FUN_005f4720` |
| 0x0191 | `FUN_005f4760` |
| 0x0192 | `FUN_005f47a0` |
| 0x0193 | `FUN_005f4820` |
| 0x0194 | `FUN_005f4850` |
