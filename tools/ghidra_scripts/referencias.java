// Quien toca una direccion de datos, y si la lee o la escribe.
//
// POR QUE. Es la pregunta que Angel_unpacked.c no puede responder, y la que
// cierra cada hallazgo: encontrada la tabla de reparto en DAT_00b0d4e8 (1024
// punteros a funcion, 250 puestos), lo que falta es el que la LEE, porque ese
// es el despachador y el que dice de donde vienen los bytes.
//
//     python tools/ghidra.py --script referencias.java 00b0d4e8
//
//@category AO
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class referencias extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            println("falta la direccion: --script referencias.java 00b0d4e8");
            return;
        }
        Address dir = currentProgram.getAddressFactory()
                .getDefaultAddressSpace().getAddress(args[0].replace("0x", ""));
        Reference[] refs = getReferencesTo(dir);
        println("== " + refs.length + " referencias a " + dir);
        for (Reference r : refs) {
            Function f = currentProgram.getFunctionManager()
                    .getFunctionContaining(r.getFromAddress());
            println(String.format("   %-10s %-14s %s",
                    r.getFromAddress(), r.getReferenceType(),
                    f == null ? "(sin funcion)" : f.getName() + " @" + f.getEntryPoint()));
        }
    }
}
