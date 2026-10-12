// Todas las funciones del binario con un salto calculado de muchos destinos.
//
// POR QUE EN TODO EL BINARIO. Subir desde recv no llega al reparto S->C: el
// transporte (0081e900) parte la trama en sub-mensajes y los ENCOLA (0081dde0,
// lista de nodos {puntero,tamano,siguiente}); el reparto pasa despues, en la
// capa de juego, asi que no hay camino de llamadas entre recv y el. Y tampoco
// se registra en una tabla: el unico registrador del binario (0078bd70, 250
// entradas en DAT_00b0d4e8) resulto ser la API nativa de la maquina virtual de
// scripts del cliente, cuyo interprete es 00787450.
//
// Asi que el reparto es un switch y hay que buscarlo a lo ancho. Lo que no se
// puede es creerse el primero que salga: contar "casos que coinciden con
// opcodes conocidos" ya dio TRES falsos positivos, y conviene dejarlos
// escritos porque son el motivo de que este script solo liste y no concluya:
//
//     0042ee80  la maquina virtual de SQLite  (171 casos, los 25 opcodes)
//     004c3460  manejador de controles de interfaz (64 casos: 0x9c5, 0x9cd...)
//     005b1160  el switch de estados del bucle principal (36 casos, 1..0x24)
//
// Los dos ultimos ganaron porque los opcodes de este juego son numeros bajos y
// seguidos, asi que CUALQUIER enumeracion de 30 valores los contiene. El filtro
// bueno no es el recuento: es si la funcion recibe un puntero y un tamano y
// lee de ahi.
//
//@category AO
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.FlowType;

import java.util.*;

public class saltos_grandes extends GhidraScript {

    private static final int MIN_DESTINOS = 30;

    @Override
    public void run() throws Exception {
        List<Object[]> filas = new ArrayList<>();
        FunctionIterator it = currentProgram.getFunctionManager().getFunctions(true);
        while (it.hasNext()) {
            if (monitor.isCancelled()) return;
            Function f = it.next();
            Set<Address> destinos = new HashSet<>();
            int saltos = 0;
            InstructionIterator ii =
                    currentProgram.getListing().getInstructions(f.getBody(), true);
            while (ii.hasNext()) {
                Instruction i = ii.next();
                FlowType fl = i.getFlowType();
                if (fl != null && fl.isComputed() && fl.isJump()) {
                    saltos++;
                    destinos.addAll(Arrays.asList(i.getFlows()));
                }
            }
            if (destinos.size() >= MIN_DESTINOS) {
                filas.add(new Object[]{destinos.size(), saltos, f});
            }
        }
        filas.sort((a, b) -> ((Integer) b[0]) - ((Integer) a[0]));
        println("== " + filas.size() + " funciones con " + MIN_DESTINOS + "+ destinos");
        for (Object[] r : filas) {
            Function f = (Function) r[2];
            println(String.format("   %-10s %-28s %4d destinos  %2d saltos  %6d bytes  la llaman %d",
                    f.getEntryPoint(), f.getName(), (Integer) r[0], (Integer) r[1],
                    f.getBody().getNumAddresses(),
                    getReferencesTo(f.getEntryPoint()).length));
        }
    }
}
