// Runs JUnit 4 test classes with the real JUnitCore and writes one junit XML report.
// Used by scripts/jobs/kotlin_jvm.py. Exit code 0 only when every test passed and at least one ran.
import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStreamWriter;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.runner.Description;
import org.junit.runner.JUnitCore;
import org.junit.runner.Request;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;
import org.junit.runner.notification.RunListener;

public final class JUnitXmlRunner {
    private static final class Case {
        final String cls;
        final String name;
        long startNs;
        double seconds;
        String failure;
        boolean skipped;

        Case(String cls, String name) {
            this.cls = cls;
            this.name = name;
        }
    }

    private static String esc(String s) {
        if (s == null) return "";
        StringBuilder b = new StringBuilder();
        for (char c : s.toCharArray()) {
            switch (c) {
                case '&': b.append("&amp;"); break;
                case '<': b.append("&lt;"); break;
                case '>': b.append("&gt;"); break;
                case '"': b.append("&quot;"); break;
                default:
                    if (c < 0x20 && c != '\n' && c != '\t' && c != '\r') b.append(' ');
                    else b.append(c);
            }
        }
        return b.toString();
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 2) {
            System.err.println("usage: JUnitXmlRunner <out.xml> <test class>...");
            System.exit(2);
        }
        String out = args[0];
        Map<String, Case> cases = new LinkedHashMap<>();
        JUnitCore core = new JUnitCore();
        core.addListener(new RunListener() {
            private Case get(Description d) {
                String key = d.getClassName() + "#" + d.getMethodName();
                return cases.computeIfAbsent(key, k -> new Case(d.getClassName(), d.getMethodName()));
            }

            @Override public void testStarted(Description d) { get(d).startNs = System.nanoTime(); }

            @Override public void testFinished(Description d) {
                Case c = get(d);
                c.seconds = (System.nanoTime() - c.startNs) / 1e9;
                System.out.println((c.failure == null ? "PASS " : "FAIL ") + c.cls + "." + c.name);
            }

            @Override public void testFailure(Failure f) {
                Description d = f.getDescription();
                if (d.getMethodName() == null) {
                    Case c = get(Description.createTestDescription(d.getClassName(), "<class setup>"));
                    c.failure = f.getTrace();
                    System.out.println("FAIL " + d.getClassName() + " (class): " + f.getMessage());
                } else {
                    get(d).failure = f.getTrace();
                }
            }

            @Override public void testAssumptionFailure(Failure f) { get(f.getDescription()).skipped = true; }

            @Override public void testIgnored(Description d) { get(d).skipped = true; }
        });
        List<Class<?>> classes = new ArrayList<>();
        for (int i = 1; i < args.length; i++) classes.add(Class.forName(args[i]));
        Result r = core.run(Request.classes(classes.toArray(new Class<?>[0])));

        int failures = 0, skipped = 0;
        for (Case c : cases.values()) {
            if (c.failure != null) failures++;
            if (c.skipped) skipped++;
        }
        File f = new File(out);
        if (f.getParentFile() != null) f.getParentFile().mkdirs();
        try (Writer w = new OutputStreamWriter(new FileOutputStream(f), StandardCharsets.UTF_8)) {
            w.write("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
            w.write(String.format("<testsuites><testsuite name=\"kotlin-jvm\" tests=\"%d\" failures=\"%d\" errors=\"0\" skipped=\"%d\" time=\"%.3f\">%n",
                cases.size(), failures, skipped, r.getRunTime() / 1000.0));
            for (Case c : cases.values()) {
                w.write(String.format("  <testcase classname=\"%s\" name=\"%s\" time=\"%.3f\"", esc(c.cls), esc(c.name), c.seconds));
                if (c.failure != null) {
                    w.write("><failure message=\"failed\">" + esc(c.failure) + "</failure></testcase>\n");
                } else if (c.skipped) {
                    w.write("><skipped/></testcase>\n");
                } else {
                    w.write("/>\n");
                }
            }
            w.write("</testsuite></testsuites>\n");
        }
        System.out.printf("kotlin-jvm: %d tests, %d failed, %d skipped%n", cases.size(), failures, skipped);
        System.exit(failures == 0 && cases.size() - skipped > 0 ? 0 : 1);
    }
}
