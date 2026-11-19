// Runs a NiFi ExecuteScript transform outside NiFi, with a mocked session.
//   groovy Run.groovy <script.groovy> <input file> <output.jsonl> [attr=value ...]
// Writes every FlowFile sent to success as one JSON line; prints what went where.
// Used by nifi/test/run.sh, which runs it in the groovy:4.0 Docker image.

interface OutputStreamCallback { void process(OutputStream out) }
enum Scope { LOCAL, CLUSTER }

class FF {
    Map<String, String> attrs = [:]
    byte[] content = new byte[0]
    String getAttribute(String k) { attrs[k] }
}

class StateMap {
    Map<String, String> m
    Map<String, String> toMap() { m }
}

class Session {
    FF input
    List<FF> success = [], failure = []
    boolean inputRemoved = false
    FF get() { def f = input; input = null; f }
    InputStream read(FF f) { new ByteArrayInputStream(f.content) }
    FF create(FF parent) { new FF(attrs: new LinkedHashMap(parent.attrs)) }
    FF write(FF f, OutputStreamCallback cb) { def b = new ByteArrayOutputStream(); cb.process(b); f.content = b.toByteArray(); f }
    FF putAttribute(FF f, String k, String v) { f.attrs[k] = v; f }
    void transfer(FF f, Object rel) { (rel == 'success' ? success : failure) << f }
    void remove(FF f) { inputRemoved = true }
}

class State {
    Map<String, String> saved = [:]
    StateMap getState(Scope s) { new StateMap(m: saved) }
    void setState(Map m, Scope s) { saved = new LinkedHashMap(m) }
}

def (scriptPath, inputPath, outPath) = args[0..2]
def attrs = args.size() > 3 ? args[3..-1].collectEntries { a -> def i = a.indexOf('='); [(a[0..<i]): a[(i + 1)..-1]] } : [:]

// NiFi provides these imports; the plain Groovy image doesn't have the jars.
def text = new File(scriptPath).text
    .replace('import org.apache.commons.io.IOUtils', '')
    .replace('import org.apache.nifi.components.state.Scope', '')

def session = new Session(input: new FF(attrs: attrs, content: new File(inputPath).bytes))
def logged = []
def log = [info: { m -> logged << "INFO  $m" }, warn: { m -> logged << "WARN  $m" }, error: { m -> logged << "ERROR $m" }]
def binding = new Binding(session: session, log: log, REL_SUCCESS: 'success', REL_FAILURE: 'failure',
                          context: [stateManager: new State()])
new GroovyShell(this.class.classLoader, binding).evaluate(text, new File(scriptPath).name)

new File(outPath).withWriter('UTF-8') { w -> session.success.each { f -> w << new String(f.content, 'UTF-8') << '\n' } }
logged.each { println "  $it" }
println "  success=${session.success.size()} failure=${session.failure.size()} input_removed=${session.inputRemoved}"
