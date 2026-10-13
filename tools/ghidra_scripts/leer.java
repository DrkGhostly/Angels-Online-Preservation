// Lee palabras de 4 bytes de una direccion y dice a que apunta cada una.
//
// POR QUE. Hace falta para las vtables, que es por donde pasa el reparto de
// paquetes de este cliente: el bucle que vacia la cola de recepcion llama al
// metodo virtual en +0x10 del oyente, y el oyente del mundo tiene su vtable
// en 0x8C0114. Angel_unpacked.c solo lista algunas entradas como "weak" y se
// salta justo la que interesa, y tablas_de_punteros.java no la ve porque solo
// imprime las tablas de 16 entradas o mas y una vtable asi es mas corta.
//
//     python tools/ghidra.py --script leer.java 008c0114 8
//
//@category AO
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSpace;
import ghidra.program.model.listing.Function;

public class leer extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            println("falta la direccion: --script leer.java 008c0114 8");
            return;
        }
        AddressSpace esp = currentProgram.getAddressFactory().getDefaultAddressSpace();
        long base = Long.parseLong(args[0].replace("0x", ""), 16);
        int cuantas = args.length > 1 ? Integer.parseInt(args[1]) : 8;

        for (int i = 0; i < cuantas; i++) {
            long dir = base + i * 4L;
            long v;
            try {
                v = Integer.toUnsignedLong(currentProgram.getMemory()
                        .getInt(esp.getAddress(dir)));
            } catch (Exception e) {
                println(String.format("   +%-4x %08x   (sin leer: %s)",
                        i * 4, dir, e.getMessage()));
                continue;
            }
            String aque = "";
            try {
                Address d = esp.getAddress(v);
                Function f = currentProgram.getFunctionManager().getFunctionAt(d);
                if (f != null) {
                    aque = "-> " + f.getName() + "  (la llaman "
                            + getReferencesTo(f.getEntryPoint()).length + ")";
                } else if (currentProgram.getMemory().contains(d)) {
                    aque = "-> " + d + " (no es entrada de funcion)";
                }
            } catch (Exception e) { /* fuera del mapa */ }
            println(String.format("   +%-4x %08x = %08x   %s", i * 4, dir, v, aque));
        }
    }
}
