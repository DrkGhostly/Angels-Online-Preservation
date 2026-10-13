// Las instrucciones de un tramo, tal cual. Para cuando el C no basta.
//
// POR QUE. El descompilador reescribe, y a veces lo que hace falta es justo
// lo que tira: en 0081e900 la llamada al encolador sale como
// FUN_0081dde0(_Dst, tamano, 0) con tres argumentos, pero la funcion es
// __thiscall y el objeto va en ECX, que el C no ensena. Sin saber QUE objeto
// es, no se puede buscar quien vacia esa cola, y quien la vacia es el
// despachador de paquetes del servidor al cliente.
//
//     python tools/ghidra.py --script desensamblar.java 0081ea90 60
//
// El segundo argumento es cuantas instrucciones imprimir.
//
//@category AO
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;

public class desensamblar extends GhidraScript {

    @Override
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 1) {
            println("falta la direccion: --script desensamblar.java 0081ea90 60");
            return;
        }
        Address dir = currentProgram.getAddressFactory()
                .getDefaultAddressSpace().getAddress(args[0].replace("0x", ""));
        int cuantas = args.length > 1 ? Integer.parseInt(args[1]) : 40;

        Instruction i = getInstructionAt(dir);
        if (i == null) {
            i = getInstructionAfter(dir);
        }
        for (int n = 0; i != null && n < cuantas; n++, i = i.getNext()) {
            StringBuilder extra = new StringBuilder();
            for (Reference r : i.getReferencesFrom()) {
                if (r.getReferenceType().isCall() || r.getReferenceType().isData()) {
                    var f = currentProgram.getFunctionManager()
                            .getFunctionAt(r.getToAddress());
                    extra.append("   -> ").append(f != null ? f.getName()
                            : r.getToAddress().toString());
                }
            }
            println(String.format("   %s  %-44s%s", i.getAddress(), i, extra));
        }
    }
}
