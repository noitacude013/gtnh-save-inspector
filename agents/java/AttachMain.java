import com.sun.tools.attach.VirtualMachine;

/**
 * Tiny attach helper used by gtnh-save-inspector's live probe.
 *
 * Usage: java --add-modules jdk.attach -cp <this dir> AttachMain <pid> <agent.jar> [agentArgs]
 */
public class AttachMain {

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("usage: AttachMain <pid> <agent.jar> [agentArgs]");
            System.exit(2);
        }
        String agentArgs = args.length > 2 ? args[2] : null;
        VirtualMachine vm = VirtualMachine.attach(args[0]);
        try {
            vm.loadAgent(args[1], agentArgs);
            System.out.println("agent loaded into pid " + args[0]);
        } finally {
            try {
                vm.detach();
            } catch (Throwable ignored) {
            }
        }
    }
}
