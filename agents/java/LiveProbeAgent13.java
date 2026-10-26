import java.io.File;
import java.io.FileOutputStream;
import java.io.PrintStream;
import java.lang.instrument.Instrumentation;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.math.BigInteger;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Date;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Live probe agent for gtnh-save-inspector.
 *
 * Attached to a running GTNH client/server JVM. Every interval it writes one JSON line with the
 * state of all GregTech meta tile entities it can find:
 *
 * {"time":..., "tick":..., "machines":[{"class":"MTEEyeOfHarmony","dim":180,"x":..,"y":..,
 *  "z":..,"chunk":[cx,cz],"chunkModified":true,"fields":{...}}]}
 *
 * The agent is read-only: it never writes to the world save. Configuration args are a
 * semicolon-separated list: out=PATH;stop=PATH;interval=1000;filter=A,B;samples=1;log=PATH
 */
public class LiveProbeAgent13 {

    static PrintStream out;
    static PrintStream log;
    static Instrumentation inst;
    static String stopPath;
    static String filter; // comma separated simple class names, null = all GT machines
    static String mode = "machines"; // "machines" or "worlds"
    static int maxMachines = 500;
    static Set<Integer> dimFilter;
    static int targetX;
    static int targetY;
    static int targetZ;
    static String targetPos;
    static long intervalMs = 1000L;
    static int samplesLeft = 1 << 30;
    static Class<?> mcClass;
    static volatile boolean running = true;
    static long lastStatus = 0L;

    static void logline(String message) {
        try {
            if (log != null) {
                log.println(new Date() + " " + message);
            }
        } catch (Throwable ignored) {
        }
    }

    public static void agentmain(String args, Instrumentation instrumentation) {
        inst = instrumentation;
        // The agent class is loaded once per JVM: reset every option so a later attach that
        // omits an argument does not inherit it from a previous attach.
        filter = null;
        stopPath = null;
        intervalMs = 1000L;
        samplesLeft = 1 << 30;
        mode = "machines";
        maxMachines = 500;
        dimFilter = null;
        targetX = 0;
        targetY = 0;
        targetZ = 0;
        targetPos = null;
        String outPath = null;
        String logPath = null;
        try {
            if (args != null) {
                for (String part : args.split(";")) {
                    int eq = part.indexOf('=');
                    if (eq <= 0) {
                        continue;
                    }
                    String key = part.substring(0, eq).trim();
                    String value = part.substring(eq + 1).trim();
                    if (key.equals("out")) {
                        outPath = value;
                    } else if (key.equals("stop")) {
                        stopPath = value;
                    } else if (key.equals("filter")) {
                        filter = value.isEmpty() ? null : value;
                    } else if (key.equals("interval")) {
                        intervalMs = Math.max(100L, Long.parseLong(value));
                    } else if (key.equals("samples")) {
                        samplesLeft = Math.max(1, Integer.parseInt(value));
                    } else if (key.equals("log")) {
                        logPath = value;
                    } else if (key.equals("mode")) {
                        mode = value;
                    } else if (key.equals("max")) {
                        maxMachines = Math.max(1, Integer.parseInt(value));
                    } else if (key.equals("dim")) {
                        dimFilter = parseDims(value);
                    } else if (key.equals("x")) {
                        targetX = Integer.parseInt(value);
                    } else if (key.equals("y")) {
                        targetY = Integer.parseInt(value);
                    } else if (key.equals("z")) {
                        targetZ = Integer.parseInt(value);
                    } else if (key.equals("pos")) {
                        targetPos = value;
                    }
                }
            }
        } catch (Throwable t) {
            // fall through with defaults
        }
        if (targetPos != null) {
            String[] parts = targetPos.split(",");
            if (parts.length == 3) {
                try {
                    targetX = Integer.parseInt(parts[0].trim());
                    targetY = Integer.parseInt(parts[1].trim());
                    targetZ = Integer.parseInt(parts[2].trim());
                } catch (Throwable ignored) {
                }
            }
        }
        if (outPath == null) {
            logline("missing out= argument, not starting");
            return;
        }
        try {
            File outFile = new File(outPath);
            File parent = outFile.getParentFile();
            if (parent != null) {
                parent.mkdirs();
            }
            out = new PrintStream(new FileOutputStream(outFile, true), true, "UTF-8");
            if (logPath == null) {
                logPath = outPath + ".log";
            }
            log = new PrintStream(new FileOutputStream(logPath, true), true, "UTF-8");
        } catch (Throwable t) {
            return;
        }
        logline("live probe attached (interval=" + intervalMs + "ms, filter=" + filter + ")");
        Thread thread = new Thread(new Runnable() {
            @Override
            public void run() {
                loop();
            }
        }, "gtnh-save-inspector-probe");
        thread.setDaemon(true);
        thread.start();
    }

    // ------------------------------------------------------------------ //
    // reflection helpers
    // ------------------------------------------------------------------ //
    static Class<?> loadedClass(String name) {
        if (inst == null) {
            return null;
        }
        for (Class<?> candidate : inst.getAllLoadedClasses()) {
            if (name.equals(candidate.getName())) {
                return candidate;
            }
        }
        return null;
    }

    static Object findServer() {
        if (mcClass == null) {
            mcClass = loadedClass("net.minecraft.server.MinecraftServer");
        }
        if (mcClass == null) {
            return null;
        }
        for (Method method : mcClass.getMethods()) {
            if (Modifier.isStatic(method.getModifiers())
                && method.getParameterCount() == 0
                && mcClass.isAssignableFrom(method.getReturnType())) {
                try {
                    method.setAccessible(true);
                    Object value = method.invoke(null);
                    if (value != null) {
                        return value;
                    }
                } catch (Throwable ignored) {
                }
            }
        }
        for (Field field : mcClass.getDeclaredFields()) {
            if (Modifier.isStatic(field.getModifiers()) && mcClass.isAssignableFrom(field.getType())) {
                try {
                    field.setAccessible(true);
                    Object value = field.get(null);
                    if (value != null) {
                        return value;
                    }
                } catch (Throwable ignored) {
                }
            }
        }
        return null;
    }

    static List<Object> worlds(Object server) {
        List<Object> result = new ArrayList<Object>();
        collectNamed(server, "worldServers", result);
        collectNamed(server, "field_71305_c", result);
        if (result.isEmpty()) {
            Class<?> type = server.getClass();
            while (type != null && result.isEmpty()) {
                for (Field field : type.getDeclaredFields()) {
                    if (!field.getType().isArray()) {
                        continue;
                    }
                    if (!field.getType().getComponentType().getName().endsWith("WorldServer")) {
                        continue;
                    }
                    try {
                        field.setAccessible(true);
                        Object array = field.get(server);
                        if (array != null) {
                            for (Object item : (Object[]) array) {
                                if (item != null) {
                                    result.add(item);
                                }
                            }
                        }
                    } catch (Throwable ignored) {
                    }
                }
                type = type.getSuperclass();
            }
        }
        // Copy before handing the list to the sampling loop: the game thread may add/remove
        // tile entities concurrently and iterating the live ArrayList would throw CME.
        return new ArrayList<Object>(result);
    }

    static void collectNamed(Object target, String fieldName, List<Object> result) {
        Class<?> type = target.getClass();
        while (type != null) {
            try {
                Field field = type.getDeclaredField(fieldName);
                field.setAccessible(true);
                Object value = field.get(target);
                if (value instanceof Collection) {
                    for (Object item : (Collection<?>) value) {
                        if (item != null) {
                            result.add(item);
                        }
                    }
                } else if (value != null && value.getClass().isArray()) {
                    for (Object item : (Object[]) value) {
                        if (item != null) {
                            result.add(item);
                        }
                    }
                }
                return;
            } catch (NoSuchFieldException ignored) {
                type = type.getSuperclass();
            } catch (Throwable ignored) {
                return;
            }
        }
    }

    static List<Object> tileEntities(Object world) {
        List<Object> result = new ArrayList<Object>();
        collectNamed(world, "loadedTileEntityList", result);
        collectNamed(world, "field_147482_g", result);
        if (!result.isEmpty()) {
            return new ArrayList<Object>(result);
        }
        Class<?> type = world.getClass();
        while (type != null) {
            for (Field field : type.getDeclaredFields()) {
                if (!Collection.class.isAssignableFrom(field.getType())) {
                    continue;
                }
                try {
                    field.setAccessible(true);
                    Object value = field.get(world);
                    if (!(value instanceof Collection)) {
                        continue;
                    }
                    for (Object item : (Collection<?>) value) {
                        if (item != null) {
                            result.add(item);
                        }
                    }
                } catch (Throwable ignored) {
                }
            }
            type = type.getSuperclass();
        }
        return new ArrayList<Object>(result);
    }

    static Object mteOf(Object tileEntity) {
        Class<?> type = tileEntity.getClass();
        while (type != null) {
            for (Field field : type.getDeclaredFields()) {
                String fieldName = field.getName().toLowerCase();
                String fieldType = field.getType().getName();
                if (fieldName.contains("metatileentity") || fieldType.contains("MetaTileEntity")) {
                    try {
                        field.setAccessible(true);
                        Object value = field.get(tileEntity);
                        if (value != null) {
                            return value;
                        }
                    } catch (Throwable ignored) {
                    }
                }
            }
            type = type.getSuperclass();
        }
        return null;
    }

    static Object fieldValue(Object target, String... names) {
        for (String name : names) {
            Class<?> type = target.getClass();
            while (type != null) {
                try {
                    Field field = type.getDeclaredField(name);
                    field.setAccessible(true);
                    return field.get(target);
                } catch (NoSuchFieldException ignored) {
                    type = type.getSuperclass();
                } catch (Throwable ignored) {
                    return null;
                }
            }
        }
        return null;
    }

    static Object methodValue(Object target, String... names) {
        for (String name : names) {
            Class<?> type = target.getClass();
            while (type != null) {
                try {
                    Method method = type.getDeclaredMethod(name);
                    method.setAccessible(true);
                    return method.invoke(target);
                } catch (NoSuchMethodException ignored) {
                    type = type.getSuperclass();
                } catch (Throwable ignored) {
                    return null;
                }
            }
        }
        return null;
    }

    static Object methodValue(Class<?> type, Object target, String... names) {
        for (String name : names) {
            try {
                Method method = type.getDeclaredMethod(name);
                method.setAccessible(true);
                return method.invoke(target);
            } catch (Throwable ignored) {
            }
        }
        return null;
    }

    static int dimensionOf(Object world) {
        Object provider = fieldValue(world, "provider", "field_73011_w");
        if (provider == null) {
            return Integer.MIN_VALUE;
        }
        Object id = methodValue(provider, "getDimensionId", "func_76565_k");
        if (id instanceof Integer) {
            return (Integer) id;
        }
        Object field = fieldValue(provider, "dimensionId", "field_76574_g");
        return field instanceof Integer ? (Integer) field : Integer.MIN_VALUE;
    }

    static int tickOf(Object server) {
        Object value = methodValue(server, "getTickCounter", "func_71259_af", "getTickCount");
        if (value instanceof Integer) {
            return (Integer) value;
        }
        if (value instanceof Long) {
            return (int) Math.min(Integer.MAX_VALUE, (Long) value);
        }
        return -1;
    }

    // ------------------------------------------------------------------ //
    // sampling
    // ------------------------------------------------------------------ //
    static void loop() {
        while (running) {
            try {
                if (stopPath != null && new File(stopPath).exists()) {
                    writeLine("{\"status\":\"stopped\",\"time\":" + System.currentTimeMillis() + "}");
                    logline("stop requested");
                    closeQuietly();
                    return;
                }
                Object server = findServer();
                if (server == null) {
                    long now = System.currentTimeMillis();
                    if (now - lastStatus > 5000L) {
                        lastStatus = now;
                        writeLine("{\"status\":\"no-server\",\"time\":" + now + "}");
                    }
                } else if ("chunk".equals(mode) || "te".equals(mode)) {
                    String inspect;
                    try {
                        inspect = inspectLine(server);
                    } catch (Throwable error) {
                        inspect = errorJson("inspect failed: " + error);
                    }
                    writeLine(inspect);
                    writeLine("{\"status\":\"done\",\"time\":" + System.currentTimeMillis() + "}");
                    closeQuietly();
                    return;
                } else if ("worlds".equals(mode)) {
                    writeLine(worldSummaries(server));
                    writeLine("{\"status\":\"done\",\"time\":" + System.currentTimeMillis() + "}");
                    closeQuietly();
                    return;
                } else {
                    String line = sample(server);
                    if (line != null) {
                        writeLine(line);
                        if (--samplesLeft <= 0) {
                            writeLine("{\"status\":\"done\",\"time\":" + System.currentTimeMillis() + "}");
                            closeQuietly();
                            return;
                        }
                    }
                }
            } catch (Throwable t) {
                logline("ERR " + t);
            }
            try {
                Thread.sleep(intervalMs);
            } catch (InterruptedException e) {
                return;
            }
        }
    }

    static String sample(Object server) {
        int tick = tickOf(server);
        StringBuilder machines = new StringBuilder();
        int count = 0;
        for (Object world : worlds(server)) {
            int dimension = dimensionOf(world);
            if (dimFilter != null && !dimFilter.contains(dimension)) {
                continue;
            }
            for (Object tileEntity : tileEntities(world)) {
                if (count >= maxMachines) {
                    break;
                }
                if (!tileEntity.getClass().getName().endsWith("BaseMetaTileEntity")) {
                    continue;
                }
                Object mte = mteOf(tileEntity);
                if (mte == null) {
                    continue;
                }
                String simpleName = mte.getClass().getSimpleName();
                if (filter != null && !filterMatches(simpleName)) {
                    continue;
                }
                try {
                    String json = machineJson(mte, tileEntity, world, dimension);
                    if (json != null) {
                        if (machines.length() > 0) {
                            machines.append(',');
                        }
                        machines.append(json);
                        count++;
                    }
                } catch (Throwable ignored) {
                }
            }
        }
        return "{\"time\":" + System.currentTimeMillis()
            + ",\"tick\":" + tick
            + ",\"count\":" + count
            + ",\"machines\":[" + machines + "]}";
    }


    static Set<Integer> parseDims(String text) {
        Set<Integer> result = new HashSet<Integer>();
        for (String part : text.split(",")) {
            try {
                result.add(Integer.parseInt(part.trim()));
            } catch (Throwable ignored) {
            }
        }
        return result;
    }

    static String worldSummaries(Object server) {
        StringBuilder json = new StringBuilder();
        json.append("{\"mode\":\"worlds\",\"time\":").append(System.currentTimeMillis());
        json.append(",\"worlds\":[");
        boolean firstWorld = true;
        for (Object world : worlds(server)) {
            int dimension = dimensionOf(world);
            Collection<?> tileEntities = tileEntities(world);
            int gtCount = 0;
            Map<String, Integer> classes = new HashMap<String, Integer>();
            for (Object tileEntity : tileEntities) {
                if (tileEntity == null || !tileEntity.getClass().getName().endsWith("BaseMetaTileEntity")) {
                    continue;
                }
                gtCount++;
                Object mte = mteOf(tileEntity);
                String name = mte == null ? "?" : mte.getClass().getSimpleName();
                classes.put(name, classes.containsKey(name) ? classes.get(name) + 1 : 1);
            }
            if (!firstWorld) {
                json.append(',');
            }
            firstWorld = false;
            json.append("{\"dim\":").append(dimension)
                .append(",\"tes\":").append(tileEntities.size())
                .append(",\"gtTes\":").append(gtCount)
                .append(",\"classes\":{");
            boolean firstClass = true;
            for (Map.Entry<String, Integer> entry : classes.entrySet()) {
                if (!firstClass) {
                    json.append(',');
                }
                firstClass = false;
                json.append(quote(entry.getKey())).append(':').append(entry.getValue());
            }
            json.append("}}");
        }
        json.append(']');
        json.append('}');
        return json.toString();
    }

    static boolean filterMatches(String simpleName) {
        for (String candidate : filter.split(",")) {
            String trimmed = candidate.trim();
            if (!trimmed.isEmpty()
                && (simpleName.equals(trimmed) || simpleName.startsWith(trimmed) || simpleName.endsWith(trimmed))) {
                return true;
            }
        }
        return false;
    }


    static int targetDimension() {
        if (dimFilter != null && !dimFilter.isEmpty()) {
            return dimFilter.iterator().next();
        }
        return Integer.MIN_VALUE;
    }

    static String errorJson(String message) {
        return "{\"status\":\"error\",\"message\":" + quote(message) + "}";
    }

    static Object findWorldByDim(Object server, int dimension) {
        for (Object world : worlds(server)) {
            if (dimensionOf(world) == dimension) {
                return world;
            }
        }
        return null;
    }

    static Boolean boolObject(Object value) {
        return value instanceof Boolean ? (Boolean) value : null;
    }

    static Boolean boolMethod2(Object target, int a, int b, String... names) {
        for (String name : names) {
            Class<?> type = target.getClass();
            while (type != null) {
                try {
                    Method method = type.getDeclaredMethod(name, int.class, int.class);
                    method.setAccessible(true);
                    Object value = method.invoke(target, a, b);
                    if (value instanceof Boolean) {
                        return (Boolean) value;
                    }
                    break;
                } catch (NoSuchMethodException ignored) {
                    type = type.getSuperclass();
                } catch (Throwable ignored) {
                    break;
                }
            }
        }
        return null;
    }

    static Object findTileEntity(Object world, int x, int y, int z) {
        // The chunk map is the authoritative loaded-chunk source: no world.getTileEntity,
        // which can load a chunk if it was unloaded between checks.
        Object chunk = findChunk(world, x, z);
        if (chunk == null) {
            return null;
        }
        Object map = fieldValue(chunk, "chunkTileEntityMap", "field_150816_i");
        if (!(map instanceof Map)) {
            return null;
        }
        // 1.7.10 stores TE keys with chunk-local x/z (x & 15, z & 15), not absolute.
        int localX = x & 15;
        int localZ = z & 15;
        for (Object entry : ((Map<?, ?>) map).entrySet()) {
            Object key = ((Map.Entry<?, ?>) entry).getKey();
            Object value = ((Map.Entry<?, ?>) entry).getValue();
            Integer kx = intObject(fieldValue(key, "x", "chunkPosX", "field_151329_a"));
            Integer ky = intObject(fieldValue(key, "y", "chunkPosY", "field_151327_b"));
            Integer kz = intObject(fieldValue(key, "z", "chunkPosZ", "field_151328_c"));
            if (kx != null && kx == localX && ky != null && ky == y
                && kz != null && kz == localZ) {
                return value;
            }
        }
        return null;
    }

static String chunkJson(Object world, int dimension) {
        Object chunk = findChunk(world, targetX, targetZ);
        if (chunk == null) {
            return errorJson("chunk is not loaded (dim " + dimension + " block " + targetX + "," + targetZ + ")");
        }
        Integer chunkX = intObject(fieldValue(chunk, "xPosition", "field_76635_g"));
        Integer chunkZ = intObject(fieldValue(chunk, "zPosition", "field_76647_h"));
        if (chunkX == null) {
            chunkX = targetX >> 4;
        }
        if (chunkZ == null) {
            chunkZ = targetZ >> 4;
        }
        Boolean modified = boolObject(fieldValue(chunk, "field_76643_l", "isModified"));
        Boolean hasEntities = boolObject(fieldValue(chunk, "field_76644_m", "hasEntities"));
        Object tileEntityMap = fieldValue(chunk, "chunkTileEntityMap", "field_150816_i");
        int tileEntities = tileEntityMap instanceof Map ? ((Map<?, ?>) tileEntityMap).size() : -1;
        return "{\"mode\":\"chunk\",\"dim\":" + dimension
            + ",\"blockX\":" + targetX + ",\"blockZ\":" + targetZ
            + ",\"chunkX\":" + chunkX + ",\"chunkZ\":" + chunkZ
            + ",\"isModified\":" + (modified == null ? "null" : modified.toString())
            + ",\"hasEntities\":" + (hasEntities == null ? "null" : hasEntities.toString())
            + ",\"tileEntities\":" + tileEntities + "}";
    }

    static String teJson(Object world, int dimension) {
        Object chunk = findChunk(world, targetX, targetZ);
        if (chunk == null) {
            return errorJson("chunk is not loaded (dim " + dimension + " block "
                + targetX + "," + targetZ + "); refusing to load it");
        }
        Object tileEntity = findTileEntity(world, targetX, targetY, targetZ);
        if (tileEntity == null) {
            return errorJson("no tile entity at " + targetX + "," + targetY + "," + targetZ
                + " in dim " + dimension);
        }
        Object mte = mteOf(tileEntity);
        StringBuilder fields = new StringBuilder();
        appendFields(mte != null ? mte : tileEntity, fields);
        Boolean modified = boolObject(fieldValue(chunk, "field_76643_l", "isModified"));
        return "{\"mode\":\"te\",\"dim\":" + dimension
            + ",\"x\":" + targetX + ",\"y\":" + targetY + ",\"z\":" + targetZ
            + ",\"teClass\":" + quote(tileEntity.getClass().getSimpleName())
            + ",\"mteClass\":" + quote(mte == null ? "" : mte.getClass().getSimpleName())
            + ",\"chunkModified\":" + (modified == null ? "null" : modified.toString())
            + ",\"inventory\":" + inventoryJson(mte == null ? tileEntity : mte)
            + ",\"fields\":{" + fields + "}}";
    }

    static String inspectLine(Object server) {
        int dimension = targetDimension();
        if (dimension == Integer.MIN_VALUE) {
            return errorJson("missing dim=... for inspect mode");
        }
        Object world = findWorldByDim(server, dimension);
        if (world == null) {
            return errorJson("dimension " + dimension + " is not loaded");
        }
        if ("chunk".equals(mode)) {
            return chunkJson(world, dimension);
        }
        return teJson(world, dimension);
    }

    static String inventoryJson(Object mte) {
        if (mte == null) {
            return "null";
        }
        Object inventory = fieldValue(mte, "mInventory", "inventory");
        if (inventory == null || !inventory.getClass().isArray()) {
            return "null";
        }
        Object[] items = (Object[]) inventory;
        int used = 0;
        int total = 0;
        StringBuilder list = new StringBuilder();
        for (Object stack : items) {
            if (stack == null) {
                continue;
            }
            Integer count = intObject(fieldValue(stack, "stackSize", "field_77994_a"));
            if (count == null || count <= 0) {
                continue;
            }
            used++;
            total += count;
            if (list.length() < 600) {
                Object item = methodValue(stack, "getItem", "func_77973_b");
                String itemName = item == null ? null
                    : stringMethod(item, "getUnlocalizedName", "func_77658_a", "getName");
                Integer damage = intMethodValue(stack, "getItemDamage", "func_77960_j");
                if (list.length() > 0) {
                    list.append(',');
                }
                list.append("{\"name\":").append(quote(itemName == null ? "?" : itemName))
                    .append(",\"count\":").append(count)
                    .append(",\"damage\":").append(damage == null ? 0 : damage).append('}');
            }
        }
        return "{\"slots\":" + items.length + ",\"slotsUsed\":" + used
            + ",\"itemCount\":" + total + ",\"items\":[" + list + "]}";
    }

    static String fluidEntry(String name, Object stack) {
        Object fluid = methodValue(stack, "getFluid", "func_151000_a");
        if (fluid == null) {
            return null;
        }
        String fluidName = stringMethod(fluid, "getUnlocalizedName", "getName");
        Integer amount = intObject(fieldValue(stack, "amount", "field_77991_e"));
        return quote(name) + ":{\"fluid\":" + quote(fluidName == null ? "?" : fluidName)
            + ",\"amount\":" + (amount == null ? 0 : amount) + "}";
    }

    static String stringMethod(Object target, String... names) {
        for (String name : names) {
            Object value = methodValue(target, name);
            if (value instanceof String) {
                return (String) value;
            }
        }
        return null;
    }

    static String machineJson(Object mte, Object tileEntity, Object world, int dimension) {
        Integer x = intMethodValue(tileEntity, "getXCoord", "func_145834_a");
        Integer y = intMethodValue(tileEntity, "getYCoord", "func_145835_b");
        Integer z = intMethodValue(tileEntity, "getZCoord", "func_145839_c");
        if (x == null || y == null || z == null) {
            x = intObject(fieldValue(tileEntity, "xCoord", "field_145851_c"));
            y = intObject(fieldValue(tileEntity, "yCoord", "field_145848_d"));
            z = intObject(fieldValue(tileEntity, "zCoord", "field_145849_e"));
        }
        if (x == null || y == null || z == null) {
            return null;
        }

        StringBuilder fields = new StringBuilder();
        appendFields(mte, fields);

        Boolean chunkModified = null;
        Integer chunkX = null;
        Integer chunkZ = null;
        Object chunk = findChunk(world, x, z);
        if (chunk != null) {
            Object modified = fieldValue(chunk, "field_76643_l", "isModified");
            if (modified instanceof Boolean) {
                chunkModified = (Boolean) modified;
            }
            chunkX = intObject(fieldValue(chunk, "xPosition", "field_76635_g"));
            chunkZ = intObject(fieldValue(chunk, "zPosition", "field_76647_h"));
        }
        if (chunkX == null) {
            chunkX = x >> 4;
        }
        if (chunkZ == null) {
            chunkZ = z >> 4;
        }

        StringBuilder json = new StringBuilder();
        json.append("{\"class\":").append(quote(mte.getClass().getSimpleName()));
        json.append(",\"dim\":").append(dimension);
        json.append(",\"x\":").append(x).append(",\"y\":").append(y).append(",\"z\":").append(z);
        json.append(",\"chunk\":[").append(chunkX).append(',').append(chunkZ).append(']');
        json.append(",\"chunkModified\":").append(chunkModified == null ? "null" : chunkModified.toString());
        json.append(",\"fields\":{").append(fields).append('}');
        json.append(",\"inventory\":").append(inventoryJson(mte));
        json.append('}');
        return json.toString();
    }


    static Object findChunk(Object world, int x, int z) {
        int chunkX = x >> 4;
        int chunkZ = z >> 4;
        Object chunkProvider = methodValue(world, "getChunkProvider", "func_72863_F");
        if (chunkProvider == null) {
            chunkProvider = fieldValue(world, "chunkProvider", "field_72970_t");
        }
        if (chunkProvider == null) {
            return null;
        }
        long key = ((long) chunkX & 0xffffffffL) | (((long) chunkZ & 0xffffffffL) << 32);
        // Scan the provider's fields for a loaded-chunk container. Do not call
        // getChunkFrom*/provideChunk: those load/generate chunks.
        for (Class<?> type = chunkProvider.getClass(); type != null; type = type.getSuperclass()) {
            for (Field field : type.getDeclaredFields()) {
                if (Modifier.isStatic(field.getModifiers())) {
                    continue;
                }
                Object holder;
                try {
                    field.setAccessible(true);
                    holder = field.get(chunkProvider);
                } catch (Throwable ignored) {
                    continue;
                }
                if (holder == null) {
                    continue;
                }
                Object found = chunkFromHolder(holder, key, chunkX, chunkZ);
                if (found != null) {
                    return found;
                }
            }
        }
        return null;
    }

    static Object chunkFromHolder(Object holder, long key, int chunkX, int chunkZ) {
        if (holder instanceof Map) {
            Object value = ((Map<?, ?>) holder).get(Long.valueOf(key));
            if (value != null) {
                return value;
            }
            for (Object entry : ((Map<?, ?>) holder).entrySet()) {
                Object candidate = ((Map.Entry<?, ?>) entry).getValue();
                if (isChunkAt(candidate, chunkX, chunkZ)) {
                    return candidate;
                }
            }
        }
        String[] getters = {"func_76164_a", "get"};
        for (String name : getters) {
            try {
                Method get = holder.getClass().getMethod(name, long.class);
                get.setAccessible(true);
                Object value = get.invoke(holder, key);
                if (value != null) {
                    return value;
                }
            } catch (Throwable ignored) {
            }
        }
        try {
            Method get = holder.getClass().getMethod("get", Object.class);
            get.setAccessible(true);
            Object value = get.invoke(holder, Long.valueOf(key));
            if (value != null) {
                return value;
            }
        } catch (Throwable ignored) {
        }
        if (holder instanceof Iterable) {
            for (Object candidate : (Iterable<?>) holder) {
                if (isChunkAt(candidate, chunkX, chunkZ)) {
                    return candidate;
                }
            }
        }
        return null;
    }

    static boolean isChunkAt(Object candidate, int chunkX, int chunkZ) {
        if (candidate == null) {
            return false;
        }
        Integer cx = intObject(fieldValue(candidate, "xPosition", "field_76635_g"));
        Integer cz = intObject(fieldValue(candidate, "zPosition", "field_76647_h"));
        return cx != null && cz != null && cx == chunkX && cz == chunkZ;
    }

static Integer intMethodValue(Object target, String... names) {
        Object value = methodValue(target, names);
        return intObject(value);
    }

    static Integer intObject(Object value) {
        if (value instanceof Integer) {
            return (Integer) value;
        }
        if (value instanceof Number) {
            return ((Number) value).intValue();
        }
        return null;
    }

    static void appendFields(Object mte, StringBuilder fields) {
        Class<?> type = mte.getClass();
        int written = 0;
        while (type != null && type != Object.class && written < 120) {
            for (Field field : type.getDeclaredFields()) {
                if (written >= 120) {
                    break;
                }
                if (Modifier.isStatic(field.getModifiers()) || field.isSynthetic()) {
                    continue;
                }
                String name = field.getName();
                if (name.equals("validFluidMap")) {
                    try {
                        field.setAccessible(true);
                        Object map = field.get(mte);
                        written += appendFluidMap(map, fields, written);
                    } catch (Throwable ignored) {
                    }
                    continue;
                }
                try {
                    field.setAccessible(true);
                    Object value = field.get(mte);
                    String entry = entryFor(name, value);
                    if (entry == null && value != null
                        && value.getClass().getName().contains("FluidStack")) {
                        entry = fluidEntry(name, value);
                    }
                    if (entry == null) {
                        continue;
                    }
                    if (written > 0) {
                        fields.append(',');
                    }
                    fields.append(entry);
                    written++;
                } catch (Throwable ignored) {
                }
            }
            type = type.getSuperclass();
        }
    }

    static int appendFluidMap(Object map, StringBuilder fields, int written) {
        if (!(map instanceof Map) || ((Map<?, ?>) map).size() > 32) {
            return 0;
        }
        int count = 0;
        for (Map.Entry<?, ?> entry : ((Map<?, ?>) map).entrySet()) {
            String key = unlocalizedName(entry.getKey());
            if (key == null) {
                continue;
            }
            if (written + count > 0) {
                fields.append(',');
            }
            fields.append(quote("stored." + key)).append(':').append(numberJson(entry.getValue()));
            count++;
        }
        return count;
    }

    static String unlocalizedName(Object fluid) {
        Object name = methodValue(fluid, "getUnlocalizedName");
        if (name instanceof String) {
            return (String) name;
        }
        return null;
    }

    static String entryFor(String name, Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof Boolean) {
            return quote(name) + ':' + value;
        }
        if (value instanceof Integer || value instanceof Long || value instanceof Short || value instanceof Byte) {
            return quote(name) + ':' + value;
        }
        if (value instanceof Float || value instanceof Double) {
            double number = ((Number) value).doubleValue();
            if (Double.isNaN(number) || Double.isInfinite(number)) {
                return null;
            }
            return quote(name) + ':' + number;
        }
        if (value instanceof BigInteger) {
            return quote(name) + ':' + quote(value.toString());
        }
        if (value instanceof String) {
            return quote(name) + ':' + quote((String) value);
        }
        if (value instanceof Enum) {
            return quote(name) + ':' + quote(((Enum<?>) value).name());
        }
        if (name.equals("shutDownReason") || name.equals("checkRecipeResult")) {
            return quote(name) + ":{\"key\":" + quote(reasonKey(value)) + '}';
        }
        return null;
    }

    static String reasonKey(Object value) {
        // SimpleCheckRecipeResult/SimpleShutDownReason keep the real key in a private field;
        // getID() returns the message id ("simple_result") for check results.
        for (String fieldName : new String[]{"key", "mKey"}) {
            Object key = fieldValue(value, fieldName);
            if (key instanceof String) {
                return (String) key;
            }
        }
        for (String methodName : new String[]{"getID", "getKey", "getUnlocalizedKey"}) {
            Object key = methodValue(value, methodName);
            if (key instanceof String) {
                return (String) key;
            }
        }
        return String.valueOf(value);
    }

    static String numberJson(Object value) {
        if (value instanceof Number) {
            return value.toString();
        }
        return quote(String.valueOf(value));
    }

    static String quote(String text) {
        StringBuilder builder = new StringBuilder(text.length() + 2);
        builder.append('"');
        for (int i = 0; i < text.length(); i++) {
            char ch = text.charAt(i);
            switch (ch) {
                case '"':
                    builder.append("\\\"");
                    break;
                case '\\':
                    builder.append("\\\\");
                    break;
                case '\n':
                    builder.append("\\n");
                    break;
                case '\r':
                    builder.append("\\r");
                    break;
                case '\t':
                    builder.append("\\t");
                    break;
                default:
                    if (ch < 0x20) {
                        builder.append(String.format("\\u%04x", (int) ch));
                    } else {
                        builder.append(ch);
                    }
            }
        }
        builder.append('"');
        return builder.toString();
    }

    static void writeLine(String line) {
        try {
            if (out != null) {
                out.println(line);
            }
        } catch (Throwable ignored) {
        }
    }

    static void closeQuietly() {
        try {
            if (out != null) {
                out.flush();
                out.close();
            }
        } catch (Throwable ignored) {
        }
    }
}
