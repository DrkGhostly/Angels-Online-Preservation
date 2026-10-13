// Tablas de manejadores que se rellenan DESDE CODIGO, store a store.
//
// POR QUE. El reparto de paquetes de este juego no es un switch ni una tabla
// ya escrita en el fichero: es un array de entradas de 16 bytes que una sola
// funcion llena de golpe, con cientos de
//
//     *(code **)(this + 0x7b0 + opcode * 0x10) = Manejador;
//
// En el cliente de IGG esa funcion es 005e5350 y pone 203 entradas. Para
// comparar con otro binario -- el de Global, recompilado con VS2022, donde
// ninguna direccion coincide -- hace falta encontrarla por su FORMA, que es
// lo que hace esto: funciones que guardan muchas direcciones de funcion en
// posiciones de un mismo registro base.
//
// Imprime, de la que gane, el desplazamiento de cada store. El opcode sale
// de ahi: (desplazamiento - base) / paso, donde el paso es la distancia mas
// repetida entre desplazamientos consecutivos.
//
//     python tools/ghidra.py --script tabla_en_codigo.java --cual global
//
//@category AO
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;

import java.util.*;

public class tabla_en_codigo extends GhidraScript {

    private static final int MIN_STORES = 30;

    @Override
    public void run() throws Exception {
        var fm = currentProgram.getFunctionManager();
        var esp = currentProgram.getAddressFactory().getDefaultAddressSpace();

        List<Object[]> cand = new ArrayList<>();
        FunctionIterator it = fm.getFunctions(true);
        while (it.hasNext()) {
            if (monitor.isCancelled()) return;
            Function f = it.next();
            // desplazamiento -> funcion guardada
            TreeMap<Long, String> puestos = new TreeMap<>();
            InstructionIterator ii =
                    currentProgram.getListing().getInstructions(f.getBody(), true);
            while (ii.hasNext()) {
                Instruction i = ii.next();
                if (!i.getMnemonicString().equalsIgnoreCase("MOV")) continue;
                if (i.getNumOperands() < 2) continue;
                // operando 1: un inmediato que sea entrada de funcion
                Object[] fuente = i.getOpObjects(1);
                if (fuente.length != 1 || !(fuente[0] instanceof Scalar)) continue;
                long v = ((Scalar) fuente[0]).getUnsignedValue();
                Function dest;
                try {
                    dest = fm.getFunctionAt(esp.getAddress(v));
                } catch (Exception e) { continue; }
                if (dest == null) continue;
                // operando 0: [registro + desplazamiento]
                Long desp = desplazamiento(i);
                // Los desplazamientos NEGATIVOS son variables locales o
                // campos por debajo del puntero, no la tabla. Colandolos, la
                // base deducida se iba a un numero negativo y todos los
                // opcodes salian mal: paso en el cliente de IGG, donde un
                // store a [ebp-0x80] arrastro la cuenta entera.
                if (desp == null) continue;
                puestos.put(desp, dest.getName());
            }
            if (puestos.size() >= MIN_STORES) {
                cand.add(new Object[]{puestos.size(), f, puestos});
            }
        }
        cand.sort((a, b) -> ((Integer) b[0]) - ((Integer) a[0]));
        println("== funciones que llenan una tabla de manejadores: " + cand.size());
        for (int k = 0; k < Math.min(cand.size(), 6); k++) {
            Function f = (Function) cand.get(k)[1];
            println(String.format("   %-10s %-26s %4d entradas  %6d bytes",
                    f.getEntryPoint(), f.getName(), (Integer) cand.get(k)[0],
                    f.getBody().getNumAddresses()));
        }
        if (cand.isEmpty()) {
            println("   ninguna: este binario reparte de otra forma");
            return;
        }

        @SuppressWarnings("unchecked")
        TreeMap<Long, String> puestos = (TreeMap<Long, String>) cand.get(0)[2];
        // el paso: la distancia mas repetida entre desplazamientos seguidos
        Map<Long, Integer> saltos = new HashMap<>();
        Long previo = null;
        for (Long d : puestos.keySet()) {
            if (previo != null) {
                long s = d - previo;
                if (s > 0) saltos.merge(s, 1, Integer::sum);
            }
            previo = d;
        }
        long paso = saltos.entrySet().stream()
                .max(Map.Entry.comparingByValue()).map(Map.Entry::getKey).orElse(16L);

        // LA BASE SE SACA DEL GRUPO DENSO, no del primer store. Entre los
        // stores se cuelan algunos que no son de la tabla -- punteros
        // guardados en campos sueltos, o en variables locales con
        // desplazamiento negativo -- y tomando el minimo a secas la base se
        // iba a un numero absurdo y TODOS los opcodes salian mal. Los de la
        // tabla comparten resto al dividir por el paso, asi que se queda el
        // resto mas repetido y el resto se descarta.
        Map<Long, Integer> restos = new HashMap<>();
        for (Long d : puestos.keySet()) {
            restos.merge(Math.floorMod(d, paso), 1, Integer::sum);
        }
        long resto = restos.entrySet().stream()
                .max(Map.Entry.comparingByValue()).map(Map.Entry::getKey).orElse(0L);
        TreeMap<Long, String> dela = new TreeMap<>();
        for (var e : puestos.entrySet()) {
            if (Math.floorMod(e.getKey(), paso) == resto && e.getKey() > 0) {
                dela.put(e.getKey(), e.getValue());
            }
        }
        if (dela.size() < MIN_STORES) {
            println("   el grupo denso quedo en " + dela.size() + ": no concluyo");
            return;
        }
        puestos = dela;
        long base = puestos.firstKey() - paso;   // el opcode 1 va en el primero
        println("");
        println(String.format("== la mayor: paso 0x%x, base deducida 0x%x", paso, base));
        println("== opcode -> manejador");
        for (var e : puestos.entrySet()) {
            long op = (e.getKey() - base) / paso;
            println(String.format("   0x%04x  %s", op, e.getValue()));
        }
    }

    /** El desplazamiento de un destino [registro + N], o null si no lo es. */
    private Long desplazamiento(Instruction i) {
        Object[] objs = i.getOpObjects(0);
        if (objs.length < 2) return null;
        Long d = null;
        boolean hayRegistro = false;
        for (Object o : objs) {
            if (o instanceof Scalar) d = ((Scalar) o).getValue();
            else hayRegistro = true;
        }
        return hayRegistro ? d : null;
    }
}
