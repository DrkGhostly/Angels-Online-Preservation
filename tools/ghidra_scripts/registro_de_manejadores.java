// Busca el registrador de manejadores: registrar(opcode, funcion).
//
// POR QUE. El reparto S->C no es un switch (se comprobo: los dos candidatos
// eran IDs de controles de interfaz y estados del bucle principal) y tampoco
// es una tabla de punteros ya escrita en el fichero (se escanearon .rdata y
// .data enteros: la mayor tiene 90 huecos y no contiene el ancla conocida).
// Queda el tercer patron, el habitual en clientes de esta epoca: la tabla se
// LLENA EN EJECUCION, con una tanda de llamadas registrar(opcode, manejador).
//
// Eso deja un rastro inconfundible en .text: un PUSH de la direccion de una
// funcion, un PUSH de una constante pequena al lado, y todos acabando en la
// MISMA llamada. Se agrupa por destino de la llamada y el registrador es el
// que gane por goleada.
//
//@category AO
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;

import java.util.*;

public class registro_de_manejadores extends GhidraScript {

    /** Cuantas instrucciones mirar hacia delante buscando la llamada. */
    private static final int VENTANA = 12;

    @Override
    public void run() throws Exception {
        var fm = currentProgram.getFunctionManager();
        var esp = currentProgram.getAddressFactory().getDefaultAddressSpace();

        // destino de la llamada -> lista de (opcode, manejador, donde)
        Map<String, List<long[]>> porRegistrador = new HashMap<>();
        Map<String, Address> dirReg = new HashMap<>();

        InstructionIterator it = currentProgram.getListing().getInstructions(true);
        while (it.hasNext()) {
            if (monitor.isCancelled()) return;
            Instruction i = it.next();
            if (!i.getMnemonicString().equalsIgnoreCase("PUSH")) continue;
            Long valor = inmediato(i);
            if (valor == null || valor == 0) continue;
            Function manejador;
            try {
                manejador = fm.getFunctionAt(esp.getAddress(valor));
            } catch (Exception e) { continue; }
            if (manejador == null) continue;

            // hacia atras y hacia delante: el opcode es la otra constante
            Long opcode = constanteCerca(i);
            if (opcode == null) continue;

            // la llamada que cierra el grupo
            Instruction j = i;
            Address destino = null;
            for (int n = 0; n < VENTANA && j != null; n++) {
                j = j.getNext();
                if (j == null) break;
                if (j.getFlowType() != null && j.getFlowType().isCall()) {
                    Address[] f = j.getFlows();
                    if (f.length > 0) destino = f[0];
                    break;
                }
            }
            if (destino == null) continue;
            Function reg = fm.getFunctionAt(destino);
            String clave = reg == null ? destino.toString() : reg.getName();
            dirReg.put(clave, destino);
            porRegistrador.computeIfAbsent(clave, k -> new ArrayList<>())
                    .add(new long[]{opcode, valor, i.getAddress().getOffset()});
        }

        List<Map.Entry<String, List<long[]>>> orden = new ArrayList<>(porRegistrador.entrySet());
        orden.sort((a, b) -> b.getValue().size() - a.getValue().size());
        println("== posibles registradores (destino de la llamada, cuantos registros)");
        for (int k = 0; k < Math.min(orden.size(), 10); k++) {
            var e = orden.get(k);
            println(String.format("   %-22s %s   %4d registros",
                    e.getKey(), dirReg.get(e.getKey()), e.getValue().size()));
        }
        if (orden.isEmpty()) return;

        // el ganador, al detalle y ordenado por opcode
        var g = orden.get(0);
        println("");
        println("== " + g.getKey() + " al detalle");
        List<long[]> filas = g.getValue();
        filas.sort((a, b) -> Long.compare(a[0], b[0]));
        for (long[] f : filas) {
            Function m = fm.getFunctionAt(esp.getAddress(f[1]));
            println(String.format("   0x%04x  %08x  %-26s  (registrado en %08x)",
                    f[0], f[1], m == null ? "?" : m.getName(), f[2]));
        }
    }

    /** El inmediato de un PUSH, si lo tiene. */
    private Long inmediato(Instruction i) {
        if (i.getNumOperands() < 1) return null;
        Object[] ops = i.getOpObjects(0);
        if (ops.length != 1 || !(ops[0] instanceof Scalar)) return null;
        if (ops[0] instanceof Register) return null;
        return ((Scalar) ops[0]).getUnsignedValue();
    }

    /** Una constante pequena en los PUSH/MOV vecinos: el opcode. */
    private Long constanteCerca(Instruction centro) {
        Instruction[] cerca = new Instruction[6];
        Instruction a = centro;
        for (int n = 0; n < 3; n++) { a = a == null ? null : a.getPrevious(); cerca[n] = a; }
        a = centro;
        for (int n = 3; n < 6; n++) { a = a == null ? null : a.getNext(); cerca[n] = a; }
        for (Instruction i : cerca) {
            if (i == null) continue;
            String m = i.getMnemonicString();
            if (!m.equalsIgnoreCase("PUSH") && !m.equalsIgnoreCase("MOV")) continue;
            for (int op = 0; op < i.getNumOperands(); op++) {
                Object[] objs = i.getOpObjects(op);
                if (objs.length != 1 || !(objs[0] instanceof Scalar)) continue;
                long v = ((Scalar) objs[0]).getUnsignedValue();
                if (v > 0 && v < 0x400) return v;
            }
        }
        return null;
    }
}
