# El cliente de Global, evaluado

Pregunta: el cliente de Global (el `angel.dat` de Steam, recompilado con
VS2022) habla el mismo protocolo que el de IGG, o sea, podria conectarse a
nuestro servidor?

Respuesta corta: **si**. Mismo transporte, misma arquitectura de reparto, y
de los 39 opcodes que nuestro servidor manda NO FALTA NI UNO.

## El transporte es identico

La cabecera de 6 bytes de Global se arma igual, campo por campo
(FUN_0073f360, encontrada por la constante 0x1357, que aparece en los dos
binarios):

    u16 tamano  ^ 0x1357
    u16 marca   = tamano ^ un contador de secuencia que da la vuelta en 0x7fff
    u8  banderas ^ (byte)tamano     bit0 cifrada, con el tamano redondeado a 16
    u8  suma de control
    cuerpo = paquete de sub-mensajes, cada uno u16 tamano + cuerpo

## El reparto es la misma idea, en otra direccion

| | IGG | Global |
|---|---|---|
| la rellena | `FUN_005e5350` | `FUN_005c04b0` |
| base de la tabla | `this + 0x7a0` | `this + 0x6b8` |
| paso | 0x10 | 0x10 |
| hueco que limpia | 0x2000 (512 entradas) | 0x2000 (512 entradas) |
| manejadores puestos | 203 | 233 |

El opcode es el primer u16 del sub-mensaje y el manejador sale de
`base + opcode * 0x10`, igual en los dos.

## Los opcodes

De los 203 de IGG, **196 estan tambien en Global**. Global anade 37 nuevos
(numeros altos: 0x154, 0x171-0x173, 0x196-0x19b...) y pierde 7 que IGG tenia
(0x70, 0x137, 0x138, 0x142, 0x15f, 0x162, 0x16f).

Lo que decide: de los 39 opcodes que nuestro servidor manda, **ninguno esta
entre esos 7**. Los trece que mas se usan -- 0x0001, 0x0004, 0x0005, 0x0008,
0x000e, 0x0012, 0x0017, 0x0018, 0x001b, 0x001d, 0x0023, 0x0024 y 0x0026 --
estan todos.

## Lo que esto NO demuestra

Que el numero de opcode exista no garantiza que el CUERPO sea el mismo. Entre
una version y otra se añaden campos, y el 0x0001 -- los 184 bytes de la
apariencia del jugador -- es justo el tipo de mensaje que crece. Eso hay que
mirarlo mensaje a mensaje, y ahora se puede: cada manejador de esta tabla es
el que lee su propio cuerpo.

Y quedan dos cosas que no son del protocolo:

  * `steam_api.dll` lo importa de forma ESTATICA: sin esa DLL al lado el
    proceso no arranca, y aun con ella puede negarse si SteamAPI_Init falla;
  * sus .pak son otros (data1/2/3 + update/update2 contra data1 +
    update..update26), asi que el contenido tampoco es intercambiable sin
    probarlo.

## Como se llego, por si hay que repetirlo

El atajo fue la constante `0x1357`: localizarla en `.text` lleva directo al
lector de tramas, y de ahi a la cola y al reparto. El camino largo desde
`recv` no sirve en ninguno de los dos clientes, porque la cola corta el grafo
de llamadas.

`tools/ghidra_scripts/tabla_en_codigo.java` encuentra la funcion que rellena
la tabla por su forma, y acierta en los dos binarios (203 y 233). Lo que NO
hace bien es deducir la base, asi que sus numeros de opcode no valen: en IGG
daba FUN_005f4850 para el opcode 1 cuando el bueno es FUN_005e97c0, y no
acertaba ni uno. La base buena sale del `memset` del principio de esa
funcion, que limpia desde el opcode 1.

## La tabla de Global

| opcode | manejador | esta en IGG |
|---|---|---|
| 0x0001 | `FUN_005c7b81` | si |
| 0x0002 | `LAB_005ca21d` | si |
| 0x0003 | `FUN_005ccade` | si |
| 0x0004 | `FUN_005cdc43` | si |
| 0x0005 | `FUN_005ce0a7` | si |
| 0x0006 | `FUN_005c8c19` | si |
| 0x0008 | `FUN_005c4d36` | si |
| 0x0009 | `LAB_005c8fc4` | si |
| 0x000b | `FUN_005c3433` | si |
| 0x000c | `FUN_005c7592` | si |
| 0x000d | `FUN_005c402b` | si |
| 0x000e | `FUN_005c8eb4` | si |
| 0x000f | `FUN_005cde5d` | si |
| 0x0010 | `FUN_005c8295` | si |
| 0x0011 | `FUN_005c93f5` | si |
| 0x0012 | `FUN_005c3cbc` | si |
| 0x0013 | `FUN_005c82db` | si |
| 0x0014 | `FUN_005cfc71` | si |
| 0x0015 | `FUN_005c8030` | si |
| 0x0016 | `FUN_005d0d2c` | si |
| 0x0017 | `FUN_005c4e34` | si |
| 0x0018 | `FUN_005cc838` | si |
| 0x0019 | `FUN_005cdd87` | si |
| 0x001a | `LAB_005c4fba` | si |
| 0x001b | `FUN_005cd760` | si |
| 0x001c | `FUN_005d0676` | si |
| 0x001d | `FUN_005cddbc` | si |
| 0x001e | `FUN_005cfb49` | si |
| 0x001f | `FUN_005cd9b9` | si |
| 0x0020 | `LAB_005c895c` | si |
| 0x0021 | `FUN_005c4e6a` | si |
| 0x0022 | `FUN_005cd8db` | si |
| 0x0023 | `FUN_005d1842` | si |
| 0x0024 | `LAB_005c65f2` | si |
| 0x0025 | `FUN_005c63ca` | si |
| 0x0026 | `LAB_005c5f76` | si |
| 0x0027 | `FUN_005c9a7d` | si |
| 0x0028 | `FUN_0058c3bb` | si |
| 0x0029 | `FUN_0058c9b9` | si |
| 0x002a | `FUN_0058c4e7` | si |
| 0x002b | `FUN_0058c152` | si |
| 0x002c | `FUN_0058c340` | si |
| 0x002d | `FUN_0058cd28` | si |
| 0x002e | `FUN_0058cc49` | si |
| 0x002f | `FUN_0058c6fc` | si |
| 0x0030 | `FUN_0058cd54` | si |
| 0x0031 | `FUN_005cc41e` | si |
| 0x0032 | `FUN_005cbc33` | si |
| 0x0033 | `LAB_005cbe4e` | si |
| 0x0034 | `FUN_005cbb04` | si |
| 0x0035 | `FUN_005c8de2` | si |
| 0x0036 | `FUN_005c8d4c` | si |
| 0x003a | `LAB_005cec0c` | si |
| 0x003b | `FUN_005cf21a` | si |
| 0x003c | `FUN_005a58df` | si |
| 0x003d | `FUN_005a57bc` | si |
| 0x003e | `FUN_005a5319` | si |
| 0x003f | `FUN_005a4ad0` | si |
| 0x0040 | `FUN_005a4a76` | si |
| 0x0041 | `LAB_005a4cef` | si |
| 0x0042 | `LAB_005a58ce` | si |
| 0x0043 | `FUN_005cd36c` | si |
| 0x0044 | `LAB_005cfbc2` | si |
| 0x0045 | `FUN_005ceaf6` | si |
| 0x0046 | `LAB_005cf188` | si |
| 0x0047 | `FUN_005ceebe` | si |
| 0x0048 | `FUN_005ceff4` | si |
| 0x0049 | `FUN_005cf3df` | si |
| 0x004a | `LAB_005cf0dd` | si |
| 0x004b | `FUN_005cc2ef` | si |
| 0x004c | `FUN_005ce0f7` | si |
| 0x004d | `FUN_005c7cea` | si |
| 0x004e | `FUN_005c7f30` | si |
| 0x004f | `FUN_005c3854` | si |
| 0x0050 | `FUN_005cb412` | si |
| 0x0051 | `FUN_005c9c6a` | si |
| 0x0052 | `FUN_005c9e2e` | si |
| 0x0053 | `FUN_005c4525` | si |
| 0x0054 | `FUN_005c692c` | si |
| 0x0055 | `FUN_005c6804` | si |
| 0x0056 | `FUN_005c6831` | si |
| 0x0057 | `FUN_005c6fd3` | si |
| 0x0058 | `FUN_005c6ed2` | si |
| 0x005a | `FUN_005c6f1f` | si |
| 0x005b | `FUN_005c57f6` | si |
| 0x005c | `FUN_005cb0bf` | si |
| 0x005d | `FUN_005c50d5` | si |
| 0x005e | `FUN_005cd9fe` | si |
| 0x005f | `FUN_005c3ca0` | si |
| 0x0060 | `FUN_005da8e8` | si |
| 0x0061 | `FUN_005da7ff` | si |
| 0x0062 | `FUN_005da834` | si |
| 0x0063 | `FUN_005da8c5` | si |
| 0x0064 | `FUN_005cb959` | si |
| 0x0065 | `FUN_005cba66` | si |
| 0x0066 | `FUN_005c9e60` | si |
| 0x0067 | `FUN_005c9670` | si |
| 0x0068 | `FUN_005cb642` | si |
| 0x0069 | `FUN_005c8282` | si |
| 0x006a | `FUN_005c80fd` | si |
| 0x006b | `FUN_005c8262` | si |
| 0x006c | `LAB_005c8275` | si |
| 0x006d | `FUN_005c7ba0` | si |
| 0x006e | `LAB_005cb560` | si |
| 0x006f | `FUN_005c5481` | NO |
| 0x0121 | `FUN_005c445a` | si |
| 0x0122 | `FUN_005cb119` | si |
| 0x0123 | `FUN_005c5de8` | si |
| 0x0124 | `FUN_005c5dfe` | si |
| 0x0125 | `FUN_005c5149` | si |
| 0x0126 | `FUN_005c7a8e` | si |
| 0x0127 | `FUN_005c4266` | si |
| 0x0128 | `LAB_005ce36f` | si |
| 0x0129 | `FUN_005c3ab4` | si |
| 0x012a | `FUN_005cda75` | si |
| 0x012b | `FUN_005cf4d4` | si |
| 0x012e | `LAB_005cb1f3` | si |
| 0x012f | `FUN_005ce594` | si |
| 0x0130 | `FUN_005ce6c2` | si |
| 0x0131 | `FUN_005cea3d` | si |
| 0x0132 | `FUN_005c9940` | si |
| 0x0133 | `FUN_005ce986` | si |
| 0x0134 | `FUN_005c7096` | si |
| 0x0135 | `FUN_005c9253` | si |
| 0x0136 | `FUN_005c4f15` | si |
| 0x013a | `FUN_005c3952` | si |
| 0x013b | `FUN_005c3a48` | si |
| 0x013c | `FUN_005c3a7a` | si |
| 0x013d | `FUN_005c97e2` | si |
| 0x013f | `FUN_005c58bc` | si |
| 0x0140 | `FUN_005cc736` | si |
| 0x0141 | `FUN_005c72ae` | si |
| 0x0143 | `FUN_005c74ed` | si |
| 0x0144 | `FUN_005c5ab6` | si |
| 0x0145 | `FUN_005c7538` | si |
| 0x0146 | `FUN_005c71a8` | si |
| 0x0147 | `FUN_005c943f` | si |
| 0x0148 | `FUN_005c979c` | si |
| 0x0149 | `FUN_005c7288` | si |
| 0x014a | `FUN_005d05ef` | si |
| 0x014b | `FUN_005c71f6` | si |
| 0x014c | `FUN_005d0528` | si |
| 0x014d | `FUN_005cf7c9` | si |
| 0x014e | `FUN_005c4c8f` | si |
| 0x0152 | `FUN_005c5721` | si |
| 0x0153 | `FUN_005c5679` | si |
| 0x0154 | `FUN_005c8635` | NO |
| 0x0156 | `FUN_005c33e4` | si |
| 0x0157 | `FUN_005c43dd` | si |
| 0x0158 | `FUN_005c4976` | si |
| 0x0159 | `FUN_005c49cc` | si |
| 0x015a | `FUN_005c4602` | si |
| 0x015b | `FUN_005c46c7` | si |
| 0x015c | `LAB_005c45d5` | si |
| 0x015d | `FUN_005c49f3` | si |
| 0x015e | `FUN_005c579d` | si |
| 0x0160 | `FUN_005d006c` | si |
| 0x0161 | `FUN_005d0127` | si |
| 0x0163 | `FUN_005caf91` | si |
| 0x0164 | `FUN_005cad0b` | si |
| 0x0165 | `FUN_005ca49a` | si |
| 0x0166 | `FUN_005caed5` | si |
| 0x0167 | `FUN_005caf53` | si |
| 0x0168 | `FUN_005ca76c` | si |
| 0x0169 | `FUN_005ca933` | si |
| 0x016a | `FUN_005cac31` | si |
| 0x016b | `FUN_005c5856` | si |
| 0x016c | `LAB_005c583d` | si |
| 0x016d | `FUN_005c5892` | si |
| 0x016e | `FUN_005ca6ec` | si |
| 0x0170 | `FUN_005c7bcb` | si |
| 0x0171 | `FUN_005c437d` | NO |
| 0x0172 | `FUN_005cb5a7` | NO |
| 0x0173 | `FUN_005cf9f3` | NO |
| 0x0174 | `FUN_005c399a` | si |
| 0x0175 | `FUN_005c396c` | si |
| 0x0176 | `FUN_005c39b6` | si |
| 0x0177 | `FUN_005c39d2` | si |
| 0x0178 | `FUN_005c39ee` | si |
| 0x017a | `FUN_005c544d` | si |
| 0x017b | `FUN_005c9dfa` | si |
| 0x017d | `FUN_005c37d6` | si |
| 0x017e | `FUN_005c5f61` | si |
| 0x017f | `LAB_005cdd15` | NO |
| 0x0180 | `FUN_005d86af` | si |
| 0x0182 | `FUN_005c7bff` | si |
| 0x0183 | `FUN_005a4caa` | NO |
| 0x0184 | `FUN_005a4d83` | NO |
| 0x0185 | `FUN_005a4b24` | NO |
| 0x0186 | `FUN_005d0cdb` | si |
| 0x0187 | `FUN_005cb7e0` | si |
| 0x0188 | `FUN_005cb87f` | si |
| 0x0189 | `FUN_005cb76f` | si |
| 0x018a | `FUN_005cb7a3` | si |
| 0x018b | `FUN_005c8e80` | si |
| 0x018c | `FUN_005c56f3` | si |
| 0x018d | `FUN_005bec46` | si |
| 0x018e | `FUN_005bea34` | si |
| 0x018f | `FUN_005beb8e` | si |
| 0x0190 | `FUN_005becba` | si |
| 0x0191 | `FUN_005bec99` | si |
| 0x0192 | `FUN_005bec78` | si |
| 0x0193 | `FUN_005beb26` | si |
| 0x0194 | `LAB_005bec64` | si |
| 0x0195 | `FUN_005beb6b` | si |
| 0x0196 | `FUN_005cb0ec` | NO |
| 0x0197 | `FUN_005cb10a` | NO |
| 0x0198 | `FUN_005cb0fb` | NO |
| 0x0199 | `FUN_005dac50` | NO |
| 0x019a | `FUN_005d2069` | NO |
| 0x019b | `FUN_005d20d7` | NO |
| 0x019c | `FUN_005d205a` | NO |
| 0x019d | `FUN_005cd6bb` | NO |
| 0x019e | `FUN_005cd6eb` | NO |
| 0x019f | `FUN_005a4a5f` | NO |
| 0x01a0 | `FUN_005a51e6` | NO |
| 0x01a1 | `FUN_005a4e57` | NO |
| 0x01a2 | `FUN_005a4c14` | NO |
| 0x01a3 | `FUN_005a4a8d` | NO |
| 0x01a4 | `FUN_005a59c3` | NO |
| 0x01a5 | `FUN_005cde6e` | NO |
| 0x01a6 | `FUN_005c6732` | NO |
| 0x01a7 | `FUN_005c6757` | NO |
| 0x01a8 | `FUN_005c67a5` | NO |
| 0x01a9 | `FUN_005c677d` | NO |
| 0x01aa | `FUN_005c67de` | NO |
| 0x01ab | `FUN_005c704c` | NO |
| 0x01ac | `FUN_005c78f8` | NO |
| 0x01ad | `FUN_005cf548` | NO |
| 0x01ae | `FUN_005cb376` | NO |
| 0x01b3 | `LAB_005c801a` | NO |
| 0x01b4 | `FUN_005dac74` | NO |
| 0x01b5 | `FUN_005da7ac` | NO |
