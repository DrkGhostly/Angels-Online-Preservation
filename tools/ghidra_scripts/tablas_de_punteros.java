// Busca tablas de punteros a funcion: el reparto opcode -> manejador.
//
// POR QUE. Se busco el despachador S->C como un switch y no lo es. El
// transporte (0081e900) parte la trama en sub-mensajes y los ENCOLA con
// 0081dde0 en una lista enlazada; el reparto ocurre despues, en la capa de
// juego, y un reparto de ~150 opcodes en un cliente de esta epoca se hace con
// una tabla de punteros, no con un switch. Una tabla asi es trivial de
// encontrar por su forma: muchos enteros seguidos que son entradas de funcion.
//
// ANCLA. El proyecto ya tenia anotado 0x5EB130 como el manejador de la ficha
// del jugador (0x0026). Si la tabla del reparto existe, 0x5EB130 cae dentro, y
// entonces el indice de cada hueco da el opcode de los demas. Se pasa como
// argumento para no fiarse de la forma sola.
//
//     python tools/ghidra.py --script tablas_de_punteros.java 5eb130
//
//@category AO
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.MemoryBlock;

import java.util.ArrayList;
import java.util.List;

public class tablas_de_punteros extends GhidraScript {

    private static final int MIN_ENTRADAS = 16;

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        Long ancla = null;
        if (args.length > 0) {
            ancla = Long.parseLong(args[0].replace("0x", ""), 16);
            println("== ancla: " + Long.toHexString(ancla));
        }
        var fm = currentProgram.getFunctionManager();
        var mem = currentProgram.getMemory();

        for (MemoryBlock b : mem.getBlocks()) {
            if (!b.isInitialized() || b.isExecute()) continue;
            println("== bloque " + b.getName() + " " + b.getStart() + ".." + b.getEnd());
            long ini = b.getStart().getOffset(), fin = b.getEnd().getOffset() - 3;
            List<Long> corrida = new ArrayList<>();
            long dirCorrida = 0;
            for (long a = ini; a <= fin; a += 4) {
                if (monitor.isCancelled()) return;
                long v;
                try {
                    v = Integer.toUnsignedLong(mem.getInt(
                            currentProgram.getAddressFactory()
                                    .getDefaultAddressSpace().getAddress(a)));
                } catch (Exception e) { v = 0; }
                boolean esFuncion = false;
                if (v != 0) {
                    try {
                        Address d = currentProgram.getAddressFactory()
                                .getDefaultAddressSpace().getAddress(v);
                        esFuncion = fm.getFunctionAt(d) != null;
                    } catch (Exception e) { /* fuera de rango */ }
                }
                if (esFuncion) {
                    if (corrida.isEmpty()) dirCorrida = a;
                    corrida.add(v);
                } else {
                    volcar(dirCorrida, corrida, ancla);
                    corrida.clear();
                }
            }
            volcar(dirCorrida, corrida, ancla);
        }
    }

    private void volcar(long dir, List<Long> corrida, Long ancla) {
        if (corrida.size() < MIN_ENTRADAS) return;
        int donde = ancla == null ? -1 : corrida.indexOf(ancla);
        println(String.format("   %08x  %4d entradas%s", dir, corrida.size(),
                donde >= 0 ? "   <<< EL ANCLA ESTA EN EL HUECO " + donde : ""));
        if (donde < 0) return;
        var fm = currentProgram.getFunctionManager();
        for (int i = 0; i < corrida.size(); i++) {
            Address d = currentProgram.getAddressFactory()
                    .getDefaultAddressSpace().getAddress(corrida.get(i));
            Function f = fm.getFunctionAt(d);
            println(String.format("      [%3d] 0x%04x  %08x  %s", i, i,
                    corrida.get(i), f == null ? "?" : f.getName()));
        }
    }
}
