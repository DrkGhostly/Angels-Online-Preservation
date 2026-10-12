// Descompila una funcion a C y la imprime. La herramienta de uso diario.
//
//     python tools/ghidra.py --script descompilar.java 004c3460
//     python tools/ghidra.py --script descompilar.java 004c3460 120
//
// El segundo argumento es cuantos segundos esperar al descompilador; las
// funciones gordas de este cliente -- hay una de 160 KB de C -- pasan del
// minuto por defecto.
//
// Imprime tambien QUIEN LLAMA a esa funcion, que es justo lo que no se puede
// sacar de Angel_unpacked.c.
//
//@category AO
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

import java.util.LinkedHashSet;
import java.util.Set;

public class descompilar extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            println("falta la direccion: --script descompilar.java 004c3460");
            return;
        }
        Address dir = currentProgram.getAddressFactory()
                .getDefaultAddressSpace().getAddress(args[0].replace("0x", ""));
        int segundos = args.length > 1 ? Integer.parseInt(args[1]) : 120;

        Function f = currentProgram.getFunctionManager().getFunctionContaining(dir);
        if (f == null) {
            println("no hay ninguna funcion en " + dir);
            return;
        }
        println("== " + f.getName() + " en " + f.getEntryPoint()
                + "  (" + f.getBody().getNumAddresses() + " bytes)");

        // Quien la llama: lo que el fichero plano no sabe.
        Set<String> de = new LinkedHashSet<>();
        for (Reference r : getReferencesTo(f.getEntryPoint())) {
            Function g = currentProgram.getFunctionManager()
                    .getFunctionContaining(r.getFromAddress());
            de.add(g == null ? r.getFromAddress().toString()
                    : g.getName() + " @" + g.getEntryPoint());
        }
        println("== la llaman " + de.size() + ":");
        int n = 0;
        for (String s : de) {
            println("   " + s);
            if (++n >= 15) { println("   ..."); break; }
        }

        DecompInterface dec = new DecompInterface();
        try {
            dec.openProgram(currentProgram);
            DecompileResults res = dec.decompileFunction(f, segundos, monitor);
            if (res == null || !res.decompileCompleted()) {
                println("== el descompilador no termino: "
                        + (res == null ? "sin resultado" : res.getErrorMessage()));
                return;
            }
            println("== C:");
            println(res.getDecompiledFunction().getC());
        } finally {
            dec.dispose();
        }
    }
}
