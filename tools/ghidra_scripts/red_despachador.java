// Encuentra la capa de red del cliente y, desde ella, el despachador S->C.
//
// ESTO ES LO QUE EL FICHERO PLANO NO PUEDE HACER. Angel_unpacked.c no tiene
// referencias cruzadas, asi que para encontrar el despachador solo queda
// adivinar por la forma -- "la funcion con mas casos que parezcan opcodes" --
// y eso ya dio un falso positivo: salio SQLite, cuya maquina virtual tiene
// unos 170 opcodes y gano con los 25 conocidos entre sus 171 casos.
//
// Aqui se va al reves y sin adivinar: se parte de las funciones de socket que
// el cliente IMPORTA de WS2_32 y se sube por quien las llama. El que reciba
// los bytes y los reparta tiene que estar en ese arbol.
//
// VA EN JAVA Y NO EN PYTHON a proposito: los scripts de PyGhidra piden
// arrancar Ghidra con su lanzador propio, y los de Java corren tal cual en
// analyzeHeadless sin instalar nada.
//
//@category AO
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.FunctionIterator;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.symbol.FlowType;
import ghidra.program.model.symbol.Reference;

import java.util.*;

public class red_despachador extends GhidraScript {

    // Como recibe bytes un cliente de Windows de esta epoca.
    private static final List<String> OBJETIVOS = Arrays.asList(
            "recv", "WSARecv", "recvfrom", "WSARecvFrom", "ReadFile");
    private static final int NIVELES = 4;
    private static final int MIN_DESTINOS = 20;

    @Override
    public void run() throws Exception {
        var fm = currentProgram.getFunctionManager();

        // 1. las funciones de socket, sean externas o thunks locales
        Set<Function> semillas = new LinkedHashSet<>();
        Iterator<Function> ext = fm.getExternalFunctions();
        while (ext.hasNext()) {
            Function f = ext.next();
            if (OBJETIVOS.contains(f.getName())) semillas.add(f);
        }
        FunctionIterator todas = fm.getFunctions(true);
        while (todas.hasNext()) {
            Function f = todas.next();
            if (OBJETIVOS.contains(f.getName())) semillas.add(f);
        }
        println("== funciones de socket encontradas: " + semillas.size());
        for (Function f : semillas) {
            println("   " + f.getName() + "  " + f.getEntryPoint());
        }
        if (semillas.isEmpty()) {
            println("   ninguna: el cliente quiza use otra biblioteca");
            return;
        }

        // 2. subir por quien las llama, nivel a nivel
        Set<Function> vistos = new HashSet<>(semillas);
        Set<Function> frente = new LinkedHashSet<>(semillas);
        Map<Integer, Set<Function>> porNivel = new LinkedHashMap<>();
        for (int n = 1; n <= NIVELES; n++) {
            Set<Function> nuevo = new LinkedHashSet<>();
            for (Function f : frente) {
                for (Reference r : getReferencesTo(f.getEntryPoint())) {
                    Function g = fm.getFunctionContaining(r.getFromAddress());
                    if (g != null && !vistos.contains(g)) nuevo.add(g);
                }
            }
            vistos.addAll(nuevo);
            porNivel.put(n, nuevo);
            frente = nuevo;
            println("== nivel " + n + ": " + nuevo.size() + " funciones que llaman");
            if (nuevo.isEmpty()) break;
        }

        // 3. de todas ellas, las que reparten a muchos sitios
        List<Object[]> cand = new ArrayList<>();
        for (var e : porNivel.entrySet()) {
            for (Function f : e.getValue()) {
                int d = destinosCalculados(f);
                if (d >= MIN_DESTINOS) cand.add(new Object[]{d, e.getKey(), f});
            }
        }
        cand.sort((a, b) -> ((Integer) b[0]) - ((Integer) a[0]));
        println("");
        println("== candidatos a DESPACHADOR (saltos calculados con muchos destinos)");
        if (cand.isEmpty()) {
            println("   ninguno con " + MIN_DESTINOS
                    + "+ destinos; subir NIVELES o bajar el umbral");
        }
        for (int i = 0; i < Math.min(cand.size(), 12); i++) {
            Object[] c = cand.get(i);
            Function f = (Function) c[2];
            println(String.format("   %-10s %-34s %4d destinos   a %s saltos del socket",
                    f.getEntryPoint(), f.getName(), (Integer) c[0], c[1]));
        }
    }

    /** Cuantos destinos distintos tiene la tabla de saltos de esa funcion.
     *  Un despachador reparte desde un salto calculado; una funcion normal no. */
    private int destinosCalculados(Function f) {
        Set<Address> destinos = new HashSet<>();
        InstructionIterator it =
                currentProgram.getListing().getInstructions(f.getBody(), true);
        while (it.hasNext()) {
            Instruction i = it.next();
            FlowType fl = i.getFlowType();
            if (fl != null && fl.isComputed() && fl.isJump()) {
                destinos.addAll(Arrays.asList(i.getFlows()));
            }
        }
        return destinos.size();
    }
}
